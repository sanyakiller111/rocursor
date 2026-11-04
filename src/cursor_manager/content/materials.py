"""
materials.py — текстуры мира: гладкий пластик, без студов, спокойная вода.

На диске у Roblox остались только три группы текстур материалов
(roblox_paths.MATERIAL_*): пластик, атлас поверхностей studs.dds и карты
нормалей воды. Своих картинок под них мы не держим — пресет переделывает
оригинал Roblox, поэтому яркость и раскладка атласа всегда совпадают с
текущей версией клиента:

  flat  каждый тайл атласа заливается своим средним цветом: рисунок и
        рельеф пропадают, тон остаётся. Для карт нормалей среднее — это
        почти ровная нормаль, то есть поверхность без бугров.
  dark  то же, но цвет темнее — тёмный пластик.
  keep  оригинал без изменений (группа, которую пресет не трогает).

Пресет описывает все три группы сразу, поэтому в config один слот
«material»: новый пресет заменяет предыдущий целиком.

Выход — DDS того же формата (DXT1/DXT5), размера и числа мипов, что и
оригинал: заголовок копируется как есть, пересчитываются только блоки.
Залитые тайлы кодируются без потерь, у мелких мипов работает простой
кодировщик по диапазону.
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageStat

from cursor_manager.core import roblox_paths as RP


class MaterialError(Exception):
    pass


GROUPS = {
    "plastic": RP.MATERIAL_PLASTIC,
    "studs": RP.MATERIAL_STUDS,
    "water": RP.MATERIAL_WATER,
}
GROUP_TITLE = {"plastic": "пластик", "studs": "студы", "water": "вода"}
DARK = 0.55

PRESETS: list[dict] = [
    {"id": "smooth-plastic", "name": "гладкий пластик", "group": "пластик",
     "glyph": "▢", "parts": {"plastic": "flat"},
     "blurb": "пластик без шума и рельефа, только чистый цвет детали"},
    {"id": "dark-plastic", "name": "тёмный пластик", "group": "пластик",
     "glyph": "■", "parts": {"plastic": "dark"},
     "blurb": "гладкий и заметно темнее — карты выглядят ночными"},
    {"id": "no-studs", "name": "без студов", "group": "студы",
     "glyph": "◎", "parts": {"studs": "flat"},
     "blurb": "старые поверхности studs/inlet/weld без рисунка"},
    {"id": "calm-water", "name": "спокойная вода", "group": "вода",
     "glyph": "≈", "parts": {"water": "flat"},
     "blurb": "вода без ряби: ровная, как стекло"},
    {"id": "min-textures", "name": "минимум текстур", "group": "fps",
     "glyph": "▦", "parts": {"plastic": "flat", "studs": "flat", "water": "flat"},
     "blurb": "всё сразу: гладкий пластик, без студов, спокойная вода. "
              "для fps вместе с «низкими текстурами» во вкладке fps буст"},
]
for _p in PRESETS:
    _p.setdefault("license", "из файлов roblox")
    _p.setdefault("author", "sanyakiller111")


def load_presets() -> list[dict]:
    return [dict(p) for p in PRESETS]


def mode_for(preset: dict, filename: str) -> str:
    for group, names in GROUPS.items():
        if filename.lower() in names:
            return str(preset.get("parts", {}).get(group, "keep"))
    return "keep"


# ─────────────────────────────────────────────────────────────────────────────
# DDS
# ─────────────────────────────────────────────────────────────────────────────
HEADER = 128
BLOCK = {b"DXT1": 8, b"DXT5": 16}


def read_header(data: bytes) -> dict:
    if len(data) < HEADER or data[:4] != b"DDS ":
        raise MaterialError("не DDS")
    height, width = struct.unpack_from("<II", data, 12)
    mips = max(1, struct.unpack_from("<I", data, 28)[0])
    fourcc = data[84:88]
    if fourcc not in BLOCK:
        raise MaterialError(f"формат {fourcc!r} не поддерживается")
    return {"width": width, "height": height, "mips": mips, "fourcc": fourcc}


def _levels(width: int, height: int, mips: int):
    for i in range(mips):
        yield max(1, width >> i), max(1, height >> i)


def expected_size(info: dict) -> int:
    block = BLOCK[info["fourcc"]]
    return HEADER + sum(((w + 3) // 4) * ((h + 3) // 4) * block
                        for w, h in _levels(info["width"], info["height"], info["mips"]))


def _rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _unpack565(c: int) -> tuple[int, int, int]:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def _color_block(px: list[tuple]) -> bytes:
    c_max = max(px, key=lambda p: p[0] * 3 + p[1] * 6 + p[2])
    c_min = min(px, key=lambda p: p[0] * 3 + p[1] * 6 + p[2])
    c0, c1 = _rgb565(*c_max[:3]), _rgb565(*c_min[:3])
    if c0 == c1:
        return struct.pack("<HHI", c0, c1, 0)
    if c0 < c1:
        c0, c1 = c1, c0
    e0, e1 = _unpack565(c0), _unpack565(c1)
    palette = [e0, e1,
               tuple((2 * a + b) // 3 for a, b in zip(e0, e1)),
               tuple((a + 2 * b) // 3 for a, b in zip(e0, e1))]
    bits = 0
    for i, p in enumerate(px):
        best = min(range(4), key=lambda k: sum((p[j] - palette[k][j]) ** 2 for j in range(3)))
        bits |= best << (2 * i)
    return struct.pack("<HHI", c0, c1, bits)


def _alpha_block(alphas: list[int]) -> bytes:
    a0, a1 = max(alphas), min(alphas)
    if a0 == a1:
        return bytes((a0, a1, 0, 0, 0, 0, 0, 0))
    palette = [a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)]
    bits = 0
    for i, a in enumerate(alphas):
        best = min(range(8), key=lambda k: abs(a - palette[k]))
        bits |= best << (3 * i)
    return bytes((a0, a1)) + bits.to_bytes(6, "little")


def _encode_level(im: Image.Image, fourcc: bytes) -> bytes:
    w, h = im.size
    raw = im.tobytes()
    out = bytearray()
    cache: dict[bytes, bytes] = {}
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            px = []
            for y in range(by, by + 4):
                yy = min(y, h - 1)
                for x in range(bx, bx + 4):
                    xx = min(x, w - 1)
                    o = (yy * w + xx) * 4
                    px.append(tuple(raw[o:o + 4]))
            key = bytes(v for p in px for v in p)
            block = cache.get(key)
            if block is None:
                color = _color_block(px)
                block = (_alpha_block([p[3] for p in px]) + color
                         if fourcc == b"DXT5" else color)
                cache[key] = block
            out += block
    return bytes(out)


def _flatten(im: Image.Image, factor: float = 1.0) -> Image.Image:
    """Каждый квадратный тайл атласа — своим средним цветом."""
    w, h = im.size
    tile = min(w, h)
    out = Image.new("RGBA", (w, h))
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            box = (x, y, min(x + tile, w), min(y + tile, h))
            mean = ImageStat.Stat(im.crop(box)).mean
            rgb = tuple(max(0, min(255, round(c * factor))) for c in mean[:3])
            out.paste(rgb + (round(mean[3]),), box)
    return out


def transform(data: bytes, mode: str) -> bytes:
    """Переделать один DDS. keep возвращает исходные байты."""
    if mode == "keep":
        return data
    if mode not in ("flat", "dark"):
        raise MaterialError(f"неизвестный режим: {mode}")
    info = read_header(data)
    if len(data) != expected_size(info):
        raise MaterialError("размер файла не сходится с заголовком DDS")
    try:
        with Image.open(io.BytesIO(data)) as src:
            base = src.convert("RGBA")
    except OSError as exc:
        raise MaterialError(f"DDS не читается: {exc}") from exc
    # у карт нормалей (DXT5) темнить нечего — только выравниваем
    factor = DARK if mode == "dark" and info["fourcc"] == b"DXT1" else 1.0
    flat = _flatten(base, factor)
    body = bytearray()
    for i, (w, h) in enumerate(_levels(info["width"], info["height"], info["mips"])):
        level = flat if i == 0 else flat.resize((w, h), Image.Resampling.BOX)
        body += _encode_level(level, info["fourcc"])
    out = data[:HEADER] + bytes(body)
    if len(out) != len(data):
        raise MaterialError("пересобранный DDS другого размера")
    return out


def build(preset: dict, sources: dict[str, Path], out_dir: Path) -> dict[str, Path]:
    """
    sources — имя файла Roblox → оригинал (бэкап или живой файл).
    Возвращает имя → готовый файл в out_dir. Результат кэшируется по
    содержимому оригинала: повторная установка ничего не пересчитывает.
    """
    import hashlib
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for name, src in sources.items():
        data = src.read_bytes()
        mode = mode_for(preset, name)
        digest = hashlib.sha256(data).hexdigest()[:10]
        dest = out_dir / f"{mode}-{digest}-{name}"
        if not dest.is_file():
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(transform(data, mode))
            tmp.replace(dest)
        result[name] = dest
    return result


def write_dds(im: Image.Image, fourcc: bytes = b"DXT1", mips: int | None = None) -> bytes:
    """Записать картинку в DDS — для тестов и инструментов."""
    w, h = im.size
    if mips is None:
        mips = max(w, h).bit_length()
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000
    linear = ((w + 3) // 4) * ((h + 3) // 4) * BLOCK[fourcc]
    header = struct.pack("<4sIIIIIII44sII4s20sIIII", b"DDS ", 124, flags, h, w,
                         linear, 0, mips, b"\0" * 44, 32, 0x4, fourcc, b"\0" * 20,
                         0x1000 | 0x8 | 0x400000, 0, 0, 0) + b"\0" * 4
    im = im.convert("RGBA")
    body = b"".join(_encode_level(im if i == 0 else im.resize(s, Image.Resampling.BOX), fourcc)
                    for i, s in enumerate(_levels(w, h, mips)))
    return header + body
