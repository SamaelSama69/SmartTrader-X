# SmartTrader — Gemini CLI Work Plan

This file is your persistent instruction set. Read it at the start of every session.
Work through tasks in order. Do not skip ahead. After each task, run its verify step
before moving on. If a verify step fails, fix the issue before proceeding.

Follow the coding rules in `CLAUDE.md` at all times:
- Touch only what the task requires. Do not refactor adjacent code.
- Write the minimum code that makes the verify step pass.
- If anything is ambiguous, stop and ask rather than guessing.

---

## How to read this file

Each task is structured as:

```
### TASK-N: Short title
**File(s):** which files to touch
**Problem:** what is wrong
**Fix:** exactly what to do
**Verify:** the command to run to confirm it is done
```

A task is complete only when its verify command passes without errors.

---

## Completed Tasks ✅

- [x] TASK-1  Remove debug print statements from `strategies/stocks.py`
- [x] TASK-2  Fix CRLF line endings in `auto_bot.py`, `dashboard_v2.py`, `shoonya_broker.py`
- [x] TASK-3  Create `requirements-ml.txt`, move `vectorbt` out of core requirements
- [x] TASK-4  Suppress benign OpenVINO CISA warnings, document in README
- [x] TASK-5  Add Shoonya keys to `test_env_example_completeness`
- [x] TASK-6  Fix Zerodha → Shoonya references in README and INDIAN_TRADING_GUIDE.md
- [x] TASK-7  Update README project structure diagram to match actual files
- [x] TASK-8  Wire `SEBIComplianceManager` into `auto_bot.py` order flow
- [x] TASK-9  Wire `Notifier` (Telegram) into `auto_bot.py` trade events
- [x] TASK-10 Create `tests/test_auto_bot.py` with 4 tests
- [x] TASK-11 Create `tests/test_startup_smoke.py` with 8 smoke tests
- [x] TASK-12 Run full suite, fix all remaining failures
- [x] TASK-13 Fix contrarian score formula and wire it into entry decisions
- [x] TASK-14 Fix Dashboard Bot Status heartbeat check
- [x] TASK-15 Fix `[Errno 22]` absolute path handling in model loading
- [x] TASK-16 Centralize Sentiment Analysis via FastAPI Server
- [x] TASK-17 Fix Server Deprecations & Port Conflicts
- [x] TASK-18 Create Dedicated Server Startup Script
- [x] TASK-19 Implement Timed Log Rotation
- [x] TASK-20 Enable Persistent Server Logging
- [x] TASK-21 Add Manual Data Refresh Button to Dashboard

---

### TASK-21: Add Manual Data Refresh Button to Dashboard
**File:** `dashboard_v2.py`
**Problem:** Dashboard data (prices, sentiment) could stay cached for up to 15 minutes, preventing users from seeing immediate changes.
**Fix:** Added a "Refresh Market Data 🔄" button to the sidebar that clears Streamlit's data cache (`st.cache_data.clear()`).
**Verify:** Click the button in the dashboard; confirm a "Cache cleared" message appears and data reloads.

### TASK-19: Implement Timed Log Rotation
**File:** `config.py`
**Problem:** Main application logs were growing indefinitely without rotation.
**Fix:** Implemented `TimedRotatingFileHandler` set to daily rotation with 7 days of retention.
**Verify:** Check `logs/smart_trader.log` exists; older files will appear as `.log.YYYY-MM-DD`.

### TASK-20: Enable Persistent Server Logging
**File:** `sentiment_server.py`, `run_sentiment_server.bat`
**Problem:** Sentiment Server activity was only visible in its terminal, making history audits difficult.
**Fix:** Added an internal rotating file handler to `sentiment_server.py` that writes to `logs/sentiment_server.log`.
**Verify:** Run the server and confirm `logs/sentiment_server.log` contains initialization and analysis details.

---

### TASK-17: Fix Server Deprecations & Port Conflicts
**File:** `sentiment_server.py`, `utils/multilingual_sentiment.py`
**Problem:** 
1. `on_event` was deprecated in FastAPI.
2. `[Errno 10048]` occurred if port 8005 was already bound.
3. `[Errno 22]` persisted due to absolute path handling in Windows.
**Fix:** 
- Migrated to `lifespan` async handler in FastAPI.
- Switched to relative paths for model loading to avoid drive letter colons in HF cache logic.
- Implemented automatic port cleanup in the startup script.

### TASK-18: Create Dedicated Server Startup Script
**File:** `run_sentiment_server.bat`
**Problem:** Manual startup was error-prone and didn't handle process cleanup.
**Fix:** Created a professional batch file that terminates old PIDs on port 8005 and initializes the venv environment.
**Verify:** Run `run_sentiment_server.bat` and check `http://127.0.0.1:8005/health`.

---

### TASK-14: Fix Dashboard Bot Status heartbeat check
**File:** `dashboard_v2.py`
**Problem:** Bot status in sidebar was hardcoded to "RUNNING".
**Fix:** Implemented heartbeat logic checking `memory/latest_scan_results.json` timestamp and mtime.
**Verify:** Stop `auto_bot.py` and confirm dashboard shows "OFFLINE" after 20 mins.

### TASK-15: Fix `[Errno 22]` absolute path handling
**File:** `utils/multilingual_sentiment.py`
**Problem:** OpenVINO loader incorrectly parsed Windows absolute paths as repo IDs.
**Fix:** Added `local_files_only=True` when loading from local model directory.
**Verify:** Logs should no longer show `Errno 22` or `hub\models--C:` errors.

### TASK-16: Centralize Sentiment Analysis via FastAPI Server
**Files:** `sentiment_server.py`, `utils/multilingual_sentiment.py`, `requirements.txt`
**Problem:** Bot and Dashboard ran redundant heavy ML models, consuming double memory/iGPU.
**Fix:** Created `sentiment_server.py` and updated engine to use REST API.
**Verify:** `python sentiment_server.py` runs, and Bot/GUI analyze news without loading local weights.
