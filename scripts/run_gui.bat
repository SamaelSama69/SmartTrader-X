@echo off
cd /d "%~dp0\.."
echo Starting SmartTrader Pro Dashboard...
.\venv\Scripts\python.exe -m streamlit run dashboard_v2.py
pause
