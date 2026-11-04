"""
pcclean.py — мусор Windows, который пересоздаётся сам: временные файлы,
кэши шейдеров, кэши браузеров и Discord, корзина.

Правило то же, что в maintenance.py: удаляется только содержимое папок из
фиксированного списка, clean() сверяет каждый путь со свежим scan_junk().
Занятые файлы (браузер открыт) молча попадают в skipped — это нормально.

Намеренно не трогаем: куки, историю, пароли и вкладки браузеров (только
Cache/Code Cache/GPUCache), Prefetch (ускоряет запуск программ), папку
Загрузки. Системные папки (C:\\Windows\\Temp, кэш обновлений) требуют прав —
их чистит админ-скрипт: admin_steps().
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from cursor_manager.core import maintenance
from cursor_manager.core.elevate import ps_quote

_measure = maintenance._measure
_remove_contents = maintenance._remove_contents


def _env(name: str, fallback: Path) -> Path:
    return Path(os.environ.get(name) or fallback)


def _browser_caches(root: Path) -> list[Path]:
    """Кэши всех профилей Chromium-браузера: Default, Profile 1, …"""
    out = []
    if not root.is_dir():
        return out
    for profile in root.iterdir():
        if not profile.is_dir() or not (profile.name == "Default"
                                        or profile.name.startswith("Profile ")):
            continue
        for sub in ("Cache", "Code Cache", "GPUCache"):
            out.append(profile / sub)
    return out


def _candidates() -> list[dict]:
    local = _env("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    roaming = _env("APPDATA", Path.home() / "AppData" / "Roaming")
    temp = _env("TEMP", local / "Temp")
    items = [
        ("Временные файлы", temp),
        ("Кэш шейдеров DirectX", local / "D3DSCache"),
        ("Кэш шейдеров NVIDIA", local / "NVIDIA" / "DXCache"),
        ("Кэш шейдеров NVIDIA (GL)", local / "NVIDIA" / "GLCache"),
        ("Кэш шейдеров AMD", local / "AMD" / "DxCache"),
        ("Кэш Discord", roaming / "discord" / "Cache"),
        ("Кэш Discord (код)", roaming / "discord" / "Code Cache"),
        ("Кэш Discord (GPU)", roaming / "discord" / "GPUCache"),
    ]
    browsers = {
        "Chrome": local / "Google" / "Chrome" / "User Data",
        "Edge": local / "Microsoft" / "Edge" / "User Data",
        "Яндекс": local / "Yandex" / "YandexBrowser" / "User Data",
        "Brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
    }
    for name, root in browsers.items():
        for path in _browser_caches(root):
            items.append((f"Кэш {name}: {path.parent.name} / {path.name}", path))
    opera = roaming / "Opera Software"
    for sub in ("Opera Stable", "Opera GX Stable"):
        items.append((f"Кэш {sub}", local / "Opera Software" / sub / "Cache"))
        items.append((f"Кэш {sub} (код)", opera / sub / "Code Cache"))
    out = [{"title": t, "path": p, "kind": "contents"} for t, p in items]
    # в %TEMP% живёт распакованный onefile-exe этой же программы (_MEI…)
    # и наши админ-скрипты — их не трогаем
    out[0]["skip"] = ("_mei", "sk-admin-")
    # Roblox — из старого модуля, со всеми его оговорками
    for c in maintenance._candidates():
        out.append(c)
    return out


def scan_junk() -> list[dict]:
    res = []
    seen = set()
    for c in _candidates():
        p: Path = c["path"]
        key = os.path.normcase(str(p))
        if key in seen or not p.is_dir() or p.is_symlink():
            continue
        seen.add(key)
        size, files = _measure(p)
        if not files and c["kind"] == "contents":
            continue
        res.append({"title": c["title"], "path": str(p), "bytes": size,
                    "files": files, "kind": c["kind"]})
    return res


def clean(items) -> dict:
    allowed = {os.path.normcase(str(c["path"])): c for c in _candidates()}
    removed_b = removed_f = 0
    skipped: list[dict] = []
    for it in items or []:
        raw = it.get("path") if isinstance(it, dict) else None
        cand = allowed.get(os.path.normcase(str(raw))) if raw else None
        p = Path(raw) if raw else None
        if cand is None or p is None or p.is_symlink():
            skipped.append({"path": str(raw), "reason": "путь вне разрешённых"})
            continue
        if not p.is_dir():
            continue
        skip = cand.get("skip", ())
        for child in (list(p.iterdir()) if skip else [p]):
            if skip and child.name.lower().startswith(skip):
                continue
            if child.is_dir() and not child.is_symlink():
                b, f = _remove_contents(child, False, skipped)
                if child != p:
                    try:
                        os.rmdir(child)
                    except OSError:
                        pass
            else:
                try:
                    b, f = child.lstat().st_size, 1
                    child.unlink()
                except OSError as exc:
                    b = f = 0
                    skipped.append({"path": str(child), "reason": str(exc)})
            removed_b += b
            removed_f += f
        if cand["kind"] == "dir":
            try:
                os.rmdir(p)
            except OSError:
                pass
    return {"removed_bytes": removed_b, "removed_files": removed_f, "skipped": skipped}


# ─────────────────────────────────────────────────────────────────────────────
# Корзина
# ─────────────────────────────────────────────────────────────────────────────
class _QueryInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_size() -> int:
    try:
        info = _QueryInfo(ctypes.sizeof(_QueryInfo), 0, 0)
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return int(info.i64Size)
    except (AttributeError, OSError):
        pass
    return 0


def empty_recycle_bin() -> int:
    """Очистить корзину без окон подтверждения. Возвращает освобождённые байты."""
    size = recycle_bin_size()
    try:
        # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    except (AttributeError, OSError):
        return 0
    return size


# ─────────────────────────────────────────────────────────────────────────────
# Админская часть: системные папки и оперативная память
# ─────────────────────────────────────────────────────────────────────────────
_PURGE_CS = r'''
using System; using System.Runtime.InteropServices;
public static class SkMem {
  [StructLayout(LayoutKind.Sequential, Pack = 4)]
  public struct TP { public int Count; public long Luid; public int Attr; }
  [DllImport("ntdll.dll")] static extern int NtSetSystemInformation(int c, ref int i, int l);
  [DllImport("advapi32.dll")] static extern bool OpenProcessToken(IntPtr h, int a, out IntPtr t);
  [DllImport("advapi32.dll")] static extern bool LookupPrivilegeValue(string s, string n, out long l);
  [DllImport("advapi32.dll")] static extern bool AdjustTokenPrivileges(IntPtr t, bool d, ref TP n, int l, IntPtr p, IntPtr r);
  public static int Purge() {
    IntPtr t; OpenProcessToken(System.Diagnostics.Process.GetCurrentProcess().Handle, 0x28, out t);
    long l; LookupPrivilegeValue(null, "SeProfileSingleProcessPrivilege", out l);
    TP p = new TP(); p.Count = 1; p.Luid = l; p.Attr = 2;
    AdjustTokenPrivileges(t, false, ref p, 0, IntPtr.Zero, IntPtr.Zero);
    int cmd = 4;  // MemoryPurgeStandbyList
    return NtSetSystemInformation(80, ref cmd, 4);
  }
}
'''


def purge_memory_step() -> tuple[str, str]:
    """Очистить standby list — то же, что делает ISLC. Нужны права."""
    return ("ram", f"Add-Type -TypeDefinition @'\r\n{_PURGE_CS.strip()}\r\n'@\r\n"
                   "$r = [SkMem]::Purge(); if ($r -ne 0) { throw \"NTSTATUS $r\" }")


def admin_clean_steps() -> list[tuple[str, str]]:
    def wipe(path_expr: str) -> str:
        return (f"$p = {path_expr}; if (Test-Path -LiteralPath $p) {{ "
                "Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue | "
                "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue }")
    return [
        ("windows-temp", wipe("Join-Path $env:SystemRoot 'Temp'")),
        ("update-cache",
         "Stop-Service wuauserv -Force -ErrorAction SilentlyContinue\r\n"
         + wipe("Join-Path $env:SystemRoot 'SoftwareDistribution\\Download'")
         + "\r\nStart-Service wuauserv -ErrorAction SilentlyContinue"),
        ("nvidia-cache", wipe(f"Join-Path $env:ProgramData {ps_quote('NVIDIA Corporation\\NV_Cache')}")),
    ]
