@echo off
cd /d "%~dp0\.."
echo Starting SmartTrader Pro Autonomous Bot...
.\venv\Scripts\python.exe auto_bot.py
pause
