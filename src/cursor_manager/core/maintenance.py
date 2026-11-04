"""
maintenance.py — «почистить» и «починить».

scan_junk() ищет только то, что Roblox или эта программа создаст заново:

  %LOCALAPPDATA%\\Roblox\\logs        журналы клиента и студии, нужны разве что
                                    для разбора вылетов; пересоздаются.
  %TEMP%\\Roblox                    временные файлы запуска.
  %LOCALAPPDATA%\\Roblox\\Downloads   скачанные установщики/обновления; при
                                    следующем обновлении скачиваются снова.
  Roblox\\Versions\\version-*        прошлые версии плеера. Текущая (её находит
                                    cursor_core.resolve_roblox_dir) не
                                    трогается; если текущую не нашли или
                                    Roblox запущен, старые версии не
                                    предлагаются. Папки студии не берём:
                                    берутся только те, где есть
                                    RobloxPlayerBeta.exe.
  %APPDATA%\\RobloxCursorChanger\\cache  кэш этой программы (превью, небо);
                                    собирается заново. Бэкапы лежат в backup\\
                                    и сюда не входят.

Намеренно вне списка: rbx-storage*, LocalStorage, GlobalBasicSettings*,
AnalysticsSettings, ClientSettings — там вход в аккаунт и настройки игрока.

clean() не доверяет переданному списку: удаляется только то, что совпало
по пути со свежим scan_junk(), так что подсунуть чужой путь нельзя.
"""
from __future__ import annotations

import os
from pathlib import Path

from cursor_manager.core import cursor_core, fps
from cursor_manager.core import roblox_paths as RP


class MaintenanceError(Exception):
    pass


def roblox_running() -> bool:
    return fps.roblox_running()


def _local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _roaming() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home())


def _temp() -> Path:
    return Path(os.environ.get("TEMP") or os.environ.get("TMP") or Path.home())


def _measure(path: Path) -> tuple[int, int]:
    size = files = 0
    for dirpath, _dirs, names in os.walk(path, followlinks=False):
        for n in names:
            try:
                st = os.lstat(os.path.join(dirpath, n))
            except OSError:
                continue
            size += st.st_size
            files += 1
    return size, files


def _candidates() -> list[dict]:
    """Кандидаты с видом удаления: contents — очистить папку, dir — снести целиком."""
    items = [{"title": t, "path": p, "kind": "contents"} for t, p in (
        ("Журналы Roblox", _local() / "Roblox" / "logs"),
        ("Временные файлы Roblox", _temp() / "Roblox"),
        ("Скачанные установщики Roblox", _local() / "Roblox" / "Downloads"),
        ("Кэш программы", _roaming() / "RobloxCursorChanger" / "cache"),
    )]

    versions = _local() / "Roblox" / "Versions"
    try:
        current = cursor_core.resolve_roblox_dir()
    except Exception:
        current = None
    if current is not None and versions.is_dir() and not roblox_running():
        cur = os.path.normcase(str(Path(current)))
        for d in sorted(versions.glob("version-*")):
            if not d.is_dir() or d.is_symlink() or os.path.normcase(str(d)) == cur:
                continue
            if not (d / "RobloxPlayerBeta.exe").is_file():
                continue
            items.append({"title": f"Старая версия Roblox {d.name}",
                          "path": d, "kind": "dir"})
    return items


def scan_junk() -> list[dict]:
    """
    Только сканирование: [{"title", "path", "bytes", "files", "kind"}].
    Пустые и несуществующие папки пропускаются.
    """
    res = []
    for c in _candidates():
        p: Path = c["path"]
        if not p.is_dir() or p.is_symlink():
            continue
        size, files = _measure(p)
        if not files and c["kind"] == "contents":
            continue
        res.append({"title": c["title"], "path": str(p),
                    "bytes": size, "files": files, "kind": c["kind"]})
    return res


def _remove_contents(root: Path, dry: bool, skipped: list) -> tuple[int, int]:
    removed_b = removed_f = 0
    for dirpath, dirs, names in os.walk(root, topdown=False, followlinks=False):
        for n in names:
            fp = os.path.join(dirpath, n)
            try:
                size = os.lstat(fp).st_size
                if not dry:
                    os.unlink(fp)
                removed_b += size
                removed_f += 1
            except OSError as exc:
                skipped.append({"path": fp, "reason": str(exc)})
        for d in dirs:
            dp = os.path.join(dirpath, d)
            try:
                if os.path.islink(dp):
                    if not dry:
                        os.unlink(dp)
                elif not dry:
                    os.rmdir(dp)
            except OSError:
                pass  # не пустая из-за занятого файла — он уже в skipped
    return removed_b, removed_f


def clean(items, dry_run: bool = False) -> dict:
    """
    Удалить выбранные элементы scan_junk. Возвращает
    {"removed_bytes", "removed_files", "skipped": [{"path","reason"}]}.
    """
    allowed = {os.path.normcase(str(c["path"])): c for c in _candidates()}
    removed_b = removed_f = 0
    skipped: list[dict] = []
    for it in items or []:
        raw = it.get("path") if isinstance(it, dict) else None
        if not raw:
            skipped.append({"path": str(raw), "reason": "нет пути"})
            continue
        cand = allowed.get(os.path.normcase(str(raw)))
        p = Path(raw)
        if cand is None or p.is_symlink():
            skipped.append({"path": str(raw), "reason": "путь вне разрешённых"})
            continue
        if not p.is_dir():
            continue
        n_before = len(skipped)
        b, f = _remove_contents(p, dry_run, skipped)
        removed_b += b
        removed_f += f
        if cand["kind"] == "dir" and not dry_run:
            try:
                os.rmdir(p)
            except OSError:
                if len(skipped) == n_before:
                    skipped.append({"path": str(p), "reason": "папка не пуста"})
    return {"removed_bytes": removed_b, "removed_files": removed_f,
            "skipped": skipped}


def repair(version_dir) -> dict:
    """
    Вернуть всё, что трогал FPS-буст: флаги и настройки игры.

    Курсоры, небо и звуки возвращает UI. Отчёт:
    {"flags": {backend: результат fps.revert_flags}, "basic": bool,
     "removed_empty": [путь], "skipped": [строка], "errors": [строка]}
    """
    rep: dict = {"flags": {}, "basic": False, "removed_empty": [],
                 "skipped": [], "errors": []}
    backends = ["direct"]
    if RP.bloxstrap_installed():
        backends.append("bloxstrap")
    for be in backends:
        try:
            rep["flags"][be] = fps.revert_flags(Path(version_dir), be)
            target = fps.flags_path(Path(version_dir), be)
            if target.is_file() and not fps._read_json(target):
                target.unlink()
                rep["removed_empty"].append(str(target))
        except (fps.FpsError, OSError) as exc:
            rep["errors"].append(f"{be}: {exc}")
    if roblox_running():
        rep["skipped"].append("настройки игры: закрой Roblox и повтори")
    else:
        try:
            rep["basic"] = fps.revert_basic()
        except OSError as exc:
            rep["errors"].append(f"настройки игры: {exc}")
    return rep
