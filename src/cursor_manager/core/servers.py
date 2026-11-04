"""
servers.py — список серверов игры и вход на выбранный.

Только открытые эндпоинты Roblox, без логина и cookies:

  apis.roblox.com/universes/v1/places/<placeId>/universe   placeId → universeId
  games.roblox.com/v1/games?universeIds=<id>               имя игры
  games.roblox.com/v1/games/<placeId>/servers/Public       серверы: игроки,
      fps сервера и ping — средний пинг игроков, которые уже там. Это не твой
      пинг, а подсказка: сервер с низким пингом у всех обычно стоит ближе к
      большинству игроков, для СНГ — чаще в Европе.

Вход — ссылкой roblox://experiences/start?placeId=…&gameInstanceId=…:
Roblox открывается под аккаунтом, в который уже вошёл пользователь, программа
его не видит. Сам пинг программа не уменьшает — только выбирает сервер.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from cursor_manager.version import APP_SLUG, VERSION

USER_AGENT = f"{APP_SLUG}/{VERSION}"
SERVERS_URL = "https://games.roblox.com/v1/games/{place}/servers/Public"
UNIVERSE_URL = "https://apis.roblox.com/universes/v1/places/{place}/universe"
GAMES_URL = "https://games.roblox.com/v1/games?universeIds={universe}"
PAGE_LIMIT = 100


class ServerError(Exception):
    pass


@dataclass
class Server:
    id: str
    playing: int
    max_players: int
    fps: float
    ping: int | None

    @property
    def full(self) -> bool:
        return self.playing >= self.max_players


def parse_place(text: str) -> int:
    """Номер места из ссылки roblox.com/games/<id>/… или из голого числа."""
    text = (text or "").strip()
    m = re.search(r"roblox\.com/(?:[a-z-]+/)?games/(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"[?&]placeId=(\d+)", text)
    if m:
        return int(m.group(1))
    if text.isdigit():
        return int(text)
    raise ServerError("вставь ссылку на игру (roblox.com/games/…) или её номер")


def _wait_hint(exc: urllib.error.HTTPError) -> int:
    """Сколько секунд просит подождать Roblox (reset окна или Retry-After)."""
    for header in ("x-ratelimit-reset", "retry-after"):
        try:
            value = int(str(exc.headers.get(header, "")).split(",")[0])
        except ValueError:
            continue
        if value > 0:
            return min(value, 60)
    return 10


def _get(url: str, timeout: int = 15, waiting=None) -> dict:
    """
    GET с ожиданием при 429. Список серверов Roblox отдаёт всего 3 раза в
    минуту на один IP, поэтому ждём столько, сколько он сказал, а не
    долбим повторами; waiting(секунд) — чтобы UI показал ожидание.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                pause = _wait_hint(exc) + 1
                if waiting:
                    waiting(pause)
                time.sleep(pause)
                continue
            if exc.code in (400, 404):
                raise ServerError("игра не найдена — проверь ссылку") from exc
            raise ServerError(f"Roblox ответил {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ServerError(f"нет связи с Roblox: {exc}") from exc
    raise ServerError("Roblox просит подождать — попробуй через минуту")


def game_name(place_id: int) -> str:
    """Имя игры; пустая строка, если не вышло — это не повод падать."""
    try:
        universe = _get(UNIVERSE_URL.format(place=place_id)).get("universeId")
        if not universe:
            return ""
        data = _get(GAMES_URL.format(universe=universe)).get("data") or []
        return str(data[0].get("name") or "") if data else ""
    except ServerError:
        return ""


def list_servers(place_id: int, cursor: str = "",
                 waiting=None) -> tuple[list[Server], str]:
    """
    Одна страница — до 100 публичных серверов, самые заполненные первыми.

    Возвращает (серверы, курсор следующей страницы или ""). Страницы по
    одной, а не все сразу: лимит Roblox — 3 запроса в минуту, а лучшие по
    пингу серверы почти всегда среди заполненных.
    """
    # полные серверы отсекает сам Roblox: в популярных играх первые сотни
    # «самых заполненных» — это 12/12, и зайти туда всё равно нельзя
    query = {"sortOrder": "Desc", "limit": PAGE_LIMIT, "excludeFullGames": "true"}
    if cursor:
        query["cursor"] = cursor
    url = SERVERS_URL.format(place=place_id) + "?" + urllib.parse.urlencode(query)
    data = _get(url, waiting=waiting)
    out: list[Server] = []
    for raw in data.get("data") or []:
        try:
            out.append(Server(
                id=str(raw["id"]), playing=int(raw.get("playing") or 0),
                max_players=int(raw.get("maxPlayers") or 0),
                fps=float(raw.get("fps") or 0.0),
                ping=int(raw["ping"]) if raw.get("ping") is not None else None))
        except (KeyError, TypeError, ValueError):
            continue
    return out, str(data.get("nextPageCursor") or "")


def ranked(servers: list[Server], free_only: bool = True) -> list[Server]:
    """
    Порядок «лучший первым»: есть пинг и место, пинг ниже, FPS сервера выше.

    Серверы без пинга (пустые или только что созданные) — в конце: о них
    ничего не известно.
    """
    pool = [s for s in servers if not (free_only and s.full)]
    return sorted(pool, key=lambda s: (s.ping is None, s.ping or 0,
                                       -min(s.fps, 60.0), -s.playing))


def best(servers: list[Server]) -> Server | None:
    """Лучший сервер, где уже кто-то играет и есть место."""
    for s in ranked(servers):
        if s.ping is not None and s.playing > 0:
            return s
    return None


def join_url(place_id: int, server_id: str | None = None) -> str:
    url = f"roblox://experiences/start?placeId={int(place_id)}"
    if server_id:
        url += "&gameInstanceId=" + urllib.parse.quote(server_id, safe="-")
    return url


def join(place_id: int, server_id: str | None = None) -> str:
    """Открыть Roblox на сервере через протокол roblox:// (Windows)."""
    url = join_url(place_id, server_id)
    os.startfile(url)  # noqa: S606 — штатный обработчик протокола Roblox
    return url
