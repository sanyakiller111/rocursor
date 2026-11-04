"""
core/rcur.py — формат .rcur. Один файл = сет из трёх картинок.

Зачем. После обновления Roblox создаёт новую папку version-…, и подменённые
текстуры в ней стираются. Сет, сохранённый в файл, — ручной якорь: двойной
клик по нему возвращает курсор за секунду, без открытия окна.

Два формата, чтение поддерживает оба, запись — только бинарный.

LEGACY (текстовый)
------------------
    <base64 PNG #1>
    <base64 PNG #2>
    <base64 PNG #3>
Три строки, каждая — картинка целиком в base64. Читается, чтобы не отказывать
людям с уже сохранёнными сетами.

BINARY
------
    0..4    "RCUR\0"
    5..8    версия формата, uint32 little-endian
    9..     uint32 × 3 — длины трёх блобов
    ...     блобы подряд, в том же порядке

Ограничения на приём (файл приходит с диска, доверять нельзя):
  * магический байт RCUR обязателен
  * версия в пределах поддерживаемого диапазона
  * каждая длина проверяется против реальной длины блоба
  * суммарный размер ограничен, чтобы 4-гигабайтный заголовок не съел память
  * каждый блоб обязан быть настоящим PNG с разумными размерами
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"RCUR\x00"
FORMAT_VERSION = 1
SUPPORTED_VERSIONS = (1,)
MAX_BLOB = 4 * 1024 * 1024        # 4 МБ на картинку
MAX_TOTAL = 12 * 1024 * 1024      # 12 МБ на весь сет

# Слоты соответствуют cursor_core.FILES: две стрелки + вертикальная черта.
SLOTS = ("arrow", "far", "ibeam")


class RcurError(Exception):
    """Файл не является .rcur или повреждён."""


@dataclass
class RcurSet:
    arrow: bytes | None = None
    far: bytes | None = None
    ibeam: bytes | None = None
    name: str = ""
    blurb: str = ""
    scale: int = 100
    nudge: tuple[int, int] = (0, 0)
    files: tuple[str, ...] = SLOTS
    source_format: str = ""
    extra: dict = field(default_factory=dict)

    def blobs(self) -> list[bytes | None]:
        return [self.arrow, self.far, self.ibeam]

    def __iter__(self):
        for slot, blob in zip(self.files, self.blobs()):
            if blob:
                yield slot, blob


# ─────────────────────────────────────────────────────────────────────────────
# Проверка
# ─────────────────────────────────────────────────────────────────────────────
def _check_png(blob: bytes, where: str) -> None:
    if not blob:
        return
    if len(blob) > MAX_BLOB:
        raise RcurError(f"{where}: файл больше {MAX_BLOB // 1048576} МБ")
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RcurError(f"{where}: это не PNG")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(blob)) as im:
            im.verify()
    except Exception as exc:
        raise RcurError(f"{where}: PNG не читается ({exc})") from exc


def _validate(set_: RcurSet) -> RcurSet:
    if not any(set_.blobs()):
        raise RcurError("в сете нет ни одной картинки")
    for slot, blob in set_:
        _check_png(blob, slot)
    if len(set_.files) != len(SLOTS):
        raise RcurError(f"ожидалось {len(SLOTS)} слота, получено {len(set_.files)}")
    if not 40 <= int(set_.scale) <= 300:
        raise RcurError(f"масштаб вне диапазона 40–300: {set_.scale}")
    if not (-16 <= int(set_.nudge[0]) <= 16 and -16 <= int(set_.nudge[1]) <= 16):
        raise RcurError("смещение вне диапазона −16..16 px")
    return set_


# ─────────────────────────────────────────────────────────────────────────────
# Чтение
# ─────────────────────────────────────────────────────────────────────────────
def sniff(data: bytes) -> str:
    if data.startswith(MAGIC):
        return "binary"
    head = data.lstrip()[:64]
    if any(line for line in head.split(b"\n")[:1] if line[:1].isalnum()) and b"\x89PNG" not in data[:16]:
        # три строки base64 выглядят как текст; бинарный мусор так не начинается
        try:
            data.decode("ascii")
            return "legacy"
        except UnicodeDecodeError:
            pass
    return "unknown"


def loads(data: bytes) -> RcurSet:
    """Разобрать .rcur из памяти. Формат определяется по содержимому."""
    if len(data) > MAX_TOTAL:
        raise RcurError(f"файл больше {MAX_TOTAL // 1048576} МБ")

    kind = sniff(data)
    if kind == "binary":
        return _load_binary(data)
    if kind == "legacy":
        return _load_legacy(data)
    raise RcurError("не .rcur: нет ни магического байта RCUR, ни base64-строк")


def _load_binary(data: bytes) -> RcurSet:
    if len(data) < 9 + 12:
        raise RcurError("файл слишком короткий для бинарного формата")
    version = struct.unpack_from("<I", data, 5)[0]
    if version not in SUPPORTED_VERSIONS:
        raise RcurError(f"версия формата {version} не поддерживается "
                        f"(умею {', '.join(map(str, SUPPORTED_VERSIONS))})")
    sizes = struct.unpack_from("<III", data, 9)
    total = sum(sizes)
    if total > MAX_TOTAL:
        raise RcurError(f"заявленный объём {total} Б превышает лимит")
    expected = 21 + total
    if len(data) < expected:
        raise RcurError(f"файл короче, чем обещает заголовок: {len(data)} Б "
                        f"из {expected} — файл обрезан")
    # хвост длиннее блобов — это метаданные (или мусор после них). Обрезание
    # смертельно, лишний байт в конце безобиден: парсер хвоста его проигнорирует.

    out, pos = [], 21
    for i, size in enumerate(sizes):
        if size == 0:
            out.append(None)
            continue
        out.append(data[pos:pos + size])
        pos += size
        _check_png(out[-1], f"слот {i}")

    s = RcurSet(arrow=out[0], far=out[1], ibeam=out[2], source_format="binary")
    _attach_metadata(s, data, version)
    return _validate(s)


def _load_legacy(data: bytes) -> RcurSet:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RcurError(f"legacy-файл не текстовый: {exc}") from exc
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not 1 <= len(lines) <= len(SLOTS):
        raise RcurError(f"ожидалось до {len(SLOTS)} строк base64, найдено {len(lines)}")

    blobs = []
    for line in lines:
        try:
            blobs.append(base64.b64decode(line, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise RcurError(f"строка {len(blobs) + 1} не является base64: {exc}") from exc

    while len(blobs) < len(SLOTS):
        blobs.append(None)
    for i, b in enumerate(blobs):
        _check_png(b, f"слот {i}")

    s = RcurSet(arrow=blobs[0], far=blobs[1], ibeam=blobs[2], source_format="legacy")
    return _validate(s)


def _attach_metadata(s: RcurSet, data: bytes, version: int) -> None:
    """
    Метаданные лежат в хвосте файла после блобов: нулевой байт-разделитель,
    затем JSON. Старые версии формата без хвоста читаются как есть.
    """
    tail = data[21 + sum(len(b) for b in s.blobs() if b):]
    if not tail or tail[0:1] != b"\x00":
        return
    try:
        meta = json.loads(tail[1:].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return                      # хвост нечитаем — не повод отказывать в сете
    if not isinstance(meta, dict):
        return
    s.name   = str(meta.get("name", ""))[:120]
    s.blurb  = str(meta.get("blurb", ""))[:400]
    s.scale  = int(meta.get("scale", 100) or 100)
    nudge   = meta.get("nudge", [0, 0])
    if isinstance(nudge, (list, tuple)) and len(nudge) == 2:
        s.nudge = (int(nudge[0]), int(nudge[1]))
    if isinstance(meta.get("files"), list) and len(meta["files"]) == len(SLOTS):
        s.files = tuple(str(x)[:16] for x in meta["files"])


def load(path: str | Path) -> RcurSet:
    return loads(Path(path).read_bytes())


# ─────────────────────────────────────────────────────────────────────────────
# Запись
# ─────────────────────────────────────────────────────────────────────────────
def dumps(set_: RcurSet, *, with_metadata: bool = True) -> bytes:
    """Собрать .rcur в бинарном формате."""
    _validate(set_)
    blobs = [b or b"" for b in set_.blobs()]
    if any(len(b) > MAX_BLOB for b in blobs):
        raise RcurError("один из файлов слишком большой")

    head = MAGIC + struct.pack("<I", FORMAT_VERSION)
    head += struct.pack("<III", *(len(b) for b in blobs))
    body = b"".join(blobs)

    tail = b""
    if with_metadata:
        meta = {
            "name": set_.name[:120],
            "blurb": set_.blurb[:400],
            "scale": int(set_.scale),
            "nudge": [int(set_.nudge[0]), int(set_.nudge[1])],
            "files": list(set_.files),
            "app": "sanyakiller111-cursor-manager",
        }
        tail = b"\x00" + json.dumps(meta, ensure_ascii=False).encode("utf-8")

    return head + body + tail


def dump(set_: RcurSet, path: str | Path, **kw) -> Path:
    data = dumps(set_, **kw)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def set_from_files(arrow: str | Path, far: str | Path | None = None,
                   ibeam: str | Path | None = None, **meta) -> RcurSet:
    """Собрать сет из PNG на диске."""
    def rd(p):
        return Path(p).read_bytes() if p else None
    return RcurSet(arrow=rd(arrow), far=rd(far), ibeam=rd(ibeam), **meta)


def to_zip(set_: RcurSet, path: str | Path) -> Path:
    """
    .rcur рядом с .zip того же содержимого.

    Некоторые системы antivirus и почтовые фильтры режут нестандартные
    расширения. Zip с тем же содержимым и теми же именами внутри переживает
    пересылку без потерь — это запасной путь, а не основной формат.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        for slot, blob in set_:
            if blob:
                z.writestr(f"{slot}.png", blob)
        z.writestr("set.json", json.dumps({
            "name": set_.name, "blurb": set_.blurb, "scale": int(set_.scale),
            "nudge": [int(set_.nudge[0]), int(set_.nudge[1])], "files": list(set_.files),
        }, ensure_ascii=False, indent=1))
    return p


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("команды:")
        print("  python -m cursor_manager.core.rcur info  file.rcur")
        print("  python -m cursor_manager.core.rcur pack  arrow.png [far.png] [ibeam.png] out.rcur")
        print("  python -m cursor_manager.core.rcur tozip file.rcur")
        return 0

    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "info" and args:
            s = load(args[0])
            print(f"формат   : {s.source_format}")
            print(f"имя      : {s.name or '—'}")
            print(f"описание : {s.blurb or '—'}")
            print(f"масштаб  : {s.scale}%")
            print(f"смещение : {s.nudge}")
            for slot, blob in s:
                print(f"  {slot:6s} {len(blob):>7d} Б")
            return 0

        if cmd == "pack" and len(args) >= 2:
            paths = args[:-1]
            out = args[-1]
            s = set_from_files(*paths[:3])
            dump(s, out)
            print(f"записан  : {out} ({Path(out).stat().st_size} Б)")
            return 0

        if cmd == "tozip" and args:
            s = load(args[0])
            out = Path(args[0]).with_suffix(".zip")
            to_zip(s, out)
            print(f"записан  : {out}")
            return 0
    except RcurError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:                      # noqa: BLE001 — CLI не должен падать стеком
        print(f"непредвиденная ошибка: {exc}", file=sys.stderr)
        return 2

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())