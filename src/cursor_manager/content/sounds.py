"""Вшитые звуки: CC0-наборы по ролям (смерть, прыжок, шаги, ...).

Роль — это «что заменяем». Каждая роль знает, в какие файлы Roblox
(`content/sounds`) её класть. Формат файла в ассетах совпадает с форматом
цели (OGG для .ogg, MP3 для .mp3). Классический «oof» и вообще звуки
Roblox сюда не входят — права не наши. Запись в Roblox тут не делается.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROLES: dict[str, dict] = {
    "death": {"title": "Звук смерти", "targets": ["oof.ogg", "ouch.ogg"]},
    "jump": {"title": "Прыжок", "targets": ["action_jump.mp3"]},
    "land": {"title": "Приземление", "targets": ["action_jump_land.mp3"]},
    "footsteps": {"title": "Шаги", "targets": ["action_footsteps_plastic.mp3"]},
    "getup": {"title": "Вставание", "targets": ["action_get_up.mp3"]},
    "falling": {"title": "Падение", "targets": ["action_falling.ogg"]},
    "ui": {"title": "Ползунок громкости", "targets": ["volume_slider.ogg"]},
}


def _resource_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"


SOUNDS_DIR = _resource_root() / "sounds"
MANIFEST = SOUNDS_DIR / "manifest.json"


def load_presets() -> list[dict]:
    """Звуки из манифеста: id, name, role, path, license, author,
    source_url, targets. Битые записи и несуществующие файлы пропускаются."""
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[dict] = []
    for it in data.get("items", []):
        role = it.get("role")
        path = SOUNDS_DIR / str(it.get("file", ""))
        if role not in ROLES or not path.is_file():
            continue
        out.append({
            "id": it["id"], "name": it["name"], "role": role, "path": path,
            "license": it.get("license", "UNKNOWN"),
            "author": it.get("author", ""),
            "source_url": it.get("source_url", ""),
            "targets": list(ROLES[role]["targets"]),
        })
    return out
