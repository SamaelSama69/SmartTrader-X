"""
SmartTrader Main Orchestrator
Indian Market (NSE/BSE) Trading Analysis System
Analyzes stocks, options, and futures for profitable trading opportunities
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import json
import time
import logging
from typing import Dict, List, Optional, Tuple
import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import OUTPUT_DIR
from utils.data_fetcher import MarketDataFetcher
from utils.multilingual_sentiment import get_sentiment_engine, get_news_aggregator
from utils.screener import SmartScreener
from utils.memory_manager import PredictionMemory, MarketContextMemory
from utils.backtester import Backtester
from utils.visualizer import Visualizer
from strategies.stocks import StockStrategy, MomentumBreakoutStrategy, SectorRotationStrategy, OpeningRangeBreakout
from strategies.indian_momentum import IndianMomentumStrategy
from strategies.options import OptionsAnalyzer
from utils.shoonya_broker import ShoonyaBroker
from strategies.algorithms import AlgorithmSelector
from utils.lifecycle_manager import LifecyclePrediction
from utils.performance_tracker import StrategyPerformanceTracker
from utils.risk_manager import RiskManager
from utils.notifier import Notifier
from utils.walk_forward import WalkForwardConfig, WalkForwardValidator

from utils.nse_data import NSEDataFetcher, convert_to_nse_format, convert_from_nse_format
from utils.indian_indicators import is_expiry_day, is_budget_day
import indian_config as indian_cfg
import schedule

from utils.market_regime import IndianMarketRegime

from utils.paper_trade_manager import PaperTradeManager

logger = logging.getLogger(__name__)


class SmartTrader:
    """Main trading system orchestrator - Indian Market (NSE/BSE)"""

    def __init__(self):
        self.market = 'IN'

        self.data_fetcher = MarketDataFetcher()
        self.sentiment_engine = get_sentiment_engine()
        self.news_aggregator = get_news_aggregator()
        self.screener = SmartScreener()
        self.memory = PredictionMemory()
        self.memory.auto_verify_outcomes()
        self.market_context = MarketContextMemory()

        self.paper_trade_manager = PaperTradeManager()

        self.backtester = Backtester()
        self.visualizer = Visualizer()
        self.stock_strategy = StockStrategy(memory=self.memory)
        self.indian_momentum_strategy = IndianMomentumStrategy()
        self.breakout_strategy = MomentumBreakoutStrategy()
        self.sector_rotation   = SectorRotationStrategy()
        self.orb_strategy      = OpeningRangeBreakout()
        self.perf_tracker      = StrategyPerformanceTracker()
        self.options_analyzer = OptionsAnalyzer()

        self.nse_fetcher = NSEDataFetcher()
        self.lifecycle_manager = LifecyclePrediction()

        self.risk_manager = RiskManager(initial_capital=100000.0)
        self.notifier = Notifier()
        self.shoonya = ShoonyaBroker()
        self.news_aggregator = get_news_aggregator()
        self.auto_trade = False
        self.paper_trade = True

        self.regime_detector = IndianMarketRegime()

        kill_file = Path('kill_switch.active')
        if kill_file.exists():
            logger.critical("KILL-SWITCH FILE DETECTED — trading disabled")
            self.paper_trade = True
            self.auto_trade = False
            if hasattr(self, 'risk_manager'):
                self.risk_manager.trading_enabled = False

        logger.info("="*60)
        logger.info("  SmartTrader - Indian Market Analysis System (NSE/BSE)")
        logger.info("="*60)
        logger.info(f"  Market: NSE/BSE")
        logger.info(f"  Trading Hours: 9:15 AM - 3:30 PM IST")
        logger.info(f"  Expiry Day: Thursday")
        if is_expiry_day():
            logger.warning(f"  *** TODAY IS EXPIRY DAY (Thursday) ***")
        if is_budget_day():
            logger.warning(f"  *** TODAY IS BUDGET DAY (Feb 1st) - High Volatility Expected ***")
        
        # Display Market Sentiment
        try:
            logger.info("  [MARKET] Fetching general market sentiment...")
            mkt_sent = self.news_aggregator.get_market_sentiment()
            if mkt_sent['article_count'] > 0:
                logger.info(f"  Market Sentiment: {mkt_sent['aggregate_sentiment']:.2f} ({mkt_sent['article_count']} articles)")
        except Exception:
            pass
            
        logger.info("")

    def normalize_ticker(self, ticker: str) -> str:
        return convert_to_nse_format(ticker)

    def screen_opportunities(self):
        return self.screen_indian_opportunities()

    def screen_indian_opportunities(self):
        import pickle
        from pathlib import Path
        import time

        logger.info("[SCREEN] Loading NSE universe (200 stocks)...")
        universe = self.nse_fetcher.get_nifty_universe()

        cache_file = Path('data/indian/universe_snapshot.pkl')
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_age = time.time() - cache_file.stat().st_mtime if cache_file.exists() else 99999

        if cache_age < 14400:
            logger.info("  Using cached universe data")
            with open(cache_file, 'rb') as f:
                batch_data = pickle.load(f)
        else:
            logger.info(f"  Downloading data for {len(universe)} stocks...")
            batch_data = yf.download(
                universe, period='3mo', auto_adjust=True,
                group_by='ticker', threads=True, progress=False
            )
            with open(cache_file, 'wb') as f:
                pickle.dump(batch_data, f)

        results = []
        for ticker in universe:
            try:
                if ticker in batch_data.columns.get_level_values(0):
                    hist = batch_data[ticker].dropna()
                    if len(hist) >= 50:
                        analysis = self.analyze_ticker(ticker, detailed=False, visualize=False)
                        if 'error' not in analysis and analysis.get('signal') in ('BUY', 'SELL', 'SHORT'):
                            results.append({
                                'ticker': ticker,
                                'signal': analysis['signal'],
                                'confidence': analysis['confidence'],
                                'price': analysis.get('current_price', 0)
                            })
            except Exception as e:
                logger.debug(f"Error: {ticker}: {e}")

        results.sort(key=lambda x: x['confidence'], reverse=True)
        logger.info(f"  Found {len(results)} signals from {len(universe)} stocks")
        for r in results[:15]:
            logger.info(f"  {r['ticker']:<18} {r['signal']:<5} conf={r['confidence']:.1%} @ INR{r['price']:.2f}")
        return results

    def _sector_boost_for_ticker(self, ticker: str) -> float:
        try:
            leaders = set(self.sector_rotation.recommend_sectors())
            for sector, tickers in self.sector_rotation.SECTOR_TICKERS.items():
                if ticker in tickers and sector in leaders:
                    return 0.20
        except Exception as e:
            logger.debug(f"Sector boost unavailable for {ticker}: {e}")
        return 0.0

    def _cash_signal(self, ticker: str, regime: str) -> Dict:
        return {
            'ticker': ticker, 'timestamp': datetime.now().isoformat(),
            'signal': 'HOLD', 'confidence': 1.0,
            'current_price': 0, 'factors': {},
            'reason': f"Market regime is {regime}; new risk is disabled by strategy router.",
        }

    def _run_regime_strategy(self, strategy_id: str, ticker: str,
                             detailed: bool, regime: str,
                             sentiment_score: float = 0.0) -> Dict:
        if strategy_id == 'momentum_breakout':
            return self.breakout_strategy.analyze_ticker(ticker)
        if strategy_id == 'indian_momentum':
            df = self.data_fetcher.get_stock_data(ticker, period='1y')
            bench_df = self.data_fetcher.get_stock_data("^NSEI", period='1y')
            return self.indian_momentum_strategy.analyze_ticker(ticker, df, bench_df, sentiment_score)
        if strategy_id == 'sector_rotation':
            boost = self._sector_boost_for_ticker(ticker)
            return self.stock_strategy.analyze_ticker(
                ticker, detailed=detailed, regime=regime, sector_boost=boost
            )
        if strategy_id == 'orb':
            return self.orb_strategy.analyze(ticker)
        if strategy_id == 'cash':
            return self._cash_signal(ticker, regime)
        return self.stock_strategy.analyze_ticker(ticker, detailed=detailed, regime=regime)

    def _select_regime_strategy(self, ticker: str, detailed: bool,
                                regime: str, preferred: List[str],
                                sentiment_score: float = 0.0) -> Tuple[Dict, str]:
        fallback = None
        fallback_id = 'stock_strategy'
        weights = self.perf_tracker.get_decayed_algorithm_weights()
        aliases = {
            'momentum_breakout': 'MomentumBreakout',
            'sector_rotation': 'SectorRotation',
            'indian_momentum': 'IndianMomentum',
            'stock_strategy': 'IndianMomentum',
            'orb': 'MomentumBreakout',
            'cash': 'Cash',
        }
        ranked = sorted(
            preferred or ['stock_strategy'],
            key=lambda sid: weights.get(aliases.get(sid, sid), 1.0),
            reverse=True,
        )

        for strategy_id in ranked:
            weight = weights.get(aliases.get(strategy_id, strategy_id), 1.0)
            if strategy_id != 'cash' and weight < 0.25:
                logger.info(f"Skipping {strategy_id}: decayed performance weight too low ({weight:.2f})")
                continue
            try:
                analysis = self._run_regime_strategy(strategy_id, ticker, detailed, regime, sentiment_score)
            except Exception as e:
                logger.debug(f"Strategy {strategy_id} failed for {ticker}: {e}")
                continue

            if 'error' in analysis:
                fallback = analysis
                fallback_id = strategy_id
                continue

            signal = analysis.get('signal', 'HOLD')
            confidence = float(analysis.get('confidence', 0) or 0)
            if fallback is None:
                fallback = analysis
                fallback_id = strategy_id
            if signal in ('BUY', 'SELL') and confidence >= 0.50:
                analysis['strategy_weight'] = weight
                return analysis, strategy_id

        if fallback is not None:
            fallback['strategy_weight'] = weights.get(aliases.get(fallback_id, fallback_id), 1.0)
            return fallback, fallback_id
        analysis = self.stock_strategy.analyze_ticker(ticker, detailed=detailed, regime=regime)
        analysis['strategy_weight'] = weights.get('IndianMomentum', 1.0)
        return analysis, 'stock_strategy'

    def analyze_ticker(self, ticker: str, detailed: bool = True, force: bool = False, visualize: bool = True):
        ticker = self.normalize_ticker(ticker)
        logger.info(f"[ANALYZE] Analyzing {ticker}...")

        if not self.memory.should_recompute(ticker, force=force):
            logger.info("  Using cached analysis (use --force to override)")
            past = self.memory.get_past_predictions(ticker, days=1)
            if past:
                return past[-1]['prediction']

        regime    = self.regime_detector.get_regime()
        preferred = self.regime_detector.get_preferred_strategies(regime)

        # Fetch Free News Sentiment (now used as input to strategy)
        logger.info(f"  [NEWS] Fetching free news sentiment...")
        news_sent = self.news_aggregator.get_aggregate_sentiment(ticker)
        sentiment_score = news_sent.get('aggregate_sentiment', 0.0)

        analysis, strategy_used = self._select_regime_strategy(
            ticker=ticker, detailed=detailed, regime=regime, 
            preferred=preferred, sentiment_score=sentiment_score)

        analysis['market_regime'] = regime
        analysis['strategy_used'] = strategy_used
        analysis['risk_multiplier'] = self.regime_detector.get_risk_multiplier(regime)

        if 'error' in analysis:
            logger.error(f"  Error: {analysis['error']}")
            return analysis

        self.perf_tracker.record_signal(strategy_used, ticker,
            analysis['signal'], analysis['confidence'], analysis.get('current_price', 0))

        logger.info(f"\n{'=' * 60}")
        logger.info(f"  Analysis for {ticker}")
        logger.info(f"{'=' * 60}")
        logger.info(f"  Signal: {analysis['signal']} (Confidence: {analysis['confidence']:.1%})")
        logger.info(f"  Current Price: INR{analysis.get('current_price', 'N/A')}")

        if analysis.get('price_target'):
            logger.info(f"  Price Target: INR{analysis['price_target']}")
            logger.info(f"  Stop Loss: INR{analysis['stop_loss']}")

        if news_sent['article_count'] > 0:
            logger.info(f"\n  [NEWS] Aggregate Sentiment: {news_sent['aggregate_sentiment']:.2f} ({news_sent['article_count']} articles)")
            logger.info(f"  Top Topics: {', '.join(list(news_sent['topics'].keys())[:3])}")
            analysis['news_sentiment'] = news_sent
        else:
            logger.info(f"\n  [NEWS] No recent news found for {ticker}")

        factors = analysis.get('factors', {})
        if 'momentum_score' in factors:
            logger.info(f"\n  Momentum Score: {factors.get('momentum_score', 0):.2f}")
            logger.info(f"  VCP Pattern: {'YES' if factors.get('vcp_pattern') else 'NO'}")
            logger.info(f"  RS Score (vs NIFTY): {factors.get('rs_score', 0):.2%}")
            logger.info(f"  Price vs SMA200: {factors.get('price_vs_sma200', 0):.2%}")
        else:
            logger.info(f"\n  Sentiment: {factors.get('sentiment', {}).get('aggregate_sentiment', 0):.2f}")
            logger.info(f"  RSI: {factors.get('technical', {}).get('rsi', 'N/A')}")
            logger.info(f"  MACD Signal: {factors.get('technical', {}).get('macd_signal', 'N/A')}")
            logger.info(f"  MA Signal: {factors.get('technical', {}).get('ma_signal', 'N/A')}")

        output_file = OUTPUT_DIR / f"{ticker}_analysis.json"
        with open(output_file, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        logger.info(f"\n  Analysis saved to: {output_file}")

        if analysis.get('signal') == 'BUY' and 'current_price' in analysis:
            logger.info(f"\n  [LIFECYCLE] Creating full trade prediction...")
            try:
                lifecycle_pred = self.lifecycle_manager.create_prediction(
                    ticker, 'BUY', analysis['current_price'], analysis)
                logger.info(f"    Prediction ID: {lifecycle_pred['id']}")
                logger.info(f"    Entry: INR{lifecycle_pred['entry']['price']:.2f}")
                logger.info(f"    Target: INR{lifecycle_pred['exit_plan']['target_price']:.2f}")
                logger.info(f"    Stop Loss: INR{lifecycle_pred['exit_plan']['stop_loss']:.2f}")
                logger.info(f"    Expected Exit: {lifecycle_pred['exit_plan']['target_date']}")
            except Exception as e:
                logger.warning(f"    Warning: Could not create lifecycle prediction: {e}")

        if visualize:
            self.visualizer.create_summary_dashboard(analysis)
            self.visualizer.plot_price_with_signals(ticker)
        
        # Execute signal if in paper or auto mode
        if self.paper_trade or self.auto_trade:
            self.execute_signal(ticker, analysis)
            
        return analysis

    def show_paper_summary(self):
        """Display paper trading portfolio summary."""
        # First update positions (close those that hit stop/target)
        closed = self.paper_trade_manager.close_positions(self.perf_tracker)
        if closed > 0:
            logger.info(f"Updated paper portfolio: {closed} positions closed.")

        summary = self.paper_trade_manager.get_portfolio_summary()
        
        logger.info(f"\n{'=' * 60}")
        logger.info("  PAPER TRADING PORTFOLIO SUMMARY")
        logger.info(f"{'=' * 60}")
        logger.info(f"  Total Trades:   {summary['total_trades']}")
        logger.info(f"  Open Positions: {summary['open_count']}")
        logger.info(f"  Closed Trades:  {summary['closed_count']}")
        logger.info(f"  Win Rate:       {summary['win_rate']:.1f}%")
        logger.info(f"  Realized P&L:   {summary['realized_pnl_pct']:+.2f}%")
        
        if summary['open_positions']:
            logger.info(f"\n  Open Positions:")
            logger.info(f"  {'Ticker':<15} {'Signal':<8} {'Entry':<10} {'Price':<10} {'P&L %':<10}")
            logger.info(f"  {'-'*55}")
            for pos in summary['open_positions']:
                ticker = pos['ticker']
                # Get current price for live P&L
                try:
                    yf_ticker = ticker if (ticker.endswith('.NS') or ticker.endswith('.BO')) else f"{ticker}.NS"
                    current = float(yf.Ticker(yf_ticker).fast_info.get('lastPrice', 0) or 0)
                    pnl = ((current - pos['entry_price']) / pos['entry_price']) * 100 if pos['signal'] == 'BUY' else ((pos['entry_price'] - current) / pos['entry_price']) * 100
                except Exception:
                    current = 0
                    pnl = 0
                
                logger.info(f"  {ticker:<15} {pos['signal']:<8} {pos['entry_price']:<10.2f} {current:<10.2f} {pnl:>+7.2f}%")
        else:
            logger.info("\n  No open positions.")
        logger.info(f"{'=' * 60}\n")

    def _get_ticker_sector(self, ticker: str) -> str:
        """Find which sector a ticker belongs to."""
        for sector, tickers in self.sector_rotation.SECTOR_TICKERS.items():
            if ticker in tickers or f"{ticker}.NS" in tickers:
                return sector
        return "Diversified"

    def execute_signal(self, ticker: str, analysis: Dict):
        signal     = analysis.get('signal')
        confidence = analysis.get('confidence', 0)
        price      = analysis.get('current_price', 0)

        if not price or signal == 'HOLD':
            return

        # 1. Prevent duplicate active trades
        open_tickers = [p['ticker'] for p in self.paper_trade_manager.get_open_positions()]
        if ticker in open_tickers:
            logger.info(f"  [SIGNAL] {ticker} already has an open position. Skipping duplicate entry.")
            return

        if analysis.get('risk_multiplier', 1.0) <= 0:
            logger.warning(f"  Trade blocked ({ticker}): regime risk multiplier is zero")
            return

        quality = analysis.get('data_quality')
        if quality and not quality.get('ok', False):
            logger.warning(f"  Trade blocked ({ticker}): data quality failed: {quality.get('issues')}")
            return

        risk_multiplier = float(analysis.get('risk_multiplier', 1.0) or 0.0)
        confidence *= risk_multiplier
        if confidence <= 0:
            return

        if self.risk_manager.check_consecutive_losses():
            self.notifier.send("Circuit Breaker Active",
                               f"3 consecutive losses — skipping {ticker} {signal}", "WARNING")
            return

        shares = self.risk_manager.size_position_kelly(price, confidence)
        if shares <= 0:
            return

        check = self.risk_manager.check_trade(ticker, shares, price)
        if not check['allowed']:
            logger.warning(f"  Trade blocked ({ticker}): {check['reason']}")
            return
        shares = check['adjusted_shares']

        if self.paper_trade:
            sector = self._get_ticker_sector(ticker)
            # Determine asset type
            asset_type = 'EQUITY'
            if ticker.startswith('^') or 'NIFTY' in ticker:
                asset_type = 'INDEX'
            elif ticker.endswith('-FUT'):
                asset_type = 'FNO_FUT'
            elif ticker.endswith('-CE') or ticker.endswith('-PE'):
                asset_type = 'FNO_OPT'

            trade_id = self.paper_trade_manager.open_trade(
                ticker=ticker, signal=signal,
                entry_price=price, shares=shares,
                stop_loss=analysis.get('stop_loss'),
                target=analysis.get('price_target'),
                sector=sector,
                asset_type=asset_type
            )
            logger.info(f"  [PAPER] {signal} {shares}×{ticker} ({asset_type}) @ INR{price:.2f} (id: {trade_id})")
            self.risk_manager.record_trade(ticker, shares, price, signal)
            self.notifier.send(
                f"Paper Trade: {signal} {ticker}",
                f"{shares} shares @ INR{price:.2f} | Conf: {confidence:.0%}", "INFO"
            )
        elif self.auto_trade:
            try:
                # Login to Shoonya if not already
                if not self.shoonya.is_logged_in:
                    self.shoonya.login()

                if self.shoonya.is_logged_in:
                    # Shoonya uses 'B'/'S' for side
                    side = 'B' if signal == 'BUY' else 'S'
                    # Strip .NS/.BO for tradingsymbol if present
                    shoonya_ticker = ticker.split('.')[0]
                    
                    order = self.shoonya.place_order(shoonya_ticker, side, shares)
                    
                    if order.get('success'):
                        self.risk_manager.record_trade(ticker, shares, price, signal)
                        self.risk_manager.record_trade_history(ticker, signal, 0.0)
                        self.notifier.notify_order(ticker, signal, price, shares)
                        logger.info(f"  [LIVE] Shoonya Order placed: {signal} {shares}×{ticker} @ INR{price:.2f} (order_id: {order.get('order_id')})")
                    else:
                        logger.error(f"  [LIVE] Shoonya Order failed: {order.get('error')}")
                else:
                    logger.error("  [LIVE] Order failed: Shoonya login failed. Check credentials in .env")
                    
            except Exception as e:
                logger.error(f"  Order execution error: {e}")

        if signal == 'BUY':
            try:
                self.lifecycle_manager.create_prediction(ticker, 'BUY', price, analysis)
            except Exception as e:
                logger.warning(f"  Lifecycle creation failed: {e}")

    def run_breakout_scan(self):
        logger.info("[BREAKOUT] Scanning for 52-week high breakouts...")
        all_tickers = self.nse_fetcher.get_nifty_50_tickers()
        breakouts   = self.breakout_strategy.find_breakouts(all_tickers)

        if not breakouts:
            logger.info("  No breakouts found today.")
            return []

        logger.info(f"  {len(breakouts)} breakout(s) found:")
        for b in breakouts:
            logger.info(
                f"  {b['ticker']:<15} Vol: {b['volume_ratio']:.1f}x  "
                f"Entry: INR{b['entry_price']}  Target: INR{b['target']}  Stop: INR{b['stop_loss']}  "
                f"Conf: {b['confidence']:.0%}"
            )
            if b['confidence'] >= indian_cfg.MIN_CONFIDENCE_SWING:
                self.execute_signal(b['ticker'], b)
        return breakouts

    def run_sector_rotation(self):
        logger.info("[SECTOR] Calculating NSE sector performance (1 month)...")
        perf = self.sector_rotation.get_sector_performance()
        for sector, ret in perf.items():
            arrow = "▲" if ret > 0 else "▼"
            logger.info(f"  {sector:<10}: {arrow} {ret:+.2f}%")
        top = list(perf.keys())[:2]
        logger.info(f"\n  Recommended sectors this month: {', '.join(top)}")
        return perf

    def run_orb_scan(self, tickers=None):
        import pytz
        from datetime import datetime
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            logger.info("[ORB] Market not open yet or ORB window not complete")
            return []
        tickers = tickers or self.nse_fetcher.get_nifty_50_tickers()[:20]
        signals = []
        for ticker in tickers:
            try:
                result = self.orb_strategy.analyze(ticker)
                if result.get('signal') in ('BUY', 'SELL'):
                    logger.info(
                        f"  [ORB] {ticker:<15} {result['signal']}  "
                        f"Conf: {result['confidence']:.0%}  "
                        f"Entry: INR{result.get('current_price','—')}  "
                        f"Stop: INR{result.get('stop_loss','—')}  "
                        f"Target: INR{result.get('price_target','—')}"
                    )
                    signals.append(result)
                    if result['confidence'] >= indian_cfg.MIN_CONFIDENCE_INTRADAY:
                        self.execute_signal(ticker, result)
            except Exception as e:
                logger.debug(f"ORB error for {ticker}: {e}")
        if not signals:
            logger.info("[ORB] No breakouts detected yet")
        return signals

    def show_performance(self):
        logger.info("\n[PERFORMANCE] Strategy attribution leaderboard:")
        self.perf_tracker.print_leaderboard()
        weights = self.perf_tracker.get_decayed_algorithm_weights()
        logger.info("Dynamic algorithm weights (recent performance decay):")
        for algo, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            bar = '█' * int(w * 5)
            logger.info(f"  {algo:<22}: {w:.2f}  {bar}")

    def watch_mode(self, refresh_minutes: int = 15):
        logger.info(f"\n[WATCH] Starting live watch mode (refresh: {refresh_minutes} min)...")
        logger.info("Press Ctrl+C to stop\n")

        def _watch_cycle():
            self.paper_trade_manager.close_positions(perf_tracker=self.perf_tracker)

            try:
                opportunities = self.screener.get_top_opportunities(max_results=5)
                logger.info(f"\n{'=' * 60}")
                logger.info(f"  Watch Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'=' * 60}")
                for opp in opportunities:
                    try:
                        analysis = self.analyze_ticker(opp['ticker'], detailed=False)
                        if 'error' not in analysis:
                            logger.info(f"  {opp['ticker']}: {analysis['signal']} @ INR{analysis.get('current_price', 0):.2f} (Conf: {analysis['confidence']:.1%})")
                            if analysis.get('signal') in ('BUY', 'SELL') and analysis.get('confidence', 0) >= indian_cfg.MIN_CONFIDENCE_SWING:
                                self.execute_signal(opp['ticker'], analysis)
                    except Exception as ticker_err:
                        logger.warning(f"  Cycle error for {opp['ticker']}: {ticker_err}")
            except Exception as cycle_err:
                logger.error(f"Watch cycle failed (will retry next interval): {cycle_err}")

        _watch_cycle()
        schedule.every(refresh_minutes).minutes.do(_watch_cycle)
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nWatch mode stopped.")

    def show_memory(self, ticker: str = None):
        logger.info(f"\n[MEMORY] Prediction Memory")
        if ticker:
            ticker = self.normalize_ticker(ticker)
            stats = self.memory.get_ticker_stats(ticker)
            logger.info(f"\n  Stats for {ticker}:")
            logger.info(f"    Total Predictions: {stats['total_predictions']}")
            logger.info(f"    Accuracy: {stats['prediction_accuracy']:.1%}")
            logger.info(f"    Signal Distribution: {stats['signal_distribution']}")
        else:
            accuracy = self.memory.get_prediction_accuracy()
            logger.info(f"\n  Overall Accuracy: {accuracy.get('accuracy', 0):.1%}")
            logger.info(f"  Total Predictions: {accuracy.get('total', 0)}")
            logger.info(f"  Correct: {accuracy.get('correct', 0)}")

    def show_lifecycle(self, ticker: str = None):
        logger.info(f"\n[LIFECYCLE] Active Predictions")
        if ticker:
            ticker = self.normalize_ticker(ticker)
            active = self.lifecycle_manager.get_active_for_ticker(ticker)
            logger.info(f"\n  Active predictions for {ticker}:")
        else:
            active = self.lifecycle_manager.get_active_predictions()
            logger.info(f"\n  All active predictions ({len(active)} total):")

        if not active:
            logger.info("  No active predictions found.")
            return

        for pred in active:
            logger.info(f"\n{'=' * 50}")
            logger.info(f"  ID: {pred['id']} | Ticker: {pred['ticker']}")
            logger.info(f"  Entry: INR{pred['entry']['price']:.2f} on {pred['entry']['date']}")
            logger.info(f"  Target: INR{pred['exit_plan']['target_price']:.2f} | Stop: INR{pred['exit_plan']['stop_loss']:.2f}")

            try:
                ticker_obj = yf.Ticker(pred['ticker'])
                hist = ticker_obj.history(period='1d')
                if not hist.empty:
                    current = hist['Close'].iloc[-1]
                    pnl_pct = ((current - pred['entry']['price']) / pred['entry']['price']) * 100
                    pnl_color = '+' if pnl_pct >= 0 else ''
                    logger.info(f"  Current: INR{current:.2f} | P&L: {pnl_color}{pnl_pct:.2f}%")
            except Exception as e:
                logger.debug(f"Unable to fetch price for {pred['ticker']}: {e}")

    def check_sell(self, ticker: str):
        ticker = self.normalize_ticker(ticker)
        logger.info(f"\n[CHECK SELL] Checking {ticker}...")

        result = self.lifecycle_manager.should_sell_now(ticker)

        logger.info(f"\n  Ticker: {ticker}")
        logger.info(f"  Should Sell: {result['sell']}")
        logger.info(f"  Reason: {result['reason']}")
        logger.info(f"  Confidence: {result['confidence']:.1%}")

        if 'pnl_pct' in result:
            pnl = result['pnl_pct']
            pnl_color = '+' if pnl >= 0 else ''
            logger.info(f"  P&L: {pnl_color}{pnl:.2f}%")
        return result

    def analyze_options(self, ticker: str):
        ticker = self.normalize_ticker(ticker)
        logger.info(f"[OPTIONS] Analyzing options for {ticker}...")

        stock_analysis = self.analyze_ticker(ticker, detailed=False)
        direction = 'BULLISH' if stock_analysis.get('signal') == 'BUY' else 'BEARISH' if stock_analysis.get('signal') == 'SELL' else 'NEUTRAL'

        chain = self.options_analyzer.get_options_chain(ticker)
        if 'error' in chain:
            logger.error(f"  Error: {chain['error']}")
            return chain

        logger.info(f"\n  Options Expiration: {chain['expiration']}")
        logger.info(f"  Calls Available: {len(chain['calls'])}")
        logger.info(f"  Puts Available: {len(chain['puts'])}")

        unusual = self.options_analyzer.detect_unusual_options_activity(ticker)
        if unusual.get('unusual_activity'):
            logger.warning(f"\n  UNUSUAL OPTIONS ACTIVITY DETECTED!")
            logger.warning(f"  Activity Count: {unusual['activity_count']}")
            for act in unusual['activities'][:5]:
                logger.warning(f"    - {act['type']} @ INR{act['strike']}: Volume {act['volume']} (Avg: {act['avg_volume']:.0f})")

        strategies = self.options_analyzer.suggest_options_strategy(ticker, direction)
        if 'error' not in strategies:
            logger.info(f"\n  Suggested Strategies for {direction} outlook:")
            for s in strategies['suggested_strategies']:
                logger.info(f"    - {s['name']}: {s['description']}")
                logger.info(f"      Risk: {s['risk']} | Best if: {s['best_if']}")

        return {'chain': chain, 'unusual': unusual, 'strategies': strategies}

    def analyze_indian_index(self, index: str = 'NIFTY50'):
        logger.info(f"[INDEX] Analyzing {index}...")

        index_map = {
            'NIFTY50': '^NSEI',
            'BANKNIFTY': '^NSEBANK',
        }

        symbol = index_map.get(index.upper())
        if not symbol:
            logger.error(f"Unknown index: {index}")
            return None

        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='6mo')

            if hist.empty or len(hist) < 50:
                logger.warning("No data available")
                return None

            current_price = hist['Close'].iloc[-1]

            ma_20 = hist['Close'].rolling(20).mean().iloc[-1]
            ma_50 = hist['Close'].rolling(50).mean().iloc[-1]
            ma_200 = hist['Close'].rolling(200).mean().iloc[-1] if len(hist) >= 200 else ma_50

            logger.info(f"\n  {index} Analysis:")
            logger.info(f"  Current Price: {current_price:.2f}")
            logger.info(f"  20-day MA: {ma_20:.2f}")
            logger.info(f"  50-day MA: {ma_50:.2f}")
            logger.info(f"  200-day MA: {ma_200:.2f}")

            if current_price > ma_20 > ma_50 > ma_200:
                signal = 'BULLISH'
            elif current_price < ma_20 < ma_50:
                signal = 'BEARISH'
            else:
                signal = 'NEUTRAL'

            logger.info(f"  Signal: {signal}")
            return {
                'index': index, 'price': current_price,
                'ma_20': ma_20, 'ma_50': ma_50, 'ma_200': ma_200,
                'signal': signal
            }
        except Exception as e:
            logger.error(f"Error: {e}")
            return None

    def run_backtest(self, ticker: str, strategy: str = 'ma_crossover', days: int = 252):
        ticker = self.normalize_ticker(ticker)
        logger.info(f"[BACKTEST] Running backtest for {ticker}...")

        start_date = (datetime.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        if strategy == 'dalio_all_weather':
            logger.error("DalioAllWeather strategy is not available for Indian markets (NSE/BSE)")
            return
        elif strategy in ('indian_momentum', 'bulls_ai_momentum', 'buffett_value',
                          'dalio_all_weather', 'nifty_options_writer'):
            selector = AlgorithmSelector(market='IN')
            algo = selector.algorithms.get(strategy)
            if algo is None:
                result = {'error': f"Unknown algorithm strategy: {strategy}"}
            else:
                result = self.backtester.backtest_algorithm(algo, ticker, start_date, end_date)
        else:
            logger.error(f"Unknown strategy: {strategy}")
            return None

        if 'error' in result:
            logger.error(f"  Error: {result['error']}")
            return result

        logger.info(f"\n  Strategy: {result.get('strategy', 'N/A')}")
        logger.info(f"  Return: {result.get('return_pct', 0):.2f}%")
        logger.info(f"  Final Value: INR{result.get('final_value', 0):.2f}")
        logger.info(f"  Total Trades: {result.get('total_trades', 0)}")

        if 'max_drawdown_pct' in result:
            logger.info(f"  Max Drawdown: {result['max_drawdown_pct']:.2f}%")

        output_file = OUTPUT_DIR / f"{ticker}_{strategy}_backtest.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"\n  Results saved to: {output_file}")

        self.visualizer.plot_backtest_results({'strategies': {strategy: result}})
        return result

    def run_walk_forward(self, ticker: str, strategy: str = 'indian_momentum',
                         days: int = 756, train_bars: int = 180,
                         test_bars: int = 60):
        ticker = self.normalize_ticker(ticker)
        logger.info(f"[WALKFORWARD] {ticker} strategy={strategy}")

        data = yf.download(ticker, period=f"{days}d", progress=False, auto_adjust=True)
        data = self.backtester._flatten_df(data)
        if data.empty:
            result = {'error': 'No market data available'}
        else:
            selector = AlgorithmSelector(market='IN')
            algo = selector.algorithms.get(strategy)
            if algo is None:
                result = {'error': f"Unknown walk-forward strategy: {strategy}"}
            else:
                validator = WalkForwardValidator(WalkForwardConfig(
                    initial_capital=self.backtester.initial_capital,
                    train_bars=train_bars, test_bars=test_bars,
                ))
                result = validator.evaluate_algorithm(algo, ticker, data)

        if 'error' in result:
            logger.error(f"  Error: {result['error']}")
            return result

        summary = result['summary']
        logger.info(f"  Folds: {summary['fold_count']}")
        logger.info(f"  Median Return: {summary['median_return_pct']:.2f}%")
        logger.info(f"  Profitable Fold Rate: {summary['profitable_fold_rate']:.0%}")
        logger.info(f"  Worst Drawdown: {summary['worst_drawdown_pct']:.2f}%")
        logger.info(f"  Robust Score: {summary['robust_score']:.2f}")

        output_file = OUTPUT_DIR / f"{ticker}_{strategy}_walk_forward.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"\n  Walk-forward results saved to: {output_file}")
        return result


def kill_switch():
    from utils.notifier import Notifier
    from utils.risk_manager import RiskManager

    notifier = Notifier()
    notifier.notify_killswitch()

    from pathlib import Path
    kill_file = Path('kill_switch.active')
    kill_file.touch()
    print("KILL-SWITCH ACTIVATED - All trading disabled")
    return {'status': 'disabled'}


def main():
    parser = argparse.ArgumentParser(description='SmartTrader - Indian Market (NSE/BSE) Trading Analysis System')
    parser.add_argument('--mode', type=str, default='screen',
                        choices=['screen', 'analyze', 'options', 'backtest', 'walk-forward', 'watch', 'memory', 'index', 'lifecycle', 'check-sell', 'kill-switch', 'breakout', 'sectors', 'orb', 'perf', 'paper-summary'],
                        help='Operation mode')
    parser.add_argument('--kill-switch', action='store_true', help='Emergency stop')
    parser.add_argument('--ticker', type=str, help='Ticker symbol')
    parser.add_argument('--strategy', type=str, default='ma_crossover',
                        choices=['ma_crossover', 'rsi', 'buy_hold', 'compare',
                                 'indian_momentum', 'bulls_ai_momentum', 'buffett_value', 'dalio_all_weather', 'nifty_options_writer'],
                        help='Backtest strategy')
    parser.add_argument('--days', type=int, default=252, help='Backtest period')
    parser.add_argument('--train-bars', type=int, default=180, help='Walk-forward training bars')
    parser.add_argument('--test-bars', type=int, default=60, help='Walk-forward test bars')
    parser.add_argument('--force', action='store_true', help='Force recomputation')
    parser.add_argument('--paper', action='store_true', default=True, help='Paper trading')
    parser.add_argument('--live', action='store_true', help='Enable live orders')
    parser.add_argument('--index', type=str, default='NIFTY50', help='Index to analyze')
    args = parser.parse_args()

    if args.kill_switch:
        kill_switch()
        return

    trader = SmartTrader()
    trader.paper_trade = not args.live
    trader.auto_trade  = args.live
    if args.live:
        logger.warning("LIVE TRADING MODE ENABLED — real orders will be placed!")
        if not trader.shoonya.login():
            logger.error("Failed to login to Shoonya. Please verify SHOONYA_* credentials in .env")
            if not args.force:
                return
    else:
        logger.info("Paper trading mode active (use --live to enable real execution)")

    if args.mode == 'screen':
        trader.screen_opportunities()
    elif args.mode == 'analyze':
        if not args.ticker:
            logger.error("Error: --ticker required")
            return
        trader.analyze_ticker(args.ticker, force=args.force)
    elif args.mode == 'options':
        if not args.ticker:
            logger.error("Error: --ticker required")
            return
        trader.analyze_options(args.ticker)
    elif args.mode == 'backtest':
        if not args.ticker:
            logger.error("Error: --ticker required")
            return
        trader.run_backtest(args.ticker, args.strategy, args.days)
    elif args.mode == 'walk-forward':
        if not args.ticker:
            logger.error("Error: --ticker required")
            return
        trader.run_walk_forward(args.ticker, args.strategy, args.days,
                               train_bars=args.train_bars, test_bars=args.test_bars)
    elif args.mode == 'watch':
        trader.watch_mode()
    elif args.mode == 'memory':
        trader.show_memory(args.ticker)
    elif args.mode == 'index':
        trader.analyze_indian_index(args.index)
    elif args.mode == 'lifecycle':
        trader.show_lifecycle(args.ticker)
    elif args.mode == 'check-sell':
        if not args.ticker:
            logger.error("Error: --ticker required")
            return
        trader.check_sell(args.ticker)
    elif args.mode == 'breakout':
        trader.run_breakout_scan()
    elif args.mode == 'sectors':
        trader.run_sector_rotation()
    elif args.mode == 'orb':
        trader.run_orb_scan()
    elif args.mode == 'perf':
        trader.show_performance()
    elif args.mode == 'paper-summary':
        trader.show_paper_summary()


if __name__ == "__main__":
    main()
