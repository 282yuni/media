@echo off
cd /d "%~dp0"
title CallAgent
python main.py menu
if errorlevel 1 pause
