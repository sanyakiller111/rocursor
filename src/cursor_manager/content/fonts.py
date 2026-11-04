"""Вшитые шрифты (SIL OFL 1.1): статические TTF Regular/Bold.

Roblox рисует интерфейс шрифтом Builder Sans; подмена — файлы с теми же
именами в `content/fonts`. FreeType определяет формат по содержимому, так
что TTF под именем .otf читается. Запись в Roblox тут не делается.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGETS: dict[str, str] = {
    "BuilderSans-Regular.otf": "regular",
    "BuilderSans-Medium.otf": "regular",
    "BuilderSans-Bold.otf": "bold",
    "BuilderSans-ExtraBold.otf": "bold",
}


def _resource_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"


FONTS_DIR = _resource_root() / "fonts"
MANIFEST = FONTS_DIR / "manifest.json"


def load_presets() -> list[dict]:
    """Шрифты: id, name, regular (Path), bold (Path), license, author,
    source_url. Если Bold нет, bold указывает на Regular."""
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[dict] = []
    for it in data.get("items", []):
        files = it.get("files", {})
        reg = FONTS_DIR / str(files.get("regular", ""))
        bold = FONTS_DIR / str(files.get("bold") or files.get("regular", ""))
        if not reg.is_file() or not bold.is_file():
            continue
        out.append({
            "id": it["id"], "name": it["name"], "regular": reg, "bold": bold,
            "license": it.get("license", "UNKNOWN"),
            "author": it.get("author", ""),
            "source_url": it.get("source_url", ""),
        })
    return out


def files_for(preset: dict) -> dict[str, Path]:
    """{имя файла Roblox: Path к шрифту} для установки пресета."""
    return {name: preset[weight] for name, weight in TARGETS.items()}
