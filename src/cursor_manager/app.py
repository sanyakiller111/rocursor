# app.py - sanyakiller111, production UI на PySide6.
#
# Окно делится на страницы: вшитая библиотека, наборы и справка.
# Библиотека открывается первой: 28 курсоров, 222 прицела, 6 панорам неба.
# Наборы - ZIP-пакеты, профили и два канала применения.
#
# Запуск:  python -m cursor_manager   (канонично)
from __future__ import annotations

import html
import io
import os
import re
import sys
from pathlib import Path, PurePosixPath

from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSize, QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizeGrip, QStackedWidget, QVBoxLayout, QWidget,
)

from cursor_manager.core import cursor_core as core
from cursor_manager.core import respack, roblox_paths as RP
from cursor_manager.core import pcboost
from cursor_manager.core import profiles as prof
from cursor_manager.core import rcur
from cursor_manager.ui.boost import FpsPage, ServersPage
from cursor_manager.ui.config_page import ConfigPage
from cursor_manager.content.fonts import _resource_root
from cursor_manager.ui.glass import GlassFrame, enable_acrylic, load_fonts
from cursor_manager.ui.help_page import HelpPage
from cursor_manager.ui import nav_icons
from cursor_manager.ui.motion import NavIndicator, fade_in, glow
from cursor_manager.ui.library import KIND_TITLE, LibraryPage
from cursor_manager.ui.shiftlock_editor import ShiftlockEditor
from cursor_manager.version import VERSION, APP_NAME

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_RCUR_SLOTS = {
    "arrow": "ArrowCursor.png",
    "far": "ArrowFarCursor.png",
    "ibeam": "IBeamCursor.png",
}

# Плоский чёрный интерфейс с синим светом (макет «sanyakiller111 — новый
# интерфейс» в Claude Design). Главное правило — никаких блоков в блоках:
# группы не обводятся рамками, их разделяет только пустое место. Плитки —
# это сам контент (превью), а не коробка вокруг него. Всё активное синее и
# светится (ui/motion.glow, NavIndicator); размытие рабочего стола — ui/glass.py.
BLUE_FILL = "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5b97ff, stop:1 #2f6bf0)"
HALO = ("qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.5, fy:0.5,"
        " stop:0 rgba(59,130,246,0.30), stop:0.7 rgba(59,130,246,0.05),"
        " stop:1 rgba(255,255,255,0.02))")

DARK_QSS = """
* { font-family:'Manrope','Segoe UI Variable Text','Segoe UI',sans-serif; font-size:13px; }
QWidget { background:transparent; color:#ffffff; }
QLabel, QCheckBox { background:transparent; }
QToolTip { background:#05070d; color:#ffffff; border:1px solid rgba(91,151,255,0.35);
    border-radius:8px; padding:6px 9px; }
QMessageBox, QDialog, QMenu, QInputDialog, QFileDialog, QColorDialog { background:#000000; }

QLabel#brand { font-family:'Unbounded'; font-size:14px; font-weight:700; }
QPushButton#winbtn, QPushButton#closebtn { background:transparent; border:none;
    border-radius:8px; color:rgba(255,255,255,0.5); font-size:14px; padding:0;
    min-width:40px; max-width:40px; min-height:30px; max-height:30px; }
QPushButton#winbtn:hover { background:rgba(255,255,255,0.08); color:#ffffff; }
QPushButton#closebtn:hover { background:rgba(239,68,68,0.9); color:#ffffff; }

QPushButton#nav { background:transparent; border:none; border-radius:12px;
    color:rgba(255,255,255,0.62); font-size:14px; text-align:left;
    padding:0 12px; min-height:40px; max-height:40px; }
QPushButton#nav:hover { background:rgba(255,255,255,0.04); color:#ffffff; }
QPushButton#nav[on="true"] { background:transparent; color:#ffffff; font-weight:700; }
QLabel#navcount { color:rgba(255,255,255,0.32); font-size:12px; }
QLabel#navcount[on="true"] { color:#8fb6ff; font-weight:600; }
QPushButton#social { background:transparent; border:none; border-radius:10px;
    padding:0; min-width:36px; max-width:36px; min-height:36px; max-height:36px; }
QPushButton#social:hover { background:rgba(255,255,255,0.07); }
QLabel#ok, QLabel#bad { color:rgba(255,255,255,0.45); font-size:12px; padding:0 12px; }
QLabel#status { color:rgba(255,255,255,0.32); font-size:11px; padding:0 12px; }

QLabel#h1, QLabel#pname { font-family:'Unbounded'; font-size:26px; font-weight:700; }
QLabel#h2 { font-family:'Unbounded'; font-size:20px; font-weight:700; }
QLabel#rowtitle { font-size:16px; font-weight:700; }
QLabel#pvname { font-size:15px; font-weight:700; }
QLabel#body, QLabel#dim, QLabel#sub, QLabel#mono, QLabel#tags, QLabel#kv
    { color:rgba(255,255,255,0.55); font-size:13px; }
QLabel#faint, QLabel#label { color:rgba(255,255,255,0.42); font-size:12px; }

QLineEdit#search { background:rgba(255,255,255,0.06); border:none; border-radius:19px;
    padding:0 16px; min-height:38px; max-height:38px; color:#ffffff; }
QLineEdit { background:rgba(255,255,255,0.06); border:none; border-radius:12px;
    padding:8px 12px; color:#ffffff; selection-background-color:#3b82f6; }
QLineEdit:focus, QLineEdit#search:focus { background:rgba(59,130,246,0.16); }

/* плитка — сам контент; никаких рамок вокруг карточки */
QFrame#card, QFrame#cardwrap, QFrame#panel, QFrame#slot, QFrame#chrome,
QWidget#center, QWidget#listhost { background:transparent; border:none; }
QLabel#tile, QLabel#stage, QFrame#tile { background:rgba(255,255,255,0.045); border:2px solid transparent;
    border-radius:20px; }
QLabel#tile:hover, QFrame#tile:hover { background:rgba(255,255,255,0.075); }
QLabel#tile[sel="true"], QFrame#tile[sel="true"], QLabel#stage[sel="true"]
    { background:rgba(59,130,246,0.16); border:2px solid rgba(91,151,255,0.8); }
QLabel#cardname { font-weight:700; font-size:14px; padding:0 2px; }
QLabel#cardname[sel="true"] { color:#8fb6ff; }
QLabel#cardcap { color:rgba(255,255,255,0.42); font-size:12px; padding:0 2px; }
QLabel#cardcap[on="true"] { color:#8fb6ff; }
QLabel#preview { background:@HALO; border:none; border-radius:24px; color:rgba(255,255,255,0.4); }

QPushButton { background:rgba(255,255,255,0.06); border:none; border-radius:12px;
    color:rgba(255,255,255,0.85); padding:9px 16px; font-weight:600; }
QPushButton:hover { background:rgba(255,255,255,0.10); color:#ffffff; }
QPushButton:checked { background:rgba(59,130,246,0.18); color:#ffffff; }
QPushButton:disabled { color:rgba(255,255,255,0.25); background:rgba(255,255,255,0.03); }
QPushButton#pill, QPushButton#ghost { background:rgba(255,255,255,0.06); border:none;
    border-radius:19px; padding:0 16px; min-height:38px; color:rgba(255,255,255,0.8); }
QPushButton#pill:hover, QPushButton#ghost:hover { background:rgba(255,255,255,0.10); color:#ffffff; }
QPushButton#textbtn, QPushButton#undo { background:transparent; border:none; border-radius:20px;
    color:rgba(255,255,255,0.6); padding:0 16px; min-height:40px; }
QPushButton#textbtn:hover, QPushButton#undo:hover { color:#ffffff; background:rgba(255,255,255,0.05); }
QPushButton#go { background:@BLUE_FILL; border:none; border-radius:20px; color:#ffffff;
    font-weight:700; font-size:14px; padding:0 20px; min-height:40px; }
QPushButton#go:hover { background:#5b97ff; }
QPushButton#go:disabled { background:rgba(59,130,246,0.14); color:rgba(255,255,255,0.35); }
QPushButton#warnbtn { background:transparent; border:1px solid rgba(255,255,255,0.3); color:#ffffff; }

QComboBox { background:rgba(255,255,255,0.06); border:none; border-radius:12px;
    padding:8px 12px; color:#ffffff; }
QComboBox:hover { background:rgba(255,255,255,0.09); }
QComboBox::drop-down { border:none; width:22px; }
QComboBox QAbstractItemView { background:#05070d; border:1px solid rgba(91,151,255,0.3);
    selection-background-color:rgba(59,130,246,0.35); selection-color:#ffffff; outline:0; }
QCheckBox { color:rgba(255,255,255,0.85); spacing:10px; }
QCheckBox::indicator { width:20px; height:20px; border:none; background:transparent;
    image:url("@CHECK_OFF"); }
QCheckBox::indicator:checked { image:url("@CHECK_ON"); }
QSlider::groove:horizontal { height:4px; background:rgba(255,255,255,0.10); border-radius:2px; }
QSlider::sub-page:horizontal { background:#3b82f6; border-radius:2px; }
QSlider::handle:horizontal { background:#ffffff; width:16px; height:16px; margin:-6px 0; border-radius:8px; }

QLabel#toast { background:rgba(8,14,32,0.95); border:1px solid rgba(91,151,255,0.6);
    border-radius:18px; color:#ffffff; font-weight:700; padding:10px 18px; }

QScrollArea { background:transparent; border:none; }
QScrollBar:vertical { background:transparent; width:8px; margin:2px; }
QScrollBar::handle:vertical { background:rgba(255,255,255,0.10); min-height:30px; border-radius:3px; }
QScrollBar::handle:vertical:hover { background:#3b82f6; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:none; }
QTableWidget { background:transparent; border:none; gridline-color:transparent;
    selection-background-color:rgba(59,130,246,0.25); selection-color:#ffffff; }
QTableWidget::item { padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.05); }
QHeaderView::section { background:transparent; color:rgba(255,255,255,0.42); border:none;
    padding:6px 8px; font-size:12px; font-weight:600; }
""".replace("@BLUE_FILL", BLUE_FILL).replace("@HALO", HALO)
_CHECK_OFF, _CHECK_ON = nav_icons.checkbox_images(respack.APP_ROOT / "cache" / "ui")
DARK_QSS = DARK_QSS.replace("@CHECK_OFF", _CHECK_OFF).replace("@CHECK_ON", _CHECK_ON)

def _label(text: str, obj: str = "") -> QLabel:
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    return lab


class ResourcesPage(QWidget):
    """
    Ресурсы Roblox: категории, наборы, канал применения, профили.

    Всё состояние живёт здесь. Страница пересоздаётся целиком при смене
    вкладки, поэтому выбор категории и отметки наборов хранятся в полях
    и восстанавливаются при возврате.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = RP.KIND_CURSOR
        self.packs: list = []
        self.pack_checks: dict = {}
        self.selected: set[str] = set()
        self.profiles = prof.ensure_starter()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        root.addLayout(self._build_head())
        root.addLayout(self._build_categories())

        self.note = _label("", "dim")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        tools = QHBoxLayout()
        self.pack_count = _label("", "dim")
        tools.addWidget(self.pack_count)
        tools.addStretch(1)
        imp = QPushButton("Импорт ZIP")
        imp.setToolTip(
            "Набор - это ZIP с pack.json и файлами Roblox.\n"
            "Отклоняются: выход за пределы папки, симлинки, дубли\n"
            "имён, исполняемые файлы, превышение лимитов.")
        imp.clicked.connect(self.import_pack)
        tools.addWidget(imp)
        imp_rcur = QPushButton("Импорт .rcur")
        imp_rcur.setToolTip(
            "Применить готовый .rcur: стрелка, дальняя стрелка и IBeam.\n"
            "Масштаб и смещение из файла сохраняются.")
        imp_rcur.clicked.connect(self.import_rcur)
        tools.addWidget(imp_rcur)
        openlib = QPushButton("Папка наборов")
        openlib.clicked.connect(self.open_library)
        tools.addWidget(openlib)
        root.addLayout(tools)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.list = QVBoxLayout(self.host)
        self.list.setSpacing(8)
        self.list.setContentsMargins(2, 2, 2, 2)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        root.addWidget(self._build_profiles())

        self.status = _label("", "mono")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.select_kind(self.kind)

    # -- построение ---------------------------------------------------------
    def _build_head(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(_label("Ресурсы Roblox", "pvname"))
        row.addStretch(1)
        return row

    def _build_categories(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cat_btns: dict = {}
        for key in RP.ORDER:
            b = QPushButton(RP.get(key).label)
            b.setCheckable(True)
            b.clicked.connect(lambda _checked=False, k=key: self.select_kind(k))
            self.cat_btns[key] = b
            row.addWidget(b)
        row.addStretch(1)
        reset = QPushButton("Полный сброс")
        reset.setToolTip("Снять все наборы из библиотеки и вернуть оригиналы\n"
                         "из бэкапа. Файлы Roblox, которых нет ни в одном\n"
                         "наборе, останутся нетронутыми.")
        reset.clicked.connect(self.reset_all)
        row.addWidget(reset)
        return row

    def _build_profiles(self) -> QWidget:
        box = QFrame()
        box.setObjectName("chrome")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(_label("Профили - наборы, которые применяются вместе", "dim"))

        row = QHBoxLayout()
        self.prof_sel = QComboBox()
        self.prof_sel.setMinimumWidth(150)
        for nm in self.profiles.names():
            self.prof_sel.addItem(nm)
        self.prof_sel.currentIndexChanged.connect(self._on_profile_pick)
        row.addWidget(self.prof_sel)

        save = QPushButton("Сохранить текущий")
        save.setToolTip("Сохранить профиль из отмеченных наборов.")
        save.clicked.connect(self.save_profile)
        row.addWidget(save)
        row.addWidget(self._mk("Применить", self.apply_profile))
        row.addWidget(self._mk("Снять", self.revert_profile))
        delbtn = self._mk("Удалить", self.delete_profile)
        delbtn.setToolTip("Удалить профиль. Наборы останутся на месте.")
        row.addWidget(delbtn)
        row.addStretch(1)
        lay.addLayout(row)
        return box

    def _mk(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(slot)
        return b

    # -- категории и список --------------------------------------------------
    def select_kind(self, key: str) -> None:
        self.kind = key
        for k, b in self.cat_btns.items():
            b.setChecked(k == key)
        kind = RP.get(key)
        text = kind.hint
        if kind.caveat:
            text += "\n" + kind.caveat
        self.note.setText(text)
        self.refresh()

    def refresh(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # отметки держим между перерисовками и категориями: профиль может
        # состоять из наборов разных категорий
        self.pack_checks = {}

        self.packs = respack.scan_library(prof.library_root())
        valid = {p.id for p, e in self.packs if not e}
        self.selected &= valid
        mine = [(p, e) for p, e in self.packs if p.meta.kind == self.kind and not e]
        broken = [e for _, e in self.packs if e]
        self.pack_count.setText(
            f"наборов: {len(mine)}   повреждённых: {len(broken)}")

        if not mine:
            lab = _label("В этой категории пока нет наборов.\n"
                         "Импортируйте ZIP кнопкой сверху.", "dim")
            lab.setAlignment(Qt.AlignCenter)
            lab.setMinimumHeight(90)
            self.list.addWidget(lab)

        for pack, _ in mine:
            self.list.addWidget(self._pack_row(pack))
        self.list.addStretch(1)

    def _pack_row(self, pack) -> QWidget:
        row = QFrame()
        row.setObjectName("chrome")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)

        cb = QCheckBox()
        cb.setToolTip("Отметить, чтобы набор вошёл в профиль")
        cb.setChecked(pack.id in self.selected)
        cb.toggled.connect(
            lambda checked, pid=pack.id: self._on_pack_toggled(pid, checked))
        self.pack_checks[pack.id] = cb
        h.addWidget(cb, 0, Qt.AlignTop)

        if pack.preview and pack.preview.is_file():
            pm = QPixmap(str(pack.preview))
            if not pm.isNull():
                stage = QLabel()
                stage.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
                stage.setFixedSize(60, 60)
                h.addWidget(stage)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label(pack.meta.name, "pvname"))

        bits = [RP.get(pack.meta.kind).label]
        if pack.meta.author:
            bits.append(pack.meta.author)
        bits.append(pack.meta.license)
        bits.append(f"{len(pack.files)} файл(ов)")
        if pack.meta.version:
            bits.append(f"v{pack.meta.version}")
        col.addWidget(_label(" · ".join(bits), "mono"))

        if pack.meta.description:
            d = _label(pack.meta.description, "dim")
            d.setWordWrap(True)
            col.addWidget(d)
        if pack.missing:
            w = _label("не хватает: " + ", ".join(pack.missing), "mono")
            w.setWordWrap(True)
            col.addWidget(w)
        if pack.preview is None and pack.meta.source_url.startswith(
                ("https://", "http://")):
            url = html.escape(pack.meta.source_url, quote=True)
            link = QLabel(f'<a href="{url}">источник</a>')
            link.setOpenExternalLinks(True)
            link.setStyleSheet("color:#ffffff; text-decoration:underline;")
            col.addWidget(link)
        h.addLayout(col, 1)

        note = pack.safety_note()
        if note:
            warn = QPushButton("!")
            warn.setObjectName("warnbtn")
            warn.setToolTip(note)
            warn.setFixedWidth(28)
            h.addWidget(warn, 0, Qt.AlignTop)

        btns = QVBoxLayout()
        btns.setSpacing(4)
        btns.addWidget(self._mk("Применить", lambda p=pack: self.apply_pack(p)))
        btns.addWidget(self._mk("Снять", lambda p=pack: self.revert_pack(p)))
        chk = self._mk("Проверить", lambda p=pack: self.check_pack(p))
        chk.setToolTip("Сравнить файлы в папке Roblox с файлами набора.")
        btns.addWidget(chk)
        h.addLayout(btns)
        return row

    def _on_pack_toggled(self, pack_id: str, checked: bool) -> None:
        if checked:
            self.selected.add(pack_id)
        else:
            self.selected.discard(pack_id)

    # -- операции с набором --------------------------------------------------
    def _roblox_dir(self):
        d = core.resolve_roblox_dir()
        return Path(d) if d else None

    def _backend_key(self) -> str:
        return "direct"

    def _need_roblox(self):
        d = self._roblox_dir()
        if d is None:
            QMessageBox.warning(self, "Roblox не найден",
                                "Сначала установите Roblox. Приложение ищет\n"
                                "папку версии в реестре и в стандартных путях.")
        return d

    def apply_pack(self, pack) -> None:
        d = self._need_roblox()
        if d is None:
            return
        backend = self._backend_key()
        try:
            res = respack.install(pack, d, backend)
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Не применилось", str(exc))
            return
        lines = [f"{res['kind_label']} -> {backend}",
                 f"Файлов поставлено: {len(res['installed'])}"]
        if res["skipped"]:
            lines.append("Пропущено:")
            lines += [f"  · {s}" for s in res["skipped"]]
        lines.append("Запусти Roblox заново. После обновления клиента "
                     "программа при запуске поставит выбранное обратно.")
        self.status.setText("\n".join(lines))

    def revert_pack(self, pack) -> None:
        d = self._need_roblox()
        if d is None:
            return
        try:
            res = respack.uninstall(pack, d, self._backend_key())
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Не снялось", str(exc))
            return
        self.status.setText(
            f"Снято: {len(res['removed'])}, "
            f"возвращено из бэкапа: {len(res['restored'])}\n"
            + (f"Пропущено: {len(res['skipped'])}.\n"
               if res["skipped"] else "")
            + "Запусти Roblox заново, чтобы он перечитал файлы.")

    def check_pack(self, pack) -> None:
        d = self._need_roblox()
        if d is None:
            return
        rows = []
        for rel in pack.files:
            name = PurePosixPath(rel).name
            live = RP.destination(self._backend_key(), d, pack.meta.kind, name)
            src = pack.root / rel
            if not live.is_file():
                rows.append(f"  нет на месте: {name}")
            elif respack.sha256_of(live) != respack.sha256_of(src):
                rows.append(f"  отличается от набора: {name}")
            else:
                rows.append(f"  совпадает: {name}")
        self.status.setText("\n".join(rows) or "Набор пуст")

    def reset_all(self) -> None:
        d = self._need_roblox()
        if d is None:
            return
        if QMessageBox.question(
                self, "Полный сброс",
                "Снять все наборы из библиотеки и вернуть оригиналы\n"
                "из бэкапа? Файлы Roblox, которых нет ни в одном наборе,\n"
                "останутся нетронутыми."
        ) != QMessageBox.Yes:
            return
        res = self.profiles.reset_everything(d, self._backend_key())
        self.status.setText(
            f"Снято: {len(res['removed'])}, "
            f"возвращено: {len(res['restored'])}\n"
            + (f"Пропущено: {len(res['skipped'])}.\n"
               if res["skipped"] else "")
            + ("\n".join(res["failed"]) if res["failed"] else ""))

    def import_pack(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт набора", "", "ZIP-архивы (*.zip)")
        if not path:
            return
        try:
            pack = respack.import_zip(path, prof.library_root())
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Импорт отклонён", str(exc))
            return
        self.select_kind(pack.meta.kind)
        note = pack.safety_note()
        self.status.setText(
            f"Импортирован: {pack.meta.name}\n"
            + (note if note else "Нажми «Применить», чтобы поставить его в Roblox."))

    # -- .rcur ---------------------------------------------------------------
    def _rcur_pack(self, set_: rcur.RcurSet, version_dir: Path,
                   stem: str) -> respack.Pack:
        kind = RP.get(RP.KIND_CURSOR)
        safe = _SAFE_NAME.sub("-", stem).strip(".-")[:48] or "rcur"
        cache_dir = respack.APP_ROOT / "cache" / "rcur"
        files: dict[str, Path] = {}
        preview = None
        for slot, blob in set_:
            filename = _RCUR_SLOTS.get(slot)
            if not filename or not blob:
                continue
            live = version_dir / kind.rel(filename)
            size = (64, 64)
            if live.is_file():
                try:
                    with Image.open(live) as im:
                        size = im.size
                except OSError:
                    pass
            try:
                with Image.open(io.BytesIO(blob)) as im:
                    fitted = core.fit_cursor(
                        im.convert("RGBA"), size,
                        set_.scale / 100, set_.nudge)
            except OSError as exc:
                raise respack.PackError(
                    f"{filename}: PNG не читается: {exc}") from exc
            cache = cache_dir / f"{safe}-{filename}"
            cache.parent.mkdir(parents=True, exist_ok=True)
            fitted.save(cache, "PNG")
            files[filename] = cache
            preview = preview or cache
        if not files:
            raise respack.PackError("в .rcur нет ни одной картинки")
        license_id = str(set_.extra.get("license") or "UNKNOWN")
        meta = respack.PackMeta(
            name=set_.name or stem, author=str(set_.extra.get("author") or ""),
            license=license_id if license_id in RP.LICENSES else "UNKNOWN",
            kind=RP.KIND_CURSOR, description=set_.blurb, tags=["rcur"])
        return respack.Pack(
            meta=meta, root=Path("rcur") / safe,
            files=files, preview=preview)

    def apply_rcur_file(self, path: str | Path, confirm: bool = False) -> None:
        version_dir = self._need_roblox()
        if version_dir is None:
            return
        try:
            set_ = rcur.load(path)
        except (rcur.RcurError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Файл .rcur не открылся", str(exc))
            return
        if confirm and QMessageBox.question(
                self, "Применить .rcur",
                f"Применить «{set_.name or Path(path).stem}» к Roblox?\n"
                "Оригиналы будут сохранены в бэкап."
        ) != QMessageBox.Yes:
            return
        try:
            pack = self._rcur_pack(set_, version_dir, Path(path).stem)
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Файл .rcur не готов", str(exc))
            return
        backend = self._backend_key()
        try:
            result = respack.install(pack, version_dir, backend)
        except (respack.PackError, OSError) as exc:
            QMessageBox.critical(self, "Файл .rcur не применился", str(exc))
            return
        self.status.setText(
            f"{pack.meta.name}: применено {len(result['installed'])} файл(ов), "
            f"канал {backend}. Снять — «Снять всё» в Библиотеке.")

    def import_rcur(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт .rcur", "", "Курсоры (*.rcur);;Все файлы (*.*)")
        if path:
            self.apply_rcur_file(path, confirm=True)

    def open_library(self) -> None:
        root = prof.library_root()
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(str(root))

    # -- профили -------------------------------------------------------------
    def save_profile(self) -> None:
        text, ok = QInputDialog.getText(self, "Имя профиля", "Название:")
        name = text.strip() if ok else ""
        if not ok:
            return
        if not name:
            QMessageBox.warning(self, "Имя профиля", "Введите имя профиля.")
            return
        selected = sorted(self.selected)
        try:
            self.profiles.save_current(name, selected, self._backend_key())
        except prof.ProfileError as exc:
            QMessageBox.critical(self, "Не сохранилось", str(exc))
            return
        idx = self.prof_sel.findText(name)
        if idx < 0:
            self.prof_sel.addItem(name)
            idx = self.prof_sel.findText(name)
        self.prof_sel.setCurrentIndex(idx)
        self.status.setText(
            f"Профиль «{name}» сохранён. Наборов в нём: {len(selected)}."
            + ("" if selected else " Отметь наборы - сейчас состав пустой."))

    def _on_profile_pick(self, idx: int) -> None:
        p = self.profiles.get(self.prof_sel.itemText(idx))
        if not p:
            return
        lines = [f"Профиль «{p.name}» · канал {p.backend} · наборов: {len(p.packs)}"]
        if p.saved_at:
            lines.append(f"Сохранён: {p.saved_at}")
        try:
            clashes = self.profiles.collisions(p.name)
        except prof.ProfileError:
            clashes = []
        if clashes:
            lines.append("Коллизии:")
            lines += [f"  {c}" for c in clashes]
        d = self._roblox_dir()
        if d is not None and p.packs:
            try:
                st = self.profiles.status(p.name, d)
            except prof.ProfileError as exc:
                self.status.setText(str(exc))
                return
            drift = [r for r in st["packs"] if not r["ok"]]
            if drift:
                lines.append("Расхождения с папкой Roblox:")
                lines += [f"  {r['why']}" for r in drift]
            else:
                lines.append("Все наборы на месте и совпадают с папкой Roblox.")
        self.status.setText("\n".join(lines))

    def apply_profile(self) -> None:
        name = self.prof_sel.currentText()
        d = self._need_roblox()
        if not name or d is None:
            return
        try:
            clashes = self.profiles.collisions(name)
        except prof.ProfileError as exc:
            QMessageBox.critical(self, "Профиль не прочитался", str(exc))
            return
        if clashes and QMessageBox.question(
                self, "Коллизия в профиле",
                "Наборы забивают друг друга за одни и те же файлы:\n\n  "
                + "\n  ".join(clashes)
                + "\n\nПрименённый последним победит, остальные будут\n"
                  "перебиты. Всё равно применить?"
        ) != QMessageBox.Yes:
            return
        try:
            res = self.profiles.apply(name, d)
        except prof.ProfileError as exc:
            QMessageBox.critical(self, "Не применилось", str(exc))
            return
        rows = [f"Профиль «{name}» · канал {res['backend']}"]
        rows += [f"  {a['name']} - {len(a['files'])} файл(ов)" for a in res["applied"]]
        rows += [f"  {f}" for f in res["failed"]]
        if clashes:
            rows.append("")
            rows.append("Коллизии (победил применённый последним):")
            rows += [f"  {c}" for c in clashes]
        self.status.setText("\n".join(rows))

    def revert_profile(self) -> None:
        name = self.prof_sel.currentText()
        d = self._need_roblox()
        if not name or d is None:
            return
        try:
            res = self.profiles.revert(name, d)
        except prof.ProfileError as exc:
            QMessageBox.critical(self, "Не снялось", str(exc))
            return
        rows = [f"Профиль «{name}» снят"]
        rows += [f"  {a['name']}: снято {len(a['removed'])}, "
                 f"возвращено {len(a['restored'])}, "
                 f"пропущено {len(a.get('skipped', []))}"
                 for a in res["reverted"]]
        rows += [f"  {f}" for f in res["failed"]]
        self.status.setText("\n".join(rows))

    def delete_profile(self) -> None:
        name = self.prof_sel.currentText()
        if not name:
            return
        if QMessageBox.question(self, "Удалить профиль",
                                f"Удалить профиль «{name}»?\n"
                                "Наборы останутся на месте."
        ) != QMessageBox.Yes:
            return
        if self.profiles.remove(name):
            idx = self.prof_sel.findText(name)
            if idx >= 0:
                self.prof_sel.removeItem(idx)
            self.status.setText(f"Профиль «{name}» удалён.")


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(8)
        lay.addWidget(_label(APP_NAME, "pname"))
        lay.addWidget(_label(f"версия {VERSION}", "mono"))
        lay.addSpacing(10)

        lay.addWidget(_label("Что это", "label"))
        lay.addWidget(_label(
            "Меняет файлы, которые Roblox читает из своей папки: курсор,\n"
            "точку shift lock и skybox. Всё вшито в программу и работает\n"
            "без интернета; оригиналы сохраняются в бэкап."))
        lay.addSpacing(6)

        lay.addWidget(_label("Как применяется", "label"))
        lay.addWidget(_label(
            "Файлы пишутся прямо в папку Roblox. После обновления клиента\n"
            "программа при запуске ставит выбранное обратно."))
        lay.addSpacing(6)

        lay.addWidget(_label("Бэкап", "label"))
        lay.addWidget(_label(
            f"Перед первой заменой оригинал снимается в\n{respack.BACKUP_ROOT}\n"
            "и не перезаписывается. «вернуть оригинал» берёт файл оттуда."))
        lay.addSpacing(6)

        lay.addWidget(_label("Чего программа не делает", "label"))
        lay.addWidget(_label(
            "Не просит логин Roblox, не читает cookies и токены, не меняет\n"
            ".exe, не работает в фоне, не инжектится в Roblox. В интернет\n"
            "ходит только «лучший сервер» — к открытому списку серверов Roblox."))
        lay.addStretch(1)


SOCIALS = (
    ("telegram", "Телеграм @sanyakiller111", "https://t.me/sanyakiller111"),
    ("youtube", "YouTube", "https://www.youtube.com/@sanyakiller111"),
)


class WinButton(QPushButton):
    """Кнопка окна без фокуса; hover сбрасывается принудительно (см. reset_hover)."""

    def __init__(self, text: str, obj: str, tip: str):
        super().__init__(text)
        self.setObjectName(obj)
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFlat(True)

    def reset_hover(self) -> None:
        # у безрамочного окна после minimize/maximize/startSystemMove Leave не
        # приходит, и кнопка остаётся подсвеченной, пока мышь уже ушла
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self.setAttribute(Qt.WA_UnderMouse, False)
            QApplication.sendEvent(self, QEvent(QEvent.Leave))
            self.update()


class TitleBar(QWidget):
    """Своя полоса заголовка: у системной рамки Windows нельзя перекрасить ✕."""

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self.setObjectName("titlebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(44)
        self._window = window
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 0, 0)
        lay.setSpacing(0)
        brand = QLabel('<span style="color:#3b82f6">RO</span>cursor')
        brand.setObjectName("brand")
        brand.setTextFormat(Qt.RichText)
        lay.addWidget(brand)
        lay.addStretch(1)
        self.btn_min = WinButton("—", "winbtn", "свернуть")
        self.btn_max = WinButton("☐", "winbtn", "развернуть")
        self.btn_close = WinButton("✕", "closebtn", "закрыть")
        self.btn_min.clicked.connect(self._minimize)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(window.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

    def reset_hover(self) -> None:
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.reset_hover()

    def sync_state(self) -> None:
        """Иконка «развернуть»/«восстановить» и сброс залипшей подсветки."""
        maxed = self._window.isMaximized()
        self.btn_max.setText("❐" if maxed else "☐")
        self.btn_max.setToolTip("восстановить" if maxed else "развернуть")
        self.reset_hover()

    def _minimize(self) -> None:
        self._window.showMinimized()
        QTimer.singleShot(0, self.reset_hover)

    def _toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        QTimer.singleShot(0, self.sync_state)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._window.windowHandle():
            self._window.windowHandle().startSystemMove()
            QTimer.singleShot(0, self.reset_hover)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._toggle_max()


class MainWindow(QMainWindow):
    (PAGE_LIBRARY, PAGE_CONFIG, PAGE_PACKS, PAGE_ABOUT, PAGE_FPS, PAGE_SERVERS,
     PAGE_EDITOR, PAGE_HELP) = range(8)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(1240, 780)
        self.setMinimumSize(980, 620)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        frame = GlassFrame()
        self.setCentralWidget(frame)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(10, 0, 4, 0)
        outer.setSpacing(0)
        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        outer.addLayout(body, 1)

        self.library = LibraryPage()
        self.config_page = ConfigPage(self.library)
        self.resources = ResourcesPage()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.config_page)
        self.stack.addWidget(self.resources)
        self.stack.addWidget(AboutPage())
        self.fps_page = FpsPage(self.library)
        self.servers_page = ServersPage(self.library)
        self.stack.addWidget(self.fps_page)
        self.stack.addWidget(self.servers_page)
        self.editor = ShiftlockEditor()
        self.stack.addWidget(self.editor)
        self.editor.saved.connect(self._editor_saved)
        self.help_page = HelpPage(self.library)
        self.stack.addWidget(self.help_page)
        self.help_page.updateFound.connect(
            lambda ver, url: self.notify(f"вышла версия {ver} — вкладка «Фиксы»", True))

        body.addWidget(self._build_side())
        body.addWidget(self.stack, 1)
        self.grip = QSizeGrip(frame)
        self.grip.resize(16, 16)

        self.toast = QLabel(frame)
        self.toast.setObjectName("toast")
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)

        self.library.message.connect(self.notify)
        self.config_page.pickRequested.connect(self.show_kind)
        self.show_kind(RP.KIND_CURSOR)
        self._update_roblox()

    # -- боковое меню ----------------------------------------------------------
    # пункты меню: ключ, подпись, иконка; None — пустое место между группами
    NAV = (
        (RP.KIND_CURSOR, None, "cursor"), (RP.KIND_CROSSHAIR, None, "crosshair"),
        (RP.KIND_SKY, None, "sky"), (RP.KIND_MATERIAL, None, "material"),
        (RP.KIND_SOUND, None, "sound"), (RP.KIND_FONT, None, "font"),
        ("editor", "Конструктор", "editor"),
        None,
        ("fps", "FPS буст", "fps"), ("servers", "Лучший сервер", "servers"),
        ("help", "Фиксы", "help"), ("config", "Config", "config"),
        ("about", "О программе", "about"),
    )

    def _build_side(self) -> QWidget:
        """Боковое меню — строки прямо на фоне окна, без панели и заголовков."""
        side = QWidget()
        side.setObjectName("side")
        side.setFixedWidth(208)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(6, 18, 12, 14)
        lay.setSpacing(2)
        self.side = side
        self._nav_key = ""
        self.nav: dict[str, QPushButton] = {}
        self._nav_icon: dict[str, str] = {}
        pages = {"editor": self.PAGE_EDITOR, "fps": self.PAGE_FPS,
                 "servers": self.PAGE_SERVERS, "help": self.PAGE_HELP,
                 "config": self.PAGE_CONFIG, "about": self.PAGE_ABOUT}

        for item in self.NAV:
            if item is None:
                lay.addSpacing(22)
                continue
            key, title, icon_name = item
            if title is None:
                kind_title = KIND_TITLE[key]
                title = kind_title[:1].upper() + kind_title[1:]
                slot = lambda _=False, k=key: self.show_kind(k)
                count = len(self.library.items_of(key))
            else:
                slot = lambda _=False, i=pages[key]: self.show_page(i)
                count = None
            b = QPushButton(title)
            b.setObjectName("nav")
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setIcon(nav_icons.icon(icon_name, "#9a9aa0"))
            b.setIconSize(QSize(18, 18))
            if count is not None:
                row = QHBoxLayout(b)
                row.setContentsMargins(0, 0, 12, 0)
                row.addStretch(1)
                cnt = _label(str(count), "navcount")
                cnt.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                row.addWidget(cnt)
            b.clicked.connect(slot)
            self.nav[key] = b
            self._nav_icon[key] = icon_name
            lay.addWidget(b)
        lay.addStretch(1)

        socials = QHBoxLayout()
        socials.setContentsMargins(8, 0, 0, 0)
        socials.setSpacing(6)
        for brand, text, url in SOCIALS:
            b = QPushButton()
            b.setObjectName("social")
            b.setIcon(nav_icons.brand_icon(brand, 24))
            b.setIconSize(QSize(24, 24))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(text)
            b.setAccessibleName(text)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            socials.addWidget(b)
        socials.addStretch(1)
        lay.addLayout(socials)
        lay.addSpacing(6)
        self.roblox_label = _label("", "ok")
        lay.addWidget(self.roblox_label)
        self.version_label = _label("", "status")
        self.version_label.hide()
        self.status_text = _label("", "status")
        self.status_text.setWordWrap(True)
        lay.addWidget(self.status_text)
        self.nav_ind = NavIndicator(side)
        return side

    def _update_roblox(self) -> None:
        try:
            version_dir = core.resolve_roblox_dir()
        except OSError:
            version_dir = None
        found = version_dir is not None
        dot = "#3b82f6" if found else "rgba(255,255,255,0.3)"
        self.roblox_label.setTextFormat(Qt.RichText)
        self.roblox_label.setText(
            f'<span style="color:{dot}">●</span>&nbsp; '
            + ("Roblox найден" if found else "Roblox не найден"))
        self.roblox_label.setObjectName("ok" if found else "bad")
        self.roblox_label.style().unpolish(self.roblox_label)
        self.roblox_label.style().polish(self.roblox_label)
        self.version_label.setText(version_dir.name if found else "")

    def notify(self, text: str, toast: bool = False) -> None:
        self.status_text.setText(text)
        if not toast:
            return
        self.toast.setText(text)
        self.toast.adjustSize()
        frame = self.centralWidget()
        self.toast.move((frame.width() - self.toast.width()) // 2,
                        frame.height() - self.toast.height() - 44)
        self.toast.raise_()
        self.toast.show()
        fade_in(self.toast, dy=14, ms=260)
        self._toast_timer.start(3500)

    # -- навигация -----------------------------------------------------------
    def _switch(self, index: int, changed: bool) -> None:
        """Сменить страницу; новая проявляется снизу вверх."""
        self.stack.setCurrentIndex(index)
        if changed and self.isVisible():
            fade_in(self.stack.currentWidget())

    def show_kind(self, kind: str) -> None:
        changed = (self.stack.currentIndex() != self.PAGE_LIBRARY
                   or self.library.kind != kind)
        self.library.set_kind(kind)
        self._switch(self.PAGE_LIBRARY, changed)
        self._check_nav(kind)

    def show_page(self, index: int) -> None:
        self._switch(index, self.stack.currentIndex() != index)
        key = {self.PAGE_CONFIG: "config",
               self.PAGE_PACKS: "",
               self.PAGE_ABOUT: "about", self.PAGE_FPS: "fps",
               self.PAGE_SERVERS: "servers",
               self.PAGE_EDITOR: "editor",
               self.PAGE_HELP: "help"}.get(index, self.library.kind)
        self._check_nav(key)

    def _check_nav(self, key: str) -> None:
        for k, b in self.nav.items():
            on = k == key
            if b.property("on") == on:
                continue
            b.setProperty("on", on)
            b.setIcon(nav_icons.icon(self._nav_icon[k], "#8fb6ff" if on else "#9a9aa0"))
            for w in [b, *b.findChildren(QLabel)]:
                w.setProperty("on", on)
                w.style().unpolish(w)
                w.style().polish(w)
        self._nav_key = key
        self._place_indicator(animate=True)

    def _place_indicator(self, animate: bool = False) -> None:
        """Синяя плашка с ореолом под активным пунктом."""
        ind = getattr(self, "nav_ind", None)
        b = self.nav.get(self._nav_key)
        if ind is None or not self.isVisible():
            return
        if b is None:
            ind.hide()
            return
        ind.move_to(QRect(b.mapTo(self.side, QPoint(0, 0)), b.size()), animate)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        frame = self.centralWidget()
        if hasattr(self, "grip"):
            self.grip.move(frame.width() - 16, frame.height() - 16)
            self.grip.raise_()

    def _editor_saved(self, item_id: str, apply: bool) -> None:
        """Конструктор сохранил shiftlock: показать его в библиотеке и, если надо, поставить."""
        self.show_kind(RP.KIND_CROSSHAIR)
        self.library.added_custom(RP.KIND_CROSSHAIR, item_id)
        if apply:
            self.library._apply_selected()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_glass_tried", False):
            self._glass_tried = True
            frame = self.centralWidget()
            frame.glass = enable_acrylic(self)
            frame.update()
            # главные кнопки светятся синим; ищем после сборки всех страниц
            for b in self.findChildren(QPushButton):
                if b.objectName() in ("go", "skPrimary"):
                    glow(b)
            QTimer.singleShot(0, self._place_indicator)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "titlebar"):
            self.titlebar.sync_state()

    def restore_on_start(self) -> None:
        """Roblox обновился с прошлого запуска — вернуть выбранное из config."""
        names = self.library.restore_config()
        if pcboost.refresh_gpu():
            names.append("видеокарта для roblox")
        if names:
            self.notify("roblox обновился — вернул: " + ", ".join(names), True)


def _rcur_arg(argv: list[str]) -> str | None:
    """Путь из ярлыка .rcur: app.exe --apply file.rcur или app.exe file.rcur."""
    args = list(argv[1:])
    if "--apply" in args:
        index = args.index("--apply")
        if index + 1 < len(args):
            return args[index + 1]
        return None
    for arg in args:
        if arg.lower().endswith(".rcur"):
            return arg
    return None


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    # своё окно без рамки: без явной иконки на панели задач будет значок Qt
    icon_file = _resource_root() / "icons" / "icon.ico"
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))
    load_fonts()
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    win.show()
    pending = _rcur_arg(sys.argv)
    if pending:
        win.show_page(MainWindow.PAGE_PACKS)
        QTimer.singleShot(0, lambda: win.resources.apply_rcur_file(pending))
    else:
        QTimer.singleShot(200, win.restore_on_start)
    # тихая проверка обновлений: сеть в фоне, при ошибке — молчим
    QTimer.singleShot(3000, win.help_page.check_updates)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())