@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 전화상담
rem 쓰는 프로필 (profiles 폴더 이름). 치과 기본 설정을 쓰려면 비워 두세요: set PROFILE=
set PROFILE=임플란트
set P=
if not "%PROFILE%"=="" set P=--profile %PROFILE%

:menu
cls
echo ===============================================
echo   전화상담   (프로필: %PROFILE%)
echo ===============================================
echo   1. 점검하기          (준비가 됐는지 확인)
echo   2. 폰 연결 설정      (USB 로 꽂은 폰 찾기)
echo   3. 내 녹음 넣기      (녹음 파일을 문장별로 자르기)
echo   4. 연습하기          (전화 없이 타이핑으로)
echo   5. 고객에게 전화 시작 (1번 폰)
echo   6. 고객에게 전화 시작 (2번 폰)
echo   7. 아무 번호로 걸기
echo   8. 녹음 대본 보기
echo   0. 끝내기
echo.
set /p C=번호를 누르고 Enter: 
if "%C%"=="1" python main.py %P% doctor & pause & goto menu
if "%C%"=="2" python main.py phones & pause & goto menu
if "%C%"=="3" goto clips
if "%C%"=="4" python main.py %P% practice --voice & pause & goto menu
if "%C%"=="5" python main.py %P% next & pause & goto menu
if "%C%"=="6" python main.py --config config2.yaml %P% next & pause & goto menu
if "%C%"=="7" goto dial
if "%C%"=="8" start notepad "profiles\%PROFILE%\녹음대본.txt" & goto menu
if "%C%"=="0" exit /b
goto menu

:clips
echo 녹음 파일을 이 창으로 끌어다 놓고 Enter 를 누르세요.
set /p F=파일: 
python main.py %P% clips %F%
pause
goto menu

:dial
set /p N=걸 번호: 
set /p B=통화 목적 (없으면 Enter): 
python main.py %P% dial %N% --brief "%B%"
pause
goto menu
