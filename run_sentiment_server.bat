@echo off
SETLOCAL EnableDelayedExpansion

echo ─────────────────────────────────────────────────────────────────────────────
echo   SmartTrader - Centralized Sentiment Server (FastAPI + FinBERT)
echo ─────────────────────────────────────────────────────────────────────────────

:: Port to use
set PORT=8005

:: Check for existing process on the port
echo [*] Checking for existing process on port %PORT%...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT% ^| findstr LISTENING') do (
    echo [!] Found existing process with PID %%a on port %PORT%.
    echo [*] Terminating process...
    taskkill /F /PID %%a
    timeout /t 2 >nul
)

:: Ensure log directory exists
if not exist "logs" mkdir logs

echo [*] Starting Sentiment Server on port %PORT%...
echo [*] Initializing FinBERT (this may take 10-20 seconds on first run)...
echo [*] Activity is being logged to: logs\sentiment_server.log

:: Start the server
.\venv\Scripts\python sentiment_server.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Server failed to start.
    pause
)

ENDLOCAL
