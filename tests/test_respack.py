"""
tests/test_respack.py — наборы ресурсов: метаданные, ZIP, каналы, лицензии.

Запуск:  python tests/test_respack.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cursor_manager.core import roblox_paths as RP          # noqa: E402
from cursor_manager.core import respack                    # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def raises(fn, exc=(respack.PackError,), needle: str = "") -> bool:
    try:
        fn()
        return False
    except exc as e:
        return needle in str(e) if needle else True
    except Exception:                                         # noqa: BLE001
        return False


def png_bytes(w=64, h=64, color=(53, 160, 255, 255)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def make_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)


META = {
    "schema": 1, "name": "Neon Set", "author": "sanyakiller111",
    "license": "CC0-1.0", "kind": "cursor", "source_url": "https://example.com",
    "description": "синяя стрелка", "tags": ["neon"],
}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="respack-test-"))

    print("\n── карта путей ──")
    check("8 категорий", len(RP.KINDS) == 8, str(len(RP.KINDS)))
    check("путь курсора совпадает с разведкой",
          RP.KINDS["cursor"].path == "content/textures/Cursors/KeyboardMouse")
    check("путь прицела совпадает с разведкой",
          RP.KINDS["crosshair"].path == "content/textures")
    check("MouseLockedCursor у курсора идёт в content/textures",
          str(RP.get("cursor").rel("MouseLockedCursor.png"))
          == "content/textures/MouseLockedCursor.png")
    check("путь неба совпадает с разведкой",
          RP.KINDS["sky"].path == "PlatformContent/pc/textures/sky")
    check("категория прицела честно помечена",
          "скрипт" in RP.KINDS["crosshair"].caveat, RP.KINDS["crosshair"].caveat[:40])
    check("неизвестная категория отклоняется",
          raises(lambda: RP.get("nope"), exc=(KeyError,)))
    check("путь определяется по строке",
          RP.kind_for_path("content/textures/Cursors/KeyboardMouse/ArrowCursor.png")
          == "cursor")
    check("MouseLockedCursor определяется как прицел",
          RP.kind_for_path("content/textures/MouseLockedCursor.png") == "crosshair")
    check("путь неба не путается с редактором",
          RP.kind_for_path("PlatformContent/pc/textures/sky/sky512_ft.tex") == "sky")
    check("две категории на одном пути различаются по порядку",
          RP.kind_for_path("content/textures/Cursors/KeyboardMouse/x.png") is not None)

    print("\n── проверка имён файлов ──")
    check("правильный файл курсора принят",
          RP.validate("cursor", "ArrowCursor.png") is None)
    check("чужой файл в категории курсора отклонён",
          RP.validate("cursor", "Readme.txt") is not None)
    check("путь в имени отклонён", RP.validate("cursor", "a/b.png") is not None)
    check("'..' в имени отклонено", RP.validate("cursor", "..png") is not None)
    check("неверное расширение отклонено", RP.validate("sound", "x.png") is not None)
    check("небо принимает .tex", RP.validate("sky", "sky512_ft.tex") is None)

    print("\n── лицензии ──")
    check("CC0 можно включать в поставку", RP.bundle_allowed("CC0-1.0"))
    check("CC-BY-NC нельзя", not RP.bundle_allowed("CC-BY-NC-4.0"))
    check("GPL-3.0 нельзя без согласования", not RP.bundle_allowed("GPL-3.0"))
    check("UNKNOWN нельзя", not RP.bundle_allowed("UNKNOWN"))
    check("CC-BY можно, но не в поставку",
          RP.bundle_allowed("CC-BY-4.0") is False)
    check("неизвестная лицензия превращается в UNKNOWN",
          respack.PackMeta.from_dict({"name": "x", "license": "ВЫДУМКА"}).license
          == "UNKNOWN")
    check("набор без лицензии не проходит в поставку",
          not respack.PackMeta.from_dict({"name": "x"}).safe_for_bundle)
    check("у заблокированного набора есть объяснение",
          "CC-BY-NC-4.0" in respack.Pack(
              respack.PackMeta(name="x", license="CC-BY-NC-4.0"), Path("x")
          ).safety_note())

    print("\n── набор на диске ──")
    good = tmp / "neon"
    good.mkdir()
    (good / "pack.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    (good / "ArrowCursor.png").write_bytes(png_bytes())
    pack = respack.load_pack(good)
    check("набор читается", pack.meta.name == "Neon Set")
    check("файл внутри найден", len(pack.files) == 1, str(len(pack.files)))
    check("ошибок в наборе нет", pack.safety_note() == "", pack.safety_note())
    check("недостающие файлы перечислены",
          "ArrowFarCursor.png" in pack.missing, str(pack.missing))

    empty = tmp / "empty"
    empty.mkdir()
    (empty / "pack.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    check("пустой набор отклонён",
          raises(lambda: respack.load_pack(empty), needle="нет ни одного файла"))

    nometa = tmp / "nometa"
    nometa.mkdir()
    (nometa / "x.png").write_bytes(png_bytes())
    check("без pack.json отклонён",
          raises(lambda: respack.load_pack(nometa), needle="нет pack.json"))

    bad_kind = tmp / "badkind"
    bad_kind.mkdir()
    m = dict(META); m["kind"] = "небо"
    (bad_kind / "pack.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    (bad_kind / "x.png").write_bytes(png_bytes())
    check("неизвестная категория отклонена",
          raises(lambda: respack.load_pack(bad_kind), needle="неизвестная категория"))

    bad_schema = tmp / "badschema"
    bad_schema.mkdir()
    m = dict(META); m["schema"] = 99
    (bad_schema / "pack.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    (bad_schema / "ArrowCursor.png").write_bytes(png_bytes())
    check("чужая схема отклонена",
          raises(lambda: respack.load_pack(bad_schema), needle="схема"))

    nested = tmp / "nested"
    (nested / "sub").mkdir(parents=True)
    (nested / "pack.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    (nested / "sub" / "ArrowCursor.png").write_bytes(png_bytes())
    check("вложенность отклонена",
          raises(lambda: respack.load_pack(nested), needle="вложенность"))

    print("\n── импорт ZIP ──")
    z1 = tmp / "neon.zip"
    make_zip(z1, {
        "pack.json": json.dumps(META, ensure_ascii=False).encode(),
        "ArrowCursor.png": png_bytes(),
        "ArrowFarCursor.png": png_bytes(color=(43, 217, 138, 255)),
    })
    imported = respack.import_zip(z1, tmp / "lib")
    check("ZIP импортирован", len(imported.files) == 2, str(len(imported.files)))
    check("метаданные сохранены", imported.meta.author == "sanyakiller111")
    check("имя папки взято из имени архива", imported.id == "neon", imported.id)
    check("предпросмотр архива работает", len(respack.inspect_zip(z1)) == 3,
          str(len(respack.inspect_zip(z1))))

    z2 = tmp / "my pack.zip"
    make_zip(z2, {
        "pack.json": json.dumps(META, ensure_ascii=False).encode(),
        "ArrowCursor.png": png_bytes(),
    })
    imported2 = respack.import_zip(z2, tmp / "lib2")
    check("пробелы в имени заменяются", imported2.id == "my-pack", imported2.id)

    z3 = tmp / "набор.zip"
    make_zip(z3, {
        "pack.json": json.dumps(META, ensure_ascii=False).encode(),
        "ArrowCursor.png": png_bytes(),
    })
    imported3 = respack.import_zip(z3, tmp / "lib3")
    check("нелатинское имя получает безопасный id",
          imported3.id.startswith("pack-"), imported3.id)

    print("\n── враждебные ZIP ──")
    hostile = {
        "выход за папку": {"pack.json": json.dumps(META, ensure_ascii=False).encode(),
                          "../evil.png": png_bytes()},
        "абсолютный путь": {"pack.json": json.dumps(META, ensure_ascii=False).encode(),
                            "/etc/evil.png": png_bytes()},
        "исполняемый файл": {"pack.json": json.dumps(META, ensure_ascii=False).encode(),
                             "payload.exe": b"MZ..."},
        "нет манифеста": {"ArrowCursor.png": png_bytes()},
        "неожиданный файл": {"pack.json": json.dumps(META, ensure_ascii=False).encode(),
                             "notes.doc": b"hi"},
        "путь назад через подпапку": {
            "pack.json": json.dumps(META, ensure_ascii=False).encode(),
            "a/b/../../evil.png": png_bytes()},
        "обратный слеш": {"pack.json": json.dumps(META, ensure_ascii=False).encode(),
                          "..\\evil.png": png_bytes()},
    }
    for i, (label, entries) in enumerate(hostile.items()):
        zp = tmp / f"hostile{i}.zip"
        make_zip(zp, entries)
        try:
            respack.import_zip(zp, tmp / "badlib")
            check(f"отклонено: {label}", False, "исключения не было")
        except respack.PackError:
            check(f"отклонено: {label}", True)
        except Exception as exc:                              # noqa: BLE001
            check(f"отклонено: {label}", False, f"неверная ошибка {exc!r}")

    # симлинк внутри архива
    zl = tmp / "link.zip"
    with zipfile.ZipFile(zl, "w") as z:
        z.writestr("pack.json", json.dumps(META, ensure_ascii=False))
        info = zipfile.ZipInfo("shortcut.png")
        info.external_attr = (0xA1FF << 16)                  # симлинк
        z.writestr(info, "/etc/passwd")
    check("отклонено: симлинк",
          raises(lambda: respack.import_zip(zl, tmp / "badlib"), needle="симлинк"))

    # дубль имени
    zd = tmp / "dup.zip"
    with zipfile.ZipFile(zd, "w") as z:
        z.writestr("pack.json", json.dumps(META, ensure_ascii=False))
        z.writestr("ArrowCursor.png", png_bytes())
        z.writestr("ArrowCursor.png", png_bytes(color=(255, 0, 0, 255)))
    check("отклонено: дубль имени",
          raises(lambda: respack.import_zip(zd, tmp / "badlib"), needle="дубль"))

    # не ZIP вовсе
    fake = tmp / "fake.zip"
    fake.write_bytes(b"not a zip at all")
    check("отклонено: не ZIP",
          raises(lambda: respack.import_zip(fake, tmp / "badlib"), needle="не ZIP"))

    print("\n── каналы применения ──")
    check("известны два канала", set(RP.BACKENDS) == {"direct", "bloxstrap"})
    check("Bloxstrap не установлен на этой машине", not RP.bloxstrap_installed())
    check("прямой канал всегда доступен", RP.backend_available("direct"))

    fake_roblox = tmp / "roblox-version"
    (fake_roblox / RP.KINDS["cursor"].path).mkdir(parents=True, exist_ok=True)
    original = png_bytes(color=(255, 255, 255, 255))
    (fake_roblox / RP.KINDS["cursor"].path / "ArrowCursor.png").write_bytes(original)

    res = respack.install(imported, fake_roblox, "direct")
    check("прямая установка отработала", len(res["installed"]) == 2, str(res["installed"]))
    live = fake_roblox / RP.KINDS["cursor"].path / "ArrowCursor.png"
    check("файл на месте", live.is_file())
    check("содержимое подменено",
          respack.sha256_of(live) != respack.sha256_of_bytes(original))
    check("содержимое совпадает с набором",
          respack.sha256_of(live)
          == respack.sha256_of(imported.files["ArrowCursor.png"]))

    bak = (Path(os.environ.get("APPDATA") or Path.home()) / "RobloxCursorChanger"
           / "backup" / fake_roblox.name / RP.KINDS["cursor"].rel("ArrowCursor.png"))
    check("оригинал ушёл в бэкап", bak.is_file(), str(bak))
    check("бэкап побайтово равен оригиналу",
          bak.is_file() and respack.sha256_of(bak) == respack.sha256_of_bytes(original))

    check("канал Bloxstrap без установки отклонён",
          raises(lambda: respack.install(imported, fake_roblox, "bloxstrap"),
                 needle="Bloxstrap не установлен"))
    check("неизвестный канал отклонён",
          raises(lambda: respack.install(imported, fake_roblox, "carrier-pigeon"),
                 needle="неизвестный канал"))

    out = respack.uninstall(imported, fake_roblox, "direct")
    check("снятие вернуло оригинал из бэкапа",
          "ArrowCursor.png" in out["restored"], str(out))
    check("файл на месте после возврата", live.is_file())
    check("после отката содержимое снова исходное",
          respack.sha256_of(live) == respack.sha256_of_bytes(original))
    check("после отката путь остаётся валидным",
          RP.validate("cursor", live.name) is None)

    bak.unlink()
    out = respack.uninstall(imported, fake_roblox, "direct")
    check("без бэкапа снятие не удаляет чужой оригинал",
          live.is_file()
          and respack.sha256_of(live) == respack.sha256_of_bytes(original),
          str(out))
    check("без бэкапа файл помечен пропущенным",
          any(s.startswith("ArrowCursor.png") for s in out["skipped"]), str(out))

    print("\n── сканирование библиотеки ──")
    lib = tmp / "scan"
    lib.mkdir()
    shutil.copytree(good, lib / "neon")
    (lib / "broken").mkdir()
    found = respack.scan_library(lib)
    check("найден и рабочий, и битый", len(found) == 2, str(len(found)))
    check("битый набор помечен ошибкой, а не потерян",
          len([p for p, e in found if e]) == 1)
    check("сканирование пустой папки не падает",
          respack.scan_library(tmp / "нет-такой") == [])

    print("\n" + "=" * 58)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print("  ·", f)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())