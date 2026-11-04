"""
procs.py — тяжёлые программы и автозагрузка.

heavy() читает `tasklist /fo csv` (psutil в сборке нет) и складывает память
по имени exe: у Chrome и Discord десятки процессов, пользователю важна сумма.
Системные процессы и сама программа в список не попадают, закрыть их
нельзя даже по ошибке — close() перепроверяет имя по тому же фильтру.

Автозагрузка — так же, как её выключает Диспетчер задач: запись в
HKCU\\…\\Explorer\\StartupApproved\\{Run|StartupFolder}, первый байт 02 —
включено, 03 — выключено. Сама команда в Run не удаляется, поэтому включить
обратно можно в любой момент и здесь, и в Диспетчере задач. Записи HKLM
показываются, но менять их без прав нельзя — они помечены admin.
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Не показывать и не закрывать: ядро Windows, оболочка, драйверы, антивирус,
# Roblox (его закрывают из игры) и сама программа.
PROTECTED = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe",
    "fontdrvhost.exe", "dwm.exe", "explorer.exe", "sihost.exe", "ctfmon.exe",
    "taskhostw.exe", "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "lockapp.exe", "memory compression",
    "msmpeng.exe", "mpdefendercoreservice.exe", "nissrv.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "smartscreen.exe", "audiodg.exe", "conhost.exe",
    "dllhost.exe", "wmiprvse.exe", "spoolsv.exe", "searchindexer.exe", "wudfhost.exe",
    "nvcontainer.exe", "nvdisplay.container.exe", "atiesrxx.exe", "atieclxx.exe",
    "igfxem.exe", "robloxplayerbeta.exe", "robloxstudiobeta.exe", "powershell.exe",
    "cmd.exe", "windowsterminal.exe", "openconsole.exe", "python.exe", "pythonw.exe",
    "sanyakiller111.exe", "tasklist.exe", "taskkill.exe",
}
MIN_MB = 150


def _tasklist() -> str:
    r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                       timeout=20, creationflags=_NO_WINDOW)
    return r.stdout.decode("cp866", errors="replace")


def _mem_kb(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def protected(name: str) -> bool:
    low = name.lower()
    own = Path(sys.executable).name.lower()
    return low in PROTECTED or low == own


def heavy(min_mb: int = MIN_MB, text: str | None = None) -> list[dict]:
    """[{"name", "mb", "count"}] по убыванию памяти; только не-системное."""
    try:
        text = _tasklist() if text is None else text
    except (OSError, subprocess.SubprocessError):
        return []
    total: dict[str, dict] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 5 or protected(row[0]):
            continue
        item = total.setdefault(row[0].lower(), {"name": row[0], "kb": 0, "count": 0})
        item["kb"] += _mem_kb(row[4])
        item["count"] += 1
    out = [{"name": v["name"], "mb": v["kb"] // 1024, "count": v["count"]}
           for v in total.values() if v["kb"] // 1024 >= min_mb]
    return sorted(out, key=lambda x: -x["mb"])


def close(names: list[str]) -> dict:
    """taskkill /f /t по имени. {"closed": [...], "failed": [...]}."""
    closed, failed = [], []
    for name in names:
        if protected(name) or not name.lower().endswith(".exe"):
            failed.append(f"{name}: защищён")
            continue
        try:
            r = subprocess.run(["taskkill", "/f", "/t", "/im", name], capture_output=True,
                               timeout=20, creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as exc:
            failed.append(f"{name}: {exc}")
            continue
        (closed if r.returncode == 0 else failed).append(name)
    return {"closed": closed, "failed": failed}


# ─────────────────────────────────────────────────────────────────────────────
# Автозагрузка
# ─────────────────────────────────────────────────────────────────────────────
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
ENABLED = b"\x02" + b"\x00" * 11
DISABLED = b"\x03" + b"\x00" * 11


def _values(hive, key: str) -> dict:
    import winreg
    out = {}
    try:
        with winreg.OpenKey(hive, key) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = value
                i += 1
    except OSError:
        pass
    return out


def _startup_folder() -> Path:
    return (Path(os.environ.get("APPDATA") or Path.home())
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")


def startup_items() -> list[dict]:
    """[{"name", "command", "where", "enabled", "admin"}]."""
    import winreg
    items = []
    sources = (("HKCU", winreg.HKEY_CURRENT_USER, "Run", False),
               ("HKLM", winreg.HKEY_LOCAL_MACHINE, "Run", True))
    for label, hive, sub, admin in sources:
        approved = _values(hive, APPROVED + "\\" + sub)
        for name, command in _values(hive, RUN).items():
            flag = approved.get(name)
            enabled = not (isinstance(flag, bytes) and flag[:1] in (b"\x03", b"\x01"))
            items.append({"name": name, "command": str(command), "where": label,
                          "enabled": enabled, "admin": admin})
    approved = _values(winreg.HKEY_CURRENT_USER, APPROVED + "\\StartupFolder")
    folder = _startup_folder()
    if folder.is_dir():
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in (".lnk", ".exe", ".bat", ".cmd", ".url"):
                flag = approved.get(f.name)
                enabled = not (isinstance(flag, bytes) and flag[:1] in (b"\x03", b"\x01"))
                items.append({"name": f.name, "command": str(f), "where": "папка",
                              "enabled": enabled, "admin": False})
    return items


def set_startup(item: dict, enabled: bool) -> None:
    """Включить/выключить запись автозагрузки пользователя (HKCU или папка)."""
    import winreg
    if item.get("admin"):
        raise PermissionError("запись для всех пользователей — нужны права администратора")
    sub = "StartupFolder" if item.get("where") == "папка" else "Run"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED + "\\" + sub, 0,
                            winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, item["name"], 0, winreg.REG_BINARY,
                          ENABLED if enabled else DISABLED)
