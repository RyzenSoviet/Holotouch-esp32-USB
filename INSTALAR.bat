@echo off
title HOLOTOUCH V7 - Instalador
cd /d "%~dp0"
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
echo.
echo Instalacion terminada.
pause
