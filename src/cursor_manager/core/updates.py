"""
updates.py — проверка новой версии программы.

Один GET на JSON {"version", "url", "notes"}. Исключений наружу нет:
нет сети или битый ответ — то же, что «обновлений нет». Только https.
"""
from __future__ import annotations

import json
import re
import urllib.request

from cursor_manager import version as V


def _parts(v: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", str(v))]
    while nums and nums[-1] == 0:
        nums.pop()
    return tuple(nums)


def is_newer(a: str, b: str) -> bool:
    """a новее b; сравнение по числам, '1.10.0' > '1.9.0'."""
    return _parts(a) > _parts(b)


def _get(url: str, timeout: float) -> bytes:
    if not url.lower().startswith("https://"):
        raise ValueError("только https")
    req = urllib.request.Request(
        url, headers={"User-Agent": f"{V.APP_SLUG}/{V.VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(256 * 1024)


def check(url: str = V.UPDATE_URL, current: str = V.VERSION,
          timeout: float = 5) -> dict | None:
    """{"version", "url", "notes"}, если есть версия новее, иначе None."""
    try:
        data = json.loads(_get(url, timeout).decode("utf-8-sig"))
        ver = str(data["version"])
        if not _parts(ver) or not is_newer(ver, current):
            return None
        link = str(data.get("url") or "")
        if not link.lower().startswith("https://"):
            link = V.REPO + "/releases"
        return {"version": ver, "url": link, "notes": str(data.get("notes") or "")}
    except Exception:
        return None
