"""Иконки для интерфейса, нарисованные Pillow без Qt.

Сейчас здесь одна функция — speaker(): значок динамика («громкость»),
которым можно подписать кнопку звука. Геометрия задаётся в условных
единицах (~100 по стороне), потом вписывается в поле размера size так,
чтобы содержимое занимало около 80% поля и было центрировано по bbox.
Рисуем в 4x и уменьшаем LANCZOS: без этого края дуг выглядят зубчатыми.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

SUPERSAMPLE = 4

# Геометрия в условных единицах. Центр по вертикали — y = 50.
_BODY = (14.0, 38.0, 34.0, 62.0)      # корпус: x0, y0, x1, y1
_BODY_RADIUS = 3.0
_HORN = [(30.0, 38.0), (50.0, 22.0), (50.0, 78.0), (30.0, 62.0)]
_HORN_RADIUS = 4.0                    # скругление углов раструба
# Центр всех дуг — правый край раструба.
_WAVE_CX, _WAVE_CY = 50.0, 50.0
_WAVE_RADII = [17.0, 29.0, 41.0]      # от первой дуги к последней
_WAVE_WIDTH = 6.0                     # толщина линии дуги
_WAVE_HALF_ANGLE = 50.0               # дуга от -50 до +50 градусов
_FIELD_FILL = 0.8                     # доля поля, которую занимает значок


def _unit(dx: float, dy: float) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0, 0.0
    return dx / length, dy / length


def _rounded_polygon(points: list[tuple[float, float]], radius: float) -> list[tuple[float, float]]:
    """Скругляет углы многоугольника квадратичными кривыми Безье."""
    out: list[tuple[float, float]] = []
    n = len(points)
    for i, (px, py) in enumerate(points):
        ax, ay = points[i - 1]
        bx, by = points[(i + 1) % n]
        d_in = min(radius, math.dist((ax, ay), (px, py)) / 2)
        d_out = min(radius, math.dist((bx, by), (px, py)) / 2)
        ux, uy = _unit(ax - px, ay - py)
        vx, vy = _unit(bx - px, by - py)
        p0 = (px + ux * d_in, py + uy * d_in)
        p1 = (px + vx * d_out, py + vy * d_out)
        for step in range(9):
            t = step / 8
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * px + t ** 2 * p1[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * py + t ** 2 * p1[1]
            out.append((x, y))
    return out


def _wave_endpoints(radius: float) -> list[tuple[float, float]]:
    """Центры круглых концов дуги радиуса radius (верхний и нижний)."""
    a = math.radians(_WAVE_HALF_ANGLE)
    return [
        (_WAVE_CX + radius * math.cos(a), _WAVE_CY - radius * math.sin(a)),
        (_WAVE_CX + radius * math.cos(a), _WAVE_CY + radius * math.sin(a)),
    ]


def _content_bounds(waves: int, horn: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Bbox всей геометрии в условных единицах, с учётом толщины линий."""
    half = _WAVE_WIDTH / 2
    xs = [_BODY[0], _BODY[2]] + [p[0] for p in horn]
    ys = [_BODY[1], _BODY[3]] + [p[1] for p in horn]
    for radius in _WAVE_RADII[:waves]:
        # Внешний край дуги по всем углам и круглые концы по окружности.
        xs.append(_WAVE_CX + radius + half)
        ys.append(_WAVE_CY - radius - half)
        ys.append(_WAVE_CY + radius + half)
        for ex, ey in _wave_endpoints(radius):
            for k in range(16):
                ang = 2 * math.pi * k / 16
                xs.append(ex + half * math.cos(ang))
                ys.append(ey + half * math.sin(ang))
    return min(xs), min(ys), max(xs), max(ys)


def speaker(size: int, color=(242, 242, 245, 255), waves: int = 2) -> Image.Image:
    """Значок динамика size×size с прозрачным фоном.

    waves — число дуг звука справа, от 0 до 3. Цвет — RGB или RGBA.
    """
    if size < 1:
        raise ValueError("size должен быть положительным")
    if not 0 <= waves <= 3:
        raise ValueError("waves должен быть от 0 до 3")
    rgba = tuple(color) if len(color) == 4 else (*tuple(color), 255)

    horn = _rounded_polygon(_HORN, _HORN_RADIUS)
    minx, miny, maxx, maxy = _content_bounds(waves, horn)

    canvas = size * SUPERSAMPLE
    span = max(maxx - minx, maxy - miny)
    scale = _FIELD_FILL * canvas / span
    # Центрируем bbox содержимого, а не просто поле: значок без дуг тоже ровный.
    off_x = (canvas - (maxx - minx) * scale) / 2 - minx * scale
    off_y = (canvas - (maxy - miny) * scale) / 2 - miny * scale

    def to_px(x: float, y: float) -> tuple[float, float]:
        return x * scale + off_x, y * scale + off_y

    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x0, y0 = to_px(_BODY[0], _BODY[1])
    x1, y1 = to_px(_BODY[2], _BODY[3])
    draw.rounded_rectangle([x0, y0, x1, y1], radius=_BODY_RADIUS * scale, fill=rgba)

    draw.polygon([to_px(x, y) for x, y in horn], fill=rgba)

    half = _WAVE_WIDTH / 2
    stroke = _WAVE_WIDTH * scale
    cap = half * scale
    for radius in _WAVE_RADII[:waves]:
        # PIL рисует толщину дуги внутрь от границы эллипса: берём внешний радиус.
        ox0, oy0 = to_px(_WAVE_CX - radius - half, _WAVE_CY - radius - half)
        ox1, oy1 = to_px(_WAVE_CX + radius + half, _WAVE_CY + radius + half)
        draw.arc(
            [ox0, oy0, ox1, oy1],
            start=-_WAVE_HALF_ANGLE,
            end=_WAVE_HALF_ANGLE,
            fill=rgba,
            width=max(1, round(stroke)),
        )
        for ex, ey in _wave_endpoints(radius):
            cx, cy = to_px(ex, ey)
            draw.ellipse([cx - cap, cy - cap, cx + cap, cy + cap], fill=rgba)

    return img.resize((size, size), Image.Resampling.LANCZOS)
