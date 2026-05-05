@echo off
title Jarfish Telegram Bot
cd /d "%~dp0"
:loop
echo [%date% %time%] Starting Jarfish...
python jarvis_bot.py
echo [%date% %time%] Jarfish stopped (exit code %ERRORLEVEL%). Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
