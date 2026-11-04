"""
cursor_library.py — каталог курсоров: вшитый + автообновление.

Модель работы приложения:

    вшитый каталог (assets/cursors/)  ← всегда доступен, работает офлайн
              ↓  remote sync, если задан CATALOG_URL
    локальный кэш  (~APPDATA/.../library)
              ↓
    resolve_png(id) → путь к PNG, который cursor_core отдаёт в Roblox

Принципы, заложенные в код:

1. **Fail open на проверке, fail closed на установке.** Отсутствие сети или
   ошибка разбора манифеста не ломают приложение — оно отдаёт вшитый каталог.
   Но файл, чей SHA-256 не совпал с манифестом, никогда не попадает в кэш.

2. **Условный GET.** ETag / If-Modified-Since, чтобы проверка обновления стоила
   ~200 байт, а не полный индекс. Плюс дебаунс CHECK_INTERVAL_HOURS, чтобы
   не долбить источник при каждом запуске.

3. **Дельта.** Скачиваются только файлы, которых нет в кэше или чей хеш
   изменился. Полная перекачка каталога не происходит никогда.

4. **Атомарная подмена.** Манифест и файлы пишутся через .part + os.replace,
   поэтому прерванная загрузка не оставляет битый индекс.

5. Никаких куков, токенов и телеметрии. Запрашивается ровно один URL.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cursor_manager.version import APP_SLUG, REPO, VERSION

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_SLUG
LIBRARY_DIR = APP_DIR / "library"
INDEX_FILE = LIBRARY_DIR / "index.json"
STATE_FILE = LIBRARY_DIR / "state.json"

USER_AGENT = f"{APP_SLUG}/{VERSION} (+{REPO})"
HTTP_TIMEOUT = 15
CHECK_INTERVAL_HOURS = 24
SCHEMA = 1


# ─────────────────────────────────────────────────────────────────────────────
# Пути. При запуске из .exe ресурсы лежат в каталоге бандла, при разработке —
# рядом с исходниками. Это единственное место, которое знает про PyInstaller.
# ─────────────────────────────────────────────────────────────────────────────
def _resource_root() -> Path:
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    if meipass:                      # замороженная сборка
        return Path(meipass) / "assets"
    # src/cursor_manager/content/cursor_library.py -> корень репозитория
    return Path(__file__).resolve().parents[3] / "assets"


BUNDLED_DIR = _resource_root() / "cursors"
BUNDLED_MANIFEST = BUNDLED_DIR / "manifest.json"


# ─────────────────────────────────────────────────────────────────────────────
# Модели
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Cursor:
    id: str
    name: str
    category: str
    tags: list[str]
    file: str
    sha256: str
    bytes: int
    origin: str                    # "bundled" | "remote"
    blurb: str = ""                # одно предложение описания
    author: str = ""
    uploader: str = ""
    source_url: str = ""
    downloads: int = 0
    favorites: int = 0

    @property
    def path(self) -> Path | None:
        """Путь к PNG: сначала кэш, потом вшитая папка."""
        cached = LIBRARY_DIR / self.file
        if cached.is_file():
            return cached
        bundled = BUNDLED_DIR / self.file
        if bundled.is_file():
            return bundled
        return None


@dataclass
class SyncResult:
    ok: bool
    added: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    message: str = ""
    checked_at: str = ""


@dataclass
class _State:
    etag: str = ""
    last_modified: str = ""
    last_success: str = ""
    last_check: str = ""
    schema: int = SCHEMA
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "_State":
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {"etag", "last_modified", "last_success", "last_check", "schema"}
        return cls(**{k: v for k, v in raw.items() if k in known},
                   extra={k: v for k, v in raw.items() if k not in known})

    def save(self) -> None:
        payload = {"etag": self.etag, "last_modified": self.last_modified,
                   "last_success": self.last_success, "last_check": self.last_check,
                   "schema": self.schema, **self.extra}
        _atomic_write_json(STATE_FILE, payload)


# ─────────────────────────────────────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────────────────────────────────────
def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def _atomic_write_json(target: Path, payload: dict) -> None:
    _atomic_write_bytes(target, json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _read_manifest(path: Path) -> dict:
    """Разбор манифеста с жёсткой проверкой схемы. Бросает ValueError."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("манифест не является объектом")
    if int(raw.get("schema", 0)) != SCHEMA:
        raise ValueError(f"неподдерживаемая схема манифеста: {raw.get('schema')}")
    items = raw.get("items")
    if not isinstance(items, list):
        raise ValueError("в манифесте нет списка items")
    clean = []
    for it in items:
        if not isinstance(it, dict):
            continue
        need = ("id", "name", "file", "sha256")
        if any(k not in it for k in need):
            continue
        # отсекаем всё, что похоже на путь наружу
        name = str(it["file"])
        if "/" in name or "\\" in name or name.startswith("."):
            continue
        digest = str(it["sha256"]).lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            continue
        clean.append({
            "id": str(it["id"]),
            "name": str(it["name"]),
            "category": str(it.get("category", "Other")),
            "tags": list(it.get("tags") or []),
            "blurb": str(it.get("blurb") or "")[:400],
            "file": name,
            "sha256": digest,
            "bytes": int(it.get("bytes") or 0),
            "author": str(it.get("author") or ""),
            "uploader": str(it.get("uploader") or ""),
            "source_url": str(it.get("source_url") or ""),
            "downloads": int(it.get("downloads") or 0),
            "favorites": int(it.get("favorites") or 0),
        })
    if not clean:
        raise ValueError("манифест не содержит ни одного валидного курсора")
    return {"schema": SCHEMA, "count": len(clean), "items": clean,
            "source": raw.get("source", "remote"),
            "license": raw.get("license", ""),
            "canvas": raw.get("canvas", 0),
            "hotspot_rule": raw.get("hotspot_rule", "")}


# ─────────────────────────────────────────────────────────────────────────────
# Каталог
# ─────────────────────────────────────────────────────────────────────────────
def bundled_manifest() -> dict:
    """Вшитый манифест. Этот вызов не падает: без него приложение не запустится."""
    return _read_manifest(BUNDLED_MANIFEST)


def active_manifest() -> dict:
    """
    Кэш, если он валиден и новее вшитого; иначе вшитый.

    Вшитый каталог всегда в выигрыше при равенстве: так нельзя случайно
    остаться без курсоров, удалив кэш.
    """
    if INDEX_FILE.is_file():
        try:
            if INDEX_FILE.stat().st_mtime >= BUNDLED_MANIFEST.stat().st_mtime:
                return _read_manifest(INDEX_FILE)
        except (OSError, ValueError):
            pass
    return bundled_manifest()


def catalog() -> list[Cursor]:
    """Полный список курсоров для UI: кэш + вшитые, без дублей."""
    out: dict[str, Cursor] = {}
    # Именованные аргументы, не позиционные: у Cursor больше десяти полей,
    # и добавление нового не должно молча сдвигать остальные.
    def make(it: dict, origin: str) -> Cursor:
        return Cursor(
            id=it["id"], name=it["name"], category=it["category"], tags=it["tags"],
            file=it["file"], sha256=it["sha256"], bytes=it["bytes"], origin=origin,
            blurb=it.get("blurb", ""), author=it.get("author", ""),
            uploader=it.get("uploader", ""), source_url=it.get("source_url", ""),
            downloads=it.get("downloads", 0), favorites=it.get("favorites", 0),
        )

    try:
        for it in bundled_manifest()["items"]:
            out[it["id"]] = make(it, "bundled")
    except (OSError, ValueError):
        pass
    try:
        for it in _read_manifest(INDEX_FILE)["items"]:
            out[it["id"]] = make(it, "remote")
    except (OSError, ValueError):
        pass
    return list(out.values())


def resolve_png(cursor_id: str) -> Path | None:
    """Путь к PNG для передачи в cursor_core.apply_cursor()."""
    for c in catalog():
        if c.id == cursor_id:
            return c.path
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Синхронизация
# ─────────────────────────────────────────────────────────────────────────────
def due_for_check(force: bool = False) -> bool:
    if force:
        return True
    state = _State.load()
    if not state.last_check:
        return True
    return (time.time() - _parse_iso(state.last_check)) >= CHECK_INTERVAL_HOURS * 3600


def sync(manifest_url: str, *, force: bool = False,
         progress=None) -> SyncResult:
    """
    Обновить каталог из внешнего источника.

    progress(done: int, total: int, label: str) — вызывается в UI-потоке через
    очередь; здесь он выполняется синхронно в фоновом потоке приложения.

    Любая сетевая ошибка даёт ok=False и НЕ трогает существующий кэш.
    """
    if not manifest_url:
        return SyncResult(ok=False, message="Источник каталога не задан", checked_at=_now())
    if not due_for_check(force):
        state = _State.load()
        return SyncResult(ok=True, message="Проверка не пора", checked_at=state.last_check or "")

    state = _State.load()
    state.last_check = _now()

    try:
        manifest_bytes, headers = _get(manifest_url, etag=state.etag,
                                       last_modified=state.last_modified)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:                       # не изменилось — это успех
            state.save()
            return SyncResult(ok=True, message="Каталог не изменился",
                              total=len(catalog()), checked_at=state.last_check)
        state.save()
        return SyncResult(ok=False, message=f"Сервер ответил {exc.code}", checked_at=state.last_check)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        state.save()
        reason = getattr(exc, "reason", exc)
        return SyncResult(ok=False, message=f"Сеть недоступна: {reason}",
                          total=len(catalog()), checked_at=state.last_check)

    if manifest_bytes is None:                    # 304 без исключения
        state.save()
        return SyncResult(ok=True, message="Каталог не изменился",
                          total=len(catalog()), checked_at=state.last_check)

    state.etag = headers.get("etag", "")
    state.last_modified = headers.get("last_modified", "")

    # ── манифест разобран и провалидирован ──
    tmp_index = LIBRARY_DIR / "index.json.part"
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    tmp_index.write_bytes(manifest_bytes)
    try:
        parsed = _read_manifest(tmp_index)
    except ValueError as exc:
        tmp_index.unlink(missing_ok=True)
        state.save()
        return SyncResult(ok=False, message=f"Некорректный манифест: {exc}",
                          total=len(catalog()), checked_at=state.last_check)

    items = parsed["items"]
    verified: list[dict] = []       # в индекс попадает только то, что реально на диске
    added = updated = skipped = failed = 0
    total = len(items)

    for n, it in enumerate(items, 1):
        if progress:
            progress(n, total, it["name"])
        dest = LIBRARY_DIR / it["file"]
        # файл уже есть и совпадает — не качаем
        if dest.is_file() and sha256_of(dest) == it["sha256"]:
            verified.append(it)
            skipped += 1
            continue
        was_there = dest.is_file()
        try:
            blob = _get_bytes(_join(manifest_url, it["file"]))
        except (urllib.error.URLError, TimeoutError, OSError):
            failed += 1
            continue                            # этот файл пропустим, остальные качаем
        if hashlib.sha256(blob).hexdigest().lower() != it["sha256"]:
            failed += 1
            continue                            # fail closed: битый файл не сохраняем
        _atomic_write_bytes(dest, blob)
        verified.append(it)
        added += 0 if was_there else 1
        updated += 1 if was_there else 0

    tmp_index.unlink(missing_ok=True)

    # Ни один файл не прошёл проверку: рабочий индекс не трогаем. Иначе один
    # битый релиз обнулил бы каталог, который ещё вчера работал.
    if not verified and INDEX_FILE.is_file():
        state.last_check = _now()
        state.save()
        return SyncResult(ok=False, failed=failed,
                          message="Ни один файл не прошёл проверку целостности — каталог не изменён",
                          total=len(catalog()), checked_at=state.last_check)

    # Индекс пишется уже отфильтрованным. Иначе UI покажет курсор, который
    # физически не скачался и который нельзя установить.
    _atomic_write_json(INDEX_FILE, {
        "schema": SCHEMA,
        "source": parsed["source"],
        "license": parsed["license"],
        "canvas": parsed["canvas"],
        "hotspot_rule": parsed["hotspot_rule"],
        "count": len(verified),
        "items": verified,
    })

    state.last_success = _now()
    state.save()

    changed = added + updated
    if verified:
        note = (f"Добавлено {added}, обновлено {updated}" if changed
                else f"Все {total} курсоров на месте")
        if failed:
            note += f" · пропущено {failed}"
    else:
        note = "Ни один файл не прошёл проверку целостности"
    return SyncResult(ok=bool(verified), added=added, updated=updated, skipped=skipped,
                      total=total, message=note, checked_at=state.last_success)


def _get(url: str, *, etag: str = "", last_modified: str = "") -> tuple[bytes | None, dict]:
    """
    Условный GET. Возвращает (тело | None при 304, заголовки валидаторов).
    Кэширующие заголовки нужны для следующего запроса — без них каждый запуск
    тянул бы полный индекс вместо пустого ответа.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if etag:
        req.add_header("If-None-Match", etag)
    if last_modified:
        req.add_header("If-Modified-Since", last_modified)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        headers = {
            "etag": resp.headers.get("ETag", ""),
            "last_modified": resp.headers.get("Last-Modified", ""),
        }
        if resp.status == 304:
            return None, headers
        return resp.read(), headers


def _get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def _join(base: str, name: str) -> str:
    return base.rsplit("/", 1)[0] + "/" + name


# ─────────────────────────────────────────────────────────────────────────────
# Диагностика — для раздела «О приложении» и для отчётов о багах
# ─────────────────────────────────────────────────────────────────────────────
def diagnostics() -> dict:
    state = _State.load()
    total = len(catalog())
    missing = [c.id for c in catalog() if c.path is None]
    try:
        bundled_n = len(bundled_manifest()["items"])
    except (OSError, ValueError):
        bundled_n = 0
    try:
        cached_n = len(_read_manifest(INDEX_FILE)["items"]) if INDEX_FILE.is_file() else 0
    except (OSError, ValueError):
        cached_n = 0                     # индекс может быть пустым или битым — это не ошибка UI
    return {
        "catalog_total": total,
        "bundled": bundled_n,
        "cached": cached_n,
        "library_dir": str(LIBRARY_DIR),
        "last_success": state.last_success or "ни разу",
        "last_check": state.last_check or "ни разу",
        "missing_files": missing,
    }