"""Проверки вшитых звуков и шрифтов (без Roblox, без сети)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from cursor_manager.content import fonts, sounds  # noqa: E402
from cursor_manager.core import roblox_paths as RP  # noqa: E402

FAILS = 0


def check(name: str, ok: bool) -> None:
    global FAILS
    print(("OK   " if ok else "FAIL ") + name)
    FAILS += 0 if ok else 1


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def mp3_ok(b: bytes) -> bool:
    if b[:3] == b"ID3":
        return True
    return len(b) > 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0


def main() -> int:
    sm = json.loads(sounds.MANIFEST.read_text(encoding="utf-8"))
    sp = sounds.load_presets()
    check("звуки: все записи манифеста загружены", len(sp) == len(sm["items"]) > 0)
    check("звуки: id уникальны", len({s["id"] for s in sp}) == len(sp))
    check("звуки: sha256 совпадают",
          all(sha(s["path"]) == i["sha256"] for s, i in zip(sp, sm["items"])))
    check("звуки: лицензия CC0 и bundle_allowed",
          all(s["license"] == "CC0-1.0" and RP.bundle_allowed(s["license"]) for s in sp))
    check("звуки: автор и источник заполнены",
          all(s["author"] and s["source_url"].startswith("https://") for s in sp))
    bad = []
    for s in sp:
        b = s["path"].read_bytes()
        for t in s["targets"]:
            ok = b[:4] == b"OggS" if t.endswith(".ogg") else mp3_ok(b)
            if not ok or t.rsplit(".", 1)[1] != s["path"].suffix[1:]:
                bad.append((s["id"], t))
    check(f"звуки: формат файла совпадает с целью Roblox {bad}", not bad)
    check("звуки: имена целей проходят RP.validate",
          all(RP.validate(RP.KIND_SOUND, t) is None
              for s in sp for t in s["targets"]))
    check("звуки: смерть — не менее 6 вариантов",
          sum(s["role"] == "death" for s in sp) >= 6)
    size = sum(p.stat().st_size for p in sounds.SOUNDS_DIR.rglob("*") if p.is_file())
    check(f"звуки: вес {size // 1024} КБ <= 5 МБ", size <= 5 * 1024 * 1024)

    fm = json.loads(fonts.MANIFEST.read_text(encoding="utf-8"))
    fp = fonts.load_presets()
    check("шрифты: все записи загружены", len(fp) == len(fm["items"]) >= 6)
    allowed = {"OFL-1.1", "Apache-2.0"}
    check("шрифты: лицензии OFL/Apache",
          all(f["license"] in allowed and RP.bundle_allowed(f["license"]) for f in fp))
    sha_ok = all(sha(fonts.FONTS_DIR / fn) == it["sha256"][k]
                 for it in fm["items"] for k, fn in it["files"].items())
    check("шрифты: sha256 совпадают", sha_ok)
    for f in fp:
        img = Image.new("L", (400, 80), 0)
        try:
            for p in (f["regular"], f["bold"]):
                font = ImageFont.truetype(str(p), 40)
                ImageDraw.Draw(img).text((4, 4), "Привет", font=font, fill=255)
            ink = img.getbbox() is not None
        except Exception as e:  # noqa: BLE001
            ink = False
            print("   ", f["id"], e)
        check(f"шрифт {f['id']}: кириллица рисуется", ink)
        m = fonts.files_for(f)
        check(f"шрифт {f['id']}: files_for даёт 4 файла",
              set(m) == set(fonts.TARGETS) and all(p.is_file() for p in m.values()))
    print("FAILED" if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
