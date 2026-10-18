@echo off
cd /d "%~dp0"
title Setup
python --version >nul 2>nul
if errorlevel 1 goto nopython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython
python -m callagent.installer
pause
exit /b

:nopython
echo.
echo [!] Python is not installed.
echo     1) https://www.python.org/downloads/  -  Download Python
echo     2) Check "Add python.exe to PATH" on the first screen
echo     3) Run this file again
start https://www.python.org/downloads/
pause
