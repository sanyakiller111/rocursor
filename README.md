# sanyakiller111

Кастомизация Roblox для Windows: курсоры, shiftlock, skybox, текстуры,
звуки и шрифты. Выбрал, нажал «Применить» — готово. «Вернуть оригинал»
возвращает всё как было.

Программа сама находит установленный Roblox и пишет файлы прямо в папку
его версии. Оригиналы перед заменой сохраняются в бэкап. Все ресурсы
вшиты в программу и работают без интернета.

## Что умеет

- **Курсоры** — 500 штук: 28 своих и 472 с osuskinner.com.
- **Shiftlock** — 222 прицела и конструктор: 13 форм, размер, толщина,
  зазор, поворот, цвет, обводка, свечение, пресеты.
- **Skybox** — 34 неба: 6 нарисованы кодом, 28 панорам Poly Haven.
- **Текстуры** — гладкий или тёмный пластик, без студов, спокойная вода.
- **Звуки и шрифты** — 37 CC0-звуков (смерть, прыжок, шаги, меню) и
  9 OFL-шрифтов для интерфейса Roblox.
- **Своё** — курсор, shiftlock или skybox из любой картинки.
- **Config** — помнит выбранное; после обновления Roblox при запуске
  ставит всё обратно само.
- **FPS буст** — только разрешённые Roblox FastFlags, лимит кадров и
  качество графики из меню игры; мощная видеокарта и режим
  «Высокая производительность» в Windows. Всё откатывается.
- **Лучший сервер** — по ссылке на игру показывает серверы и заходит на
  тот, где пинг у игроков ниже.
- **Фиксы** — не грузятся картинки (публичный DNS с откатом), чистка
  мусора Roblox, «вернуть всё как было», проверка обновлений.

## Чего не делает

Не просит логин Roblox, не читает cookies и токены, не меняет `.exe`, не
инжектится в Roblox, не работает в фоне и не собирает телеметрию. В
интернет ходит только «Лучший сервер» — к открытому списку серверов
Roblox, без авторизации.

Подробно — в [`docs/SECURITY.md`](docs/SECURITY.md), там же как проверить exe.

## Запуск из исходников

Нужен Python 3.10+ и Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m cursor_manager
```

## Сборка exe

Нужен ещё Inno Setup 6 — без него сборка остановится с понятной ошибкой.

```powershell
winget install -e --id JRSoftware.InnoSetup
.\build.bat
```

| Что получится | Где |
|---|---|
| готовая программа одним файлом | `sanyakiller111.exe` в корне |
| установщик | `dist\sanyakiller111-Setup-<версия>.exe` |
| архив исходников и контрольные суммы | `dist\` |

Без цифровой подписи Windows SmartScreen может предупредить при первом
запуске. Подробности — в [`docs/BUILD.md`](docs/BUILD.md).

## Проверки

Тесты — обычные скрипты, pytest не нужен. Реальную папку Roblox они не
трогают, всё происходит во временной папке.

```powershell
$env:PYTHONIOENCODING='utf-8'
Get-ChildItem tests\test_*.py | ForEach-Object { .\.venv\Scripts\python.exe $_.FullName }
```

## Устройство

```
src/cursor_manager/   программа (python -m cursor_manager)
  app.py              окно, меню, общий стиль
  ui/                 страницы: библиотека, конструктор, FPS, серверы, фиксы, config
  core/               работа с диском Roblox: пути, бэкап, установка, флаги
  content/            ресурсы и генераторы: курсоры, прицелы, небо, звуки, шрифты
assets/               вшитые ресурсы и иконка
build/                сборка: build.py, cursor_manager.spec, installer.iss
build.bat             запуск сборки
tests/                проверки
tools/make_assets.py  генерация своих курсоров и иконки (сборка зовёт сама)
```

## Ресурсы и лицензии

Код — [MIT](LICENSE). Свои курсоры и небо — CC0-1.0, панорамы Poly Haven —
CC0, звуки Kenney — CC0, шрифты — SIL OFL. Курсоры osu! принадлежат их
авторам с osuskinner.com; ссылка на источник каждого — в
`assets/cursors/manifest.json`.

## Контакты

[Telegram](https://t.me/sanyakiller111) ·
[TikTok](https://tiktok.com/@sanyakiller111_robloxer) ·
[YouTube](https://youtube.com/@sanyakiller111_robloxer)
