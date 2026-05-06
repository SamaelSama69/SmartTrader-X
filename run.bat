@echo off
echo Starting SmartTrader Dashboard...
echo.

REM Activate virtual environment if it exists
if exist venv\Scripts\activate (
    call venv\Scripts\activate
    echo Virtual environment activated.
) else (
    echo Warning: Virtual environment not found. Using system Python.
)

REM Check if streamlit is installed
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo Streamlit not found. Installing...
    pip install streamlit pandas yfinance plotly requests python-dotenv
)

REM Run the dashboard
echo Starting Streamlit dashboard...
streamlit run dashboard.py
if errorlevel 1 (
    echo Streamlit failed, trying via python module...
    python -m streamlit run dashboard.py
)

pause
