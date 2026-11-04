# motion.py — анимации интерфейса: появление страниц, ползунок меню,
# раскрытие групп, всплывашки, синее свечение кнопок.
#
# Всё на QPropertyAnimation. Эффекты прозрачности (QGraphicsOpacityEffect)
# снимаются сразу после анимации: пока эффект висит, Qt рисует виджет через
# буфер, и прокрутка тяжёлой сетки карточек начинает подтормаживать.
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint,
                            QPropertyAnimation, QRect, QRectF, Qt)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
                               QPushButton, QWidget)

EASE = QEasingCurve.OutCubic
BLUE = QColor(59, 130, 246)


def fade_in(widget: QWidget, dy: int = 12, ms: int = 220) -> None:
    """Страница проявляется и чуть приподнимается на место."""
    old = getattr(widget, "_fade_group", None)
    if old is not None:
        old.stop()
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    end = widget.pos()
    widget.move(end + QPoint(0, dy))

    fade = QPropertyAnimation(effect, b"opacity", widget)
    fade.setDuration(ms)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(EASE)
    slide = QPropertyAnimation(widget, b"pos", widget)
    slide.setDuration(ms)
    slide.setStartValue(end + QPoint(0, dy))
    slide.setEndValue(end)
    slide.setEasingCurve(EASE)

    group = QParallelAnimationGroup(widget)
    group.addAnimation(fade)
    group.addAnimation(slide)

    def done() -> None:
        widget.setGraphicsEffect(None)
        widget.move(end)
        widget._fade_group = None

    group.finished.connect(done)
    widget._fade_group = group
    group.start()


def glow(button: QPushButton, radius: int = 30, alpha: int = 150) -> None:
    """Размытое синее свечение под кнопкой (QSS не умеет box-shadow)."""
    effect = QGraphicsDropShadowEffect(button)
    effect.setBlurRadius(radius)
    effect.setOffset(0, 4)
    c = QColor(BLUE)
    c.setAlpha(alpha)
    effect.setColor(c)
    button.setGraphicsEffect(effect)


class NavIndicator(QWidget):
    """Синяя плашка с ореолом под активным пунктом меню; переезжает плавно.

    Виджет больше пункта на GLOW со всех сторон — в этих полях рисуется ореол.
    """

    GLOW = 12

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(EASE)
        self.hide()

    def move_to(self, rect: QRect, animate: bool = True) -> None:
        g = self.GLOW
        rect = rect.adjusted(-g, -g, g, g)
        if not self.isVisible() or not animate:
            self._anim.stop()
            self.setGeometry(rect)
            self.show()
            self.lower()
            return
        if self._anim.state() == QPropertyAnimation.Running and self._anim.endValue() == rect:
            return
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(rect)
        self._anim.start()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # синий ореол: несколько расширяющихся слоёв с убывающей плотностью,
        # сама плашка без рамки — как в макете
        pad = self.GLOW
        core = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        for i in range(pad, 0, -2):
            halo = QPainterPath()
            halo.addRoundedRect(core.adjusted(-i, -i, i, i), 12 + i, 12 + i)
            p.fillPath(halo, QColor(59, 130, 246, int(10 * (1 - i / pad)) + 1))
        path = QPainterPath()
        path.addRoundedRect(core, 12, 12)
        p.fillPath(path, QColor(59, 130, 246, 44))


def expand(body: QWidget, opened: bool, on_step=None, ms: int = 220) -> None:
    """Плавно раскрыть/свернуть группу меню через maximumHeight."""
    old = getattr(body, "_exp_anim", None)
    if old is not None:
        old.stop()
    full = body.sizeHint().height()
    if opened:
        body.setMaximumHeight(0 if not body.isVisible() else body.height())
        body.setVisible(True)
    start = body.maximumHeight() if opened else body.height()
    anim = QPropertyAnimation(body, b"maximumHeight", body)
    anim.setDuration(ms)
    anim.setEasingCurve(EASE)
    anim.setStartValue(min(start, full))
    anim.setEndValue(full if opened else 0)
    if on_step is not None:
        anim.valueChanged.connect(lambda _v: on_step())

    def done() -> None:
        if opened:
            body.setMaximumHeight(16777215)
        else:
            body.setVisible(False)
        body._exp_anim = None
        if on_step is not None:
            on_step()

    anim.finished.connect(done)
    body._exp_anim = anim
    anim.start()
