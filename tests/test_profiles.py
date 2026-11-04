"""
tests/test_profiles.py — профили: сохранение, применение, снятие, статус.

Тесты работают в отдельной APPDATA, чтобы не трогать реальные профили
и реальный Roblox. Запуск:  python tests/test_profiles.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# подменяем APPDATA до импорта profiles: путь состояния вычисляется при импорте
_TMP = Path(tempfile.mkdtemp(prefix="profiles-test-"))
os.environ["APPDATA"] = str(_TMP)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cursor_manager.core import roblox_paths as RP          # noqa: E402
from cursor_manager.core import respack                    # noqa: E402
from cursor_manager.core import profiles as prof           # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def _raises(fn, needle: str = "") -> bool:
    try:
        fn()
        return False
    except prof.ProfileError as exc:
        return needle in str(exc) if needle else True
    except Exception:                                         # noqa: BLE001
        return False


def make_pack(lib: Path, name: str, color: tuple, filename: str = "ArrowCursor.png") -> None:
    from PIL import Image
    import io
    d = lib / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "pack.json").write_text(json.dumps({
        "schema": 1, "name": name, "license": "CC0-1.0", "kind": "cursor",
    }, ensure_ascii=False), encoding="utf-8")
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), color).save(buf, "PNG")
    (d / filename).write_bytes(buf.getvalue())


def fake_roblox(tmp: Path) -> Path:
    v = tmp / "version-test"
    (v / RP.get("cursor").path).mkdir(parents=True, exist_ok=True)
    (v / RP.KINDS["cursor"].path / "ArrowCursor.png").write_bytes(b"\x89PNG-stock")
    return v


def main() -> int:
    lib = prof.library_root()
    lib.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="profiles-roblox-"))
    roblox = fake_roblox(tmp)

    print("\n── стартовые профили ──")
    ps = prof.ensure_starter()
    check("заведены профили по умолчанию", len(ps.names()) >= 3, str(ps.names()))
    check("файл состояния создан", prof.profiles_file().is_file())
    check("профили пустые — наборов ещё нет", all(not ps.get(n).packs for n in ps.names()))
    check("повторный вызов не плодит дубли",
          len(prof.ensure_starter().names()) == len(ps.names()))

    print("\n── сохранение ──")
    make_pack(lib, "blue", (53, 160, 255, 255))
    make_pack(lib, "green", (43, 217, 138, 255))
# имя держим в переменной: повторяя кириллический литерал построчно,
    # легко получить две разные строки с неразличимым на экране составом
    prof_name = "\u0421\u0438\u043d\u0438\u0439+\u0437\u0435\u043b\u0451\u043d\u044b\u0439"
    ps.save_current(prof_name, ["blue", "green", "blue"], "direct")
    p = ps.get(prof_name)
    check("профиль сохранён", p is not None)
    check("дубли убраны", p.packs == ["blue", "green"], str(p.packs))
    check("проставлена дата", bool(p.saved_at))
    check("пустое имя отклонено", _raises(lambda: ps.save_current("  ", []), "пустое"))

    print("\n── перечитывание с диска ──")
    reloaded = prof.Profiles()
    got = reloaded.get(prof_name)
    check("профиль перечитан из profiles.json", got is not None)
    check("состав совпал", got is not None and got.packs == ["blue", "green"],
          str(got.packs) if got else "профиль не найден")
    check("канал совпал", got is not None and got.backend == "direct")

    bad = prof.profiles_file().with_suffix(".broken")
    bad.write_text("{ не json", encoding="utf-8")
    real = prof.profiles_file()
    real_backup = real.read_bytes()
    real.write_text("{ не json", encoding="utf-8")
    try:
        prof.Profiles()
        check("битое состояние не роняет запуск", True)
    except Exception as exc:                                  # noqa: BLE001
        check("битое состояние не роняет запуск", False, repr(exc))
    real.write_bytes(real_backup)

    print("\n── применение и снятие ──")
    res = ps.apply(prof_name, roblox)
    check("оба набора применились", len(res["applied"]) == 2, str(res["applied"]))
    check("ошибок нет", res["failed"] == [], str(res["failed"]))
    live = roblox / RP.KINDS["cursor"].path / "ArrowCursor.png"
    check("файл в папке Roblox изменился", live.read_bytes() != b"\x89PNG-stock")

    out = ps.revert(prof_name, roblox)
    check("снятие отработало", len(out["reverted"]) == 2)
    check("ошибок при снятии нет", out["failed"] == [], str(out["failed"]))

    print("\n── дрейф между набором и папкой Roblox ──")
    ps.apply("Синий+зелёный", roblox)
    live.write_bytes(b"\x89PNG-changed-by-hand")
    st = ps.status(prof_name, roblox)
    check("расхождение замечено", any(not r["ok"] for r in st["packs"]),
          str([r for r in st["packs"] if not r["ok"]]))
    ps.revert(prof_name, roblox)

    print("\n── коллизии ──")
    st = ps.status(prof_name, roblox)
    check("коллизия видна до применения",
          any("ArrowCursor.png" in c for c in st["collisions"]), str(st["collisions"]))
    check("коллизия описана как коллизия, а не как дрейф",
          any("перебит" in r["why"] for r in st["packs"] if not r["ok"]),
          str([r["why"] for r in st["packs"] if not r["ok"]]))
    rows = {r["id"]: r for r in st["packs"]}
    check("перебит ранний набор, а не последний",
          "перебит" in rows["blue"]["why"] and "перебит" not in rows["green"]["why"],
          str({k: v["why"] for k, v in rows.items()}))
    check("метод collisions совпадает с status",
          ps.collisions(prof_name) == st["collisions"])

    print("\n── наборы с разными именами не конфликтуют ──")
    make_pack(lib, "blue-far", (53, 160, 255, 255), "ArrowFarCursor.png")
    ps.save_current("Без коллизии", ["blue-far", "green"], "direct")
    check("коллизий нет", ps.collisions("Без коллизии") == [], str(ps.collisions("Без коллизии")))

    print("\n── полный сброс ──")
    ps.save_current("Один", ["blue"], "direct")
    ps.apply("Один", roblox)
    rst = ps.reset_everything(roblox, "direct")
    check("сброс отработал", "ArrowCursor.png" in rst["restored"] or
          "ArrowCursor.png" in rst["removed"], str(rst))

    print("\n── ошибки ──")
    check("несуществующий профиль при применении", _raises(
        lambda: ps.apply("нет-такого", roblox), "нет"))
    check("несуществующий профиль при снятии", _raises(
        lambda: ps.revert("нет-такого", roblox), "нет"))
    ps.save_current("Пустой", [], "direct")
    check("пустой профиль отклонён при применении", _raises(
        lambda: ps.apply("Пустой", roblox), "пусто"))
    check("удаление профиля", ps.remove("Пустой"))
    check("повторное удаление возвращает False", ps.remove("Пустой") is False)

    print("\n── битый набор в библиотеке ──")
    (lib / "broken").mkdir(exist_ok=True)
    (lib / "broken" / "pack.json").write_text("{ сломан", encoding="utf-8")
    ps.save_current("С битым", ["broken"], "direct")
    res = ps.apply("С битым", roblox)
    check("применение не падает на битом наборе", res["applied"] == [] and res["failed"],
          str(res))
    ps.remove("С битым")

    print("\n" + "═" * 58)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print("  ·", f)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())