@echo off
cd /d "%~dp0"
title CallAgent
set PY=python
if exist "%~dp0..\python\python.exe" set PY="%~dp0..\python\python.exe"
if exist "%~dp0python\python.exe" set PY="%~dp0python\python.exe"
%PY% main.py menu
if errorlevel 1 pause
