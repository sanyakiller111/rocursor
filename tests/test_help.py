"""
tests/test_help.py — maintenance, netfix, updates.

Без сети и без настоящего Roblox: окружение (LOCALAPPDATA/APPDATA/TEMP)
подменяется ДО импорта, PowerShell/UAC и HTTP — подставные функции.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory(prefix="sk-help-")
T = Path(_TMP.name)
for k, sub in (("LOCALAPPDATA", "local"), ("APPDATA", "roaming"), ("TEMP", "temp"),
               ("TMP", "temp")):
    (T / sub).mkdir(exist_ok=True)
    os.environ[k] = str(T / sub)
os.environ.pop("ROBLOX_EXTRA_DIR", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cursor_manager.core import fps, maintenance as M, netfix as N  # noqa: E402
from cursor_manager.core import updates as U  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" +
          (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def put(path: Path, data: bytes = b"x" * 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_maintenance() -> None:
    print("maintenance")
    local, roam, temp = T / "local", T / "roaming", T / "temp"
    rb = local / "Roblox"
    put(rb / "logs" / "a.log", b"1" * 100)
    put(rb / "logs" / "sub" / "b.log", b"1" * 50)
    put(temp / "Roblox" / "t.tmp")
    put(rb / "Downloads" / "roblox-player" / "setup.exe", b"1" * 20)
    put(roam / "RobloxCursorChanger" / "cache" / "c.png")
    # неприкосновенное
    keep = [put(rb / "rbx-storage.db"), put(rb / "LocalStorage" / "x.ini"),
            put(rb / "GlobalBasicSettings_13.xml"), put(rb / "AnalysticsSettings.xml"),
            put(rb / "ClientSettings" / "ClientAppSettings.json", b"{}"),
            put(roam / "RobloxCursorChanger" / "backup" / "v" / "orig.png")]
    cur, old = rb / "Versions" / "version-cur", rb / "Versions" / "version-old"
    studio = rb / "Versions" / "version-studio"
    for d in (cur, old):
        put(d / "RobloxPlayerBeta.exe")
        put(d / "content" / "textures" / "Cursors" / "KeyboardMouse" / "ArrowCursor.png")
    put(studio / "RobloxStudioBeta.exe")

    real_resolve = M.cursor_core.resolve_roblox_dir
    real_running = M.roblox_running
    M.cursor_core.resolve_roblox_dir = lambda extra=None: cur
    M.roblox_running = lambda: False
    try:
        found = M.scan_junk()
        paths = {Path(i["path"]) for i in found}
        check("все кандидаты найдены", {rb / "logs", temp / "Roblox", rb / "Downloads",
              roam / "RobloxCursorChanger" / "cache", old} <= paths, str(paths))
        check("текущая версия и студия не предлагаются",
              cur not in paths and studio not in paths)
        logs = next(i for i in found if Path(i["path"]) == rb / "logs")
        check("размер и число файлов", logs["bytes"] == 150 and logs["files"] == 2, str(logs))

        dry = M.clean(found, dry_run=True)
        check("dry_run ничего не удаляет",
              (rb / "logs" / "a.log").exists() and old.exists()
              and dry["removed_bytes"] > 0)

        # подмена: чужой путь и родитель разрешённого
        outsider = put(T / "other" / "precious.txt")
        res = M.clean([{"path": str(T / "other")}, {"path": str(rb)},
                       {"path": str(rb / "LocalStorage")}, {"path": ""}, "junk"])
        check("чужие пути в skipped", len(res["skipped"]) == 5 and
              res["removed_files"] == 0, str(res))
        check("чужие файлы целы", outsider.exists() and all(p.exists() for p in keep))

        res = M.clean(found)
        check("чистка отработала", res["removed_files"] >= 6 and not res["skipped"], str(res))
        check("логи пусты, корень остался",
              (rb / "logs").is_dir() and not any((rb / "logs").iterdir()))
        check("старая версия снесена, текущая цела", not old.exists() and cur.exists())
        check("настройки и вход целы", all(p.exists() for p in keep))
        check("после чистки сканер пуст", not M.scan_junk())

        # занятый файл не роняет clean (имитируем отказ unlink)
        put(rb / "logs" / "busy.log")
        real_unlink = os.unlink

        def fake_unlink(p, *a, **k):
            if str(p).endswith("busy.log"):
                raise PermissionError("занят")
            return real_unlink(p, *a, **k)
        os.unlink = fake_unlink
        try:
            res = M.clean(M.scan_junk())
        finally:
            os.unlink = real_unlink
        check("занятый файл пропущен", len(res["skipped"]) == 1 and
              (rb / "logs" / "busy.log").exists(), str(res))

        M.roblox_running = lambda: True
        put(rb / "Versions" / "version-old2" / "RobloxPlayerBeta.exe")
        check("при запущенном Roblox версии не предлагаются",
              not any("version-old2" in i["path"] for i in M.scan_junk()))
    finally:
        M.cursor_core.resolve_roblox_dir = real_resolve
        M.roblox_running = real_running

    # repair на временной версии
    from cursor_manager.core import respack
    print("repair")
    ver = rb / "Versions" / "version-cur"
    cs = ver / "ClientSettings" / "ClientAppSettings.json"
    fps.apply_flags(ver, ["msaa", "grass"], "direct")
    check("флаги записаны", cs.is_file())
    bs = rb / "GlobalBasicSettings_13.xml"
    bs.write_text('<roblox><int name="FramerateCap">60</int></roblox>', encoding="utf-8")
    fps.apply_basic(240, None)
    check("лимит кадров изменён", fps.read_basic().get("cap") == 240)
    M.roblox_running = lambda: False
    try:
        rep = M.repair(ver)
    finally:
        M.roblox_running = real_running
    check("файл флагов убран", not cs.exists(), str(rep))
    check("настройки игры возвращены", rep["basic"] and fps.read_basic().get("cap") == 60, str(rep))
    check("отчёт без ошибок", not rep["errors"], str(rep))
    check("бэкапы лежат в APPDATA временного окружения",
          str(respack.BACKUP_ROOT).startswith(str(roam)))
    M.roblox_running = lambda: True
    try:
        rep = M.repair(ver)
    finally:
        M.roblox_running = real_running
    check("при запущенном Roblox настройки пропущены", rep["skipped"] and not rep["basic"])


SAMPLE = json.dumps([
    {"adapter": "Ethernet", "index": 12, "servers": ["192.168.1.1"], "dhcp": True,
     "description": "Realtek"},
    {"adapter": "vEthernet (WSL)", "index": 30, "servers": [], "dhcp": True,
     "description": "Hyper-V Virtual Ethernet Adapter"},
])


def test_netfix() -> None:
    print("netfix")
    ad = N.parse_adapters(SAMPLE)
    check("разбор массива", len(ad) == 2 and ad[0]["index"] == 12 and ad[0]["dhcp"])
    one = N.parse_adapters(json.dumps({"adapter": "W", "index": 3, "servers": "8.8.8.8",
                                       "dhcp": False}))
    check("разбор одиночного объекта", one[0]["servers"] == ["8.8.8.8"] and not one[0]["dhcp"])
    check("пустой вывод", N.parse_adapters("  ") == [])
    check("виртуальный адаптер отсеивается", N._is_virtual(ad[1]) and not N._is_virtual(ad[0]))

    s = N.build_set_script(ad[:1], N.PROVIDERS["cloudflare"])
    check("set-скрипт", 'Set-DnsClientServerAddress -InterfaceIndex 12 '
          '-ServerAddresses ("1.1.1.1","1.0.0.1")' in s and "Clear-DnsClientCache" in s, s)
    saved = [{"index": 12, "servers": ["192.168.1.1"], "dhcp": True},
             {"index": 5, "servers": ["9.9.9.9"], "dhcp": False}]
    r = N.build_restore_script(saved)
    check("restore: DHCP сбрасывается", "-InterfaceIndex 12 -ResetServerAddresses" in r, r)
    check("restore: статические возвращаются", '-InterfaceIndex 5 -ServerAddresses ("9.9.9.9")' in r, r)
    try:
        N.build_set_script(ad, ["1.1.1.1; calc"])
        check("инъекция в адрес отклонена", False)
    except N.NetFixError:
        check("инъекция в адрес отклонена", True)

    # apply/restore с подменой запуска и чтения
    state = {"dns": {12: ["192.168.1.1"]}}
    real = (N.current_dns, N._run_script)

    def fake_current():
        return [{"adapter": "Ethernet", "index": 12, "servers": state["dns"][12],
                 "dhcp": True, "description": "Realtek"}]
    scripts: list[str] = []

    def fake_run_ok(text):
        scripts.append(text)
        state["dns"][12] = (["1.1.1.1", "1.0.0.1"] if "ResetServer" not in text
                            and "1.1.1.1" in text else ["192.168.1.1"])
        return True, ""
    N.current_dns, N._run_script = fake_current, fake_run_ok
    bak = N._backup_path()
    try:
        res = N.apply("cloudflare")
        check("apply применился", res["applied"] and res["adapters"] == ["Ethernet"], str(res))
        check("бэкап создан", bak.is_file() and json.loads(bak.read_text("utf-8"))[0]["servers"]
              == ["192.168.1.1"])
        before = bak.read_text("utf-8")
        N.apply("google")
        check("бэкап не перезаписан", bak.read_text("utf-8") == before)
        res = N.restore()
        check("restore вернул и удалил бэкап", res["restored"] and not bak.exists()
              and "ResetServerAddresses" in scripts[-1], str(res))
        check("restore без бэкапа — ошибка словарём",
              not N.restore()["restored"] and N.restore()["error"])

        # отказ в UAC
        state["dns"][12] = ["192.168.1.1"]
        N._run_script = lambda text: (False, "запрос прав администратора отклонён")
        res = N.apply("quad9")
        check("отказ UAC: ошибка, без падения", not res["applied"] and "отклонён" in res["error"])
        check("отказ UAC: пустой бэкап не остаётся", not bak.exists())

        # скрипт «отработал», но DNS не поменялись
        N._run_script = lambda text: (True, "")
        res = N.apply("google")
        check("проверка результата после apply", not res["applied"], str(res))
        bak.unlink(missing_ok=True)

        try:
            N.apply("evil")
            check("неизвестный провайдер", False)
        except N.NetFixError:
            check("неизвестный провайдер", True)
    finally:
        N.current_dns, N._run_script = real
        bak.unlink(missing_ok=True)

    # диагностика на моках
    real_r, real_g = N._resolve, N._get
    N._resolve = lambda h: ["1.2.3.4"]

    def fake_get(url, timeout):
        if "thumbnails" in url:
            return json.dumps({"data": [{"imageUrl": "https://tr.rbxcdn.com/x.png"}]}).encode()
        return b"PNGDATA"
    N._get = fake_get
    try:
        d = N.diagnose()
        check("diagnose ok на моках", d["ok"] and d["details"][-1]["name"] == "картинка плейса", str(d))
        N._resolve = lambda h: (_ for _ in ()).throw(OSError("нет такого хоста")) if h.startswith("tr.") else ["1.2.3.4"]
        d = N.diagnose()
        check("diagnose видит сбой резолва", not d["ok"] and not d["details"][0]["ok"])
        N._resolve = lambda h: ["1.2.3.4"]
        N._get = lambda url, timeout: (_ for _ in ()).throw(OSError("таймаут"))
        d = N.diagnose()
        check("diagnose видит сбой загрузки", not d["ok"] and not d["details"][-1]["ok"])
    finally:
        N._resolve, N._get = real_r, real_g


def test_updates() -> None:
    print("updates")
    check("1.10.0 > 1.9.0", U.is_newer("1.10.0", "1.9.0"))
    check("1.6.0 не новее 1.6.0", not U.is_newer("1.6.0", "1.6.0"))
    check("1.6 == 1.6.0", not U.is_newer("1.6", "1.6.0") and not U.is_newer("1.6.0", "1.6"))
    check("1.6.1 > 1.6", U.is_newer("1.6.1", "1.6"))
    real = U._get
    try:
        U._get = lambda url, timeout: json.dumps(
            {"version": "1.7.0", "url": "https://x.test/d", "notes": "n"}).encode()
        r = U.check(current="1.6.0")
        check("новая версия", r == {"version": "1.7.0", "url": "https://x.test/d", "notes": "n"}, str(r))
        check("та же версия — None", U.check(current="1.7.0") is None)
        U._get = lambda url, timeout: json.dumps({"version": "1.8.0", "url": "http://evil"}).encode()
        r = U.check(current="1.6.0")
        check("не-https ссылка заменена", r and r["url"].startswith("https://"), str(r))
        U._get = lambda url, timeout: b"{not json"
        check("битый JSON — None", U.check(current="1.0.0") is None)
        U._get = lambda url, timeout: b'{"nope": 1}'
        check("нет поля version — None", U.check(current="1.0.0") is None)

        def boom(url, timeout):
            raise OSError("нет сети")
        U._get = boom
        check("ошибка сети — None", U.check(current="1.0.0") is None)
    finally:
        U._get = real
    try:
        real("http://insecure.test/x", 1)
        check("http отклоняется", False)
    except ValueError:
        check("http отклоняется", True)


def main() -> int:
    test_maintenance()
    test_netfix()
    test_updates()
    _TMP.cleanup()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
