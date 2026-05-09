# Indian Trading Guide for SmartTrader

> **Note:** This guide was written for Zerodha/Kite. The codebase has since
> migrated to **Shoonya (Finvasia)** via `utils/shoonya_broker.py`. Zerodha
> support may be added in future. For Shoonya setup, see `.env.example`.

Complete guide to using SmartTrader for Indian stock markets (NSE/BSE).

## Setting Up Zerodha API

Zerodha is India's leading stock broker and provides API access for automated trading.

### Step 1: Get Zerodha Account

- Sign up at https://zerodha.com/ if you don't have an account
- Complete KYC and account activation (takes 1-2 working days)
- Subscribe to API access: https://kite.zerodha.com/api (₹2000/year)

### Step 2: Generate API Keys

1. Log in to Kite: https://kite.zerodha.com
2. Go to Profile → API Keys
3. Click "Create New App"
4. Fill in details:
   - App Name: SmartTrader
   - App Type: Web App
   - Redirect URL: http://localhost:8501
5. Note down the API Key and API Secret

### Step 3: Configure in SmartTrader

Create or edit `.env` file:

```env
ZERODHA_API_KEY=your_api_key_here
ZERODHA_API_SECRET=your_api_secret_here
ZERODHA_REDIRECT_URL=http://localhost:8501
```

### Step 4: Generate Access Token

Run the Zerodha login script (create `zerodha_login.py`):

```python
import kiteconnect
from kiteconnect import KiteConnect

api_key = "your_api_key"
api_secret = "your_api_secret"

kite = KiteConnect(api_key=api_key)
print(kite.login_url())
# Open this URL in browser, login, copy request_token from redirect URL
request_token = input("Enter request_token: ")
data = kite.generate_session(request_token, api_secret)
print("Access Token:", data["access_token"])
```

Add the access token to `.env`:

```env
ZERODHA_ACCESS_TOKEN=your_access_token
```

## Indian Market Trading Hours

### Regular Trading Hours (NSE/BSE)

| Session | Time (IST) | Notes |
|---------|------------|-------|
| Pre-Market | 09:00 AM - 09:15 AM | Order placement only |
| Normal Market | 09:15 AM - 03:30 PM | Main trading session |
| Post-Market | 03:30 PM - 04:00 PM | After-hours trading |

### Commodity Trading Hours (MCX)

| Session | Time (IST) |
|---------|------------|
| Morning | 10:00 AM - 05:00 PM |
| Evening | 05:00 PM - 11:55 PM |

### Currency Trading Hours (NSE CDS)

09:00 AM - 05:00 PM

**Note**: Markets are closed on weekends and national holidays.

## Understanding F&O (Futures and Options) in India

### Futures (FUT)

- Agreement to buy/sell stock at predetermined price on expiry
- Margin required (typically 10-20% of contract value)
- Daily mark-to-market (M2M) settlement
- Expiry: Last Thursday of the month

### Options (OPT)

- Right (not obligation) to buy (Call) or sell (Put) at strike price
- Pay premium upfront (no margin needed for buyers)
- Sellers require margin
- Expiry: Last Thursday of the month

### Lot Sizes (Example)

| Stock | Lot Size | Example Price (₹) |
|-------|----------|-------------------|
| Reliance | 250 | 2500 |
| TCS | 100 | 4000 |
| Infosys | 300 | 1500 |

### Key Terms

- **Strike Price**: Price at which option can be exercised
- **Premium**: Price paid for buying option
- **ITM (In the Money)**: Option has intrinsic value
- **OTM (Out of the Money)**: Option has no intrinsic value
- **ATM (At the Money)**: Strike price ≈ current market price

## Thursday Expiry Strategies

Weekly options expire every Thursday, monthly options expire on last Thursday.

### Strategy 1: Expiry Day Range Trading

- Trade the range between support and resistance
- Use 15-minute charts for entry/exit
- Set tight stop-loss (1-2%)

### Strategy 2: Theta Decay Strategy (Selling Options)

- Sell OTM options on Tuesday/Wednesday
- Benefit from time decay (theta) as expiry approaches
- Requires strict stop-loss

### Strategy 3: Straddle/Strangle for Events

- Buy Call + Put of same strike (Straddle) before major events
- Profit from high volatility regardless of direction
- Exit before expiry to avoid time decay

### SmartTrader Features for Expiry

1. Check "Thursday Expiry" section in dashboard
2. View support/resistance levels
3. Get sentiment-based recommendations
4. Automatic stop-loss calculator

## Budget Day Trading (India)

Budget day (usually February 1) sees high volatility.

### Preparation

1. Check pre-budget sentiment (run SmartTrader analysis)
2. Avoid holding large F&O positions overnight before budget
3. Keep cash ready for opportunities

### Budget Day Strategies

#### Strategy 1: Volatility Play

- Buy Straddle (Call + Put) early morning
- Exit by 12 PM as volatility settles
- Works if market moves >2% in either direction

#### Strategy 2: Sector-Specific Trading

- Watch for budget announcements on sectors
- Green energy, infra, defense often get budget boost
- Use SmartTrader sentiment analysis for sector stocks

#### Strategy 3: Avoid Until Clarity

- Wait for budget speech to end (typically 1-2 PM)
- Trade the trend after clarity emerges
- Use tight stop-losses

### SmartTrader Budget Features

- Budget sentiment tracker
- Sector-wise impact analysis
- Real-time news sentiment during speech
- Automatic volatility alerts

## Important Regulations

### SEBI Margin Rules

- Intraday: 50% margin for cash, 20% for F&O
- Delivery: 100% margin (no leverage)
- Peak margin penalty for brokers

### Taxation

- Short-term capital gains (STCG): 15% for F&O, 15% for stocks held <1 year
- Long-term capital gains (LTCG): 10% for stocks held >1 year (above ₹1 lakh)
- Intraday treated as business income (slab rates)

## Recommended Reading

- SEBI circulars: https://www.sebi.gov.in/
- NSE education: https://www.nseindia.com/learning
- Zerodha Varsity: https://zerodha.com/varsity/

## Screenshot Placeholders

![Zerodha API Setup Screenshot]
![Dashboard Indian Markets Section Screenshot]
![Thursday Expiry Analysis Screenshot]
![Budget Day Sentiment Tracker Screenshot]
