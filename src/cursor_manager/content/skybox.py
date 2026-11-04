"""
skybox.py — генератор неба Roblox из панорамы 360°.

Формат установлен разведкой настоящей установки
(PlatformContent\\pc\\textures\\sky\\sky512_*.tex):

    .tex — это обычный DDS
    128 байт заголовка + цепочка мип-уровней в DXT1 (BC1)

    512x512, 10 мипов, по 8 байт на блок 4x4
    131072 + 32768 + 8192 + 2048 + 512 + 128 + 32 + 8 + 8 + 8 = 174776
    174776 + 128 = 174904 байт  ← совпадает с файлом Roblox до байта

Шесть граней: ft, bk, lf, rt, up, dn.

Pillow умеет кодировать DXT1, но пишет только нулевой мип, поэтому цепочку
собираем сами: кодируем каждый уровень отдельно и склеиваем после одного
заголовка.

Чего модуль не делает: не трогает FastFlags, не ходит по сети, не меняет
исполняемые файлы Roblox. Только текстуры.
"""
from __future__ import annotations

import io
import json
import math
import struct
import sys
from pathlib import Path

from PIL import Image

FACE_SIZE = 1024        # у sky512_*.tex имя осталось от времён 512, а кадр 1024
MIP_LEVELS = 11
HEADER_SIZE = 128

# Реальные файлы Roblox, измеренные на живой установке:
#   sky512_*.tex     1024x1024, 11 мипов, 699192 Б
#   indoor512_*.tex   512x512, 10 мипов, 174904 Б
# Оба набора названы «512» — доверять имени нельзя, параметры берём из
# заголовка существующего файла.

FACES = ("ft", "bk", "lf", "rt", "up", "dn")
FACE_LABELS = {
    "ft": "перед", "bk": "зад", "lf": "лево",
    "rt": "право", "up": "верх", "dn": "низ",
}


def _resource_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"


SKYBOX_DIR = _resource_root() / "skyboxes"
SKYBOX_MANIFEST = SKYBOX_DIR / "manifest.json"


def load_presets() -> list[dict]:
    """Вшитые панорамы неба из assets/skyboxes/manifest.json."""
    if not SKYBOX_MANIFEST.is_file():
        return []
    try:
        raw = json.loads(SKYBOX_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file") or "")
        if not name or "/" in name or "\\" in name or name.startswith("."):
            continue
        path = SKYBOX_DIR / name
        if not path.is_file():
            continue
        out.append({**item, "path": path})
    return out

# Базис каждой грани: forward, right, up.
# right направлен вправо при взгляде на грань снаружи куба,
# up — вверх.
#
# Оговорка про ориентацию: формат (.tex/DXT1/мипы) проверен побайтово по
# файлам Roblox, а вот соглашение о повороте граней проверить можно только в
# самой игре — рендерер Roblox закрыт. Если небо в игре окажется зеркальным
# или повёрнутым, переворачивается MIRROR, а не переписывается проекция.
MIRROR = False

_BASIS = {
    "ft": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "bk": ((0, 0, -1), (-1, 0, 0), (0, -1, 0)),
    "lf": ((-1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "rt": ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "up": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "dn": ((0, -1, 0), (1, 0, 0), (0, 0, -1)),
}


def face_uv(face: str, size: int, i: int, j: int):
    """Точка грани -> направление в пространстве."""
    fx, fy, fz = _BASIS[face][0]
    rx, ry, rz = _BASIS[face][1]
    ux, uy, uz = _BASIS[face][2]
    u = 2.0 * (i + 0.5) / size - 1.0
    v = 1.0 - 2.0 * (j + 0.5) / size
    if MIRROR:
        u = -u
    dx = fx + u * rx + v * ux
    dy = fy + u * ry + v * uy
    dz = fz + u * rz + v * uz
    n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    return dx / n, dy / n, dz / n


def dir_to_equirect(dx: float, dy: float, dz: float, w: int, h: int):
    lon = math.atan2(dz, dx)
    lat = math.asin(max(-1.0, min(1.0, dy)))
    px = int((lon / (2 * math.pi) + 0.5) * w) % w
    py = max(0, min(h - 1, int((0.5 - lat / math.pi) * h)))
    return px, py


class SkyboxError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Заголовок DDS
# ─────────────────────────────────────────────────────────────────────────────
def dds_header(width: int, height: int, mips: int) -> bytes:
    h = bytearray(HEADER_SIZE)
    struct.pack_into("<4s", h, 0, b"DDS ")          # магия
    struct.pack_into("<I", h, 4, HEADER_SIZE - 4)     # размер заголовка = 124
    # flags: CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE | MIPMAPCOUNT
    struct.pack_into("<I", h, 8, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if mips > 1 else 0))
    struct.pack_into("<I", h, 12, height)
    struct.pack_into("<I", h, 16, width)
    struct.pack_into("<I", h, 20, int(width * 8 / 4))  # bytes per scanline для DXT
    struct.pack_into("<I", h, 24, 0)                   # depth
    struct.pack_into("<I", h, 28, mips)                 # мип-уровней
    # 11 зарезервированных uint32 остаются нулевыми
    # DDS_PIXELFORMAT (32 байта) начиная со смещения 76
    struct.pack_into("<I", h, 76, 32)                  # sizeof pixel format
    struct.pack_into("<I", h, 80, 0x4)                  # DDPF_FOURCC
    h[84:88] = b"DXT1"
    struct.pack_into("<I", h, 108, 0x1000)               # DDPF_ALPHAPIXELS
    struct.pack_into("<I", h, 112, 0x8)                 # DDSCAPS_COMPLEX
    struct.pack_into("<I", h, 116, 0x400000)            # DDSCAPS_MIPMAP | TEXTURE
    return bytes(h)


# ─────────────────────────────────────────────────────────────────────────────
# Проекция: панорама → грань куба
# ─────────────────────────────────────────────────────────────────────────────
def face_to_equirect(face: str, size: int):
    """
    Возвращает (sx, sy) — координаты пикселей исходной панорамы для каждого
    пикселя грани. Считается один раз на грань, потом только индексы.
    """
    fx, fy, fz = _BASIS[face][0]
    rx, ry, rz = _BASIS[face][1]
    ux, uy, uz = _BASIS[face][2]

    sw, sh = equirect_size(face, size)
    sx, sy = [], []
    for j in range(size):
        v = 1.0 - 2.0 * (j + 0.5) / size          # +1 сверху, −1 снизу
        for i in range(size):
            u = 2.0 * (i + 0.5) / size - 1.0       # −1 слева, +1 справа
            dx = fx + u * rx + v * ux
            dy = fy + u * ry + v * uy
            dz = fz + u * rz + v * uz
            n = math.sqrt(dx * dx + dy * dy + dz * dz)
            if n == 0:
                sx.append(0); sy.append(0); continue
            dx, dy, dz = dx / n, dy / n, dz / n
            lon = math.atan2(dz, dx)               # −π..π
            lat = math.asin(max(-1.0, min(1.0, dy)))# −π/2..π/2
            sx.append(int((lon / (2 * math.pi) + 0.5) * sw) % sw)
            sy.append(max(0, min(sh - 1, int((0.5 - lat / math.pi) * sh))))
    return sx, sy


def equirect_size(face: str, size: int) -> tuple[int, int]:
    """Размер панорамы, из которой берётся грань: та же высота, ширина вдвое."""
    # панорама строится с соотношением 2:1, грань квадратная → высота равна size
    return size * 2, size


def render_face(panorama: Image.Image, face: str, size: int = FACE_SIZE) -> Image.Image:
    """Одна грань куба из равнопромежуточной панорамы (nearest)."""
    src = panorama.convert("RGB")
    sw, sh = src.size
    data = src.load()
    out = Image.new("RGB", (size, size))
    od = out.load()
    for j in range(size):
        for i in range(size):
            dx, dy, dz = face_uv(face, size, i, j)
            px, py = dir_to_equirect(dx, dy, dz, sw, sh)
            od[i, j] = data[px, py]
    return out


def rebuild_panorama(faces: dict[str, Image.Image], w: int, h: int) -> Image.Image:
    """
    Обратная проекция: собирает панораму из шести граней куба.

    Нужна для проверки: если куб построен верно, исходная панорама и
    восстановленная совпадут. Совпадение доказывает, что грани покрывают
    сферу целиком и базисы согласованы между собой.

    Инверсия берётся из того же определения, что и прямая проекция:
    dir = f + u·r + v·up при ортонормированных r и up даёт u = dir·r,
    v = dir·up. Никакой отдельной формулы — одна точка правды.
    """
    out = Image.new("RGB", (w, h))
    od = out.load()
    size = next(iter(faces.values())).size[0]
    caches = {f: im.load() for f, im in faces.items()}

    forwards = {f: _BASIS[f][0] for f in FACES}

    for j in range(h):
        lat = math.pi * (0.5 - (j + 0.5) / h)
        cl = math.cos(lat)
        for i in range(w):
            lon = 2 * math.pi * ((i + 0.5) / w) - math.pi
            dx = cl * math.cos(lon)
            dy = math.sin(lat)
            dz = cl * math.sin(lon)

            # грань та, у которой направление заходит дальше всего вперёд
            face = max(FACES, key=lambda f: dx * forwards[f][0]
                       + dy * forwards[f][1] + dz * forwards[f][2])
            fx, fy, fz = forwards[face]
            rx, ry, rz = _BASIS[face][1]
            ux, uy, uz = _BASIS[face][2]
            u = dx * rx + dy * ry + dz * rz
            v = dx * ux + dy * uy + dz * uz
            if MIRROR:
                u = -u
            fi = int((u + 1.0) / 2.0 * size)
            fj = int((1.0 - v) / 2.0 * size)
            od[i, j] = caches[face][min(size - 1, max(0, fi)),
                                   min(size - 1, max(0, fj))]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Кодирование
# ─────────────────────────────────────────────────────────────────────────────
def _encode_mip(img: Image.Image) -> bytes:
    """Один мип-уровень в DXT1 через Pillow."""
    if img.size[0] % 4 or img.size[1] % 4:
        img = img.resize(((img.size[0] + 3) // 4 * 4, (img.size[1] + 3) // 4 * 4), Image.BICUBIC)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="DDS", pixel_format="DXT1")
    data = buf.getvalue()
    if data[:4] != b"DDS ":
        raise SkyboxError("Pillow не записал DDS")
    body = data[HEADER_SIZE:]           # отбрасываем заголовок, оставляем блоки
    blocks = (img.size[0] // 4) * (img.size[1] // 4) * 8
    return body[:blocks]


def encode_tex(face_image: Image.Image, size: int = FACE_SIZE,
               mips: int = MIP_LEVELS) -> bytes:
    """Грань куба со всей цепочкой мипов в формате .tex."""
    cur = face_image.resize((size, size), Image.LANCZOS)
    chunks = []
    w = h = size
    for _ in range(mips):
        chunks.append(_encode_mip(cur))
        # ниже 4x4 каждый уровень — всё равно один блок, но уровень должен
        # существовать: иначе Roblox не найдёт нужный мип
        nw, nh = max(4, w // 2), max(4, h // 2)
        if nw == w and nh == h:
            cur = cur.resize((4, 4), Image.BICUBIC)
        else:
            cur = cur.resize((nw, nh), Image.LANCZOS)
        w, h = nw, nh

    out = bytearray(dds_header(size, size, mips))
    for c in chunks:
        out += c
    return bytes(out)


def expected_size(size: int = FACE_SIZE, mips: int = MIP_LEVELS) -> int:
    total = 0
    for lvl in range(mips):
        w = max(4, size >> lvl)
        h = max(4, size >> lvl)
        total += (w // 4) * (h // 4) * 8
    return total + HEADER_SIZE


def read_header(path: str | Path) -> dict:
    """Читает параметры существующего .tex: размер, число мипов, сжатие."""
    raw = Path(path).read_bytes()[:HEADER_SIZE]
    if len(raw) < HEADER_SIZE or raw[:4] != b"DDS ":
        raise SkyboxError(f"{Path(path).name} — не DDS, заменять нечего")
    return {
        "width": struct.unpack_from("<I", raw, 16)[0],
        "height": struct.unpack_from("<I", raw, 12)[0],
        "mips": struct.unpack_from("<I", raw, 28)[0],
        "fourcc": raw[84:88].decode("ascii", "replace"),
        "bytes": Path(path).stat().st_size,
    }


def match_destination(destination: str | Path) -> tuple[int, int]:
    """Размер и число мипов, которые требует уже установленный Roblox."""
    h = read_header(destination)
    if h["fourcc"] != "DXT1":
        raise SkyboxError(f"сжатие {h['fourcc']} не поддерживается, нужно DXT1")
    return h["width"], h["mips"]


# ─────────────────────────────────────────────────────────────────────────────
# Публичный API
# ─────────────────────────────────────────────────────────────────────────────
def panorama_to_tex(panorama: Image.Image, face: str, size: int = FACE_SIZE,
                    mips: int = MIP_LEVELS) -> bytes:
    if face not in FACES:
        raise SkyboxError(f"неизвестная грань: {face}")
    if panorama.width != panorama.height * 2:
        raise SkyboxError(
            f"панорама должна быть 2:1 (сейчас {panorama.width}x{panorama.height}). "
            f"Обрежь или дополни изображение.")
    return encode_tex(render_face(panorama, face, size), size, mips)


def build_skybox(panorama: Image.Image, out_dir: str | Path,
                 size: int = FACE_SIZE, prefix: str = "sky512",
                 mips: int = MIP_LEVELS,
                 reference: str | Path | None = None) -> dict[str, Path]:
    """
    Пишет шесть .tex в out_dir. Возвращает {грань: путь}.

    reference — существующий .tex Roblox: по нему берутся размер и число мипов,
    иначе используются значения по умолчанию. Имя файла врёт (sky512 = 1024),
    поэтому доверять ему нельзя.
    """
    if reference is not None and Path(reference).is_file():
        size, mips = match_destination(reference)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = {}
    for face in FACES:
        data = panorama_to_tex(panorama, face, size, mips)
        p = out / f"{prefix}_{face}.tex"
        p.write_bytes(data)
        written[face] = p
    return written


def verify(path: str | Path, size: int = FACE_SIZE,
           mips: int = MIP_LEVELS) -> dict:
    """Проверяет, что .tex устроен так, как ждёт Roblox."""
    raw = Path(path).read_bytes()
    info = {
        "bytes": len(raw),
        "magic_ok": raw[:4] == b"DDS ",
        "fourcc": raw[84:88].decode("ascii", "replace"),
        "width": struct.unpack_from("<I", raw, 16)[0] if raw[:4] == b"DDS " else 0,
        "height": struct.unpack_from("<I", raw, 12)[0] if raw[:4] == b"DDS " else 0,
        "mips": struct.unpack_from("<I", raw, 28)[0] if raw[:4] == b"DDS " else 0,
    }
    info["size_ok"] = info["bytes"] == expected_size(size, mips)
    info["ok"] = (info["magic_ok"] and info["fourcc"] == "DXT1"
                  and info["width"] == size and info["height"] == size
                  and info["mips"] == mips and info["size_ok"])
    return info


def read_tex(path: str | Path) -> Image.Image:
    """Читает .tex обратно в картинку — для предпросмотра."""
    return Image.open(path).convert("RGB")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        print("команды:")
        print("  python tools/skybox.py build panorama.png out_dir")
        print("  python tools/skybox.py info some_sky512_ft.tex")
        return 0

    try:
        if argv[0] == "build" and len(argv) >= 3:
            pan = Image.open(argv[1])
            files = build_skybox(pan, argv[2])
            print(f"готово, {len(files)} граней → {argv[2]}")
            for face, p in files.items():
                v = verify(p)
                print(f"  {p.name:18s} {v['bytes']:>7d} Б  "
                      f"{v['width']}x{v['height']}  {v['fourcc']}  "
                      f"мипов {v['mips']}  {'ок' if v['ok'] else 'ПРОБЛЕМА'}")
            return 0

        if argv[0] == "info" and len(argv) >= 2:
            v = verify(argv[1])
            for k, val in v.items():
                print(f"  {k:10s} {val}")
            return 0 if v["ok"] else 1
    except SkyboxError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:                                      # noqa: BLE001
        print(f"непредвиденная ошибка: {exc}", file=sys.stderr)
        return 3

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())