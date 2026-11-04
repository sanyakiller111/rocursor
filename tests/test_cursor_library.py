"""
tests/test_cursor_library.py — проверка движка каталога.

Запуск:  python -m pytest tests/ -q      (или  python tests/test_cursor_library.py)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cursor_manager.content import cursor_library as lib  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Изолируем LIBRARY_DIR в temp, чтобы тест не трогал реальные настройки
# ─────────────────────────────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="cmtest-"))
lib.LIBRARY_DIR = TMP / "library"
lib.INDEX_FILE = lib.LIBRARY_DIR / "index.json"
lib.STATE_FILE = lib.LIBRARY_DIR / "state.json"
lib.CHECK_INTERVAL_HOURS = 0          # проверять всегда

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


# ─────────────────────────────────────────────────────────────────────────────
# Подставной сервер: отдаёт манифест, файлы, умеет 304 и битый хеш
# ─────────────────────────────────────────────────────────────────────────────
PAYLOAD = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/manifest.json":
            body = PAYLOAD["manifest"]
            if PAYLOAD.get("etag") and self.headers.get("If-None-Match") == PAYLOAD["etag"]:
                self.send_response(304)
                self.send_header("ETag", PAYLOAD["etag"])
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("ETag", PAYLOAD.get("etag", ""))
            self.send_header("Last-Modified", "Wed, 01 Oct 2026 10:00:00 GMT")
            self.end_headers()
            self.wfile.write(body)
            return

        name = self.path.lstrip("/")
        if name in PAYLOAD["files"]:
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(PAYLOAD["files"][name])
            return

        self.send_response(404)
        self.end_headers()


def build_manifest(files: dict[str, bytes], *, corrupt: bool = False) -> bytes:
    items = []
    for name, blob in files.items():
        digest = hashlib.sha256(blob).hexdigest()
        if corrupt:
            digest = "0" * 64                       # заведомо неверный хеш
        items.append({"id": name.split(".")[0], "name": name.split(".")[0].title(),
                      "category": "Test", "tags": [], "file": name,
                      "sha256": digest, "bytes": len(blob)})
    return json.dumps({"schema": 1, "source": "test", "items": items},
                      ensure_ascii=False).encode("utf-8")


def serve(files: dict[str, bytes], corrupt: bool = False) -> tuple[str, HTTPServer]:
    PAYLOAD["files"] = files
    PAYLOAD["manifest"] = build_manifest(files, corrupt=corrupt)
    PAYLOAD["etag"] = '"v1"'
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/manifest.json", srv


def main() -> int:
    print("\n── вшитый каталог ──")
    bundled = lib.bundled_manifest()
    ids = [i["id"] for i in bundled["items"]]
    check("вшитый каталог непуст", bundled["count"] > 0, str(bundled["count"]))
    check("count совпадает с числом записей", bundled["count"] == len(ids))
    check("все файлы на диске",
          all((lib.BUNDLED_DIR / i["file"]).is_file() for i in bundled["items"]))
    check("нет лишних PNG без записи в манифесте",
          {p.name for p in lib.BUNDLED_DIR.glob("*.png")}
          == {i["file"] for i in bundled["items"]})
    check("id уникальны", len(ids) == len(set(ids)))
    check("хеши валидны",
          all(len(i["sha256"]) == 64 for i in bundled["items"]))
    check("хотспот = центр", bundled["hotspot_rule"] == "center")
    base = len(bundled["items"])
    catalog = lib.catalog()
    check("catalog() отдаёт всё", len(catalog) == base, str(len(catalog)))
    check("все курсоры физически есть", all(c.path is not None for c in catalog))
    check("resolve_png работает", lib.resolve_png(ids[0]) is not None)

    print("\n── офлайн ──")
    r = lib.sync("", force=True)
    check("пустой URL не ломает", r.ok is False and "не задан" in r.message)
    check("каталог после неудачи цел", len(lib.catalog()) == base)
    r = lib.sync("http://127.0.0.1:9/manifest.json", force=True)
    check("недоступный хост не ломает", r.ok is False)
    check("после сетевой ошибки каталог цел", len(lib.catalog()) == base)

    print("\n── успешная синхронизация ──")
    good = {"alpha-cursor.png": b"\x89PNG\r\n\x1a\nalpha-payload",
            "beta-cursor.png": b"\x89PNG\r\n\x1a\nbeta-payload"}
    url, srv = serve(good)
    r = lib.sync(url, force=True)
    check("sync ok", r.ok, r.message)
    check("скачано 2 новых", r.added == 2, f"added={r.added}")
    check("пропущено 0", r.skipped == 0)
    check("файлы на диске", (lib.LIBRARY_DIR / "alpha-cursor.png").is_file())
    check("удалённые видны в каталоге", len(lib.catalog()) == base + 2, str(len(lib.catalog())))
    check("удалённый курсор резолвится", lib.resolve_png("alpha-cursor") is not None)

    print("\n── ETag / 304 ──")
    r = lib.sync(url, force=True)
    check("повтор даёт 304 и не качает", r.ok and r.added == 0 and r.updated == 0,
          f"ok={r.ok} added={r.added} updated={r.updated}")
    check("сообщение о неизменности", "не изменился" in r.message, r.message)

    print("\n── дельта ──")
    good["alpha-cursor.png"] = b"\x89PNG\r\n\x1a\nalpha-CHANGED"
    PAYLOAD["manifest"] = build_manifest(good)
    PAYLOAD["etag"] = '"v2"'          # контент изменился — ETag обязан смениться
    r = lib.sync(url, force=True)
    check("изменившийся файл обновлён", r.updated == 1, f"updated={r.updated}")
    check("неизменившийся пропущен", r.skipped == 1, f"skipped={r.skipped}")
    check("новый байт на диске",
          lib.LIBRARY_DIR.joinpath("alpha-cursor.png").read_bytes().endswith(b"alpha-CHANGED"))

    print("\n── fail closed: битый хеш ──")
    bad = {"gamma-cursor.png": b"\x89PNG\r\n\x1a\ngamma"}
    url2, srv2 = serve(bad, corrupt=True)
    r = lib.sync(url2, force=True)
    check("ни один файл не принят", r.ok is False, f"ok={r.ok}")
    check("файл с чужим хешем НЕ сохранён", not (lib.LIBRARY_DIR / "gamma-cursor.png").exists())
    check("непроверенный курсор не попал в каталог",
          all(c.id != "gamma-cursor" for c in lib.catalog()))
    check("предыдущий кэш не пострадал", len(lib.catalog()) == base + 2, str(len(lib.catalog())))
    check("все курсоры из каталога физически есть",
          all(c.path is not None for c in lib.catalog()))

    print("\n── валидация манифеста ──")
    for label, payload in (
        ("неизвестная схема", {"schema": 99, "items": [{"id": "a", "name": "a", "file": "a.png", "sha256": "a" * 64}]}),
        ("пустой items", {"schema": 1, "items": []}),
        ("нет items", {"schema": 1}),
        ("путь наружу ../x.png", {"schema": 1, "items": [{"id": "a", "name": "a", "file": "../x.png", "sha256": "a" * 64}]}),
        ("кривой sha256", {"schema": 1, "items": [{"id": "a", "name": "a", "file": "a.png", "sha256": "zz"}]}),
    ):
        p = lib.LIBRARY_DIR / "bad.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")
        try:
            lib._read_manifest(p)
            check(f"отклонено: {label}", False, "исключения не было")
        except ValueError:
            check(f"отклонено: {label}", True)
        except Exception as exc:
            check(f"отклонено: {label}", False, f"неверная ошибка {exc!r}")
        p.unlink(missing_ok=True)

    print("\n── атомарность ──")
    check("нет .part файлов", not list(lib.LIBRARY_DIR.glob("*.part")),
          str([p.name for p in lib.LIBRARY_DIR.glob("*.part")]))

    print("\n── диагностика ──")
    d = lib.diagnostics()
    check("диагностика отрабатывает", d["catalog_total"] >= 28 and "library_dir" in d)

    srv.shutdown()
    srv2.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)

    print("\n" + "═" * 58)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print("  ·", f)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())