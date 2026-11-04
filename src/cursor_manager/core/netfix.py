"""
netfix.py — «фикс картинок»: публичные DNS вместо провайдерских.

В РФ/СНГ провайдерский DNS часто не отдаёт адреса CDN Roblox (rbxcdn.com,
thumbnails.roblox.com), из-за чего иконки плейсов и аватарки не грузятся.
Фикс — поставить на активные адаптеры публичные DNS и сбросить кэш.

Чтение (current_dns, diagnose, flush) прав не требует. Запись DNS идёт
PowerShell-скриптом, запущенным ОДНИМ окном UAC; пользователь может
отказаться — тогда apply/restore вернут ошибку в словаре, не исключение.
Перед первой правкой текущие DNS сохраняются в dns-backup.json (существующий
бэкап не перезаписывается); restore() возвращает их и удаляет файл.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path

PROVIDERS: dict[str, list[str]] = {
    "cloudflare": ["1.1.1.1", "1.0.0.1"],
    "google": ["8.8.8.8", "8.8.4.4"],
    "quad9": ["9.9.9.9", "149.112.112.112"],
}

DOMAINS = ("tr.rbxcdn.com", "t0.rbxcdn.com", "c0.rbxcdn.com",
           "images.rbxcdn.com", "thumbnails.roblox.com")
_PROBE = ("https://thumbnails.roblox.com/v1/places/gameicons?placeIds=142823291"
          "&returnPolicy=PlaceHolder&size=50x50&format=Png&isCircular=false")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Виртуальные адаптеры (VPN, Hyper-V, VM) не трогаем: чужие DNS им не нужны.
_VIRTUAL = ("virtual", "vmware", "hyper-v", "vpn", "tap-", "tun", "wireguard",
            "loopback", "bluetooth", "vethernet")


class NetFixError(Exception):
    pass


def _backup_path() -> Path:
    return (Path(os.environ.get("APPDATA") or Path.home())
            / "RobloxCursorChanger" / "dns-backup.json")


def _powershell(command: str, timeout: float = 30) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + command],
            capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetFixError(f"PowerShell недоступен: {exc}") from exc
    if r.returncode != 0:
        raise NetFixError(r.stderr.decode("utf-8", "replace").strip()
                          or f"код {r.returncode}")
    return r.stdout.decode("utf-8", "replace")


# ─────────────────────────────────────────────────────────────────────────────
# Диагностика
# ─────────────────────────────────────────────────────────────────────────────
def _resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return sorted({i[4][0] for i in infos})


def _get(url: str, timeout: float) -> bytes:
    if not url.lower().startswith("https://"):
        raise ValueError("только https")
    req = urllib.request.Request(url, headers={"User-Agent": "sanyakiller111"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(2 * 1024 * 1024)


def diagnose(timeout: float = 6) -> dict:
    """
    {"ok": bool, "details": [{"name", "ok", "info"}]}: резолв доменов CDN
    через текущий DNS и скачивание иконки плейса. ok — когда всё прошло.
    """
    details = []
    for host in DOMAINS:
        try:
            ips = _resolve(host)
            details.append({"name": host, "ok": bool(ips),
                            "info": ", ".join(ips[:3])})
        except OSError as exc:
            details.append({"name": host, "ok": False, "info": str(exc)})
    try:
        meta = json.loads(_get(_PROBE, timeout).decode("utf-8", "replace"))
        img = (meta.get("data") or [{}])[0].get("imageUrl") or ""
        if not img:
            raise ValueError("API не вернул imageUrl")
        body = _get(img, timeout)
        details.append({"name": "картинка плейса", "ok": len(body) > 0,
                        "info": f"{len(body)} байт"})
    except Exception as exc:
        details.append({"name": "картинка плейса", "ok": False, "info": str(exc)})
    return {"ok": all(d["ok"] for d in details), "details": details}


# ─────────────────────────────────────────────────────────────────────────────
# Чтение DNS
# ─────────────────────────────────────────────────────────────────────────────
_READ_PS = (
    "$r=@(Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object {"
    "$i=$_.ifIndex;"
    "$d=Get-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv4 "
    "-ErrorAction SilentlyContinue;"
    "$k='HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\'"
    "+$_.InterfaceGuid;"
    "$ns=(Get-ItemProperty -Path $k -Name NameServer -ErrorAction SilentlyContinue).NameServer;"
    "[pscustomobject]@{adapter=$_.Name;index=[int]$i;servers=@($d.ServerAddresses);"
    "dhcp=[string]::IsNullOrEmpty($ns);description=$_.InterfaceDescription}});"
    "ConvertTo-Json -InputObject $r -Compress"
)


def parse_adapters(text: str) -> list[dict]:
    """Разбор JSON из PowerShell (один объект или массив)."""
    text = (text or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    out = []
    for a in data:
        servers = a.get("servers") or []
        if isinstance(servers, str):
            servers = [servers]
        out.append({"adapter": str(a.get("adapter", "")),
                    "index": int(a.get("index", 0)),
                    "servers": [str(s) for s in servers if s],
                    "dhcp": bool(a.get("dhcp", False)),
                    "description": str(a.get("description", ""))})
    return out


def current_dns() -> list[dict]:
    """[{"adapter", "index", "servers": [...], "dhcp": bool, "description"}] для активных адаптеров."""
    return parse_adapters(_powershell(_READ_PS))


def _is_virtual(a: dict) -> bool:
    text = f"{a.get('adapter', '')} {a.get('description', '')}".lower()
    return any(w in text for w in _VIRTUAL)


# ─────────────────────────────────────────────────────────────────────────────
# Скрипты
# ─────────────────────────────────────────────────────────────────────────────
def _check_servers(servers) -> list[str]:
    out = []
    for s in servers:
        try:
            out.append(str(ipaddress.IPv4Address(s)))
        except ValueError as exc:
            raise NetFixError(f"некорректный адрес DNS: {s}") from exc
    if not out:
        raise NetFixError("пустой список DNS")
    return out


def build_set_script(adapters, servers) -> str:
    servers = _check_servers(servers)
    addr = ",".join(f'"{s}"' for s in servers)
    lines = ["$ErrorActionPreference = 'Stop'"]
    for a in adapters:
        lines.append(f"Set-DnsClientServerAddress -InterfaceIndex {int(a['index'])}"
                     f" -ServerAddresses ({addr})")
    lines.append("Clear-DnsClientCache")
    return "\r\n".join(lines) + "\r\n"


def build_restore_script(saved) -> str:
    lines = ["$ErrorActionPreference = 'Stop'"]
    for a in saved:
        idx = int(a["index"])
        if a.get("dhcp") or not a.get("servers"):
            lines.append(f"Set-DnsClientServerAddress -InterfaceIndex {idx}"
                         " -ResetServerAddresses")
        else:
            addr = ",".join(f'"{s}"' for s in _check_servers(a["servers"]))
            lines.append(f"Set-DnsClientServerAddress -InterfaceIndex {idx}"
                         f" -ServerAddresses ({addr})")
    lines.append("Clear-DnsClientCache")
    return "\r\n".join(lines) + "\r\n"


def _run_elevated(script_path: str, timeout: float = 120) -> tuple[bool, str]:
    """
    Запустить .ps1 с повышением, одно окно UAC. (ok, сообщение).
    Единственное место, где реально запрашиваются права; в тестах подменяется.
    """
    p = script_path.replace("'", "''")
    outer = ("Start-Process powershell -Verb RunAs -Wait -ArgumentList "
             f"'-NoProfile -ExecutionPolicy Bypass -File \"{p}\"'")
    enc = base64.b64encode(outer.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-EncodedCommand", enc],
                           capture_output=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, "время ожидания вышло"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        low = err.lower()
        if "cancel" in low or "отмен" in low or "1223" in low:
            return False, "запрос прав администратора отклонён"
        return False, err or f"код {r.returncode}"
    return True, ""


def _run_script(text: str) -> tuple[bool, str]:
    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="sk-dns-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
        return _run_elevated(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Применение и откат
# ─────────────────────────────────────────────────────────────────────────────
def _norm(servers) -> list[str]:
    return sorted(str(s) for s in servers)


def apply(provider: str) -> dict:
    """
    {"applied": bool, "provider", "servers", "adapters": [имена], "error": str|None}.
    """
    if provider not in PROVIDERS:
        raise NetFixError(f"неизвестный провайдер DNS: {provider}")
    servers = PROVIDERS[provider]
    res = {"applied": False, "provider": provider, "servers": list(servers),
           "adapters": [], "error": None}
    try:
        adapters = [a for a in current_dns() if not _is_virtual(a)]
    except NetFixError as exc:
        res["error"] = str(exc)
        return res
    if not adapters:
        res["error"] = "активный сетевой адаптер не найден"
        return res
    res["adapters"] = [a["adapter"] for a in adapters]

    bak = _backup_path()
    created = False
    if not bak.exists():
        bak.parent.mkdir(parents=True, exist_ok=True)
        bak.write_text(json.dumps(adapters, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        created = True

    ok, msg = _run_script(build_set_script(adapters, servers))
    if ok:
        try:
            after = {a["index"]: a for a in current_dns()}
            ok = all(_norm(after.get(a["index"], {}).get("servers", []))
                     == _norm(servers) for a in adapters)
            if not ok:
                msg = "DNS не изменились после запуска скрипта"
        except NetFixError:
            pass  # скрипт отработал без ошибки, проверить не вышло
    res["applied"] = ok
    if not ok:
        res["error"] = msg or "не удалось применить"
        if created:
            bak.unlink(missing_ok=True)  # ничего не менялось — бэкап не нужен
    return res


def restore() -> dict:
    """{"restored": bool, "error": str|None}; бэкап удаляется при успехе."""
    bak = _backup_path()
    if not bak.is_file():
        return {"restored": False, "error": "сохранённых DNS нет"}
    try:
        saved = json.loads(bak.read_text(encoding="utf-8"))
        script = build_restore_script(saved)
    except (OSError, ValueError, KeyError, NetFixError) as exc:
        return {"restored": False, "error": f"бэкап повреждён: {exc}"}
    ok, msg = _run_script(script)
    if ok:
        bak.unlink(missing_ok=True)
        return {"restored": True, "error": None}
    return {"restored": False, "error": msg or "не удалось вернуть DNS"}


def flush() -> bool:
    """ipconfig /flushdns — права не нужны."""
    try:
        r = subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                           timeout=15, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0
