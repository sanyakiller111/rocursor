; ─────────────────────────────────────────────────────────────────────────────
; installer.iss — установщик Inno Setup 6
;
; Собирается:  iscc /DAppVersion=1.7.0 /DAppSlug=sanyakiller111 /DAppExe=<путь к exe> installer.iss
; (обычно через  build.bat)
;
; Порядок подписи: .exe подписывается ДО сборки установщика. Inno встраивает
; файлы на этапе компиляции, поэтому подпись должна уже быть на месте.
; Сам установщик подписывается после сборки — это делает build.py.
; ─────────────────────────────────────────────────────────────────────────────

#ifndef AppVersion
  #define AppVersion "1.7.0"
#endif
#ifndef AppExe
  #define AppExe "..\sanyakiller111.exe"
#endif
#ifndef AppSlug
  #define AppSlug "sanyakiller111"
#endif

#define AppName        "sanyakiller111"
#define AppPublisher   "sanyakiller111"
#define AppURL         "https://github.com/sanyakiller111/sanyakiller111-cursor-manager"
#define AppExeName     AppSlug + ".exe"

[Setup]
; AppId зафиксирован: он совпадает с прежним (Cursor Manager), поэтому новый
; установщик обновляет старую установку, а не ставит вторую копию.
; Не менять никогда.
AppId={{7C4E9A21-3B6F-4D18-9E52-A1C7D0F5B834}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppSlug}
; Прежняя установка жила в Programs\sanyakiller111-cursor-manager; Inno сам
; подхватит каталог по AppId (UsePreviousAppDir=yes по умолчанию).
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#AppSlug}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Подпись: задаётся переменной SignTool при локальной сборке.
; Пустое значение = установщик собирается неподписанным, что работает.
#ifdef SignTool
SignTool={#SignTool}
SignedUninstaller=yes
#endif
; Установка per-user в %LOCALAPPDATA%\Programs — не требует прав администратора
; и не пишет в Program Files. Для одиночной утилиты это правильный выбор.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; В Default.isl нет cm:CreateStartMenuIcon — объявляем своё, по языкам.
[CustomMessages]
CreateStartMenuIcon=Startup shortcuts
english.CreateStartMenuIcon=Startup shortcuts
russian.CreateStartMenuIcon=Ярлыки в меню «Пуск»

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; "checked"-флага нет: задача по умолчанию уже включена, checked запрещён
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "{cm:CreateStartMenuIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; onefile: в установщик кладётся тот же sanyakiller111.exe, что лежит в корне проекта
Source: "{#AppExe}"; DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion

[InstallDelete]
; Обновление поверх Cursor Manager 1.5.x (onedir): убираем старый exe, папку
; _internal и прежнюю группу меню «Пуск», чтобы не оставалось мусора.
Type: files; Name: "{app}\sanyakiller111-cursor-manager.exe"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{autoprograms}\sanyakiller111 Cursor Manager"

[Registry]
; ─────────────────────────────────────────────────────────────────────────────
; Ассоциация .rcur.
;
; Смысл: Roblox после обновления создаёт новую папку version-… и стирает
; подменённые текстуры. Сохранённый набор — ручной якорь. Пользователь
; дважды кликает по файлу, и всё возвращается без открытия окна.
;
; HKCR — это объединение HKLM\Software\Classes и HKCU\Software\Classes.
; При PrivilegesRequired=lowest запись идёт в ветку пользователя, установщик
; не просит права администратора.
;
; ProgId описывает ProgId целиком: расширение + команда открытия + иконка.
; ─────────────────────────────────────────────────────────────────────────────
Root: HKA; Subkey: "Software\Classes\.rcur"; ValueType: string; ValueName: ""; ValueData: "RcurFile"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.rcur"; ValueType: string; ValueName: "Content Type"; ValueData: "application/x-rcur"; Flags: uninsdeletekey

Root: HKA; Subkey: "Software\Classes\RcurFile"; ValueType: string; ValueName: ""; ValueData: "Набор курсоров Roblox"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\RcurFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Flags: uninsdeletekey
; -1 = SW_SHOWNORMAL, без консольного окна
Root: HKA; Subkey: "Software\Classes\RcurFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" --apply ""%1"""; Flags: uninsdeletekey

[Icons]
; Группа Пуск целиком управляется задачей startmenuicon: снятая галочка =
; не осталось ярлыков программы в меню Пуск (uninstaller запускается файлом).
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startmenuicon
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
; Пункт, который говорит пользователю про ассоциацию прямо в меню Пуск
Name: "{group}\Как вернуть курсор после обновления Roblox"; Filename: "{app}\{#AppExeName}"; Tasks: startmenuicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; ─────────────────────────────────────────────────────────────────────────────
; Проверку целостности здесь намеренно нет.
;
; Inno не умеет SHA-256, а подделка проверки хуже её отсутствия: она создаёт
; у пользователя ложное чувство проверенности. Целостность обеспечивается в
; другом месте:
;   • SHA256SUMS рядом с релизом — сверяется вручную (sha256sum SHA256SUMS)
;   • подпись Authenticode на .exe и на установщике — проверяется Windows
;   • открытый исходник — сборку можно повторить и сравнить хеш
; ─────────────────────────────────────────────────────────────────────────────