# glass.py — «жидкое стекло» окна: шрифты, размытие рабочего стола, свечение.
#
# Qt-стили не умеют backdrop-filter, поэтому настоящее размытие берём у
# Windows (acrylic через SetWindowCompositionAttribute), а QSS рисует поверх
# только полупрозрачные белые плёнки. Если Windows не дала acrylic (старая
# сборка, удалённый рабочий стол, SANYA_NO_GLASS=1), окно рисуется сплошным
# чёрным — без прозрачных дыр.
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from cursor_manager.content.fonts import _resource_root

UI_FONT = "Manrope"
DISPLAY_FONT = "Unbounded"


def load_fonts() -> None:
    """Вшитые OFL-шрифты интерфейса; без них Qt откатится на Segoe UI."""
    root = _resource_root() / "fonts"
    for name in ("manrope-regular.ttf", "manrope-bold.ttf", "unbounded-bold.ttf"):
        path = root / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    # хинтинг Windows округляет пробел Manrope на 11px до 2px, и слова
    # слипаются («Звуксмерти»); без хинтинга и с добавкой пробел нормальный
    font = QFont(UI_FONT)
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setWordSpacing(1.5)
    QApplication.setFont(font)


class _AccentPolicy(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _CompositionData(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


_WCA_ACCENT_POLICY = 19
_ACCENT_ACRYLIC = 4
_DWMWA_DARK = 20
_DWMWA_CORNERS = 33
_ROUND = 2


def enable_acrylic(widget: QWidget, tint: int = 0xD8000000) -> bool:
    """Размытие того, что под окном. tint — AABBGGRR, по умолчанию чёрный 85%."""
    if sys.platform != "win32" or os.environ.get("SANYA_NO_GLASS"):
        return False
    if sys.getwindowsversion().build < 17134:  # acrylic появился в 1803
        return False
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        user32 = ctypes.windll.user32
        policy = _AccentPolicy(_ACCENT_ACRYLIC, 0, tint, 0)
        data = _CompositionData(_WCA_ACCENT_POLICY,
                                ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
                                ctypes.sizeof(policy))
        if not user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)):
            return False
        dwm = ctypes.windll.dwmapi
        for attr, value in ((_DWMWA_DARK, 1), (_DWMWA_CORNERS, _ROUND)):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        return True
    except (AttributeError, OSError):
        return False


class GlassFrame(QWidget):
    """Подложка окна: чёрная тонировка и два мягких белых пятна света.

    Пятна дают стеклянным панелям, что «преломлять»: на ровном чёрном
    полупрозрачная плёнка выглядит просто серой.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("frame")
        self.glass = False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(r, QColor(0, 0, 0, 200 if self.glass else 255))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # синий ореол, как свечение вокруг аватара в референсе: два пятна,
        # которые стеклянные панели «преломляют»
        for cx, cy, rad, alpha in ((0.44, -0.14, 0.42, 78), (1.0, 1.1, 0.38, 46)):
            g = QRadialGradient(QPointF(r.width() * cx, r.height() * cy), r.width() * rad)
            g.setColorAt(0.0, QColor(45, 105, 255, alpha))
            g.setColorAt(0.5, QColor(35, 80, 220, alpha // 3))
            g.setColorAt(1.0, QColor(20, 50, 160, 0))
            p.fillRect(r, g)
        p.setPen(QColor(255, 255, 255, 22))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
