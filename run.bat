@echo off
echo Starting SmartTrader Pro Components...
echo.

echo Launching Sentiment Server...
start "Sentiment Server" scripts\run_sentiment_server.bat

echo Launching Autonomous Bot...
start "AutoBot" scripts\run_autobot.bat

echo Launching GUI Dashboard...
start "Dashboard" scripts\run_gui.bat

echo.
echo All components have been launched in separate windows!
echo You can close this window now.
pause
