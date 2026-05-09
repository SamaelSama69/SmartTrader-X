# SmartTrader Pro 🇮🇳

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**SmartTrader Pro** is an autonomous, production-grade algorithmic trading platform specifically hardened for the Indian Equity Markets (NSE/BSE).

Powered by advanced regime-aware momentum strategies, dynamic position sizing (Kelly Criterion), and multi-tiered sentiment analysis, SmartTrader Pro seamlessly moves from research to real-time execution via the Shoonya API.

---

## 🚀 Features

*   **Regime-Aware Trading:** Automatically adapts trading parameters based on current market conditions (Bull/Bear, High/Low Volatility) using standard deviation and moving average metrics.
*   **Dynamic Risk Management:** Automatically calculates position sizes using a robust Dynamic Kelly Criterion implementation.
*   **Circuit Breaker Protection:** Incorporates mandatory pre-flight circuit breaker checks, preventing order placements if a stock is trading within 0.5% of its circuit limits.
*   **Sentiment Failover Engine:** Tri-layer NLP sentiment analysis pipeline using News API, local FinBERT, and keyword fallback parsing.
*   **Earnings & Holiday Safety:** Detects NSE trading holidays and automatically scales down position sizes by 20% during earnings seasons to protect against unpredictable gap volatility.
*   **Fully Autonomous AutoBot:** A background trading engine that manages entry/exit conditions, performs EOD square-offs by 3:15 PM IST for intraday strategies, and continuously monitors live portfolio PnL.
*   **Interactive Dashboard:** A responsive Streamlit-based UI that provides a live Strategy Scanner, Backtesting Lab, and real-time Shoonya order tracking.

---

## 📁 Repository Structure

The project has been organized to keep the root directory clean while providing extensive documentation and scripts.

```text
SmartTrader/
├── docs/                      # Comprehensive Guides & Documentation
│   ├── AUTO_TRADING_GUIDE.md  # AutoBot configuration and operations
│   ├── BEGINNER_API_SETUP.md  # How to obtain API keys (Shoonya, News, etc.)
│   ├── COMPREHENSIVE_GUIDE.md # Deep dive into the architecture
│   ├── EXAMPLES.md            # Strategy code examples
│   └── INDIAN_TRADING_GUIDE.md# Indian Market specific rules (STT, Slippage)
├── scripts/                   # Helper scripts
│   ├── run_autobot.bat        # Launch the autonomous bot
│   ├── run_gui.bat            # Launch the Streamlit dashboard
│   └── run_sentiment_server.bat # Launch local FinBERT server
├── strategies/                # Core trading algorithms
├── utils/                     # Modules: Risk, Broker, Fetchers, Backtester
├── run.bat                    # Master entry point script
├── auto_bot.py                # Main headless trading loop
├── dashboard_v2.py            # Streamlit dashboard interface
└── config.py                  # Environment config
```

---

## 🛠️ Quick Start

### 1. Requirements

*   **Python 3.10+**
*   API Keys (Optional but recommended for live trading): Shoonya Broker, NewsAPI, Finnhub.

### 2. Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/SamaelSama69/SmartTrader-X.git
cd SmartTrader-X

# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install core and ML dependencies
pip install -r requirements.txt
pip install -r requirements-ml.txt
```

### 3. Configuration

Rename `.env.example` to `.env` and fill in your credentials.

```env
# Required for Live Execution
SHOONYA_USER_ID=your_id
SHOONYA_PASSWORD=your_password
SHOONYA_TOTP_KEY=your_totp_secret
SHOONYA_VENDOR_CODE=your_vendor_code
SHOONYA_API_KEY=your_api_key

# Required for Sentiment
NEWS_API_KEY=your_news_key
FINNHUB_API_KEY=your_finnhub_key
```

### 4. Running the Platform

Use the master script `run.bat` to launch the platform:

```bash
# Launch the main Streamlit Dashboard
run.bat

# Alternatively, launch components via the scripts directory:
scripts\run_gui.bat
scripts\run_autobot.bat
scripts\run_sentiment_server.bat
```

---

## 📚 Documentation

Detailed documentation is available in the `docs/` folder:

*   [Beginner API Setup](docs/BEGINNER_API_SETUP.md) — Step-by-step API integration.
*   [Indian Market Guide](docs/INDIAN_TRADING_GUIDE.md) — Slippage modeling, STT, and costs.
*   [Auto-Trading Guide](docs/AUTO_TRADING_GUIDE.md) — Operating the headless AutoBot.
*   [System Architecture](docs/COMPREHENSIVE_GUIDE.md) — Complete overview of engine logic.

---

## 🧪 Testing

The repository maintains an extensive test suite ensuring mission-critical paths (circuit breakers, regime logic, dynamic Kelly) are stable.

```bash
# Run all tests
pytest tests/ -v
```

---

## 🛡️ Disclaimer
**For Educational and Research Purposes Only.**
Algorithmic trading involves significant risk. The authors and contributors are not responsible for any financial losses incurred through the use of this software. Always test strategies thoroughly in the **Testing Lab** before deploying live capital.
