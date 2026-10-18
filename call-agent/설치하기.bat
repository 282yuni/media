@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 전화상담 설치
echo ===============================================
echo   전화상담 프로그램 설치 (처음 한 번만)
echo ===============================================
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python 이 없습니다. https://www.python.org/downloads/ 에서 설치하세요.
  echo     설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
  start https://www.python.org/downloads/
  pause
  exit /b
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [ ] ffmpeg 설치 중...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
)
echo [ ] 필요한 프로그램 설치 중... (몇 분 걸려요)
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if not exist config.yaml copy config.example.yaml config.yaml >nul
if not exist scenarios.yaml copy scenarios.example.yaml scenarios.yaml >nul
if not exist data mkdir data
python main.py desktop
echo.
echo 설치 끝! 바탕화면의 "전화상담" 을 더블클릭하세요.
pause
