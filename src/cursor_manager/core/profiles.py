"""
profiles.py — профили: наборы ресурсов, которые применяются вместе.

Профиль отвечает на вопрос «как я играл в прошлый раз». В нём лежат
идентификаторы наборов, а не файлы: файлы лежат в своих папках и могут
обновиться, профиль переживает это.

Профиль умеет три вещи:
  * применить   — поставить все наборы в выбранный канал
  * снять       — вернуть оригиналы по всем наборам профиля
  * сохранить   — записать текущий набор применённых наборов под именем
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from cursor_manager.core import respack, roblox_paths as RP

SCHEMA = 1
STATE_FILE = "profiles.json"
LIBRARY_DIR = "packs"


def _app_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "RobloxCursorChanger"


def library_root() -> Path:
    return _app_dir() / LIBRARY_DIR


def profiles_file() -> Path:
    return _app_dir() / STATE_FILE


def _target_key(kind: str, rel: str) -> str:
    """Один и тот же файл Roblox может прийти из разных категорий."""
    return RP.get(kind).rel(PurePosixPath(rel).name).as_posix()


class ProfileError(Exception):
    pass


@dataclass
class Profile:
    name: str
    packs: list[str] = field(default_factory=list)      # id наборов (имя папки)
    backend: str = "direct"
    saved_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Profiles:
    """Хранилище профилей. Читает папку целиком при первом обращении."""

    def __init__(self):
        self.path = profiles_file()
        self.items: dict[str, Profile] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in raw.get("profiles", []):
            if not isinstance(d, dict) or "name" not in d:
                continue
            try:
                p = Profile(
                    name=str(d["name"])[:64],
                    packs=[str(x)[:64] for x in (d.get("packs") or [])],
                    backend=str(d.get("backend") or "direct"),
                    saved_at=str(d.get("saved_at") or ""),
                )
            except (TypeError, ValueError):
                continue
            if p.backend not in ("direct", "bloxstrap"):
                p.backend = "direct"
            self.items[p.name] = p

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "profiles": [p.to_dict() for p in self.items.values()],
        }
        tmp = self.path.with_suffix(".json.part")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ── список ──
    def names(self) -> list[str]:
        return list(self.items)

    def get(self, name: str) -> Profile | None:
        return self.items.get(name)

    def remove(self, name: str) -> bool:
        if self.items.pop(name, None) is None:
            return False
        self.save()
        return True

    # ── сохранение ──
    def save_current(self, name: str, pack_ids: list[str], backend: str = "direct") -> Profile:
        name = str(name).strip()[:64]
        if not name:
            raise ProfileError("имя профиля пустое")
        p = Profile(
            name=name,
            packs=sorted({str(x) for x in pack_ids}),
            backend=backend,
            saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.items[name] = p
        self.save()
        return p

    def collisions(self, name: str) -> list[str]:
        """
        Какие файлы профиля забивают друг друга.

        Два набора одной категории, оба с именем ArrowCursor.png, претендуют
        на один и тот же файл в папке Roblox. Побеждает применённый последним,
        и статус потом честно пишет «отличается от набора» — и это правда,
        и это бесполезно. Коллизия полезнее: её видно до применения.
        """
        p = self.get(name)
        if p is None:
            raise ProfileError(f"профиля «{name}» нет")
        seen: dict[str, str] = {}
        out: list[str] = []
        for pid in p.packs:
            try:
                pack = respack.load_pack(library_root() / pid)
            except (respack.PackError, OSError):
                continue
            for rel in pack.files:
                key = _target_key(pack.meta.kind, rel)
                if key in seen:
                    out.append(f"{key}: «{seen[key]}» и «{pack.meta.name}»")
                else:
                    seen[key] = pack.meta.name
        return out

    # ── применение ──
    def apply(self, name: str, version_dir: Path) -> dict:
        p = self.get(name)
        if p is None:
            raise ProfileError(f"профиля «{name}» нет")
        if not p.packs:
            raise ProfileError(f"в профиле «{name}» пусто")

        root = library_root()
        applied, failed = [], []
        for pid in p.packs:
            pack_dir = root / pid
            try:
                pack = respack.load_pack(pack_dir)
            except (respack.PackError, OSError) as exc:
                failed.append(f"{pid}: {exc}")
                continue
            try:
                res = respack.install(pack, version_dir, p.backend)
                applied.append({"id": pid, "name": pack.meta.name,
                                "files": res["installed"], "skipped": res["skipped"]})
            except (respack.PackError, OSError) as exc:
                failed.append(f"{pack.meta.name}: {exc}")
        return {"profile": name, "backend": p.backend, "applied": applied, "failed": failed}

    def revert(self, name: str, version_dir: Path) -> dict:
        p = self.get(name)
        if p is None:
            raise ProfileError(f"профиля «{name}» нет")
        root = library_root()
        removed, failed = [], []
        for pid in p.packs:
            try:
                pack = respack.load_pack(root / pid)
            except (respack.PackError, OSError) as exc:
                failed.append(f"{pid}: {exc}")
                continue
            try:
                res = respack.uninstall(pack, version_dir, p.backend)
                removed.append({"id": pid, "name": pack.meta.name,
                                "removed": res["removed"],
                                "restored": res["restored"],
                                "skipped": res.get("skipped", [])})
            except (respack.PackError, OSError) as exc:
                failed.append(f"{pack.meta.name}: {exc}")
        return {"profile": name, "backend": p.backend, "reverted": removed, "failed": failed}

    def status(self, name: str, version_dir: Path) -> dict:
        """Что сейчас в папках Roblox против того, что обещает профиль."""
        p = self.get(name)
        if p is None:
            raise ProfileError(f"профиля «{name}» нет")
        # файл, за который бьются два набора, не «отличается» — он занят тем,
        # который применён последним (порядок p.packs совпадает с apply)
        contested: set[str] = set()
        winner: dict[str, str] = {}
        for pid in p.packs:
            try:
                pack = respack.load_pack(library_root() / pid)
            except (respack.PackError, OSError):
                continue
            for rel in pack.files:
                key = _target_key(pack.meta.kind, rel)
                if key in winner:
                    contested.add(key)
                winner[key] = pid

        rows = []
        for pid in p.packs:
            try:
                pack = respack.load_pack(library_root() / pid)
            except (respack.PackError, OSError) as exc:
                rows.append({"id": pid, "ok": False, "why": str(exc)})
                continue
            drift = []
            for rel in pack.files:
                key = _target_key(pack.meta.kind, rel)
                if key in contested and winner.get(key) != pid:
                    drift.append(f"{key}: перебит набором, применённым позже")
                    continue
                live = RP.destination(
                    p.backend, version_dir, pack.meta.kind, PurePosixPath(rel).name)
                if not live.is_file():
                    drift.append(f"{key}: нет на месте")
                elif respack.sha256_of(live) != respack.sha256_of(library_root() / pid / rel):
                    drift.append(f"{key}: отличается от набора")
            rows.append({"id": pid, "ok": not drift, "why": "; ".join(drift)})
        return {"profile": name, "packs": rows, "collisions": self.collisions(name)}

    def reset_everything(self, version_dir: Path, backend: str = "direct") -> dict:
        """Полный сброс: снимает все наборы из библиотеки, не трогая чужие файлы."""
        total_removed, total_restored, total_skipped, failed = [], [], [], []
        for pid in [p.name for p in library_root().iterdir() if p.is_dir()] \
                if library_root().is_dir() else []:
            try:
                pack = respack.load_pack(library_root() / pid)
            except (respack.PackError, OSError):
                continue
            try:
                res = respack.uninstall(pack, version_dir, backend)
                total_removed += res["removed"]
                total_restored += res["restored"]
                total_skipped += res.get("skipped", [])
            except (respack.PackError, OSError) as exc:
                failed.append(f"{pid}: {exc}")
        return {"removed": total_removed, "restored": total_restored,
                "skipped": total_skipped, "failed": failed}


# ── готовые профили при первом запуске ───────────────────────────────────────
STARTER_PROFILES = {
    "Стандарт": {"packs": [], "backend": "direct"},
    "Минимализм": {"packs": [], "backend": "direct"},
    "Ночь": {"packs": [], "backend": "direct"},
}


def ensure_starter() -> Profiles:
    """Заводит пустые профили, чтобы интерфейс не был пустым на первом запуске.
    Они пустые намеренно: наборов в библиотеке ещё нет."""
    ps = Profiles()
    if not ps.items:
        for name, cfg in STARTER_PROFILES.items():
            ps.save_current(name, [], cfg["backend"])
    return ps