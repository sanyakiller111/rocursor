@echo off
rem build.bat - entry point of the build pipeline, run from the project root.
rem ASCII only on purpose: cmd.exe parses .bat in the OEM code page, a UTF-8
rem BOM breaks @echo off. Russian output goes through PYTHONIOENCODING=utf-8.
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"

echo [build.bat] python = %PY%
"%PY%" build\build.py %*
set "EC=%errorlevel%"
if not "%EC%"=="0" echo [build.bat] build failed, exit code %EC%
if "%EC%"=="0" echo [build.bat] READY: %~dp0sanyakiller111.exe
if "%~1"=="" pause
exit /b %EC%
