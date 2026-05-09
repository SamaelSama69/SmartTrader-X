"""
Autonomous Trading Daemon for SmartTrader Pro
Runs in the background, analyzes sectors, picks stocks, and executes paper/live trades autonomously.
"""
import time
import logging
import schedule
import pandas as pd
from typing import List, Dict
import yfinance as yf
from datetime import datetime
from pathlib import Path
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.paper_trade_manager import PaperTradeManager
from utils.risk_manager import RiskManager
from strategies.indian_momentum import IndianMomentumStrategy
from strategies.stocks import SectorRotationStrategy
from utils.market_regime import IndianMarketRegime
from utils.multilingual_sentiment import get_news_aggregator
from utils.shoonya_broker import ShoonyaBroker
from utils.reporting_service import ReportingService
from utils.sentiment_db import SentimentDB
from utils.sebi_compliance import get_compliance_manager, AlgoStatus
from utils.notifier import Notifier
from utils.strategy_gatekeeper import StrategyGatekeeper
from utils.memory_manager import PredictionMemory
from utils.performance_tracker import StrategyPerformanceTracker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AutonomousBot:
    def __init__(self, mode='paper'):
        self.mode = mode.lower()
        self.paper_mgr = PaperTradeManager()
        self.risk_mgr = RiskManager()
        self.regime_detector = IndianMarketRegime()
        self.momentum_strategy = IndianMomentumStrategy()
        self.sector_rotation = SectorRotationStrategy()
        self.news_aggregator = get_news_aggregator()
        self.reporting_svc = ReportingService()
        self.sentiment_db = SentimentDB()
        self.compliance = get_compliance_manager()
        self.notifier = Notifier()
        self.gatekeeper = StrategyGatekeeper()
        self.prediction_memory = PredictionMemory()
        self.perf_tracker = StrategyPerformanceTracker()
        
        # Register bot with compliance manager
        self.algo_id = "SMARTTRADER_AUTO_001"
        self.compliance.register_algo(
            algo_id=self.algo_id,
            name="SmartTrader Pro Autonomous Bot",
            description="Autonomous trend-following and momentum strategy",
            strategy_type="momentum",
            broker="shoonya" if self.mode == 'live' else "paper"
        )
        # For local testing, set a dummy IP
        self.compliance.add_whitelisted_ip("127.0.0.1")
        self.compliance.set_current_ip("127.0.0.1")
        
        # Continuous Queue State
        self.sector_queue = []
        self.last_full_rotation = datetime.min
        self.signal_buffer_path = Path("memory/signal_buffer.json")
        self.global_signal_buffer = self._load_signal_buffer()
        
        self.shoonya = None
        if self.mode == 'live':
            self.shoonya = ShoonyaBroker()
            if not self.shoonya.login():
                logger.error("Failed to authenticate with Shoonya REST API. Falling back to PAPER mode.")
                self.mode = 'paper'
            else:
                logger.info("Successfully connected to Shoonya Web API.")
                
        logger.info(f"Autonomous Bot initialized in {self.mode.upper()} mode.")

    def manage_open_positions(self):
        logger.info("Checking open positions for SL/TP and SMART EXITs...")
        
        from indian_config import INTRADAY_CONFIG
        now = datetime.now()
        
        if now.weekday() < 5:  # Mon-Fri only
            eval_time = now.replace(hour=15, minute=0, second=0, microsecond=0)
            sq_time = now.replace(
                hour=INTRADAY_CONFIG['square_off_time'].hour,
                minute=INTRADAY_CONFIG['square_off_time'].minute,
                second=0, microsecond=0
            )
            
            # --- 3:00 PM Pre-Close Evaluation ---
            if eval_time <= now < sq_time and not hasattr(self, '_pre_close_evaluated'):
                logger.info("🕒 3:00 PM Pre-Close Evaluation: Reviewing automated positions...")
                open_pos = self.paper_mgr.get_open_positions()
                regime = self.regime_detector.get_regime()
                
                for pos in open_pos:
                    if pos.get('is_manual'):
                        continue  # Respect manual modes strictly
                        
                    try:
                        ticker = pos['ticker']
                        df = self._fetch_data(ticker, "1d")
                        current_price = float(df['Close'].iloc[-1]) if not df.empty else pos['entry_price']
                        
                        entry = pos['entry_price']
                        pnl_pct = ((current_price - entry) / entry) if pos['signal'] == 'BUY' else ((entry - current_price) / entry)
                        pnl_pct *= 100
                        
                        # INTRADAY -> SWING Upgrade
                        if pos.get('trade_mode') == 'INTRADAY' and pnl_pct > 2.5:
                            logger.info(f"🚀 Upgrading {ticker} to SWING (Strong momentum: +{pnl_pct:.2f}%)")
                            self.paper_mgr.update_trade_mode(pos['id'], 'SWING')
                            
                        # SWING -> INTRADAY Downgrade
                        elif pos.get('trade_mode') == 'SWING':
                            if pnl_pct < -2.0 or 'BEAR' in regime:
                                logger.warning(f"📉 Downgrading {ticker} to INTRADAY (Weakness or Bear Regime)")
                                self.paper_mgr.update_trade_mode(pos['id'], 'INTRADAY')
                                
                    except Exception as e:
                        logger.error(f"Pre-close evaluation failed for {pos.get('ticker')}: {e}")
                self._pre_close_evaluated = True

            # --- 3:15 PM EOD Square-Off ---
            if now >= sq_time:
                open_pos = self.paper_mgr.get_open_positions()
                intraday_pos = [p for p in open_pos if p.get('trade_mode') == 'INTRADAY']
                if intraday_pos:
                    logger.warning(f"EOD SQUARE-OFF: Closing {len(intraday_pos)} INTRADAY positions at {now.strftime('%H:%M')}")
                    for pos in intraday_pos:
                        try:
                            df = self._fetch_data(pos['ticker'], "1d")
                            price = float(df['Close'].iloc[-1]) if not df.empty else pos['entry_price']
                            self.paper_mgr.close_trade(pos['id'], price, reason='EOD_SQUAREOFF', source='BOT')
                            logger.info(f"EOD closed: {pos['ticker']} at ₹{price:.2f}")
                        except Exception as e:
                            logger.error(f"EOD close failed for {pos['ticker']}: {e}")
                # Reset evaluation flag for the next day
                if now.hour == 23:
                    if hasattr(self, '_pre_close_evaluated'):
                        del self._pre_close_evaluated
        
        # Add trailing stop updates
        trailing_updates = self.paper_mgr.apply_trailing_stops(atr_trail=2.0)
        for u in trailing_updates:
            logger.info(f"Trailing stop updated: {u['ticker']} | {u['old_stop']:.2f} → {u['new_stop']:.2f}")

        if self.mode == 'paper':
            # 1. Standard SL/TP Check
            closed_summaries = self.paper_mgr.close_positions()
            for summary in closed_summaries:
                logger.info(f"Closed {summary['ticker']} ({summary['reason']}) at ₹{summary['exit_price']:.2f}")
                self.notifier.send(
                    subject=f"Trade Closed: {summary['ticker']} ({summary['pnl_pct']:+.2f}%)",
                    message=f"Exit: ₹{summary['exit_price']:.2f} | Reason: {summary['reason']} | Mode: PAPER",
                    level="ORDER"
                )
                # Record outcome in PredictionMemory
                pred_id = summary.get('prediction_id', '')
                if pred_id:
                    pnl_pct = summary['pnl_pct'] / 100.0  # summary stores as percent
                    self.prediction_memory.record_outcome(pred_id, {
                        'exit_price': summary['exit_price'],
                        'pnl_pct': pnl_pct,
                        'correct': pnl_pct > 0 if summary.get('signal') == 'BUY' else pnl_pct < 0,
                        'exit_reason': summary['reason'],
                    })
                # Record in PerformanceTracker
                strategy_name = summary.get('strategy', 'indian_momentum')
                self.perf_tracker.record_trade_history(
                    algorithm=strategy_name,
                    signal=summary.get('signal', 'BUY'),
                    pnl_pct=summary['pnl_pct'] / 100.0
                )
            
            # 2. Smart Exit Logic (Contrarian)
            open_pos = self.paper_mgr.get_open_positions()
            for pos in open_pos:
                try:
                    ticker = pos['ticker']
                    # Optimize: Use 3mo instead of 1y for faster checks
                    df = self._fetch_data(ticker, "3mo") 
                    if df.empty: continue
                    
                    # Fetch current sentiment via modern engine
                    news_data = self.news_aggregator.fetch_news(ticker, days=3)
                    
                    # Compute aggregate sentiment robustly
                    res = self.news_aggregator.get_aggregate_sentiment_from_news(ticker, news_data)
                    sent_score = res['aggregate_sentiment']
                    
                    # Analyze for Smart Exit
                    bench_df = self._fetch_data("^NSEI", "3mo")
                    result = self.momentum_strategy.analyze_ticker(ticker, df, bench_df, sent_score)
                    c_score = result['factors'].get('contrarian_score', 0)
                    
                    # Smart Exit Rule for LONGs: News is bad, but price is high (Overextended)
                    if pos['signal'] == 'BUY' and c_score < -1.4:
                        logger.info(f"[SMART EXIT] {ticker} is OVEREXTENDED (Score: {c_score:.2f}). Taking profits early.")
                        self.paper_mgr.close_trade(pos['id'], result['current_price'], reason="SMART", source='BOT')
                        
                    # Smart Exit Rule for SHORTs: News is recovering, but price is low (Bullish Underdog)
                    elif pos['signal'] == 'SHORT' and c_score > 1.4:
                        logger.info(f"[SMART EXIT] {ticker} showing RECOVERY BUZZ (Score: {c_score:.2f}). Covering early.")
                        self.paper_mgr.close_trade(pos['id'], result['current_price'], reason="SMART", source='BOT')
                        
                except Exception as e:
                    logger.error(f"Smart Exit check failed for {ticker}: {e}")
                    
        elif self.mode == 'live':
            logger.info("Live position management is active.")
            
    def run_continuous_scan(self):
        """Main non-blocking loop that cycles through sectors."""
        if not self.is_market_open():
            logger.info("Market closed. Managing open positions and scanning for next day...")
            self.manage_open_positions()
            # We do NOT return here. We want to continue scanning 24/7 to populate the Global Signal Buffer
            # and find Top Opportunities for the next day.

        # 1. Check if it's time to refresh the Sector Queue (Every 15 mins)
        if (datetime.now() - self.last_full_rotation).total_seconds() > 900:
            logger.info("CYCLE: 15-Minute Re-evaluation of Sector Performance...")
            perf = self.sector_rotation.get_sector_performance()
            self.sector_queue = list(perf.keys())
            self.last_full_rotation = datetime.now()
            
        if not self.sector_queue:
            logger.warning("Sector queue empty. Initializing...")
            self.sector_queue = list(self.sector_rotation.SECTOR_TICKERS.keys())

        # 2. Pick next sector and scan it
        sector = self.sector_queue.pop(0)
        logger.info(f"SCAN: Resuming scan for Sector [{sector}]")
        
        tickers = self.sector_rotation.SECTOR_TICKERS.get(sector, [])
        target_stocks = [t if t.endswith('.NS') else f"{t}.NS" for t in tickers]
        
        # Optimize: Batch fetch technical data for the entire sector
        logger.info(f"  Fetching batch data for {len(target_stocks)} stocks...")
        batch_data = yf.download(target_stocks, period="1y", group_by='ticker', threads=True, progress=False, auto_adjust=True)
        
        bench_df = self._fetch_data("^NSEI", "1y")
        open_tickers = [p['ticker'] for p in self.paper_mgr.get_open_positions()]
        risk_mult = self.regime_detector.get_risk_multiplier(self.regime_detector.get_regime())

        sector_signals = []
        for ticker in target_stocks:
            try:
                if ticker in open_tickers: continue

                # Get data from batch
                if len(target_stocks) > 1:
                    if ticker not in batch_data.columns.levels[0]: continue
                    df = batch_data[ticker].dropna(subset=['Close']).copy()
                else:
                    df = batch_data.dropna(subset=['Close']).copy()
                    
                if df.empty or len(df) < 50: continue
                if hasattr(df.index, 'tz') and df.index.tz is not None:
                    df.index = df.index.tz_convert(None)
                    
                # DEEP SENTIMENT SCAN via Modern Engine
                news_data = self.news_aggregator.fetch_news(ticker, days=3)
                sentiment_res = self.news_aggregator.get_aggregate_sentiment_from_news(ticker, news_data)
                sent_score = sentiment_res['aggregate_sentiment']
                
                top_headlines = [n['title'] for n in news_data[:3]]
                all_snippets = []
                for n in news_data: all_snippets.extend(n.get('key_snippets', []))

                # Analyze Strategy
                result = self.momentum_strategy.analyze_ticker(ticker, df, bench_df, sent_score)

                # Persist in Sentiment DB
                self.sentiment_db.update_ticker(ticker, sent_score, top_headlines, result['reason'], all_snippets)

                if result['signal'] != 'HOLD':
                    item = {
                        "ticker": ticker, "signal": result['signal'], "confidence": result['confidence'],
                        "reason": result['reason'], "momentum": result['factors'].get('momentum_score', 0),
                        "sentiment": sent_score, "headlines": top_headlines, "snippets": all_snippets[:5],
                        "timestamp": datetime.now().isoformat()
                    }
                    sector_signals.append(item)

                # Execute Trade ( Kelly > 0.5)
                if result['signal'] in ('BUY', 'SHORT') and result['confidence'] > 0.5:
                    
                    # --- Gatekeeper: only trade strategies that have been validated ---
                    strategy_id = result.get('strategy_used', 'indian_momentum')
                    gate_ok, gate_reason = self.gatekeeper.allow_trade(strategy_id, ticker)
                    if not gate_ok:
                        logger.info(f"[GATEKEEPER] Blocked {ticker} ({strategy_id}): {gate_reason}")
                        continue
                    elif "No backtest data" in gate_reason:
                        logger.warning(f"[GATEKEEPER] {ticker} ({strategy_id}) has no test data — proceeding at reduced size")
                        # Reduce confidence to 50% of normal when untested
                        result['confidence'] *= 0.5

                    # After result is obtained and before trade execution, optionally override with best validated:
                    best_validated = self.gatekeeper.get_best_validated_strategy(ticker)
                    if best_validated and best_validated != strategy_id:
                        logger.debug(f"Gatekeeper suggests {best_validated} over {strategy_id} for {ticker}")

                    price = result['current_price']
                    # Reduce position size by 20% during earnings season (gap risk)
                    from indian_config import is_earnings_season
                    earnings_discount = 0.80 if is_earnings_season() else 1.0
                    
                    # Dynamic Kelly: use REAL performance stats instead of hardcoded defaults
                    perf_stats = self.perf_tracker.get_strategy_stats(strategy_id)
                    adjusted_confidence = result['confidence'] * risk_mult * earnings_discount
                    if perf_stats and perf_stats.get('win_rate') is not None:
                        shares = self.risk_mgr.size_position_dynamic(
                            price, adjusted_confidence, perf_stats
                        )
                    else:
                        shares = self.risk_mgr.size_position_kelly(price, adjusted_confidence)
                    
                    # Pass sector to risk check
                    risk_check = self.risk_mgr.check_trade(ticker, shares, price, sector=sector)
                    
                    if shares > 0 and risk_check['allowed']:
                        final_shares = risk_check['adjusted_shares']
                        
                        # SEBI Compliance Check
                        comp_res, reason = self.compliance.validate_order(
                            algo_id=self.algo_id, symbol=ticker, side=result['signal'],
                            quantity=final_shares, price=price
                        )
                        if not comp_res:
                            logger.warning(f"COMPLIANCE BLOCK: {ticker} rejected. Reason: {reason}")
                            continue

                        # Record prediction BEFORE opening trade
                        pred_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        self.prediction_memory.add_prediction(ticker, {
                            'signal': result['signal'],
                            'confidence': result['confidence'],
                            'price': price,
                            'stop_loss': result['stop_loss'],
                            'price_target': result['price_target'],
                            'strategy': strategy_id,
                            'sector': sector,
                        })

                        self.paper_mgr.open_trade(
                            ticker, result['signal'], price, final_shares,
                            result['stop_loss'], result['price_target'],
                            sector=sector, prediction_id=pred_id,
                            strategy=strategy_id
                        )
                        # Record trade in risk manager with sector context
                        self.risk_mgr.record_trade(ticker, final_shares, price, result['signal'], sector=sector)
                        logger.info(f"ORDER: [AUTO] {result['signal']} {ticker} executed (Sector: {sector}).")
                        
                        # Notify
                        self.notifier.send(
                            subject=f"Trade Opened: {result['signal']} {ticker}",
                            message=f"Entry: ₹{price:.2f} | SL: ₹{result['stop_loss']} | Tgt: ₹{result['price_target']} | Mode: {self.mode.upper()}",
                            level="ORDER"
                        )

            except Exception as e:
                logger.error(f"Error in sector {sector} for {ticker}: {e}")
                
        # 3. Update Global Signal Buffer (Keep last 30 best signals across all sectors)
        # Remove old signals from THIS sector first to avoid duplicates
        self.global_signal_buffer = [s for s in self.global_signal_buffer if s['ticker'] not in [t for t in target_stocks]]
        self.global_signal_buffer.extend(sector_signals)
        
        # Sort by confidence and keep top 30
        self.global_signal_buffer = sorted(self.global_signal_buffer, key=lambda x: x['confidence'], reverse=True)[:30]
        self._save_signal_buffer()
        
        # 4. Save results for GUI (Merge with WATCH signals from DB)
        final_ui_list = list(self.global_signal_buffer)
        all_db_signals = self.sentiment_db.get_all_active_signals(threshold=0.3)
        for sig in all_db_signals:
            if not any(r['ticker'] == sig['ticker'] for r in final_ui_list):
                final_ui_list.append({
                    "ticker": sig['ticker'], "signal": "WATCH", "confidence": 0.0,
                    "reason": sig.get('reason', 'Strong historical sentiment'), "momentum": 0.0,
                    "sentiment": sig['current_score'], "headlines": sig['current_headlines'],
                    "snippets": sig.get('current_snippets', []), "timestamp": sig['last_updated']
                })

        self._save_scan_results(final_ui_list)
        logger.info(f"Sector [{sector}] scan complete. Buffer now has {len(self.global_signal_buffer)} signals.")


    def _save_scan_results(self, results):
        try:
            logger.info("Bot: Updating shared GUI data...")
            indices = {"NIFTY 50": "^NSEI", "BANK NIFTY": "^NSEBANK", "INDIA VIX": "^INDIAVIX"}
            idx_data = {}
            for name, ticker in indices.items():
                try:
                    h = self._fetch_data(ticker, period="5d")
                    if not h.empty:
                        curr = float(h['Close'].iloc[-1])
                        if len(h) >= 2:
                            prev = float(h['Close'].iloc[-2])
                            pct = ((curr/prev)-1)*100
                        else:
                            pct = 0.0
                        idx_data[name] = {"price": curr, "pct": pct}
                    else:
                        logger.warning(f"Indices fetch returned empty df for {ticker}")
                except Exception as e: 
                    logger.error(f"Error fetching index {name}: {e}")

            market_news = self.news_aggregator.fetch_news("Indian Stock Market", days=1)
            mkt_sent = self.news_aggregator.get_aggregate_sentiment_from_news("Indian Stock Market", market_news)
            
            clean_news = []
            for n in market_news[:20]: # Increased to 20
                clean_news.append({
                    "title": n['title'], "source": n['source'], "link": n['link'], "published": n['published'],
                    "sentiment": n['sentiment'].sentiment_score, "description": n.get('description', '')[:250]
                })

            path = Path("memory/latest_scan_results.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Atomic update: Write to temp file first, then rename
            temp_path = path.with_suffix(".tmp")
            with open(temp_path, 'w') as f:
                json.dump({
                    "last_updated": datetime.now().strftime("%H:%M:%S"),
                    "regime": self.regime_detector.get_regime(),
                    "regime_metrics": self.regime_detector.current_metrics,
                    "indices": idx_data,
                    "market_sentiment": mkt_sent,
                    "all_news": clean_news,
                    "results": results
                }, f, indent=2)
            
            import os
            os.replace(temp_path, path)
            logger.info("Bot: Shared GUI data updated successfully.")
        except Exception as e:
            logger.error(f"Failed to save scan results: {e}")

    def _fetch_data(self, ticker, period):
        try:
            df = yf.Ticker(ticker).history(period=period)
            if hasattr(df.index, 'tz') and df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            return df
        except: return pd.DataFrame()

    def run_weekly_validation(self):
        """
        Automatically re-runs backtests and walk-forward tests for all strategies
        currently being traded. Runs every Sunday at midnight so Monday trading
        uses fresh validation data.

        Called by: schedule.every().sunday.at("00:00").do(bot.run_weekly_validation)
        """
        from utils.testing_engine import TestingEngine
        from indian_config import POPULAR_INDIAN_STOCKS

        logger.info("[GATEKEEPER] Starting weekly strategy re-validation...")
        engine = TestingEngine()

        # Strategies the autobot actually uses
        active_strategies = ["indian_momentum", "momentum_breakout", "sector_rotation"]
        # Representative tickers (top 10 most frequently traded)
        rep_tickers = [t + ".NS" for t in POPULAR_INDIAN_STOCKS.get("large_cap", [])[:10]]

        for strategy in active_strategies:
            for ticker in rep_tickers[:3]:   # validate on 3 tickers per strategy
                try:
                    logger.info(f"[GATEKEEPER] Validating {strategy} on {ticker}...")
                    engine.run_walk_forward(strategy, ticker, days=365, force=True)
                except Exception as e:
                    logger.error(f"[GATEKEEPER] Validation failed for {strategy}/{ticker}: {e}")

        # Reload gatekeeper cache
        self.gatekeeper = StrategyGatekeeper()
        gk_sum = self.gatekeeper.summary()
        logger.info(
            f"[GATEKEEPER] Weekly validation complete: "
            f"{gk_sum['passed']}/{gk_sum['total_tests']} passed"
        )
        self.notifier.send(
            subject="Weekly Strategy Validation Complete",
            message=(
                f"Passed: {gk_sum['passed']}/{gk_sum['total_tests']} "
                f"({gk_sum['pass_rate']:.0f}% pass rate)"
            ),
            level="INFO"
        )

    def generate_weekly_pdf(self):
        self.reporting_svc.generate_weekly_report(self.paper_mgr.conn)

    def is_market_open(self):
        """Check if Indian market is currently open (9:15 AM - 3:30 PM, excl. weekends & NSE holidays)."""
        from indian_config import get_nse_holidays
        now = datetime.now()
        if now.weekday() >= 5: return False
        # Check NSE holiday calendar
        today_str = now.strftime('%Y-%m-%d')
        if today_str in get_nse_holidays(now.year): return False
        m_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        m_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return m_open <= now <= m_close

    def _load_signal_buffer(self) -> List[Dict]:
        """Load signal buffer from disk."""
        try:
            if self.signal_buffer_path.exists():
                with open(self.signal_buffer_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load signal buffer: {e}")
        return []

    def _save_signal_buffer(self):
        """Save current signal buffer to disk."""
        try:
            self.signal_buffer_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.signal_buffer_path, 'w') as f:
                json.dump(self.global_signal_buffer, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save signal buffer: {e}")

def main():
    import sys, time
    mode = 'paper'
    if len(sys.argv) > 1 and sys.argv[1] == '--live': mode = 'live'
    bot = AutonomousBot(mode=mode)
    schedule.every().sunday.at("00:00").do(bot.run_weekly_validation)
    schedule.every().friday.at("18:00").do(bot.generate_weekly_pdf)
    logger.info("SmartTrader AutoBot running. Press Ctrl+C to stop.")
    SCAN_INTERVAL = 120
    while True:
        scan_start = time.time()
        try: bot.run_continuous_scan()
        except Exception as e: logger.error(f"Scan crashed: {e}", exc_info=True)
        schedule.run_pending()
        elapsed = time.time() - scan_start
        wait = max(15, SCAN_INTERVAL - elapsed)
        logger.info(f"Scan took {elapsed:.0f}s — next in {wait:.0f}s.")
        time.sleep(wait)

if __name__ == "__main__": main()
