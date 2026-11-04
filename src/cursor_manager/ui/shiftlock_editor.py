"""
shiftlock_editor.py — конструктор shiftlock: форма, размеры, цвет, обводка,
свечение, живое превью и готовые пресеты.

Рисует content.custom.draw_shiftlock (всё рисование там), сохраняет результат
как свой элемент категории shiftlock вместе с параметрами, чтобы рисунок был
воспроизводимым. Применение — обычным путём библиотеки (сигнал saved ловит
MainWindow), поэтому здесь нет записи в Roblox.
"""
from __future__ import annotations

import random

from PIL import Image, ImageDraw
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSlider,
    QVBoxLayout, QWidget,
)

from cursor_manager.content import custom

SWATCHES = (("белый", "#ffffff"), ("красный", "#ff3b3b"), ("зелёный", "#22c55e"),
            ("синий", "#3b82f6"), ("жёлтый", "#ffd400"), ("розовый", "#ff4fd8"),
            ("голубой", "#00e5ff"), ("чёрный", "#000000"))
BACKDROPS = (("тёмный", "dark"), ("светлый", "light"), ("игровой", "game"))
# формы в редакторе; «крест + точка» собирается из креста и галочки «точка»
EDITOR_SHAPES = ("dot", "circle", "circle_dot", "cross", "cross_gap", "plus",
                 "x", "t", "square", "diamond", "triangle", "chevron")
BIG = 288          # сторона большого превью
PER_ROW = 6

# слайдеры: ключ параметра, подпись, мин, макс, значение, суффикс
SLIDERS = {
    "size": ("длина линий", 4, 60, 22, " px"),
    "scale": ("размер", 40, 180, 100, " %"),
    "thickness": ("толщина линий", 1, 20, 6, " px"),
    "gap": ("зазор", 0, 30, 8, " px"),
    "dot_size": ("точка в центре", 2, 20, 5, " px"),
    "rotation": ("поворот", 0, 359, 0, "°"),
    "opacity": ("непрозрачность", 10, 100, 100, " %"),
    "outline": ("толщина обводки", 1, 8, 2, " px"),
    "glow_strength": ("сила свечения", 1, 10, 4, ""),
}

BASE = dict(shape="cross", color="#ffffff", size=22, scale=100, thickness=6,
            gap=8, dot_size=5, rotation=0, opacity=100, center_dot=True,
            filled=False, outline=2, outline_color="#000000", glow=False,
            glow_color="#00e5ff", glow_strength=4)

PRESETS = (
    ("Классика", dict(shape="cross", center_dot=True, color="#ffffff")),
    ("Точка", dict(shape="dot", center_dot=True, color="#ffffff", dot_size=6)),
    ("Кольцо", dict(shape="circle", center_dot=False, color="#ffffff",
                    size=12, thickness=3)),
    ("Снайпер", dict(shape="cross_gap", center_dot=False, color="#ff3b3b",
                     size=26, thickness=3, gap=10)),
    ("Неон", dict(shape="cross", center_dot=True, color="#00e5ff", thickness=4,
                  size=20, glow=True, glow_color="#00e5ff", glow_strength=6,
                  outline=1, outline_color="#0b0b0e")),
    ("Красный X", dict(shape="x", center_dot=False, color="#ff3b3b", size=18,
                       thickness=5, gap=4)),
    ("Ромб", dict(shape="diamond", center_dot=True, color="#ffd400", size=18,
                  thickness=4)),
    ("Мишень", dict(shape="circle_dot", center_dot=True, color="#22c55e",
                    size=14, thickness=3)),
    ("Шеврон", dict(shape="chevron", center_dot=False, color="#ff4fd8", size=18,
                    thickness=5)),
    ("Пиксель", dict(shape="square", center_dot=True, color="#ffffff", size=10,
                     thickness=3, outline=1)),
)

STYLE = """
QWidget#shiftlockEditor { background: transparent; }
QWidget#shiftlockEditor QLabel { background: transparent; }
QWidget#shiftlockEditor QLabel#skMuted { color: rgba(255,255,255,0.42); font-size: 12px; }
QWidget#shiftlockEditor QLabel#skValue { color: rgba(255,255,255,0.55); font-size: 12px; }
QWidget#shiftlockEditor QFrame#skStage { background: rgba(255,255,255,0.045); border: none; border-radius: 20px; }
QWidget#shiftlockEditor QScrollArea { background: transparent; border: none; }
QWidget#shiftlockEditor QScrollArea > QWidget > QWidget { background: transparent; }
QWidget#shiftlockEditor QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,0.12); border-radius: 2px; }
QWidget#shiftlockEditor QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 2px; }
QWidget#shiftlockEditor QSlider::handle:horizontal { background: #ffffff; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QWidget#shiftlockEditor QSlider:disabled::sub-page:horizontal { background: rgba(255,255,255,0.12); }
QWidget#shiftlockEditor QSlider::handle:horizontal:disabled { background: rgba(255,255,255,0.3); }
QWidget#shiftlockEditor QPushButton { background: rgba(255,255,255,0.045); color: #ffffff; border: 2px solid transparent; border-radius: 12px; padding: 7px 14px; font-size: 13px; }
QWidget#shiftlockEditor QPushButton:hover { background: rgba(255,255,255,0.08); }
QWidget#shiftlockEditor QPushButton:checked { background: rgba(59,130,246,0.16); border: 2px solid rgba(91,151,255,0.8); }
QWidget#shiftlockEditor QPushButton#skShape { padding: 4px; }
QWidget#shiftlockEditor QPushButton#skPrimary { background: #3b82f6; border: none; border-radius: 20px; color: #ffffff; font-weight: 700; font-size: 14px; padding: 0 20px; }
QWidget#shiftlockEditor QPushButton#skPrimary:hover { background: #5b97ff; }
QWidget#shiftlockEditor QLineEdit { background: rgba(255,255,255,0.045); color: #ffffff; border: none; border-radius: 12px; padding: 8px 12px; font-size: 13px; }
QWidget#shiftlockEditor QLineEdit:focus { background: rgba(59,130,246,0.16); }
QWidget#shiftlockEditor QCheckBox { color: #ffffff; font-size: 13px; spacing: 8px; }
"""


def _pixmap(img: Image.Image) -> QPixmap:
    """PIL RGBA -> QPixmap (копия данных, чтобы буфер не пропал раньше времени)."""
    img = img.convert("RGBA")
    qimg = QImage(img.tobytes("raw", "RGBA"), img.width, img.height,
                  4 * img.width, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def backdrop(kind: str, size: int) -> Image.Image:
    """Фон превью: тёмная/светлая сцена или условный игровой вид."""
    if kind == "light":
        return Image.new("RGBA", (size, size), (196, 214, 232, 255))
    if kind == "game":
        im = Image.new("RGBA", (size, size))
        d = ImageDraw.Draw(im)
        horizon = int(size * 0.55)
        for y in range(size):
            if y < horizon:
                f = y / max(1, horizon)
                col = tuple(int(a + (b - a) * f) for a, b in ((92, 150, 226), (186, 218, 244)))
            else:
                f = (y - horizon) / max(1, size - horizon)
                col = tuple(int(a + (b - a) * f) for a, b in ((92, 138, 70), (54, 92, 48)))
            d.line([(0, y), (size, y)], fill=col + (255,))
        return im
    return Image.new("RGBA", (size, size), (14, 16, 22, 255))


class ShiftlockEditor(QWidget):
    # id сохранённого элемента, применить сразу
    saved = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("shiftlockEditor")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.shape_key = BASE["shape"]
        self.colors = {"color": BASE["color"], "outline_color": BASE["outline_color"],
                       "glow_color": BASE["glow_color"]}
        self.bg = "dark"
        self.sliders: dict[str, tuple[QSlider, QLabel]] = {}
        self._swatches: dict[str, list[tuple[QPushButton, str]]] = {}
        self._loading = False

        # дебаунс: двигая слайдер, не перерисовываем на каждый пиксель
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self.redraw)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(18)
        root.addWidget(self._build_left())
        root.addWidget(self._build_right(), 1)
        self.set_params(BASE)

    # ── левая колонка: превью, имя, сохранение ───────────────────────────
    def _build_left(self) -> QWidget:
        left = QWidget()
        left.setFixedWidth(BIG + 40)
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        title = QLabel("Конструктор")
        title.setObjectName("h1")
        lay.addWidget(title)
        sub = self._muted("Собери свою точку для shiftlock. Готовый рисунок "
                          "появится в категории «своё».")
        lay.addWidget(sub)

        stage = QFrame()
        stage.setObjectName("skStage")
        sl = QVBoxLayout(stage)
        sl.setContentsMargins(10, 10, 10, 10)
        sl.setSpacing(10)
        self.big = QLabel()
        self.big.setFixedSize(BIG, BIG)
        self.big.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.big, 0, Qt.AlignHCenter)

        bgrow = QHBoxLayout()
        bgrow.setSpacing(6)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for text, key in BACKDROPS:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(key == self.bg)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_bg(k))
            group.addButton(b)
            bgrow.addWidget(b)
        sl.addLayout(bgrow)

        real = QHBoxLayout()
        real.setSpacing(12)
        self.tiny = QLabel()
        self.tiny.setFixedSize(32, 32)
        self.tiny_zoom = QLabel()
        self.tiny_zoom.setFixedSize(96, 96)
        real.addWidget(self.tiny)
        real.addWidget(self.tiny_zoom)
        cap = self._muted("так в игре: 32×32 px и то же крупнее")
        cap.setWordWrap(True)
        real.addWidget(cap, 1)
        sl.addLayout(real)
        lay.addWidget(stage)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Название, например «мой крест»")
        lay.addWidget(self.name)
        go = QPushButton("Сохранить и применить")
        go.setObjectName("skPrimary")
        go.setFixedHeight(40)
        go.setCursor(Qt.PointingHandCursor)
        go.clicked.connect(lambda: self._save(True))
        lay.addWidget(go)
        keep = QPushButton("Только сохранить")
        keep.setCursor(Qt.PointingHandCursor)
        keep.clicked.connect(lambda: self._save(False))
        lay.addWidget(keep)
        lay.addStretch(1)
        return left

    # ── правая колонка: секции настроек ──────────────────────────────────
    def _build_right(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(26)

        # Форма
        lay = self._section(col, "Форма")
        grid = QGridLayout()
        grid.setSpacing(6)
        self.shape_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, key in enumerate(EDITOR_SHAPES):
            b = QPushButton()
            b.setObjectName("skShape")
            b.setCheckable(True)
            b.setFixedSize(66, 56)
            b.setToolTip(custom.SHAPES[key])
            b.setIcon(QIcon(_pixmap(self._shape_icon(key))))
            b.setIconSize(QSize(40, 40))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_shape(k))
            group.addButton(b)
            self.shape_buttons[key] = b
            grid.addWidget(b, i // PER_ROW, i % PER_ROW)
        grid.setColumnStretch(PER_ROW, 1)
        lay.addLayout(grid)
        self.shape_name = self._muted("")
        lay.addWidget(self.shape_name)
        self.center_dot = QCheckBox("Точка в центре поверх формы")
        self.center_dot.toggled.connect(self._changed)
        lay.addWidget(self.center_dot)
        self.filled = QCheckBox("Залить фигуру (кольцо, квадрат, ромб, треугольник)")
        self.filled.toggled.connect(self._changed)
        lay.addWidget(self.filled)

        # Размеры
        lay = self._section(col, "Размеры")
        for key in ("scale", "size", "thickness", "gap", "dot_size", "rotation",
                    "opacity"):
            self._add_slider(lay, key)

        # Цвет
        lay = self._section(col, "Цвет")
        lay.addLayout(self._swatch_row("color"))

        # Обводка и свечение
        lay = self._section(col, "Обводка и свечение")
        self.outline_on = QCheckBox("Обводка")
        self.outline_on.toggled.connect(self._changed)
        lay.addWidget(self.outline_on)
        self._add_slider(lay, "outline")
        lay.addWidget(self._muted("Цвет обводки"))
        lay.addLayout(self._swatch_row("outline_color"))
        lay.addSpacing(6)
        self.glow_on = QCheckBox("Мягкое свечение")
        self.glow_on.toggled.connect(self._changed)
        lay.addWidget(self.glow_on)
        self._add_slider(lay, "glow_strength")
        lay.addWidget(self._muted("Цвет свечения"))
        lay.addLayout(self._swatch_row("glow_color"))

        # Пресеты
        lay = self._section(col, "Пресеты")
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (title, preset) in enumerate(PRESETS):
            b = QPushButton(title)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, p=preset: self.set_params({**BASE, **p}))
            grid.addWidget(b, i // 4, i % 4)
        lay.addLayout(grid)
        rnd = QPushButton("Случайный")
        rnd.setCursor(Qt.PointingHandCursor)
        rnd.clicked.connect(self.randomize)
        lay.addWidget(rnd)
        reset = QPushButton("Сбросить всё")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(lambda: self.set_params(BASE))
        lay.addWidget(reset)
        col.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    # ── кирпичики интерфейса ─────────────────────────────────────────────
    @staticmethod
    def _muted(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("skMuted")
        lab.setWordWrap(True)
        return lab

    def _section(self, parent: QVBoxLayout, title: str) -> QVBoxLayout:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        head = QLabel(title)
        head.setObjectName("rowtitle")
        lay.addWidget(head)
        parent.addWidget(box)
        return lay

    def _add_slider(self, lay: QVBoxLayout, key: str) -> None:
        title, lo, hi, value, suffix = SLIDERS[key]
        row = QHBoxLayout()
        row.setSpacing(10)
        name = QLabel(title)
        name.setFixedWidth(140)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        shown = QLabel(f"{value}{suffix}")
        shown.setObjectName("skValue")
        shown.setMinimumWidth(48)
        shown.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(
            lambda v, lab=shown, suf=suffix: (lab.setText(f"{v}{suf}"), self._changed()))
        row.addWidget(name)
        row.addWidget(slider, 1)
        row.addWidget(shown)
        lay.addLayout(row)
        self.sliders[key] = (slider, shown)

    def _swatch_row(self, attr: str) -> QHBoxLayout:
        line = QHBoxLayout()
        line.setSpacing(6)
        self._swatches[attr] = []
        for name, color in SWATCHES:
            b = QPushButton()
            b.setFixedSize(26, 26)
            b.setToolTip(name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, a=attr, c=color: self._set_color(a, c))
            line.addWidget(b)
            self._swatches[attr].append((b, color))
        more = QPushButton("Свой…")
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(lambda _=False, a=attr: self._pick_any(a))
        line.addWidget(more)
        line.addStretch(1)
        self._refresh_swatches(attr)
        return line

    def _refresh_swatches(self, attr: str) -> None:
        current = self.colors[attr].lower()
        for b, color in self._swatches[attr]:
            edge = "#ffffff" if color == current else "rgba(255,255,255,0.2)"
            width = 2 if color == current else 1
            b.setStyleSheet(f"QPushButton {{ background: {color}; border: {width}px solid {edge};"
                            f" border-radius: 13px; padding: 0; }}")

    @staticmethod
    def _shape_icon(key: str) -> Image.Image:
        im = custom.draw_shiftlock(
            shape=key, color="#f2f2f5", size=26, thickness=8, gap=10, outline=0,
            side=80, scale=100, center_dot=custom.default_dot(key))
        return im

    # ── состояние ────────────────────────────────────────────────────────
    def _changed(self, *_) -> None:
        if not self._loading:
            self._timer.start()

    def _set_bg(self, key: str) -> None:
        self.bg = key
        self.redraw()

    def _set_shape(self, key: str, *, reset_dot: bool = True) -> None:
        self.shape_key = key
        if key in self.shape_buttons:
            self.shape_buttons[key].setChecked(True)
        if reset_dot:
            self.center_dot.blockSignals(True)
            self.center_dot.setChecked(custom.default_dot(key))
            self.center_dot.blockSignals(False)
        self.shape_name.setText(custom.SHAPES.get(key, ""))
        self.sliders["gap"][0].setEnabled(key in custom.GAP_SHAPES)
        self.filled.setEnabled(key in custom.FILL_SHAPES)
        self._changed()

    def _set_color(self, attr: str, color: str) -> None:
        self.colors[attr] = color
        self._refresh_swatches(attr)
        self._changed()

    def _pick_any(self, attr: str) -> None:
        color = QColorDialog.getColor(QColor(self.colors[attr]), self, "Цвет")
        if color.isValid():
            self._set_color(attr, color.name())

    def params(self) -> dict:
        """Параметры для custom.draw_shiftlock (и для сохранения в манифест)."""
        p = {k: s.value() for k, (s, _) in self.sliders.items()}
        p.update(shape=self.shape_key, center_dot=self.center_dot.isChecked(),
                 filled=self.filled.isChecked(), glow=self.glow_on.isChecked(),
                 glow_color=self.colors["glow_color"], color=self.colors["color"],
                 outline_color=self.colors["outline_color"])
        if not self.outline_on.isChecked():
            p["outline"] = 0
        return p

    def set_params(self, params: dict) -> None:
        """Выставить все контролы из словаря параметров (пресет, сброс, загрузка)."""
        p = {**BASE, **params}
        self._loading = True
        try:
            for key, (slider, _) in self.sliders.items():
                if p.get(key) is not None:
                    slider.setValue(int(p[key]))
            self.outline_on.setChecked(p["outline"] > 0)
            if p["outline"] > 0:
                self.sliders["outline"][0].setValue(int(p["outline"]))
            self.glow_on.setChecked(bool(p["glow"]))
            self.filled.setChecked(bool(p["filled"]))
            for attr in self.colors:
                self.colors[attr] = p.get(attr) or self.colors[attr]
                self._refresh_swatches(attr)
            self._set_shape(p["shape"], reset_dot=False)
            dot = p.get("center_dot")
            self.center_dot.setChecked(custom.default_dot(p["shape"]) if dot is None
                                       else bool(dot))
        finally:
            self._loading = False
        self.redraw()

    def randomize(self) -> None:
        rnd = random.Random()
        shape = rnd.choice(EDITOR_SHAPES)
        color = rnd.choice(SWATCHES)[1]
        glow = rnd.random() < 0.35
        self.set_params({
            **BASE, "shape": shape, "color": color,
            "center_dot": rnd.random() < 0.5,
            "size": rnd.randint(10, 32), "thickness": rnd.randint(2, 8),
            "gap": rnd.randint(2, 14), "rotation": rnd.choice((0, 0, 0, 15, 30, 45)),
            "outline": rnd.choice((0, 1, 2, 3)),
            "outline_color": "#000000" if color != "#000000" else "#ffffff",
            "glow": glow, "glow_color": color, "glow_strength": rnd.randint(3, 8),
            "filled": rnd.random() < 0.25,
        })

    # ── рисование ────────────────────────────────────────────────────────
    def image(self) -> Image.Image:
        """Итоговая картинка 128×128 — то, что сохраняется."""
        return custom.draw_shiftlock(**custom.normalize_params(self.params()))

    def redraw(self) -> None:
        self._timer.stop()
        p = custom.normalize_params(self.params())
        big = custom.draw_shiftlock(side=BIG, **p)
        scene = backdrop(self.bg, BIG)
        scene.alpha_composite(big)
        self.big.setPixmap(_pixmap(scene))
        real = custom.draw_shiftlock(**p).resize((32, 32), Image.Resampling.LANCZOS)
        small = backdrop(self.bg, 32)
        small.alpha_composite(real)
        self.tiny.setPixmap(_pixmap(small))
        self.tiny_zoom.setPixmap(_pixmap(small.resize((96, 96), Image.Resampling.NEAREST)))

    def _save(self, apply: bool) -> None:
        params = custom.normalize_params(self.params())
        name = self.name.text().strip() or f"мой {custom.SHAPES[params['shape']]}"
        try:
            item = custom.add("crosshair", custom.draw_shiftlock(**params), name,
                              params=params)
        except custom.CustomError as exc:
            QMessageBox.critical(self, "Не сохранилось", str(exc))
            return
        self.saved.emit(item["id"], apply)
