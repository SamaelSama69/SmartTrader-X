# Auto Trading Guide for SmartTrader

Guide to setting up automated trading with safety features in SmartTrader.

## Enabling One-Click Trading

### Step 1: Enable in Config

Edit `config.py` or create `.env` entries:

```env
# Auto Trading Settings
AUTO_TRADING_ENABLED=true
AUTO_TRADING_MODE=paper  # paper or live
MAX_POSITION_SIZE=10000  # Max ₹ per position
MAX_DAILY_LOSS=5000     # Daily loss limit
```

### Step 2: Configure Strategy

Select which strategies to run automatically:

```python
# In config.py or dashboard settings
AUTO_STRATEGIES = [
    "momentum",
    "mean_reversion",
    "options_expiry"
]
```

### Step 3: Start Auto Trading

In the dashboard:
1. Go to "Auto Trading" section
2. Click "Enable Auto Trading"
3. Confirm with 2FA (if enabled)
4. Status will show "Auto Trading Active"

Or via command line:

```cmd
python main.py --auto-trade
```

## Risk Management Settings

### Position Sizing

Configure in `.env`:

```env
# Position Sizing
MAX_POSITION_PERCENT=5    # Max 5% of portfolio per position
MAX_SECTOR_EXPOSURE=20    # Max 20% in single sector
MAX_LEVERAGE=1            # No leverage for cash, 5x for F&O
```

### Stop Loss Settings

```env
# Stop Loss
DEFAULT_STOP_LOSS=2       # 2% stop loss
TRAILING_STOP_LOSS=true   # Enable trailing stop
TRAILING_STOP_PERCENT=1  # Trail by 1%
```

### Daily Limits

```env
# Daily Limits
MAX_DAILY_TRADES=10       # Max trades per day
MAX_DAILY_PROFIT=10000    # Take profit and stop
MAX_DAILY_LOSS=5000       # Stop trading after loss
```

### Risk Checks

SmartTrader performs these checks before every trade:
1. Position size within limits
2. Daily loss not exceeded
3. Market hours check
4. Volatility check (avoid trading during crashes)
5. Sentiment check (avoid trading against strong negative sentiment)

## Connecting Brokers

### Shoonya (Finvasia) - THE BEST FREE API (Zero Brokerage, Zero API Fees)

Shoonya is the recommended broker for SmartTrader because they offer **Zero Brokerage** and **Zero API Charges** for life.

1. Sign up for a prism account at https://prism.finvasia.com/
2. Go to "API Management" and create a new API Key.
3. You will need your **User ID**, **Password**, **TOTP Key**, **Vendor Code**, and **API Key**.
4. Add these to your `.env` file:

```env
SHOONYA_USER_ID=your_id
SHOONYA_PASSWORD=your_password
SHOONYA_TOTP_KEY=your_totp_key
SHOONYA_VENDOR_CODE=your_vendor_code_VC
SHOONYA_API_KEY=your_api_key
```

### Zerodha (Kite Connect API)

Already covered in INDIAN_TRADING_GUIDE.md. Additional auto-trading settings:

```env
ZERODHA_AUTO_TRADING=true
ZERODHA_PRODUCT_TYPE=MIS  # MIS for intraday, CNC for delivery
ZERODHA_ORDER_TYPE=MARKET # MARKET or LIMIT
```

### Groww API

Groww does not provide public API access currently. Use Zerodha or Paytm instead.

### Paytm Money API

1. Sign up for Paytm Money API at https://paytmmoney.com/api
2. Get API key and secret
3. Add to `.env`:

```env
PAYTM_API_KEY=your_paytm_api_key
PAYTM_API_SECRET=your_paytm_api_secret
PAYTM_AUTO_TRADING=true
```

4. Authorize via OAuth in dashboard

## Safety Features and Kill Switches

### Kill Switch (Emergency Stop)

**Dashboard**: Big red "KILL SWITCH" button in header
- Immediately cancels all open orders
- Squares off all positions
- Disables auto trading
- Sends email/SMS alert

**Command Line**:
```cmd
python main.py --kill-switch
```

**Keyboard Shortcut**: Ctrl+Alt+K (when dashboard is open)

### Circuit Breakers

SmartTrader automatically stops trading if:
- Market crashes >5% in a day
- Individual stock moves >10% against position
- API connection lost for >5 minutes
- Daily loss limit exceeded
- Broker API returns error 3 times in a row

### Paper Trading Mode (Recommended for Testing)

Always test strategies in paper trading first:

```env
AUTO_TRADING_MODE=paper
PAPER_TRADING_BALANCE=100000  # Virtual ₹1 lakh
```

Paper trading simulates real trading without real money:
- Real market prices
- Virtual orders
- Full P&L tracking
- No real risk

### Cooldown Periods

After triggering kill switch:
- 30-minute cooldown before manual restart
- Requires 2FA to restart
- Log review required

### Audit Logs

All auto-trading actions are logged to:
- `logs/auto_trading.log`
- Includes: order time, price, quantity, reason
- Tamper-proof (append-only)

View logs:
```cmd
type logs\auto_trading.log
```

## Monitoring Auto Trading

### Dashboard Monitoring

1. **Live Positions**: View all open positions with P&L
2. **Order Book**: See pending/executed orders
3. **P&L Chart**: Real-time profit/loss graph
4. **Risk Meters**: Visual indicators for exposure/risk

### Alerts and Notifications

Configure in `.env`:

```env
# Notifications
ENABLE_EMAIL_ALERTS=true
ALERT_EMAIL=your_email@example.com

ENABLE_SMS_ALERTS=false
ALERT_PHONE=+919876543210

ENABLE_DESKTOP_NOTIFICATIONS=true
```

Alerts triggered for:
- Trade executed
- Stop loss hit
- Daily profit/loss target reached
- Kill switch activated
- Connection lost

## Recommended Setup for Beginners

1. Start with **Paper Trading** mode
2. Set low position sizes (₹5000 max)
3. Enable all safety features
4. Monitor for 1 week before going live
5. Switch to **Live** with small amounts first

## Troubleshooting Auto Trading

### Issue: Orders Not Executing

**Check**:
- Market hours (9:15 AM - 3:30 PM)
- Sufficient balance
- API keys valid
- Kill switch not active

### Issue: Too Many False Signals

**Solution**:
- Adjust sentiment threshold in config
- Increase minimum signal strength
- Add confirmation from multiple indicators

### Issue: API Rate Limits

**Solution**:
- Zerodha: 10 orders/second, 3000/day
- Implement rate limiting in config:
```env
ORDER_DELAY_SECONDS=1
MAX_ORDERS_PER_MINUTE=30
```

## Legal Disclaimer

- Automated trading involves risk of financial loss
- Test thoroughly in paper trading first
- You are responsible for all trades executed
- SmartTrader is a tool, not financial advice
- Consult SEBI-registered advisor before trading
