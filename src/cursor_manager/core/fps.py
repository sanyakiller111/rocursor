"""
fps.py — облегчить графику Roblox: разрешённые FastFlags и лимит кадров.

Два файла, оба — штатные настройки клиента, никаких инжектов:

  ClientAppSettings.json  FastFlags. С 29.09.2025 Roblox читает только
      флаги из своего allowlist, остальные молча игнорирует, поэтому здесь
      только они (список — FLAG_OPTIONS). Файл лежит в папке версии
      (<version>\\ClientSettings\\), а у Bloxstrap — в оверлее
      Modifications\\ClientSettings\\, его же правит редактор флагов Bloxstrap.
      Пишем слиянием: чужие ключи не трогаем.

  GlobalBasicSettings_13.xml  настройки из меню игры: лимит кадров
      (FramerateCap) и качество графики. Roblox перечитывает файл при
      запуске и перезаписывает при выходе — менять его можно только при
      закрытом Roblox.

Перед первой правкой каждого файла оригинал уходит в бэкап (существующий
бэкап не перезаписывается); revert_* возвращает его.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from cursor_manager.core import respack
from cursor_manager.core import roblox_paths as RP


class FpsError(Exception):
    pass


# Опции интерфейса → разрешённые флаги. Значения строками, как их пишет
# Bloxstrap: клиент принимает и так, и так, а смешение ломает его редактор.
FLAG_OPTIONS: dict[str, dict] = {
    "msaa": {
        "title": "без сглаживания (MSAA 0)",
        "hint": "убирает сглаживание краёв — заметный прирост на слабых видеокартах",
        "flags": {"FIntDebugForceMSAASamples": "0"},
    },
    "textures": {
        "title": "низкие текстуры",
        "hint": "текстуры в минимальном качестве — меньше видеопамяти",
        "flags": {"DFFlagTextureQualityOverrideEnabled": "True",
                  "DFIntTextureQualityOverride": "0"},
    },
    "quality": {
        "title": "минимальный уровень графики",
        "hint": "принудительно самый низкий уровень рендера",
        "flags": {"DFIntDebugFRMQualityLevelOverride": "1"},
    },
    "grass": {
        "title": "без травы",
        "hint": "трава на ландшафте не рисуется и не качается",
        "flags": {"FIntFRMMaxGrassDistance": "0",
                  "FIntFRMMinGrassDistance": "0",
                  "FIntGrassMovementReducedMotionFactor": "0"},
    },
    "lod": {
        "title": "упрощать дальние объекты",
        "hint": "CSG-детали раньше переключаются на низкую детализацию",
        "flags": {"DFIntCSGLevelOfDetailSwitchingDistance": "0",
                  "DFIntCSGLevelOfDetailSwitchingDistanceL12": "0",
                  "DFIntCSGLevelOfDetailSwitchingDistanceL23": "0",
                  "DFIntCSGLevelOfDetailSwitchingDistanceL34": "0"},
    },
    "d3d11": {
        "title": "DirectX 11",
        "hint": "на многих ПК стабильнее и быстрее, чем выбор по умолчанию",
        "flags": {"FFlagDebugGraphicsPreferD3D11": "True"},
    },
    "voxel": {
        "title": "заморозить пересчёт освещения",
        "hint": "останавливает вокселизатор света: +FPS, но тени и свет "
                "могут не обновляться — включай, если совсем лагает",
        "flags": {"DFFlagDebugPauseVoxelizer": "True"},
    },
    "skygray": {
        "title": "серое небо",
        "hint": "небо рисуется одним цветом; перекрывает выбранный skybox",
        "flags": {"FFlagDebugSkyGray": "True"},
    },
}

# «максимум FPS»: всё, кроме серого неба — оно ломает выбранный skybox
PRESET_MAX = ("msaa", "textures", "quality", "grass", "lod", "d3d11", "voxel")
PRESET_BALANCED = ("msaa", "grass", "d3d11")

# Лимит кадров из меню игры. Официально меню даёт до 240; значения выше
# пользователи ставят в файл руками (5000 встречается чаще всего), но
# Roblox их не обещает — в UI они помечены как «без гарантий».
FPS_CAPS = (60, 144, 240, 360, 5000)
# Уровень графики из меню: 0 — авто, 1..10 — ползунок.
QUALITY_LEVELS = tuple(range(0, 11))

OWN_FLAGS = {name for opt in FLAG_OPTIONS.values() for name in opt["flags"]}


# ─────────────────────────────────────────────────────────────────────────────
# FastFlags
# ─────────────────────────────────────────────────────────────────────────────
def flags_path(version_dir: Path, backend: str) -> Path:
    if backend == "bloxstrap":
        return RP.bloxstrap_mods() / "ClientSettings" / "ClientAppSettings.json"
    return version_dir / "ClientSettings" / "ClientAppSettings.json"


def _flags_backup(version_dir: Path, backend: str) -> Path:
    tag = "bloxstrap" if backend == "bloxstrap" else version_dir.name
    return respack.BACKUP_ROOT / tag / "ClientSettings" / "ClientAppSettings.json"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise FpsError(f"{path.name} не читается: {exc}") from exc
    if not isinstance(data, dict):
        raise FpsError(f"{path.name}: ожидался JSON-объект")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def flags_for(options) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in options:
        if key not in FLAG_OPTIONS:
            raise FpsError(f"неизвестная опция: {key}")
        out.update(FLAG_OPTIONS[key]["flags"])
    return out


def apply_flags(version_dir: Path, options, backend: str = "direct") -> dict:
    """
    Записать флаги выбранных опций. Наши флаги, которых нет в выборе,
    убираются; чужие ключи (свои флаги пользователя, Bloxstrap) остаются.
    """
    target = flags_path(version_dir, backend)
    backup = _flags_backup(version_dir, backend)
    current = _read_json(target)
    if not backup.exists() and not backup.with_suffix(".absent").exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            backup.write_bytes(target.read_bytes())
        else:
            # файла не было: запоминаем это, чтобы откат его удалил
            backup.with_suffix(".absent").write_text("", encoding="utf-8")
    wanted = flags_for(options)
    merged = {k: v for k, v in current.items() if k not in OWN_FLAGS}
    merged.update(wanted)
    _write_json(target, merged)
    return {"path": str(target), "flags": wanted}


def revert_flags(version_dir: Path, backend: str = "direct") -> dict:
    """Вернуть файл флагов к оригиналу из бэкапа; без бэкапа — убрать наши ключи."""
    target = flags_path(version_dir, backend)
    backup = _flags_backup(version_dir, backend)
    if backup.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(backup.read_bytes())
        return {"restored": str(target)}
    if backup.with_suffix(".absent").exists():
        if target.is_file():
            leftover = {k: v for k, v in _read_json(target).items()
                        if k not in OWN_FLAGS}
            if leftover:
                _write_json(target, leftover)
            else:
                target.unlink()
        return {"removed": str(target)}
    if target.is_file():
        leftover = {k: v for k, v in _read_json(target).items() if k not in OWN_FLAGS}
        _write_json(target, leftover)
    return {"cleaned": str(target)}


def active_options(version_dir: Path, backend: str = "direct") -> list[str]:
    """Какие опции сейчас реально стоят в файле флагов."""
    try:
        current = _read_json(flags_path(version_dir, backend))
    except FpsError:
        return []
    return [key for key, opt in FLAG_OPTIONS.items()
            if all(str(current.get(k)) == v for k, v in opt["flags"].items())]


# ─────────────────────────────────────────────────────────────────────────────
# GlobalBasicSettings: лимит кадров и уровень графики
# ─────────────────────────────────────────────────────────────────────────────
def basic_settings_path() -> Path | None:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Roblox"
    found = []
    for p in root.glob("GlobalBasicSettings_*.xml"):
        m = re.fullmatch(r"GlobalBasicSettings_(\d+)\.xml", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return max(found)[1] if found else None


_FIELDS = {
    "cap": ("int", "FramerateCap"),
    "quality": ("token", "SavedQualityLevel"),
    "graphics": ("int", "GraphicsQualityLevel"),
}


def _field_re(tag: str, name: str) -> re.Pattern:
    return re.compile(rf'(<{tag} name="{name}">)(-?\d+)(</{tag}>)')


def read_basic(path: Path | None = None) -> dict:
    path = path or basic_settings_path()
    if path is None or not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for key, (tag, name) in _FIELDS.items():
        m = _field_re(tag, name).search(text)
        if m:
            out[key] = int(m.group(2))
    return out


def roblox_running() -> bool:
    """Roblox перезапишет файл настроек при выходе — править только без него."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq RobloxPlayerBeta.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "RobloxPlayerBeta.exe" in out


def apply_basic(cap: int | None, quality: int | None,
                path: Path | None = None) -> dict:
    """
    Поменять лимит кадров и уровень графики в настройках из меню игры.

    quality: 0 — авто, 1..10 — ползунок графики. Поля, которых нет в
    файле, не добавляются: значит, эта версия Roblox их не знает.
    """
    path = path or basic_settings_path()
    if path is None or not path.is_file():
        raise FpsError("файл настроек Roblox не найден — запусти Roblox один раз")
    backup = respack.BACKUP_ROOT / "settings" / path.name
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(path.read_bytes())
    text = path.read_text(encoding="utf-8", errors="replace")
    changed = {}
    wanted = {}
    if cap is not None:
        wanted["cap"] = int(cap)
    if quality is not None:
        wanted["quality"] = int(quality)
        # GraphicsQualityLevel — внутренняя шкала 1..21, ползунок 1..10 ≈ ×2
        wanted["graphics"] = max(1, int(quality) * 2 - 1) if quality else 1
    for key, value in wanted.items():
        tag, name = _FIELDS[key]
        text, n = _field_re(tag, name).subn(rf"\g<1>{value}\g<3>", text)
        if n:
            changed[name] = value
    tmp = path.with_suffix(".xml.part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return {"path": str(path), "changed": changed}


def revert_basic(path: Path | None = None) -> bool:
    path = path or basic_settings_path()
    if path is None:
        return False
    backup = respack.BACKUP_ROOT / "settings" / path.name
    if not backup.is_file():
        return False
    path.write_bytes(backup.read_bytes())
    return True
