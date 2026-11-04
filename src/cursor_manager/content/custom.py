"""
custom.py — свои курсоры, shiftlock и skybox из картинки пользователя.

Картинка нормализуется под категорию и кладётся в
%APPDATA%\\RobloxCursorChanger\\custom\\<kind>\\<id>.<ext> вместе с
manifest.json. Для библиотеки это обычные элементы с категорией «своё»:
курсор — Cursor с собственным путём, shiftlock — CustomShiftlock (готовая
картинка вместо пресета crosshair), skybox — словарь, как у вшитых панорам.

Здесь нет записи в Roblox: только своя папка. В Roblox элементы попадают
тем же respack.install, что и вшитые.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageOps

from cursor_manager.content import cursor_library as lib

CUSTOM_ROOT = Path(os.environ.get("APPDATA", Path.home())) / "RobloxCursorChanger" / "custom"
CATEGORY = "своё"
KINDS = ("cursor", "crosshair", "sky")
MAX_SOURCE = 64 * 1024 * 1024          # больше — это уже не картинка
CURSOR_SIDE = 256
SHIFTLOCK_SIDE = 128
SKY_SIZE = (2048, 1024)


class CustomError(Exception):
    pass


@dataclass
class CustomCursor(lib.Cursor):
    """Курсор пользователя: путь хранится явно, а не ищется в каталоге."""
    custom_path: str = ""

    @property
    def path(self) -> Path | None:
        p = Path(self.custom_path)
        return p if p.is_file() else None


@dataclass
class CustomShiftlock:
    """Shiftlock из картинки: те же поля, что у crosshair.Preset, плюс файл."""
    id: str
    name: str
    image_path: str
    game: str = CATEGORY
    blurb: str = ""
    license: str = "UNKNOWN"
    note: str = ""
    # параметры конструктора (None у картинок из файла и у старых элементов)
    params: dict | None = None


def _dir(kind: str) -> Path:
    if kind not in KINDS:
        raise CustomError(f"неизвестная категория: {kind}")
    return CUSTOM_ROOT / kind


def _manifest(kind: str) -> Path:
    return _dir(kind) / "manifest.json"


def _read(kind: str) -> list[dict]:
    try:
        data = json.loads(_manifest(kind).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return [it for it in (items or []) if isinstance(it, dict) and it.get("id")]


def _write(kind: str, items: list[dict]) -> None:
    path = _manifest(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps({"schema": 1, "items": items}, ensure_ascii=False,
                              indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _new_id(kind: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or kind
    return f"my-{slug}-{int(time.time() * 1000) % 10_000_000:07d}"


# ─────────────────────────────────────────────────────────────────────────────
# Нормализация картинки под категорию
# ─────────────────────────────────────────────────────────────────────────────
def _open(source: Path) -> Image.Image:
    try:
        if source.stat().st_size > MAX_SOURCE:
            raise CustomError("файл больше 64 МБ")
        with Image.open(source) as im:
            im = ImageOps.exif_transpose(im)
            im.load()
            return im.copy()
    except CustomError:
        raise
    except (OSError, ValueError) as exc:
        raise CustomError(f"это не картинка или она повреждена: {exc}") from exc


def _trim(im: Image.Image) -> Image.Image:
    """Срезать прозрачные поля: курсор/прицел занимает всю свою клетку."""
    im = im.convert("RGBA")
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def normalize(kind: str, im: Image.Image) -> Image.Image:
    if kind == "cursor":
        im = _trim(im)
        im.thumbnail((CURSOR_SIDE, CURSOR_SIDE), Image.Resampling.LANCZOS)
        return im
    if kind == "crosshair":
        im = _trim(im)
        im.thumbnail((SHIFTLOCK_SIDE, SHIFTLOCK_SIDE), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (SHIFTLOCK_SIDE, SHIFTLOCK_SIDE), (0, 0, 0, 0))
        canvas.alpha_composite(im, ((SHIFTLOCK_SIDE - im.width) // 2,
                                    (SHIFTLOCK_SIDE - im.height) // 2))
        return canvas
    # skybox: равнопромежуточная панорама 2:1; обычное фото обрезается по
    # центру до 2:1 — получится небо «вокруг», пусть и со швом сзади
    im = im.convert("RGB")
    w, h = im.size
    if w < 64 or h < 32:
        raise CustomError("картинка слишком маленькая для неба")
    if w / h > 2:
        new_w = h * 2
        im = im.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    elif w / h < 2:
        new_h = w // 2
        im = im.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
    return im.resize(SKY_SIZE, Image.Resampling.LANCZOS)


def add(kind: str, source: Path | Image.Image, name: str,
        params: dict | None = None) -> dict:
    """
    Сохранить картинку как свой элемент категории; вернуть запись манифеста.
    params — параметры конструктора shiftlock: кладутся в манифест, чтобы
    рисунок можно было воспроизвести и править.
    """
    name = (name or "").strip()[:40] or "своё"
    im = source if isinstance(source, Image.Image) else _open(Path(source))
    out = normalize(kind, im)
    item_id = _new_id(kind, name)
    folder = _dir(kind)
    folder.mkdir(parents=True, exist_ok=True)
    if kind == "sky":
        target = folder / f"{item_id}.jpg"
        out.save(target, "JPEG", quality=90)
    else:
        target = folder / f"{item_id}.png"
        out.save(target, "PNG")
    blob = target.read_bytes()
    item = {"id": item_id, "name": name, "file": target.name,
            "w": out.width, "h": out.height,
            "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
    if params is not None and kind == "crosshair":
        item["params"] = normalize_params(params)
    items = _read(kind)
    items.insert(0, item)
    _write(kind, items)
    return item


def remove(kind: str, item_id: str) -> bool:
    items = _read(kind)
    keep = [it for it in items if it.get("id") != item_id]
    if len(keep) == len(items):
        return False
    for it in items:
        if it.get("id") == item_id:
            try:
                (_dir(kind) / Path(str(it.get("file"))).name).unlink()
            except OSError:
                pass
    _write(kind, keep)
    return True


def is_custom(item_id: str) -> bool:
    return str(item_id).startswith("my-")


def load(kind: str) -> list:
    """Свои элементы в формате, который понимает LibraryPage."""
    out = []
    folder = _dir(kind)
    for it in _read(kind):
        path = folder / Path(str(it.get("file") or "")).name
        if not path.is_file():
            continue
        if kind == "cursor":
            out.append(CustomCursor(
                id=it["id"], name=str(it.get("name") or "своё"), category=CATEGORY,
                tags=[CATEGORY], file=path.name, sha256=str(it.get("sha256") or ""),
                bytes=int(it.get("bytes") or 0), origin="custom",
                author="ты", custom_path=str(path)))
        elif kind == "crosshair":
            raw = it.get("params")
            try:
                params = normalize_params(raw) if isinstance(raw, dict) else None
            except CustomError:
                params = None
            out.append(CustomShiftlock(id=it["id"], name=str(it.get("name") or "своё"),
                                       image_path=str(path), params=params))
        else:
            out.append({"id": it["id"], "name": str(it.get("name") or "своё"),
                        "path": path, "license": "своё", "author": "ты",
                        "w": SKY_SIZE[0], "h": SKY_SIZE[1],
                        "sha256": str(it.get("sha256") or "")})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Конструктор shiftlock
# ─────────────────────────────────────────────────────────────────────────────
# ключ -> (название, тип геометрии, точка в центре по умолчанию)
_SHAPE_TABLE = {
    "dot":        ("точка", "none", True),
    "circle":     ("кольцо", "ring", False),
    "circle_dot": ("точка + кольцо", "ring", True),
    "cross":      ("крест", "bars4", False),
    "cross_dot":  ("крест + точка", "bars4", True),
    "plus":       ("крест сплошной", "bars4", False),
    "cross_gap":  ("крест с зазором", "bars4", False),
    "x":          ("X", "barsx", False),
    "t":          ("Т-образный", "barst", False),
    "square":     ("квадрат", "square", False),
    "diamond":    ("ромб", "diamond", False),
    "triangle":   ("треугольник", "triangle", False),
    "chevron":    ("шеврон", "chevron", False),
}
SHAPES = {k: v[0] for k, v in _SHAPE_TABLE.items()}
# фигуры, у которых работает «зазор» (лучи от центра)
GAP_SHAPES = frozenset(k for k, v in _SHAPE_TABLE.items()
                       if v[1] in ("bars4", "barsx", "barst") and k != "plus")
# «залить» имеет смысл только для контурных фигур
FILL_SHAPES = frozenset(k for k, v in _SHAPE_TABLE.items()
                        if v[1] in ("ring", "square", "diamond", "triangle"))

# значения по умолчанию draw_shiftlock; по ним же нормализуются сохранённые параметры
DRAW_DEFAULTS: dict = dict(
    shape="cross", color="#3d8bff", size=40, thickness=6, gap=10, outline=2,
    outline_color="#000000", scale=100, rotation=0, opacity=100,
    center_dot=None, filled=False, dot_size=None, glow=False,
    glow_color=None, glow_strength=5,
)
_RANGES = dict(size=(2, 120), thickness=(1, 40), gap=(0, 60), outline=(0, 16),
               scale=(20, 250), rotation=(0, 359), opacity=(0, 100),
               dot_size=(1, 40), glow_strength=(1, 12))


def default_dot(shape: str) -> bool:
    """Есть ли у формы центральная точка по умолчанию."""
    return _SHAPE_TABLE[shape][2]


def _hex(value: str, what: str = "цвет") -> str:
    try:
        r, g, b = ImageColor.getrgb(str(value))[:3]
    except ValueError as exc:
        raise CustomError(f"неверный {what}: {value}") from exc
    return f"#{r:02x}{g:02x}{b:02x}"


def normalize_params(params: dict | None = None) -> dict:
    """
    Привести параметры рисунка к полному проверенному виду: недостающее берётся
    из DRAW_DEFAULTS, числа зажимаются в диапазон, неизвестные ключи (в том числе
    из будущих версий) отбрасываются. Результат пригоден для draw_shiftlock(**p).
    """
    out = dict(DRAW_DEFAULTS)
    for key, value in (params or {}).items():
        if key in out and value is not None:
            out[key] = value
    if out["shape"] not in SHAPES:
        raise CustomError(f"неизвестная форма: {out['shape']}")
    try:
        for key, (lo, hi) in _RANGES.items():
            if out[key] is not None:
                out[key] = max(lo, min(hi, int(out[key])))
    except (TypeError, ValueError) as exc:
        raise CustomError(f"неверное число в параметрах: {exc}") from exc
    for key in ("color", "outline_color"):
        out[key] = _hex(out[key])
    out["glow_color"] = _hex(out["glow_color"]) if out["glow_color"] else None
    for key in ("filled", "glow"):
        out[key] = bool(out[key])
    if out["center_dot"] is not None:
        out["center_dot"] = bool(out["center_dot"])
    return out


def draw_shiftlock(shape: str = "cross", color: str = "#3d8bff",
                   size: int = 40, thickness: int = 6, gap: int = 10,
                   outline: int = 2, outline_color: str = "#000000",
                   side: int = SHIFTLOCK_SIDE, *, scale: int = 100,
                   rotation: int = 0, opacity: int = 100,
                   center_dot: bool | None = None, filled: bool = False,
                   dot_size: int | None = None, glow: bool = False,
                   glow_color: str | None = None,
                   glow_strength: int = 5) -> Image.Image:
    """
    Нарисовать shiftlock на прозрачном холсте side×side.

    Размеры — в пикселях холста 128 (при другом side масштабируются): size —
    длина лучей/радиус, gap — зазор от центра, scale — общий масштаб в %.
    center_dot=None — точка по умолчанию для формы, True/False — принудительно.
    Рисуем в 4× и уменьшаем, чтобы края были гладкими.
    """
    if shape not in SHAPES:
        raise CustomError(f"неизвестная форма: {shape}")
    kind = _SHAPE_TABLE[shape][1]
    k = 4
    s = side * k
    c = s / 2
    u = side / SHIFTLOCK_SIDE * k * max(1, scale) / 100
    t = max(1, thickness) * u
    g = max(0, gap) * u
    if shape == "plus":
        g = 0
    elif shape == "cross_gap":
        g = max(g, t * 1.2 + 2 * u)
    L = max(2, size) * u
    o = max(0, outline) * u
    dot_r = (dot_size * u) if dot_size else t * 0.75
    with_dot = default_dot(shape) if center_dot is None else bool(center_dot)
    rot = math.radians(rotation)

    def pt(radius: float, ang: float) -> tuple[float, float]:
        return (c + radius * math.cos(ang), c + radius * math.sin(ang))

    def ngon(n: int, apothem: float, start: float) -> list[tuple[float, float]]:
        radius = apothem / math.cos(math.pi / n)
        return [pt(radius, start + rot + i * 2 * math.pi / n) for i in range(n)]

    def mask(grow: float) -> Image.Image:
        m = Image.new("L", (s, s), 0)
        d = ImageDraw.Draw(m)
        if kind == "ring":
            r = L * 0.9
            d.ellipse((c - r - grow, c - r - grow, c + r + grow, c + r + grow), fill=255)
            inner = r - t - grow
            if not filled and inner > 0:
                d.ellipse((c - inner, c - inner, c + inner, c + inner), fill=0)
        elif kind in ("square", "diamond", "triangle"):
            n, a, start = {"square": (4, L * 0.75, math.pi / 4),
                           "diamond": (4, L * 0.9 * math.cos(math.pi / 4), 0.0),
                           "triangle": (3, L * 0.55, -math.pi / 2)}[kind]
            d.polygon(ngon(n, a + grow, start), fill=255)
            inner = a - t - grow
            if not filled and inner > 0:
                d.polygon(ngon(n, inner, start), fill=0)
        elif kind in ("bars4", "barsx", "barst"):
            base = {"bars4": (0, 90, 180, 270), "barsx": (45, 135, 225, 315),
                    "barst": (0, 90, 180)}[kind]
            half = t / 2 + grow
            for deg in base:
                a = math.radians(deg) + rot
                dx, dy = math.cos(a), math.sin(a)
                px, py = -dy, dx
                near, far = g - grow, g + L + grow
                d.polygon([(c + dx * near + px * half, c + dy * near + py * half),
                           (c + dx * far + px * half, c + dy * far + py * half),
                           (c + dx * far - px * half, c + dy * far - py * half),
                           (c + dx * near - px * half, c + dy * near - py * half)],
                          fill=255)
        elif kind == "chevron":
            pts = [(-L * 0.8, L * 0.45), (0.0, -L * 0.45), (L * 0.8, L * 0.45)]
            cr, sr = math.cos(rot), math.sin(rot)
            line = [(c + x * cr - y * sr, c + x * sr + y * cr) for x, y in pts]
            d.line(line, fill=255, width=max(1, int(t + 2 * grow)), joint="curve")
        if with_dot:
            r = dot_r + grow
            d.ellipse((c - r, c - r, c + r, c + r), fill=255)
        return m

    def solid(rgb: str, m: Image.Image) -> Image.Image:
        layer = Image.new("RGBA", (s, s), ImageColor.getrgb(rgb)[:3] + (255,))
        layer.putalpha(m)
        return layer

    fill_mask = mask(0)
    edge_mask = mask(o) if o else fill_mask
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    if glow:
        strength = max(1, glow_strength)
        blur = edge_mask.filter(ImageFilter.GaussianBlur(strength * 1.2 * k * side / SHIFTLOCK_SIDE))
        gain = 1.5 + strength * 0.15
        blur = blur.point(lambda v: min(255, int(v * gain)))
        out.alpha_composite(solid(glow_color or color, blur))
    if o:
        out.alpha_composite(solid(outline_color, edge_mask))
    out.alpha_composite(solid(color, fill_mask))
    if opacity < 100:
        a = max(0, opacity)
        out.putalpha(out.getchannel("A").point(lambda v: v * a // 100))
    return out.resize((side, side), Image.Resampling.LANCZOS)
