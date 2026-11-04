"""
tests/test_rcur.py — формат .rcur: оба формата, метаданные, отказ на мусоре.

Запуск:  python tests/test_rcur.py
"""
from __future__ import annotations

import base64
import io
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cursor_manager.core import rcur  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def png(size=(64, 64), color=(53, 160, 255, 255)) -> bytes:
    from PIL import Image
    img = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


A, B, C = png(color=(53, 160, 255, 255)), png(color=(43, 217, 138, 255)), png(color=(224, 49, 49, 255))


def main() -> int:
    print("\n── бинарный формат ──")
    s = rcur.RcurSet(arrow=A, far=B, name="Мой сет", blurb="синяя стрелка", scale=120, nudge=(2, -3))
    data = rcur.dumps(s)
    check("магика на месте", data.startswith(b"RCUR\x00"))
    check("версия записана", struct.unpack_from("<I", data, 5)[0] == 1)
    check("три длины", struct.unpack_from("<III", data, 9) == (len(A), len(B), 0))

    back = rcur.loads(data)
    check("round-trip стрелка", back.arrow == A)
    check("round-trip второй слот", back.far == B)
    check("пустой слот остаётся пустым", back.ibeam is None)
    check("имя сохранено", back.name == "Мой сет")
    check("описание сохранено", back.blurb == "синяя стрелка")
    check("масштаб сохранён", back.scale == 120)
    check("смещение сохранено", back.nudge == (2, -3))
    check("формат определён как binary", back.source_format == "binary")

    print("\n── legacy формат ──")
    legacy = b"\n".join(base64.b64encode(x) for x in (A, B, C))
    ls = rcur.loads(legacy)
    check("определён как legacy", ls.source_format == "legacy")
    check("слот 1", ls.arrow == A)
    check("слот 2", ls.far == B)
    check("слот 3", ls.ibeam == C)
    check("пустые строки пропущены", rcur.loads(base64.b64encode(A)).arrow == A
          and rcur.loads(base64.b64encode(A)).far is None)

    print("\n── смена формата при перезаписи ──")
    conv = rcur.dumps(ls)
    check("legacy → binary", rcur.loads(conv).source_format == "binary")
    check("картинки уцелели", rcur.loads(conv).ibeam == C)

    print("\n── отказ на мусоре ──")
    cases = {
        "пустой файл": b"",
        "случайные байты": b"\x12\x34\x56\x78\x9a" * 40,
        "бинарный с обрезанным хвостом": data[:len(data) // 2],
        "завышенная длина блоба": rcur.MAGIC + struct.pack("<I", 1) + struct.pack("<III", 99_000_000, 0, 0),
        "неизвестная версия": rcur.MAGIC + struct.pack("<I", 99) + struct.pack("<III", 0, 0, 0),
        "legacy с битым base64": b"not-base64-@@@\n@@@@",
        "png подменён мусором": rcur.dumps(rcur.RcurSet(arrow=A))[:21] + b"NOTAPNG!" + b"\x00" * 8,
    }
    for label, payload in cases.items():
        try:
            rcur.loads(payload)
            check(f"отклонено: {label}", False, "исключения не было")
        except rcur.RcurError:
            check(f"отклонено: {label}", True)
        except Exception as exc:                  # noqa: BLE001
            check(f"отклонено: {label}", False, f"неверная ошибка {exc!r}")

    print("\n── терпимость к лишнему хвосту ──")
    try:
        padded = rcur.loads(data + b"\x00junk-after-metadata")
        check("дописанные байты не ломают файл", padded.arrow == A)
    except rcur.RcurError as exc:
        check("дописанные байты не ломают файл", False, str(exc))
    no_meta = rcur.dumps(rcur.RcurSet(arrow=A), with_metadata=False)
    check("файл без метаданных читается", rcur.loads(no_meta).arrow == A)

    print("\n── проверка содержимого ──")
    try:
        rcur.dumps(rcur.RcurSet(arrow=A, far=B, scale=500))
        check("масштаб вне диапазона отклонён", False)
    except rcur.RcurError:
        check("масштаб вне диапазона отклонён", True)
    try:
        rcur.dumps(rcur.RcurSet(arrow=A, far=B, nudge=(99, 0)))
        check("смещение вне диапазона отклонён", False)
    except rcur.RcurError:
        check("смещение вне диапазона отклонён", True)
    try:
        rcur.dumps(rcur.RcurSet())
        check("пустой сет отклонён", False)
    except rcur.RcurError:
        check("пустой сет отклонён", True)

    print("\n── zip-экспорт ──")
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rcurtest-"))
    out = tmp / "set.zip"
    rcur.to_zip(ls, out)
    import zipfile
    with zipfile.ZipFile(out) as z:
        names = sorted(z.namelist())
    check("zip содержит слоты", "arrow.png" in names and "far.png" in names and "ibeam.png" in names, str(names))
    check("zip содержит метаданные", "set.json" in names)

    print("\n── совместимость слоёв с cursor_core ──")
    from cursor_manager.core import cursor_core as cc
    check("в FILES есть IBeamCursor.png", "IBeamCursor.png" in cc.FILES)
    check("IBeamCursor выключен по умолчанию", "IBeamCursor.png" not in cc.DEFAULT_FILES)
    check("все три активных слота есть в FILES",
          all(n in cc.FILES for n in ("ArrowCursor.png", "ArrowFarCursor.png", "IBeamCursor.png")))
    check("три слота .rcur совпадают с именами файлов Roblox",
          set(rcur.SLOTS) == {"arrow", "far", "ibeam"})

    print("\n" + "═" * 58)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print("  ·", f)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())