"""
library.py — вшитая библиотека: курсоры, shiftlock и skybox.

Страница не зависит от ZIP-наборов: элементы каталога превращаются в
обычный respack.Pack в памяти и устанавливаются тем же кодом, что и
пользовательские наборы. Так сохраняются бэкапы, проверка имён и канал direct.

Курсоры osuskinner.com тоже вшиты: tools/fetch_osu.py кладёт их в
assets/cursors вместе со ссылкой, и для страницы они обычные элементы
каталога с категорией «osu!». Сети здесь нет.

Что выбрано, помнит core.config: после «применить» слот записывается вместе
с версией Roblox, и при следующем запуске restore_config() ставит всё
заново, если Roblox успел обновиться в новую папку.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from PIL import Image
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from cursor_manager.content import crosshair as cross
from cursor_manager.content import custom
from cursor_manager.content import cursor_library as lib
from cursor_manager.content import fonts as fnt
from cursor_manager.content import materials as mat
from cursor_manager.content import sounds as snd
from cursor_manager.content import skybox as sky
from cursor_manager.core import config as cfg
from cursor_manager.core import fps
from cursor_manager.core import respack, roblox_paths as RP
from cursor_manager.core import cursor_core as core
from cursor_manager.ui import icons
from cursor_manager.ui.motion import glow

SKY_CACHE = respack.APP_ROOT / "cache" / "skybox"
CURSOR_CACHE = respack.APP_ROOT / "cache" / "cursor"
CROSSHAIR_CACHE = respack.APP_ROOT / "cache" / "crosshair"
MATERIAL_CACHE = respack.APP_ROOT / "cache" / "material"
# готовые миниатюры панорам и курсоров: декод 2048-пиксельного PNG/JPEG — до
# 40 мс на картинку, и без кэша первый заход на skybox подвисал на секунду
THUMB_CACHE = respack.APP_ROOT / "cache" / "thumb"
# сколько миллисекунд за тик таймера можно тратить на дорисовку миниатюр
THUMB_BUDGET_MS = 12

KINDS = (RP.KIND_CURSOR, RP.KIND_CROSSHAIR, RP.KIND_SKY, RP.KIND_MATERIAL,
         RP.KIND_SOUND, RP.KIND_FONT)
KIND_TITLE = {RP.KIND_CURSOR: "курсоры", RP.KIND_CROSSHAIR: "shiftlock",
              RP.KIND_SKY: "skybox", RP.KIND_SOUND: "звуки", RP.KIND_FONT: "шрифты",
              RP.KIND_MATERIAL: "текстуры"}
KIND_ONE = {RP.KIND_CURSOR: "курсор", RP.KIND_CROSSHAIR: "shiftlock",
            RP.KIND_SKY: "skybox", RP.KIND_SOUND: "звук", RP.KIND_FONT: "шрифт",
            RP.KIND_MATERIAL: "текстуры"}
# у этих категорий своих картинок нет — кнопка «загрузить своё» прячется
NO_CUSTOM = (RP.KIND_SOUND, RP.KIND_FONT, RP.KIND_MATERIAL)
# цвета картинок, нарисованных кодом, — токены айдентики (RGBA)
INK = (242, 242, 245, 255)

# Карточек за порцию: курсоров несколько сотен, а каждая карточка — это
# виджеты и картинка, поэтому сетка достраивается по мере прокрутки.
PAGE_SIZE = 24
CARD_W = 150
CARD_H = 178
GAP_X = 18
GAP_Y = 22
TILE_H = 128
THUMB = 64
THUMB_SKY = (148, 74)
PREVIEW = 128


_UNSET = object()


def _pil_pixmap(im: Image.Image) -> QPixmap:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qim = QImage(data, im.width, im.height, im.width * 4,
                 QImage.Format_RGBA8888)
    return QPixmap.fromImage(qim.copy())


def _safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)
    return cleaned.strip(".-") or "item"


def _live_size(path: Path, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.size
    except OSError:
        return fallback


def _fitted_png(source: Path, size: tuple[int, int], cache: Path) -> Path:
    """Подгоняет PNG под размер оригинала, не растягивая на весь холст."""
    try:
        with Image.open(source) as im:
            if im.size == size and im.mode == "RGBA":
                return source
            fitted = core.fit_cursor(im.convert("RGBA"), size)
    except OSError as exc:
        raise respack.PackError(f"картинка не читается: {source.name}: {exc}") from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    fitted.save(cache, "PNG")
    return cache


def _render_crosshair(entry, size: int) -> Image.Image:
    """Shiftlock: пресет crosshair рисуется кодом, свой — из картинки."""
    if isinstance(entry, custom.CustomShiftlock):
        with Image.open(entry.image_path) as im:
            return im.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    return cross.render_preset(entry, size)


def _render_text(text: str, font_path, size, scale: float) -> Image.Image:
    """Карточка звука или шрифта: крупный глиф/надпись на прозрачном фоне."""
    from PIL import ImageDraw, ImageFont
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = max(10, int(h * scale * (1.6 if font_path is None else 1.0)))
    try:
        font = (ImageFont.truetype(str(font_path), px) if font_path
                else ImageFont.truetype("seguisym.ttf", px))
    except OSError:
        font = ImageFont.load_default(px)
    draw = ImageDraw.Draw(img)
    box = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    x = (w - (box[2] - box[0])) / 2 - box[0]
    y = (h - (box[3] - box[1])) / 2 - box[1]
    draw.multiline_text((x, y), text, font=font, fill=INK, align="center")
    return img


def _repolish(widget: QWidget) -> None:
    """QSS читает динамические свойства только после повторной полировки."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def entry_id(kind: str, entry) -> str:
    if isinstance(entry, dict):
        return str(entry.get("id") or entry.get("name") or kind)
    return str(entry.id)


def entry_name(kind: str, entry) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("id") or kind)
    return str(entry.name)


def slot_key(kind: str, entry) -> str:
    """Ключ слота в config: у звуков — своя ячейка на каждую роль."""
    if kind == RP.KIND_SOUND and isinstance(entry, dict):
        return cfg.SOUND_PREFIX + str(entry.get("role") or "other")
    return kind


class Card(QFrame):
    """Карточка сетки без рамки: плитка с картинкой, имя, подпись. Клик выбирает."""
    clicked = Signal()

    def __init__(self, pixmap: QPixmap | None, name: str, caption: str,
                 thumb: tuple[int, int], parent=None, pending: bool = False):
        super().__init__(parent)
        self.setObjectName("cardwrap")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(CARD_H)
        self.setMinimumWidth(CARD_W)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        tile = QLabel()
        tile.setObjectName("tile")
        tile.setAlignment(Qt.AlignCenter)
        tile.setFixedHeight(TILE_H)
        self.tile = tile
        self.stage = tile              # старое имя
        if pixmap is not None:
            tile.setPixmap(pixmap)
        elif not pending:
            tile.setText("?")
        lay.addWidget(tile)
        lay.addSpacing(10)
        self.name = QLabel(name)
        self.name.setObjectName("cardname")
        self.name.setContentsMargins(2, 0, 2, 0)
        lay.addWidget(self.name)
        lay.addSpacing(2)
        self.caption = QLabel(caption)
        self.caption.setObjectName("cardcap")
        self.caption.setContentsMargins(2, 0, 2, 0)
        lay.addWidget(self.caption)
        lay.addStretch(1)
        self._title = name
        self._caption = caption
        self._sel = False
        self._on = False

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        """Миниатюра дорисована позже; None — картинки нет."""
        if pixmap is not None:
            self.tile.setPixmap(pixmap)
        else:
            self.tile.setText("?")

    def mark(self, selected: bool, installed: bool) -> None:
        if selected == self._sel and installed == self._on:
            return
        if selected != self._sel:
            # свечение только у одной выбранной: эффект гонит отрисовку через
            # буфер, и на всей сетке прокрутка тормозила бы
            if selected:
                glow(self.tile, 40, 110)
            else:
                self.tile.setGraphicsEffect(None)
        self._sel, self._on = selected, installed
        self.tile.setProperty("sel", selected)
        self.name.setProperty("sel", selected)
        self.caption.setProperty("on", installed)
        self.caption.setText(self._caption + (" · установлен" if installed else ""))
        for w in (self.tile, self.name, self.caption):
            _repolish(w)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class LibraryPage(QWidget):
    """Сетка вшитых ресурсов, панель выбранного и применение."""

    # осталось для совместимости с app.py: категорий больше нет, всегда ([], "")
    categoriesChanged = Signal(list, str)
    # текст в строку статуса; второй аргумент — показать ещё и всплывашку
    message = Signal(str, bool)
    # конфиг изменился: применили или сняли что-то
    configChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = RP.KIND_CURSOR
        self.category = ""
        self._shown = 0                # сколько карточек уже в сетке
        self._entries: list = []
        self._cols = 1
        self._cursors = None
        self._crosshairs = None
        self._skies = None
        self._sounds = None
        self._fonts = None
        self._player = None
        self._built = ""               # kind, для которого собрана сетка
        self._gen = 0                  # поколение сетки: старые карточки не дорисовываем
        self._pending: list = []       # (поколение, kind, entry, size, card)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._fill_thumbs)
        self._thumbs: dict[tuple[str, str], QPixmap] = {}
        self.cards: list[tuple[object, Card]] = []
        self.selected = None
        self.config = cfg.Config.load()
        self._build()
        QTimer.singleShot(0, self.refresh)

    # ─────────────────────────────────────────────────────────────────────
    # Построение
    # ─────────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        center = QWidget()
        center.setObjectName("center")
        col = QVBoxLayout(center)
        col.setContentsMargins(20, 18, 28, 0)
        col.setSpacing(18)

        head = QHBoxLayout()
        head.setSpacing(16)
        self.title = QLabel("")
        self.title.setObjectName("h1")
        head.addWidget(self.title)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setFixedSize(260, 38)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_changed)
        head.addWidget(self.search)
        self.add_btn = QPushButton("Загрузить своё")
        self.add_btn.setObjectName("pill")
        self.add_btn.setFixedHeight(38)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setToolTip("PNG/JPG с компьютера: курсор, shiftlock или "
                                "панорама неба 2:1 (обычное фото обрежется)")
        self.add_btn.clicked.connect(self._add_custom)
        head.addWidget(self.add_btn)
        col.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.verticalScrollBar().valueChanged.connect(self._maybe_more)
        self.host = QWidget()
        self.host.setObjectName("listhost")
        # сетка прижата к верху растяжкой снизу: строки дописываются по мере
        # прокрутки, и растяжка внутри самой сетки ехала бы вслед за ними
        host_lay = QVBoxLayout(self.host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(GAP_X)
        self.grid.setVerticalSpacing(GAP_Y)
        self.grid.setContentsMargins(0, 0, 0, 24)
        host_lay.addLayout(self.grid)
        host_lay.addStretch(1)
        self.scroll.setWidget(self.host)
        col.addWidget(self.scroll, 1)
        root.addWidget(center, 1)

        root.addWidget(self._build_panel())

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(180)
        self._filter_timer.timeout.connect(self.refresh)

    def _build_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidecol")
        panel.setFixedWidth(300)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 18, 28, 24)
        lay.setSpacing(14)

        self.preview = QLabel()
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(236)
        lay.addWidget(self.preview)

        self.p_name = QLabel("")
        self.p_name.setObjectName("h2")
        self.p_name.setWordWrap(True)
        self.p_name.setContentsMargins(0, 6, 0, 0)
        lay.addWidget(self.p_name)
        self.p_tags = QLabel("")
        self.p_tags.setObjectName("faint")
        self.p_tags.setWordWrap(True)
        lay.addWidget(self.p_tags)
        self.p_info = QLabel("")
        self.p_info.setObjectName("body")
        self.p_info.setWordWrap(True)
        self.p_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.p_info)

        lay.addStretch(1)
        self.play_btn = QPushButton("Прослушать")
        self.play_btn.setObjectName("pill")
        self.play_btn.setFixedHeight(38)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(self._play)
        lay.addWidget(self.play_btn)
        self.delete_btn = QPushButton("Удалить своё")
        self.delete_btn.setObjectName("textbtn")
        self.delete_btn.setFixedHeight(38)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self._delete_custom)
        lay.addWidget(self.delete_btn)
        self.apply_btn = QPushButton("Применить")
        self.apply_btn.setObjectName("go")
        self.apply_btn.setFixedHeight(48)
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self._apply_selected)
        glow(self.apply_btn)
        lay.addWidget(self.apply_btn)
        self.revert_btn = QPushButton("Вернуть оригинал")
        self.revert_btn.setObjectName("textbtn")
        self.revert_btn.setFixedHeight(44)
        self.revert_btn.setCursor(Qt.PointingHandCursor)
        self.revert_btn.clicked.connect(self._revert_selected)
        lay.addWidget(self.revert_btn)
        self._show_selected()
        return panel

    # ─────────────────────────────────────────────────────────────────────
    # Данные и фильтры
    # ─────────────────────────────────────────────────────────────────────
    def set_kind(self, key: str) -> None:
        # та же вкладка без поиска: сетка уже построена, пересоздавать нечего
        unchanged = (key == self._built and not self.search.text()
                     and bool(self.cards))
        self.kind = key
        self.category = ""
        self.selected = None
        if unchanged:
            self._mark_cards()
            self._show_selected()
            return
        self._shown = 0
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refresh()

    # старое имя: на него завязаны тесты и app.py
    _set_kind = set_kind

    def set_category(self, value: str) -> None:
        """Категорий больше нет; метод оставлен, чтобы старые вызовы не падали."""

    def _filter_changed(self) -> None:
        self._shown = 0
        self._filter_timer.start()

    def _load_cursors(self):
        if self._cursors is None:
            try:
                self._cursors = custom.load("cursor") + lib.catalog()
            except Exception as exc:
                self._cursors = []
                self.message.emit(f"каталог курсоров не открылся: {exc}", False)
        return self._cursors

    def _load_crosshairs(self):
        if self._crosshairs is None:
            try:
                self._crosshairs = custom.load("crosshair") + cross.load_presets()[0]
            except Exception as exc:
                self._crosshairs = []
                self.message.emit(f"shiftlock не загрузились: {exc}", False)
        return self._crosshairs

    def _load_skies(self):
        if self._skies is None:
            self._skies = custom.load("sky") + sky.load_presets()
        return self._skies

    def reload(self, kind: str | None = None) -> None:
        """Сбросить кэш списка: после добавления/удаления своего элемента."""
        if kind in (None, RP.KIND_CURSOR):
            self._cursors = None
        if kind in (None, RP.KIND_CROSSHAIR):
            self._crosshairs = None
        if kind in (None, RP.KIND_SKY):
            self._skies = None
        self._thumbs = {k: v for k, v in self._thumbs.items()
                        if kind is not None and k[0] != kind}

    def items_of(self, kind: str) -> list:
        if kind == RP.KIND_CURSOR:
            return self._load_cursors()
        if kind == RP.KIND_CROSSHAIR:
            return self._load_crosshairs()
        if kind == RP.KIND_SOUND:
            if self._sounds is None:
                self._sounds = snd.load_presets()
            return self._sounds
        if kind == RP.KIND_FONT:
            if self._fonts is None:
                self._fonts = fnt.load_presets()
            return self._fonts
        if kind == RP.KIND_MATERIAL:
            return mat.PRESETS
        return self._load_skies()

    def find(self, kind: str, item_id: str):
        for entry in self.items_of(kind):
            if entry_id(kind, entry) == item_id:
                return entry
        return None

    def _category_of(self, entry) -> str:
        if self.kind == RP.KIND_CURSOR:
            return entry.category
        if self.kind == RP.KIND_CROSSHAIR:
            return entry.game
        if self.kind == RP.KIND_SOUND:
            return snd.ROLES.get(entry.get("role"), {}).get("title", "")
        if self.kind == RP.KIND_MATERIAL:
            return entry.get("group", "")
        if self.kind == RP.KIND_SKY and custom.is_custom(entry.get("id", "")):
            return custom.CATEGORY
        return ""

    def categories(self) -> list[str]:
        return []

    def _filtered(self):
        query = self.search.text().strip().lower()
        items = self.items_of(self.kind)
        if not query:
            return items
        if self.kind == RP.KIND_CURSOR:
            return [c for c in items if query in " ".join(
                (c.name, c.category, c.author, c.blurb, *c.tags)).lower()]
        if self.kind == RP.KIND_CROSSHAIR:
            return [p for p in items if query in " ".join(
                (p.name, p.game, p.blurb, p.note)).lower()]
        return [s for s in items if query in " ".join(
            (str(s.get("name", "")), str(s.get("id", "")))).lower()]

    # ─────────────────────────────────────────────────────────────────────
    # Сетка
    # ─────────────────────────────────────────────────────────────────────
    def _columns(self) -> int:
        width = self.scroll.viewport().width() or 4 * (CARD_W + GAP_X)
        return max(2, min(6, (width + GAP_X) // (CARD_W + GAP_X)))

    def refresh(self) -> None:
        self.title.setText(KIND_TITLE[self.kind].capitalize())
        self.search.setPlaceholderText(
            f"Найти среди {len(self.items_of(self.kind))}")
        self.categoriesChanged.emit([], "")
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                # hide() сразу: deleteLater сработает только на следующем
                # цикле событий, и до него старые карточки накладывались.
                item.widget().hide()
                item.widget().deleteLater()
        self.cards = []
        self._gen += 1
        self._pending = []

        try:
            entries = self._filtered()
        except Exception as exc:
            entries = []
            self.message.emit(f"не удалось загрузить список: {exc}", False)
        self._entries = entries

        if not entries:
            empty = QLabel("Ничего не найдено")
            empty.setObjectName("faint")
            self.grid.addWidget(empty, 0, 0)
        self._cols = self._columns()
        for c in range(self._cols):
            self.grid.setColumnStretch(c, 1)
        if self._shown == 0:
            # новый список — наверх; без сигнала, иначе _maybe_more
            # дорисовал бы карточки ещё до первой порции
            bar = self.scroll.verticalScrollBar()
            bar.blockSignals(True)
            bar.setValue(0)
            bar.blockSignals(False)
        self._built = self.kind
        self._last_cols = self._cols
        target, self._shown = max(PAGE_SIZE, self._shown), 0
        self._add_cards(target)
        self._mark_cards()
        self._show_selected()

    def _add_cards(self, count: int) -> None:
        """
        Дорисовать следующие карточки в конец сетки. Вся сетка сразу — это
        сотни виджетов с картинками, поэтому они подгружаются по мере прокрутки.
        """
        start = self._shown
        for index, entry in enumerate(self._entries[start:start + count], start):
            card = self._card(entry)
            card.clicked.connect(lambda e=entry: self.select(e))
            self.cards.append((entry, card))
            self.grid.addWidget(card, index // self._cols, index % self._cols)
        self._shown = min(len(self._entries), start + count)
        # окно высокое и полоса прокрутки ещё не появилась — догрузить сразу
        QTimer.singleShot(0, self._maybe_more)

    def _maybe_more(self, *_args) -> None:
        # скрытая страница не знает своей высоты — догрузится, когда покажут
        if self._shown >= len(self._entries) or not self.isVisible():
            return
        # высоту считаем сами: сразу после добавления карточек Qt ещё не
        # пересчитал полосу прокрутки, и maximum() врёт
        rows = -(-self._shown // max(1, self._cols))
        content = rows * (CARD_H + GAP_Y)
        bottom = self.scroll.verticalScrollBar().value() + self.scroll.viewport().height()
        if content - bottom < 400:
            self._add_cards(PAGE_SIZE)
            self._mark_cards()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._maybe_more)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.cards and self._columns() != getattr(self, "_last_cols", 0):
            self._last_cols = self._columns()
            QTimer.singleShot(0, self.refresh)

    def _fill_thumbs(self) -> None:
        """Дорисовать миниатюры порциями, не блокируя окно дольше кадра."""
        import time
        deadline = time.perf_counter() + THUMB_BUDGET_MS / 1000
        while self._pending and time.perf_counter() < deadline:
            gen, kind, entry, size, card = self._pending.pop(0)
            if gen != self._gen:
                continue
            card.set_pixmap(self._thumb(kind, entry, size))
        if self._pending:
            self._thumb_timer.start(0)

    def _disk_thumb(self, path: Path, kind: str, eid: str, size) -> Path:
        st = path.stat()
        name = f"{kind}-{_safe_id(eid)}-{size[0]}x{size[1]}-{st.st_mtime_ns}-{st.st_size}.png"
        return THUMB_CACHE / name

    def _thumb(self, kind: str, entry, size, lazy: bool = False) -> QPixmap | None:
        key = (kind, entry_id(kind, entry), str(size))
        if key in self._thumbs:
            return self._thumbs[key]
        if lazy:
            return None
        pixmap = None
        try:
            if kind == RP.KIND_CROSSHAIR:
                pixmap = _pil_pixmap(_render_crosshair(entry, size[0]))
            elif kind == RP.KIND_SOUND:
                pixmap = _pil_pixmap(icons.speaker(int(min(size) * 0.7), INK))
            elif kind == RP.KIND_FONT:
                pixmap = _pil_pixmap(_render_text("Аа", entry.get("regular"), size, 0.5))
            elif kind == RP.KIND_MATERIAL:
                pixmap = _pil_pixmap(_render_text(entry.get("glyph", "▦"), None, size, 0.55))
            else:
                path = entry.path if kind == RP.KIND_CURSOR else entry.get("path")
                if isinstance(path, Path) and path.is_file():
                    cached = self._disk_thumb(path, kind, key[1], size)
                    if cached.is_file():
                        with Image.open(cached) as im:
                            pixmap = _pil_pixmap(im)
                    else:
                        with Image.open(path) as im:
                            # курсоры osu! бывают до 512 px, панорамы — 2048
                            if im.format == "JPEG":
                                im.draft("RGB", (size[0] * 2, size[1] * 2))
                            preview = im.convert("RGBA")
                            # reduce в разы быстрее LANCZOS по большой панораме
                            factor = min(preview.width // (size[0] * 2),
                                         preview.height // (size[1] * 2))
                            if factor >= 2:
                                preview = preview.reduce(factor)
                            preview.thumbnail(size, Image.Resampling.LANCZOS)
                        pixmap = _pil_pixmap(preview)
                        try:
                            cached.parent.mkdir(parents=True, exist_ok=True)
                            preview.save(cached, "PNG")
                        except OSError:
                            pass
        except Exception:
            pixmap = None
        self._thumbs[key] = pixmap
        return pixmap

    def _card(self, entry) -> Card:
        kind = self.kind
        size = THUMB_SKY if kind in (RP.KIND_SKY, RP.KIND_FONT) else (THUMB, THUMB)
        caption = self._category_of(entry) or KIND_ONE[kind]
        pixmap = self._thumb(kind, entry, size, lazy=True)
        card = Card(pixmap, entry_name(kind, entry), caption, size,
                    pending=pixmap is None)
        if pixmap is None:
            self._pending.append((self._gen, kind, entry, size, card))
            self._thumb_timer.start(0)
        return card

    def _mark_cards(self) -> None:
        installed = {s.id for k, s in self.config.slots.items()
                     if cfg.slot_kind(k) == self.kind}
        sel_id = entry_id(self.kind, self.selected) if self.selected is not None else ""
        for entry, card in self.cards:
            eid = entry_id(self.kind, entry)
            card.mark(eid == sel_id, eid in installed)

    # ─────────────────────────────────────────────────────────────────────
    # Панель выбранного
    # ─────────────────────────────────────────────────────────────────────
    def select(self, entry) -> None:
        self.selected = entry
        self._mark_cards()
        self._show_selected()

    def _show_selected(self) -> None:
        entry = self.selected
        has = entry is not None
        self.apply_btn.setEnabled(has)
        self.revert_btn.setEnabled(True)
        self.delete_btn.setVisible(
            has and custom.is_custom(entry_id(self.kind, entry)))
        self.play_btn.setVisible(has and self.kind == RP.KIND_SOUND)
        self.add_btn.setVisible(self.kind not in NO_CUSTOM)
        if not has:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Выбери карточку")
            self.p_name.setText(KIND_TITLE[self.kind].capitalize())
            self.p_tags.setVisible(False)
            self.p_info.setText(self._kind_hint())
            return
        kind = self.kind
        size = (240, 120) if kind in (RP.KIND_SKY, RP.KIND_FONT) else (PREVIEW, PREVIEW)
        if kind == RP.KIND_FONT:
            pixmap = _pil_pixmap(_render_text("Привет, Roblox!\nАа Бб 123",
                                              entry.get("regular"), size, 0.16))
        else:
            pixmap = self._thumb(kind, entry, size)
        self.preview.setText("" if pixmap else "?")
        self.preview.setPixmap(pixmap or QPixmap())
        self.p_name.setText(entry_name(kind, entry))
        tags = []
        if kind == RP.KIND_CURSOR:
            tags = [entry.category, entry.author or "sanyakiller111"]
        elif kind == RP.KIND_CROSSHAIR:
            tags = [entry.game or "shiftlock", entry.license]
        elif kind == RP.KIND_SOUND:
            tags = [self._category_of(entry), str(entry.get("license") or "")]
        elif kind == RP.KIND_FONT:
            tags = [str(entry.get("license") or ""), str(entry.get("author") or "")[:30]]
        elif kind == RP.KIND_MATERIAL:
            tags = [entry.get("group", ""), "из файлов Roblox"]
        else:
            tags = [str(entry.get("license") or "CC0-1.0"),
                    str(entry.get("author") or "")]
        tag_line = " · ".join(t for t in tags if t)
        self.p_tags.setText(tag_line)
        self.p_tags.setVisible(bool(tag_line))
        self.p_info.setText(self._kind_hint())

    def _kind_hint(self) -> str:
        if self.kind == RP.KIND_CURSOR:
            return ("Файлы ArrowCursor.png и ArrowFarCursor.png.\n"
                    "Картинка подгоняется под размер оригинала, обычно 64×64.")
        if self.kind == RP.KIND_CROSSHAIR:
            return ("Файл MouseLockedCursor.png, обычно 32×32.\n"
                    "Показывается по центру при включённом shift lock.")
        if self.kind == RP.KIND_SOUND:
            entry = self.selected
            targets = ", ".join(entry.get("targets", [])) if isinstance(entry, dict) else ""
            return ("Заменяет звук Roblox: " + targets) if targets else (
                "Звуки смерти, прыжка, шагов и меню.\nУ каждой роли свой слот.")
        if self.kind == RP.KIND_FONT:
            return ("Шрифт интерфейса Roblox (BuilderSans).\n"
                    "Текст, который рисует сама игра, не меняется.")
        if self.kind == RP.KIND_MATERIAL:
            blurb = (self.selected.get("blurb", "") + "\n\n"
                     if isinstance(self.selected, dict) else "")
            return (blurb + "Переделывает пластик, студы и воду из файлов Roblox.\n"
                    "Траву, кирпич и дерево Roblox качает из сети, их не заменить.")
        return ("Шесть граней sky512_*.tex, DXT1 с мипами.\n"
                "Первый раз собирается около 10 секунд.")

    # ─────────────────────────────────────────────────────────────────────
    # Применение
    # ─────────────────────────────────────────────────────────────────────
    def _roblox_dir(self) -> Path | None:
        try:
            version_dir = core.resolve_roblox_dir()
        except OSError as exc:
            QMessageBox.critical(self, "Roblox не найден", str(exc))
            return None
        if version_dir is None:
            QMessageBox.warning(
                self, "Roblox не найден",
                "Не удалось найти папку Versions установленного Roblox. "
                "Запусти Roblox один раз и открой программу снова.")
        return version_dir

    def _backend_key(self) -> str:
        """Канал один — прямо в папку Roblox; оверлей Bloxstrap только чистим."""
        return "direct"

    def _install(self, pack: respack.Pack, label: str,
                 version_dir: Path | None = None) -> bool:
        version_dir = version_dir or self._roblox_dir()
        if version_dir is None:
            return False
        backend = self._backend_key()
        try:
            result = respack.install(pack, version_dir, backend)
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Не удалось применить", str(exc))
            return False
        skipped = result.get("skipped", [])
        self.message.emit(
            f"Применено: {label}. Оригинал сохранён в бэкапе"
            + (f", пропущено: {len(skipped)}" if skipped else ""), True)
        return True

    def _revert(self, pack: respack.Pack, label: str) -> bool:
        version_dir = self._roblox_dir()
        if version_dir is None:
            return False
        try:
            result = respack.uninstall(pack, version_dir, self._backend_key())
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Не удалось снять", str(exc))
            return False
        skipped = result.get("skipped", [])
        self.message.emit(
            f"{label}: снято, восстановлено из бэкапа: {len(result.get('restored', []))}"
            + (f", пропущено {len(skipped)}" if skipped else ""), True)
        return True

    def pack_for(self, kind: str, entry, version_dir: Path | None,
                 generate: bool = True) -> respack.Pack:
        if kind == RP.KIND_CURSOR:
            return self._cursor_pack(entry, version_dir)
        if kind == RP.KIND_CROSSHAIR:
            return self._crosshair_pack(entry, version_dir, generate=generate)
        if kind in (RP.KIND_SOUND, RP.KIND_FONT):
            return self._file_pack(kind, entry)
        if kind == RP.KIND_MATERIAL:
            return self._material_pack(entry, version_dir)
        if version_dir is None:
            raise respack.PackError("для skybox нужна папка Roblox")
        return self._sky_pack(entry, version_dir, generate=generate)

    def _cursor_pack(self, c, version_dir: Path | None = None) -> respack.Pack:
        path = c.path
        if path is None:
            raise respack.PackError(f"файл курсора «{c.name}» не найден")
        files = {}
        for name in ("ArrowCursor.png", "ArrowFarCursor.png"):
            if version_dir is None:
                files[name] = path
                continue
            live = version_dir / RP.get(RP.KIND_CURSOR).rel(name)
            size = _live_size(live, (64, 64))
            cache = CURSOR_CACHE / f"{_safe_id(c.id)}-{size[0]}x{size[1]}-{name}"
            files[name] = _fitted_png(path, size, cache)
        meta = respack.PackMeta(
            name=c.name, author=c.author or "sanyakiller111",
            license="CC0-1.0", kind=RP.KIND_CURSOR,
            description=c.blurb, tags=list(c.tags))
        return respack.Pack(
            meta=meta, root=Path("builtin") / _safe_id(c.id),
            files=files,
            preview=path)

    def _crosshair_pack(self, p, version_dir: Path | None = None,
                        generate: bool = True) -> respack.Pack:
        if version_dir is None:
            size = 32
        else:
            live = version_dir / RP.get(RP.KIND_CROSSHAIR).rel("MouseLockedCursor.png")
            size = _live_size(live, (32, 32))[0]
        # v2: рисовалка точек исправлена — старые (пустые) PNG не берём
        path = CROSSHAIR_CACHE / f"{_safe_id(p.id)}-{size}x{size}-v2.png"
        if generate:
            try:
                image = _render_crosshair(p, size)
            except Exception as exc:
                raise respack.PackError(f"не удалось нарисовать прицел: {exc}") from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, "PNG")
        meta = respack.PackMeta(
            name=p.name, author="sanyakiller111", license=(
                p.license if p.license in RP.LICENSES else "UNKNOWN"),
            kind=RP.KIND_CROSSHAIR, description=p.blurb or p.note,
            tags=[p.game] if p.game else [])
        return respack.Pack(
            meta=meta, root=Path("builtin") / _safe_id(p.id),
            files={"MouseLockedCursor.png": path}, preview=path)

    def _file_pack(self, kind: str, entry: dict) -> respack.Pack:
        """Звук или шрифт: готовые файлы кладутся под именами файлов Roblox."""
        if kind == RP.KIND_SOUND:
            files = {name: Path(entry["path"]) for name in entry.get("targets", [])}
        else:
            files = {name: Path(p) for name, p in fnt.files_for(entry).items()}
        missing = [n for n, p in files.items() if not p.is_file()]
        if not files or missing:
            raise respack.PackError(f"нет файлов для «{entry_name(kind, entry)}»")
        license_id = str(entry.get("license") or "UNKNOWN")
        meta = respack.PackMeta(
            name=entry_name(kind, entry), author=str(entry.get("author") or ""),
            license=license_id if license_id in RP.LICENSES else "UNKNOWN",
            kind=kind, description="", tags=[kind])
        return respack.Pack(meta=meta, root=Path("builtin") / _safe_id(entry_id(kind, entry)),
                            files=files, preview=None)

    def _material_pack(self, preset: dict, version_dir: Path | None) -> respack.Pack:
        """
        Текстуры: пересобрать оригиналы Roblox. Оригинал берётся из бэкапа,
        если он есть, — иначе из папки версии; в пакет попадают все три
        группы, чтобы новый пресет целиком заменял предыдущий.
        """
        if version_dir is None:
            raise respack.PackError("для текстур нужна папка Roblox")
        kind = RP.get(RP.KIND_MATERIAL)
        sources = {}
        for name in kind.files:
            backup = respack.BACKUP_ROOT / version_dir.name / kind.rel(name)
            live = version_dir / kind.rel(name)
            src = backup if backup.is_file() else live
            if src.is_file():
                sources[name] = src
        if not sources:
            raise respack.PackError("в папке Roblox нет текстур пластика, студов и воды")
        try:
            files = mat.build(preset, sources, MATERIAL_CACHE / version_dir.name)
        except (mat.MaterialError, OSError) as exc:
            raise respack.PackError(f"не удалось собрать текстуры: {exc}") from exc
        meta = respack.PackMeta(
            name=entry_name(RP.KIND_MATERIAL, preset), author="sanyakiller111",
            license="UNKNOWN", kind=RP.KIND_MATERIAL,
            description=str(preset.get("blurb") or ""), tags=["material"])
        return respack.Pack(meta=meta, root=Path("builtin") / _safe_id(preset["id"]),
                            files=files, preview=None)

    def _play(self) -> None:
        """Прослушать выбранный звук — без записи куда-либо."""
        entry = self.selected
        if self.kind != RP.KIND_SOUND or not isinstance(entry, dict):
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            self.message.emit("проигрывание звука недоступно в этой сборке", False)
            return
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._audio.setVolume(0.8)
            self._player.setAudioOutput(self._audio)
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(entry["path"])))
        self._player.play()

    def _sky_reference(self, version_dir: Path) -> tuple[int, int]:
        sky_dir = version_dir / RP.get(RP.KIND_SKY).path
        for face in sky.FACES:
            ref = sky_dir / f"sky512_{face}.tex"
            if ref.is_file():
                try:
                    return sky.match_destination(ref)
                except (OSError, sky.SkyboxError):
                    break
        return sky.FACE_SIZE, sky.MIP_LEVELS

    def _sky_pack(self, item: dict, version_dir: Path,
                  generate: bool = True) -> respack.Pack:
        size, mips = self._sky_reference(version_dir)
        identifier = _safe_id(str(item.get("id") or "skybox"))
        digest = str(item.get("sha256") or "")[:8]
        suffix = f"-{digest}" if digest else ""
        out = SKY_CACHE / f"{identifier}-{size}x{mips}{suffix}"
        files = {f"sky512_{face}.tex": out / f"sky512_{face}.tex"
                 for face in sky.FACES}
        if generate:
            valid = all(p.is_file() and sky.verify(p, size, mips)["ok"]
                        for p in files.values())
            if not valid:
                panorama_path = item.get("path")
                if not isinstance(panorama_path, Path) or not panorama_path.is_file():
                    raise respack.PackError("панорама неба не найдена")
                try:
                    with Image.open(panorama_path) as im:
                        written = sky.build_skybox(
                            im.convert("RGB"), out, size=size,
                            prefix="sky512", mips=mips)
                except (OSError, sky.SkyboxError) as exc:
                    raise respack.PackError(f"не удалось собрать небо: {exc}") from exc
                files = {f"sky512_{face}.tex": written[face] for face in sky.FACES}
                for path in files.values():
                    if not sky.verify(path, size, mips)["ok"]:
                        raise respack.PackError(
                            f"сгенерированный файл не прошёл проверку: {path.name}")
        meta = respack.PackMeta(
            name=str(item.get("name") or "Небо"),
            author=str(item.get("author") or "sanyakiller111"),
            license=str(item.get("license") or "CC0-1.0"),
            kind=RP.KIND_SKY,
            description=str(item.get("blurb") or ""),
            tags=["skybox"])
        preview = item.get("path")
        return respack.Pack(
            meta=meta, root=Path("builtin") / identifier,
            files=files, preview=preview if isinstance(preview, Path) else None)

    def _apply_selected(self) -> None:
        entry = self.selected
        if entry is None:
            return
        version_dir = self._roblox_dir()
        if version_dir is None:
            return
        self.install_entry(self.kind, entry, version_dir)

    def install_entry(self, kind: str, entry, version_dir: Path,
                      quiet: bool = False) -> bool:
        """
        Поставить элемент категории и запомнить его слот в config.

        quiet — для пакетной установки: ошибки не всплывают окнами, а
        возвращаются False, чтобы один сломанный элемент не останавливал остальные.
        """
        name = entry_name(kind, entry)
        if kind == RP.KIND_SKY:
            self.message.emit("Собираю шесть граней skybox, первый раз это занимает около 10 секунд", False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            pack = self.pack_for(kind, entry, version_dir)
        except (respack.PackError, OSError) as exc:
            QApplication.restoreOverrideCursor()
            if not quiet:
                QMessageBox.critical(self, f"{KIND_ONE.get(kind, kind)} не готов", str(exc))
            return False
        QApplication.restoreOverrideCursor()
        if quiet:
            try:
                respack.install(pack, version_dir, self._backend_key())
            except (respack.PackError, OSError):
                return False
        elif not self._install(pack, name, version_dir=version_dir):
            return False
        self.config.remember(slot_key(kind, entry), entry_id(kind, entry), name,
                             self._backend_key(), version_dir.name)
        self.config.save()
        if kind == self.kind:
            self._mark_cards()
        self.configChanged.emit()
        return True

    def _revert_selected(self) -> None:
        if self.selected is not None:
            self.revert_slot(slot_key(self.kind, self.selected))
            return
        keys = [k for k in self.config.slots if cfg.slot_kind(k) == self.kind]
        for key in keys or [self.kind]:
            self.revert_slot(key)

    def revert_slot(self, key: str) -> None:
        """Вернуть оригинал слота: снять то, что записано в конфиге."""
        kind = cfg.slot_kind(key)
        slot = self.config.slots.get(key)
        entry = self.find(kind, slot.id) if slot else None
        if entry is None:
            entry = self.selected if kind == self.kind else None
        if entry is None:
            items = self.items_of(kind)
            entry = items[0] if items else None
        if entry is None:
            return
        version_dir = self._roblox_dir()
        if version_dir is None:
            return
        try:
            pack = self.pack_for(kind, entry, version_dir, generate=False)
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Не удалось снять", str(exc))
            return
        if self._revert(pack, KIND_ONE.get(kind, kind)):
            self.config.forget(key)
            self.config.save()
            if kind == self.kind:
                self._mark_cards()
            self.configChanged.emit()

    def slot_state(self, key: str, version_dir=_UNSET) -> str:
        """
        none — ничего не выбрано; on — файлы на месте; off — слетели.

        version_dir можно передать готовый (в т.ч. None): поиск папки Roblox
        обходит диск ~30 мс, а вкладка config спрашивает про шесть слотов.
        """
        kind = cfg.slot_kind(key)
        slot = self.config.slots.get(key)
        if slot is None:
            return "none"
        entry = self.find(kind, slot.id)
        if version_dir is _UNSET:
            try:
                version_dir = core.resolve_roblox_dir()
            except OSError:
                version_dir = None
        if entry is None or version_dir is None:
            return "off"
        try:
            pack = self.pack_for(kind, entry, version_dir,
                                 generate=kind == RP.KIND_CROSSHAIR)
        except (respack.PackError, OSError):
            return "off"
        for rel, src in pack.files.items():
            dest = RP.destination("direct", version_dir, kind,
                                  PurePosixPath(rel).name)
            try:
                if (not dest.is_file() or not Path(src).is_file()
                        or respack.sha256_of(dest) != respack.sha256_of(Path(src))):
                    return "off"
            except OSError:
                return "off"
        return "on"

    def restore_config(self, force: bool = False) -> list[str]:
        """
        Roblox обновился (direct) — поставить слоты из конфига заново.

        При запуске зовётся без force и без диалогов: если Roblox не найден
        или элемент пропал из каталога, слот просто пропускается. force —
        кнопка «поставить заново» на вкладке config: ставит в текущем канале,
        даже если версия Roblox не менялась.
        """
        try:
            version_dir = core.resolve_roblox_dir()
        except OSError:
            return []
        if version_dir is None:
            return []
        if not force and not self.config.needs_restore(version_dir.name):
            return []
        backend = "direct"
        restored = []
        for key, slot in list(self.config.slots.items()):
            kind = cfg.slot_kind(key)
            entry = self.find(kind, slot.id)
            if entry is None:
                continue
            try:
                pack = self.pack_for(kind, entry, version_dir)
                respack.install(pack, version_dir, backend)
            except (respack.PackError, OSError):
                continue
            restored.append(slot.name)
        if self.config.fps_options:
            try:
                fps.apply_flags(version_dir, self.config.fps_options, backend)
                restored.append("fps-флаги")
            except (fps.FpsError, OSError):
                pass
        self.config.version = version_dir.name
        self.config.save()
        self.configChanged.emit()
        return restored

    def _revert_backends(self, pack: respack.Pack, version_dir: Path) -> list[str]:
        """Каналы, где у набора есть следы: бэкап direct и/или оверлей."""
        kind = RP.get(pack.meta.kind)
        has_backup = any(
            (respack.BACKUP_ROOT / version_dir.name
             / kind.rel(PurePosixPath(rel).name)).is_file()
            for rel in pack.files)
        backends = ["direct"] if has_backup else []
        # старые файлы оверлея Bloxstrap — уборка, а не канал установки
        if RP.bloxstrap_installed() and any(
                RP.destination("bloxstrap", version_dir, pack.meta.kind,
                               PurePosixPath(rel).name).is_file()
                for rel in pack.files):
            backends.append("bloxstrap")
        return backends or [self._backend_key()]

    def revert_all(self) -> None:
        version_dir = self._roblox_dir()
        if version_dir is None:
            return
        if QMessageBox.question(
                self, "Снять всё",
                "Вернуть оригинальные курсоры, shiftlock, skybox, текстуры, звуки и шрифт?\n"
                "Файлы, которых нет в бэкапе, будут удалены."
        ) != QMessageBox.Yes:
            return
        packs = []
        try:
            cursors = self._load_cursors()
            if cursors:
                cursor_pack = self._cursor_pack(cursors[0])
                kind = RP.get(RP.KIND_CURSOR)
                ibeam_backup = (respack.BACKUP_ROOT / version_dir.name
                                / kind.rel("IBeamCursor.png"))
                if RP.bloxstrap_installed() or ibeam_backup.is_file():
                    cursor_pack.files["IBeamCursor.png"] = (
                        cursor_pack.files["ArrowCursor.png"])
                packs.append(cursor_pack)
            presets = self._load_crosshairs()
            if presets:
                packs.append(self._crosshair_pack(presets[0], generate=False))
            skies = self._load_skies()
            if skies:
                packs.append(self._sky_pack(skies[0], version_dir, generate=False))
            seen_roles = set()
            for item in self.items_of(RP.KIND_SOUND):
                if item.get("role") not in seen_roles:
                    seen_roles.add(item.get("role"))
                    packs.append(self._file_pack(RP.KIND_SOUND, item))
            fonts_ = self.items_of(RP.KIND_FONT)
            if fonts_:
                packs.append(self._file_pack(RP.KIND_FONT, fonts_[0]))
            if "material" in self.config.slots:
                packs.append(self._material_pack(mat.PRESETS[0], version_dir))
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Не удалось подготовить снятие", str(exc))
            return
        removed = restored = skipped = 0
        failed = []
        for pack in packs:
            for backend in self._revert_backends(pack, version_dir):
                try:
                    result = respack.uninstall(pack, version_dir, backend)
                    removed += len(result["removed"])
                    restored += len(result["restored"])
                    skipped += len(result.get("skipped", []))
                except (respack.PackError, OSError) as exc:
                    failed.append(str(exc))
        self.config.slots.clear()
        self.config.save()
        self._mark_cards()
        self.configChanged.emit()
        self.message.emit(
            f"Снято: {removed}, восстановлено из бэкапа: {restored}"
            + (f", пропущено: {skipped}" if skipped else "")
            + (". Ошибки: " + "; ".join(failed) if failed else ""), True)

    # старое имя: им пользуются тесты и страница наборов
    _revert_all = revert_all

    # ─────────────────────────────────────────────────────────────────────
    # Своё из картинки
    # ─────────────────────────────────────────────────────────────────────
    def _add_custom(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"своё: {KIND_ONE[self.kind]}", "",
            "Картинки (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return
        name, ok = QInputDialog.getText(self, "название", "как назвать:",
                                        text=Path(path).stem[:40])
        if not ok:
            return
        try:
            item = custom.add(self.kind, Path(path), name)
        except custom.CustomError as exc:
            QMessageBox.critical(self, "не получилось", str(exc))
            return
        self.added_custom(self.kind, item["id"])

    def added_custom(self, kind: str, item_id: str) -> None:
        """Показать только что добавленный свой элемент выбранным."""
        self.reload(kind)
        if self.kind != kind:
            self.set_kind(kind)
        self._built = ""               # список изменился — сетку собрать заново
        self._shown = 0
        self.selected = self.find(kind, item_id)
        self.refresh()
        self.message.emit("Добавлено — нажми «Применить»", True)

    def _delete_custom(self) -> None:
        entry = self.selected
        if entry is None:
            return
        eid = entry_id(self.kind, entry)
        if not custom.is_custom(eid):
            return
        if QMessageBox.question(self, "удалить", f"удалить «{entry_name(self.kind, entry)}»?\n"
                                "если он сейчас стоит в roblox — сначала «вернуть оригинал»."
                                ) != QMessageBox.Yes:
            return
        custom.remove(self.kind, eid)
        self.selected = None
        self.reload(self.kind)
        self.refresh()
