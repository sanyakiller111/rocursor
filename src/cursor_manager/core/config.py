"""
config.py — что пользователь выбрал во вшитой библиотеке.

Три слота: курсор, shiftlock (MouseLockedCursor.png) и skybox. В слоте
хранится только id элемента каталога и имя для показа — сами файлы
собирает UI из content/, потому что core не зависит от content.

Зачем: канал direct пишет в папку version-…, а Roblox при обновлении
ставится в новую папку, и всё слетает. Конфиг помнит, на какую версию
ставили; при запуске UI сравнивает её с текущей и ставит слоты заново.

Файл: %APPDATA%\\RobloxCursorChanger\\config.json, рядом с бэкапами.
Запись — через .part + os.replace, чтобы обрыв не оставил битый JSON.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cursor_manager.core import respack

CONFIG_FILE = respack.APP_ROOT / "config.json"
SCHEMA = 1
SLOTS = ("cursor", "crosshair", "sky", "material", "font")
# у звуков слот на каждую роль: «sound:death», «sound:jump»…
SOUND_PREFIX = "sound:"


def valid_slot(key: str) -> bool:
    return key in SLOTS or (key.startswith(SOUND_PREFIX) and len(key) > len(SOUND_PREFIX))


def slot_kind(key: str) -> str:
    """Категория roblox_paths для ключа слота."""
    return "sound" if key.startswith(SOUND_PREFIX) else key


@dataclass
class Slot:
    id: str
    name: str
    applied_at: str = ""


@dataclass
class Config:
    backend: str = "direct"
    version: str = ""                      # имя папки version-…, куда ставили
    slots: dict[str, Slot] = field(default_factory=dict)
    # вкладка fps: включённые опции core.fps, лимит кадров и уровень графики
    fps_options: list[str] = field(default_factory=list)
    fps_cap: int | None = None
    fps_quality: int | None = None
    # вкладка серверов: последние игры [{"place": id, "name": …}]
    recent_places: list[dict] = field(default_factory=list)

    # ── чтение и запись ────────────────────────────────────────────────
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Битый или чужой файл не ломает запуск: просто пустой конфиг."""
        path = path or CONFIG_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            return cls()
        slots = {}
        for key, value in (raw.get("slots") or {}).items():
            if valid_slot(key) and isinstance(value, dict) and value.get("id"):
                slots[key] = Slot(id=str(value["id"]),
                                  name=str(value.get("name") or value["id"]),
                                  applied_at=str(value.get("applied_at") or ""))
        fps = raw.get("fps") if isinstance(raw.get("fps"), dict) else {}

        def _int(value):
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        recent = [r for r in (raw.get("recent_places") or [])
                  if isinstance(r, dict) and _int(r.get("place"))][:8]
        # канал один — direct; старое "bloxstrap" из прежних версий читаем как direct
        return cls(backend="direct",
                   version=str(raw.get("version") or ""), slots=slots,
                   fps_options=[str(o) for o in (fps.get("options") or [])],
                   fps_cap=_int(fps.get("cap")), fps_quality=_int(fps.get("quality")),
                   recent_places=recent)

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_FILE
        payload = {"schema": SCHEMA, "backend": self.backend,
                   "version": self.version,
                   "slots": {k: asdict(v) for k, v in self.slots.items()},
                   "fps": {"options": self.fps_options, "cap": self.fps_cap,
                           "quality": self.fps_quality},
                   "recent_places": self.recent_places}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, path)

    # ── изменения ──────────────────────────────────────────────────────
    def remember(self, slot: str, item_id: str, name: str,
                 backend: str, version: str) -> None:
        if not valid_slot(slot):
            raise ValueError(f"неизвестный слот: {slot}")
        self.slots[slot] = Slot(
            id=item_id, name=name,
            applied_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.backend = "direct"        # поле осталось ради формата файла
        self.version = version

    def forget(self, slot: str) -> None:
        self.slots.pop(slot, None)

    def remember_place(self, place: int, name: str) -> None:
        self.recent_places = [{"place": int(place), "name": name}] + [
            r for r in self.recent_places if r.get("place") != int(place)][:7]

    def needs_restore(self, current_version: str) -> bool:
        """
        Пора ставить заново: канал direct и Roblox уже в другой папке.

        Bloxstrap не в счёт — он сам подкладывает оверлей после обновления.
        Флаги FPS тоже живут в папке версии, поэтому считаются наравне со
        слотами; лимит кадров — в общих настройках и не слетает.
        """
        return (self.backend == "direct" and bool(self.slots or self.fps_options)
                and bool(self.version) and self.version != current_version)
