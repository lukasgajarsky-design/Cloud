@echo off
rem Installs the remixer on Windows: FFmpeg and Node.js via winget, then .venv with Demucs and the analysis libraries.
rem Double-click it, or run it from Command Prompt. Safe to run again.
rem Exit codes are checked with "neq 0" because winget fails with negative codes, which "if errorlevel 1" misses.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo.
echo === Claude Strudel Remixer: inštalácia ===
echo.

where /q uv
if %errorlevel% neq 0 goto :no_uv

set "RESTART="
where /q ffmpeg
if %errorlevel% neq 0 call :winget_install FFmpeg Gyan.FFmpeg
if %errorlevel% neq 0 goto :fail
where /q node
if %errorlevel% neq 0 call :winget_install Node.js OpenJS.NodeJS.LTS
if %errorlevel% neq 0 goto :fail
if defined RESTART goto :restart

rem PyTorch, sphn and soxr have no Windows on ARM builds, so use x64 Python there (Windows runs it in emulation)
set "PYTHON=3.12"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PYTHON=cpython-3.12-windows-x86_64-none"

rem uv downloads Python 3.12 if needed; --seed adds pip, which setup_and_verify.py uses
if exist ".venv\Scripts\python.exe" goto :setup
uv venv --python %PYTHON% --seed .venv
if %errorlevel% neq 0 goto :fail

:setup
".venv\Scripts\python.exe" setup_and_verify.py
if %errorlevel% neq 0 goto :fail

echo.
echo Hotovo. Skopíruj skladbu do priečinka input, napríklad input\moja-skladba.wav,
echo otvor tento priečinok v Claude Code a napíš: Remixni input/moja-skladba.wav
echo.
pause
exit /b 0

:winget_install
echo %1 chýba, inštalujem cez winget...
where /q winget
if %errorlevel% neq 0 goto :no_winget
winget install -e --id %2 --accept-source-agreements --accept-package-agreements
if %errorlevel% neq 0 goto :winget_failed
set "RESTART=1"
exit /b 0

:no_winget
echo Chýba winget. Nainštaluj %1 ručne a spusti install.bat znova.
exit /b 1

:winget_failed
echo winget skončil s chybou. Ak už je %1 nainštalovaný, zatvor toto okno a spusti install.bat znova.
exit /b 1

:no_uv
echo Chýba uv. Spusti v Command Prompte tento príkaz, potom otvor nové okno a spusti install.bat znova:
echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
goto :fail

:restart
echo.
echo Nainštalované. Zatvor toto okno a spusti install.bat znova, aby Windows načítal nové programy.
echo.
pause
exit /b 0

:fail
echo.
echo Inštalácia sa nedokončila, chyba je vypísaná vyššie.
echo.
pause
exit /b 1
