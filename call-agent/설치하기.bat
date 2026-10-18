@echo off
cd /d "%~dp0"
title Setup
echo ==================================================
echo   CallAgent setup (first time only, 3-10 minutes)
echo ==================================================
if exist "%~dp0python\python.exe" goto install
echo.
echo [1/3] Downloading Python (about 40MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/astral-sh/python-build-standalone/releases/download/20241206/cpython-3.12.8+20241206-x86_64-pc-windows-msvc-install_only.tar.gz' -OutFile '%~dp0py.tar.gz'"
if not exist "%~dp0py.tar.gz" goto fail
tar -xzf "%~dp0py.tar.gz" -C "%~dp0."
del "%~dp0py.tar.gz"
if not exist "%~dp0python\python.exe" goto fail

:install
echo.
echo [2/3] Installing libraries...
"%~dp0python\python.exe" -m pip install --disable-pip-version-check --no-warn-script-location -r "%~dp0requirements.txt"
if errorlevel 1 goto fail
echo.
echo [3/3] Preparing...
"%~dp0python\python.exe" -m callagent.installer
pause
exit /b

:fail
echo.
echo [!] Setup failed. Please take a screenshot of this window and send it.
pause
