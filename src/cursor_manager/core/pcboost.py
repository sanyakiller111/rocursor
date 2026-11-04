"""
pcboost.py — настройки Windows, от которых зависит FPS в Roblox.

Ничего не трогает в самом Roblox и не работает в фоне; всё обратимо:

  видеокарта  на ноутбуках с двумя видеокартами Windows часто отдаёт
      Roblox встроенной. Настройка «Графика → Высокая производительность»
      хранится в HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences:
      имя значения — полный путь к exe, данные — «GpuPreference=2;».
      Путь меняется с каждой версией Roblox, поэтому enable_gpu() ставит
      его всем найденным RobloxPlayerBeta.exe, а refresh_gpu() при запуске
      программы дописывает новые версии.

  питание     активная схема → «Высокая производительность» (powercfg).
      Если её нет (часто на ноутбуках), она создаётся из стандартного
      шаблона Windows. Прежняя схема запоминается и возвращается.

  игровой режим  HKCU\\Software\\Microsoft\\GameBar\\AutoGameModeEnabled = 1.

Прежние значения лежат в %APPDATA%\\RobloxCursorChanger\\pcboost.json —
disable_* возвращает ровно их (или удаляет то, чего раньше не было).
Админ не нужен: всё в HKCU, а смена схемы питания доступна пользователю.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from cursor_manager.core import respack
from cursor_manager.core import roblox_paths as RP

STATE_FILE = respack.APP_ROOT / "pcboost.json"
GPU_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
GAMEBAR_KEY = r"Software\Microsoft\GameBar"
GAMEMODE_VALUE = "AutoGameModeEnabled"
HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
# «Максимальная производительность»: скрытый шаблон, его надо копировать
ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
EXE = "RobloxPlayerBeta.exe"
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class BoostError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Низкий уровень: реестр HKCU и powercfg. Тесты подменяют эти функции.
# ─────────────────────────────────────────────────────────────────────────────
def _hive(name: str):
    import winreg
    return winreg.HKEY_LOCAL_MACHINE if name == "HKLM" else winreg.HKEY_CURRENT_USER


def reg_get(key: str, name: str, hive: str = "HKCU"):
    """Чтение работает и для HKLM без прав — так запоминаются оригиналы."""
    import winreg
    try:
        with winreg.OpenKey(_hive(hive), key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_set(key: str, name: str, value, hive: str = "HKCU") -> None:
    import winreg
    with winreg.CreateKeyEx(_hive(hive), key, 0, winreg.KEY_SET_VALUE) as k:
        kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
        winreg.SetValueEx(k, name, 0, kind, value)


def reg_delete(key: str, name: str, hive: str = "HKCU") -> None:
    import winreg
    try:
        with winreg.OpenKey(_hive(hive), key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass


def powercfg(*args: str) -> str:
    try:
        done = subprocess.run(
            ["powercfg", *args], capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BoostError(f"powercfg не запустился: {exc}") from exc
    text = done.stdout.decode("cp866", errors="replace")
    if done.returncode != 0:
        raise BoostError(f"powercfg {' '.join(args)}: код {done.returncode}")
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Состояние
# ─────────────────────────────────────────────────────────────────────────────
def load_state(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ─────────────────────────────────────────────────────────────────────────────
# Видеокарта
# ─────────────────────────────────────────────────────────────────────────────
def roblox_exes() -> list[Path]:
    """Все RobloxPlayerBeta.exe: свои версии Roblox и версии Bloxstrap."""
    from cursor_manager.core import cursor_core
    found: dict[str, Path] = {}
    roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Roblox" / "Versions",
             RP.bloxstrap_versions()]
    dirs = [d for root in roots if root.is_dir() for d in root.iterdir() if d.is_dir()]
    try:
        dirs += list(cursor_core.find_roblox_versions())
    except OSError:
        pass
    for d in dirs:
        exe = Path(d) / EXE
        if exe.is_file():
            found.setdefault(str(exe).lower(), exe)
    return list(found.values())


def _with_pref(old: str | None, pref: int) -> str:
    """Поменять GpuPreference, не трогая другие пары (AppStatus=0; …)."""
    parts = [p for p in (old or "").split(";") if p and not p.startswith("GpuPreference=")]
    return ";".join(parts + [f"GpuPreference={pref}"]) + ";"


def gpu_enabled(state: dict | None = None) -> bool:
    return bool((state if state is not None else load_state()).get("gpu_on"))


def enable_gpu(exes: list[Path] | None = None) -> list[str]:
    """Дать Roblox мощную видеокарту. Возвращает пути, которым поставили."""
    exes = roblox_exes() if exes is None else exes
    if not exes:
        raise BoostError("RobloxPlayerBeta.exe не найден — запусти Roblox один раз")
    state = load_state()
    saved = state.setdefault("gpu", {})
    done = []
    for exe in exes:
        name = str(exe)
        current = reg_get(GPU_KEY, name)
        want = _with_pref(current, 2)
        if current == want:
            continue
        saved.setdefault(name, current)       # первый раз — настоящий оригинал
        reg_set(GPU_KEY, name, want)
        done.append(name)
    state["gpu_on"] = True
    save_state(state)
    return done


def refresh_gpu() -> list[str]:
    """При запуске: если включено, дописать новые версии Roblox. Тихо."""
    if not gpu_enabled():
        return []
    try:
        return enable_gpu()
    except (BoostError, OSError):
        return []


def disable_gpu() -> int:
    state = load_state()
    restored = 0
    for name, old in (state.get("gpu") or {}).items():
        if old is None:
            reg_delete(GPU_KEY, name)
        else:
            reg_set(GPU_KEY, name, old)
        restored += 1
    state["gpu"], state["gpu_on"] = {}, False
    save_state(state)
    return restored


# ─────────────────────────────────────────────────────────────────────────────
# Питание и игровой режим
# ─────────────────────────────────────────────────────────────────────────────
def active_scheme() -> str:
    match = _GUID.search(powercfg("/getactivescheme"))
    if not match:
        raise BoostError("не удалось прочитать активную схему питания")
    return match.group(0).lower()


def _best_scheme() -> tuple[str, bool]:
    """
    (GUID, создана ли нами). Сначала «Максимальная производительность» —
    её копию создаём сами и удаляем при откате; на ноутбуках с Modern
    Standby Windows её не даёт, тогда «Высокая производительность».
    """
    try:
        match = _GUID.search(powercfg("-duplicatescheme", ULTIMATE))
        if match:
            return match.group(0).lower(), True
    except BoostError:
        pass
    listing = powercfg("/list").lower()
    if HIGH_PERF in listing:
        return HIGH_PERF, False
    match = _GUID.search(powercfg("-duplicatescheme", HIGH_PERF))
    if not match:
        raise BoostError("в этой Windows нет схемы «Высокая производительность»")
    return match.group(0).lower(), True


def power_enabled(state: dict | None = None) -> bool:
    return bool((state if state is not None else load_state()).get("power_on"))


def enable_power() -> str:
    """Высокая производительность + игровой режим. Возвращает GUID схемы."""
    state = load_state()
    current = active_scheme()
    target = state.get("power_scheme")
    if not target or target not in powercfg("/list").lower():
        target, created = _best_scheme()
        state["power_created"] = target if created else None
    if not state.get("power_on"):
        state["power_prev"] = current
        state["gamemode_prev"] = reg_get(GAMEBAR_KEY, GAMEMODE_VALUE)
    if current != target:
        powercfg("/setactive", target)
    reg_set(GAMEBAR_KEY, GAMEMODE_VALUE, 1)
    state["power_scheme"], state["power_on"] = target, True
    save_state(state)
    return target


def disable_power() -> None:
    state = load_state()
    if not state.get("power_on"):
        return
    prev = state.get("power_prev")
    if prev and _GUID.fullmatch(prev):
        powercfg("/setactive", prev)
    created = state.get("power_created")
    if created and created != prev and _GUID.fullmatch(created):
        try:
            powercfg("-delete", created)
        except BoostError:
            pass
        state["power_created"] = state["power_scheme"] = None
    old = state.get("gamemode_prev")
    if old is None:
        reg_delete(GAMEBAR_KEY, GAMEMODE_VALUE)
    else:
        reg_set(GAMEBAR_KEY, GAMEMODE_VALUE, old)
    state["power_on"] = False
    save_state(state)
