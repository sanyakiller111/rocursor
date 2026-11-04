# nav_icons.py — линейные иконки бокового меню (те же контуры, что в макете).
#
# Рисуются из SVG через QtSvg: одна строка пути на иконку, цвет обводки
# подставляется при рендере, поэтому активный и обычный пункт — одна иконка.
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "cursor": '<path d="M5 3l13 7-6 2-2 6z"/>',
    "crosshair": '<circle cx="12" cy="12" r="7"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    "sky": '<path d="M6 17a4 4 0 010-8 6 6 0 0111.3 1.5A3.5 3.5 0 0117 17z"/>',
    "material": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M4 12h16M12 4v16"/>',
    "sound": '<path d="M4 10v4h4l5 4V6L8 10z"/><path d="M16 9a4 4 0 010 6M18.5 6.5a7.5 7.5 0 010 11"/>',
    "font": '<path d="M5 19L11 5l6 14M7.5 14h7"/>',
    "editor": '<path d="M4 20l4-1 11-11-3-3L5 16z"/>',
    "fps": '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    "servers": '<path d="M5 18v-3M10 18v-6M15 18V9M20 18V5"/>',
    "help": '<path d="M14.5 6.5a4 4 0 00-5.2 5.2L4 17l3 3 5.3-5.3a4 4 0 005.2-5.2l-2.5 2.5-2.5-.5-.5-2.5z"/>',
    "config": '<path d="M5 7h14M5 12h14M5 17h9"/>',
    "about": '<circle cx="12" cy="12" r="8"/><path d="M12 11v5M12 8h.01"/>',
}


def pixmap(name: str, color: str, size: int = 18, ratio: float = 2.0) -> QPixmap:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
           f'stroke-linejoin="round">{_PATHS.get(name, "")}</svg>')
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(px.rect()))
    p.end()
    px.setDevicePixelRatio(ratio)
    return px


def icon(name: str, color: str, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, color, size))


# Оригинальные значки соцсетей (цвета и формы брендов), для ссылок в меню.
_BRANDS = {
    "telegram": ('<circle cx="12" cy="12" r="12" fill="#2AABEE"/>'
                 '<path fill="#ffffff" d="M5.43 11.87l11.6-4.47c.54-.2 1 .13.83.94l-1.98 9.32'
                 'c-.15.66-.54.82-1.1.51l-3-2.22-1.45 1.4c-.16.16-.3.3-.6.3l.21-3.05 5.56-5.02'
                 'c.24-.21-.05-.33-.38-.12l-6.87 4.33-2.96-.92c-.64-.2-.66-.64.14-.95z"/>'),
    "youtube": ('<rect x="0.5" y="4.5" width="23" height="15" rx="4.5" fill="#FF0000"/>'
                '<path fill="#ffffff" d="M9.75 8.6v6.8l5.9-3.4z"/>'),
}


def brand_icon(name: str, size: int = 22) -> QIcon:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           f'{_BRANDS[name]}</svg>')
    ratio = 2.0
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(px.rect()))
    p.end()
    px.setDevicePixelRatio(ratio)
    return QIcon(px)


def checkbox_images(folder: Path) -> tuple[str, str]:
    """Галочка выкл/вкл как SVG-файлы для QSS `image:`.

    Рамка QSS с дробной толщиной и скруглением рисуется рвано; SVG Qt
    сглаживает ровно. Возвращает пути со слешами, как их ждёт url() в QSS.
    """
    off = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
           '<rect x="1" y="1" width="18" height="18" rx="5.5" fill="none" '
           'stroke="#ffffff" stroke-opacity="0.28" stroke-width="1.6"/></svg>')
    on = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
          '<rect x="0.5" y="0.5" width="19" height="19" rx="6" fill="#3b82f6"/>'
          '<path d="M5.5 10.3l3 3 6-6.6" fill="none" stroke="#ffffff" '
          'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    paths = []
    for name, svg in (("check-off.svg", off), ("check-on.svg", on)):
        path = folder / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not path.is_file() or path.read_text(encoding="utf-8") != svg:
                path.write_text(svg, encoding="utf-8")
        except OSError:
            pass
        paths.append(path.as_posix())
    return paths[0], paths[1]
