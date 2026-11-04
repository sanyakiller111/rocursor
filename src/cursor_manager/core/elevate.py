"""
elevate.py — одно окно UAC на пачку действий, которым нужны права админа.

Python-процесс программы работает без прав. Всё, что пишет в HKLM, чистит
системные папки или зовёт админские командлеты, собирается в один .ps1:
каждый шаг обёрнут в try/catch, а итог (шаг → "ok" или текст ошибки)
скрипт пишет JSON-файлом, который читает вызывающий код. Пользователь
может отказаться от UAC — тогда run() вернёт ok=False, а не исключение.

Строки в скрипт попадают только через ps_quote() — одинарные кавычки
PowerShell, внутри которых нет подстановок.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def build(steps: list[tuple[str, str]], result_path: Path) -> str:
    """steps — [(имя шага, код PowerShell)]."""
    lines = ["$ErrorActionPreference = 'Stop'",
             "$ProgressPreference = 'SilentlyContinue'",
             "$res = [ordered]@{}"]
    for name, code in steps:
        lines.append("try {\r\n" + code + f"\r\n$res[{ps_quote(name)}] = 'ok'\r\n}} "
                     f"catch {{ $res[{ps_quote(name)}] = $_.Exception.Message }}")
    lines.append(f"$res | ConvertTo-Json | Set-Content -Encoding UTF8 -Path {ps_quote(result_path)}")
    return "\r\n".join(lines) + "\r\n"


def launch(script_path: str, timeout: float = 600) -> tuple[bool, str]:
    """Запустить .ps1 с повышением и дождаться. Тесты подменяют эту функцию."""
    outer = ("Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
             + ps_quote(f'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"'))
    enc = base64.b64encode(outer.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-EncodedCommand", enc],
                           capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
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


def run(steps: list[tuple[str, str]]) -> tuple[bool, dict]:
    """
    Выполнить шаги одним UAC. (ok, {шаг: "ok" | ошибка}).
    ok=False без словаря — UAC отклонён или PowerShell не запустился.
    """
    if not steps:
        return True, {}
    tmp = Path(tempfile.mkdtemp(prefix="sk-admin-"))
    script, result = tmp / "boost.ps1", tmp / "result.json"
    try:
        script.write_text(build(steps, result), encoding="utf-8-sig")
        ok, msg = launch(str(script))
        if not ok:
            return False, {"uac": msg}
        try:
            data = json.loads(result.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return True, {name: "нет отчёта от скрипта" for name, _ in steps}
        return True, {str(k): str(v) for k, v in data.items()}
    finally:
        for p in (script, result):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
