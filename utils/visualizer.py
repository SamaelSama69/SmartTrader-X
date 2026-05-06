"""
Visualization Utilities
Creates charts and dashboards for analysis results
"""

import logging
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from datetime import datetime
from config import OUTPUT_DIR

logger = logging.getLogger(__name__)

# Set style
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")


class Visualizer:
    """Create charts for trading analysis"""

    def __init__(self):
        self.output_dir = OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def plot_price_with_signals(self, ticker: str, signals: pd.DataFrame = None):
        """Plot price chart with buy/sell signals"""
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period='6mo')

            if hist.empty:
                logger.warning(f"No data for {ticker}")
                return

            fig, ax = plt.subplots(figsize=(12, 6))
            ax.plot(hist.index, hist['Close'], label='Close Price', linewidth=2)

            # Add moving averages
            ma20 = hist['Close'].rolling(20).mean()
            ma50 = hist['Close'].rolling(50).mean()
            ax.plot(hist.index, ma20, label='MA 20', alpha=0.7, linestyle='--')
            ax.plot(hist.index, ma50, label='MA 50', alpha=0.7, linestyle='--')

            ax.set_title(f'{ticker} Price Chart', fontsize=14)
            ax.set_xlabel('Date')
            ax.set_ylabel('Price ($)')
            ax.legend()
            ax.grid(True, alpha=0.3)

            plt.tight_layout()
            output_path = self.output_dir / f"{ticker}_price_chart.png"
            plt.savefig(output_path, dpi=150)
            plt.close()
            logger.info(f"Saved: {output_path}")

        except Exception as e:
            logger.error(f"Chart error: {e}")

    def plot_sentiment_gauge(self, sentiment_score: float, ticker: str):
        """Create a gauge chart for sentiment"""
        try:
            fig, ax = plt.subplots(figsize=(8, 4))

            # Create gauge
            colors = ['#FF4444', '#FFA500', '#FFFF00', '#90EE90', '#00CC00']
            labels = ['Very Negative', 'Negative', 'Neutral', 'Positive', 'Very Positive']

            # Simple horizontal bar
            ax.barh(0, 1, color='lightgray', height=0.3)
            color_idx = min(int((sentiment_score + 1) / 2 * 5), 4)
            ax.barh(0, (sentiment_score + 1) / 2, color=colors[color_idx], height=0.3)

            ax.set_xlim(0, 1)
            ax.set_ylim(-0.5, 0.5)
            ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
            ax.set_xticklabels(['-1', '-0.5', '0', '0.5', '1'])
            ax.set_yticks([])
            ax.set_title(f'{ticker} Sentiment: {sentiment_score:.2f}', fontsize=12)

            plt.tight_layout()
            output_path = self.output_dir / f"{ticker}_sentiment.png"
            plt.savefig(output_path, dpi=150)
            plt.close()
            logger.info(f"Saved: {output_path}")

        except Exception as e:
            logger.error(f"Gauge error: {e}")

    def plot_backtest_results(self, backtest_results: Dict):
        """Plot backtest equity curve"""
        try:
            if 'error' in backtest_results:
                logger.warning(f"Cannot plot: {backtest_results['error']}")
                return

            # This is simplified - would need equity curve data
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

            # Return comparison
            strategies = backtest_results.get('strategies', {})
            names = list(strategies.keys())
            returns = [strategies[n].get('return_pct', 0) for n in names]

            ax1.bar(names, returns, color=['green' if r > 0 else 'red' for r in returns])
            ax1.set_title('Strategy Returns Comparison')
            ax1.set_ylabel('Return (%)')
            ax1.tick_params(axis='x', rotation=45)

            # Drawdown (placeholder)
            ax2.text(0.5, 0.5, 'Equity curve data needed\nfrom backtest engine',
                     horizontalalignment='center', verticalalignment='center')
            ax2.set_title('Equity Curve')
            ax2.axis('off')

            plt.tight_layout()
            output_path = self.output_dir / "backtest_results.png"
            plt.savefig(output_path, dpi=150)
            plt.close()
            logger.info(f"Saved: {output_path}")

        except Exception as e:
            logger.error(f"Backtest plot error: {e}")

    def plot_screener_results(self, results: List[Dict]):
        """Plot top screened stocks"""
        if not results:
            return

        try:
            df = pd.DataFrame(results[:10])  # Top 10

            fig, ax = plt.subplots(figsize=(12, 6))

            colors = ['green' if x > 0 else 'red' for x in df['price_change_1m']]
            ax.barh(df['ticker'], df['price_change_1m'], color=colors)
            ax.set_xlabel('1-Month Price Change (%)')
            ax.set_title('Top Screening Results - 1 Month Performance')
            ax.axvline(x=0, color='black', linewidth=0.5)

            plt.tight_layout()
            output_path = self.output_dir / "screener_results.png"
            plt.savefig(output_path, dpi=150)
            plt.close()
            logger.info(f"Saved: {output_path}")

        except Exception as e:
            logger.error(f"Screener plot error: {e}")

    def create_summary_dashboard(self, analysis: Dict):
        """Create a summary dashboard image"""
        try:
            fig = plt.figure(figsize=(14, 10))
            fig.suptitle(f"Trading Analysis Dashboard - {analysis.get('ticker', 'N/A')}",
                        fontsize=16, fontweight='bold')

            # Price chart (top left)
            ax1 = plt.subplot(2, 2, 1)
            try:
                import yfinance as yf
                hist = yf.Ticker(analysis.get('ticker', 'AAPL')).history(period='3mo')
                if not hist.empty:
                    ax1.plot(hist.index, hist['Close'])
                    ax1.set_title('Price History (3mo)')
                    ax1.set_ylabel('Price ($)')
                    ax1.tick_params(axis='x', rotation=45)
            except Exception as e:
                logger.debug(f"Price plot failed: {e}")
                ax1.text(0.5, 0.5, 'No price data', ha='center', va='center')
                ax1.axis('off')

            # Signal summary (top right)
            ax2 = plt.subplot(2, 2, 2)
            signal = analysis.get('signal', 'HOLD')
            confidence = analysis.get('confidence', 0)
            color = 'green' if signal == 'BUY' else 'red' if signal == 'SELL' else 'gray'

            ax2.text(0.5, 0.6, signal, fontsize=24, ha='center', color=color, fontweight='bold')
            ax2.text(0.5, 0.4, f'Confidence: {confidence:.1%}', fontsize=14, ha='center')
            ax2.axis('off')
            ax2.set_title('Trading Signal')

            # Technical indicators (bottom left)
            ax3 = plt.subplot(2, 2, 3)
            tech = analysis.get('factors', {}).get('technical', {})
            if tech:
                indicators = ['rsi', 'macd_signal', 'ma_signal']
                values = [tech.get('rsi', 50), 1 if tech.get('macd_signal') == 'BULLISH' else -1, 1 if tech.get('ma_signal') == 'BULLISH' else -1]
                ax3.bar(indicators, values, color=['blue', 'green', 'orange'])
                ax3.set_title('Key Technical Indicators')
                ax3.set_ylabel('Signal')
            else:
                ax3.text(0.5, 0.5, 'No technical data', ha='center', va='center')
                ax3.axis('off')

            # Sentiment (bottom right)
            ax4 = plt.subplot(2, 2, 4)
            sentiment = analysis.get('factors', {}).get('sentiment', {})
            if sentiment:
                score = sentiment.get('aggregate_sentiment', 0)
                ax4.barh(0, score, color='green' if score > 0 else 'red', height=0.3)
                ax4.axvline(x=0, color='black')
                ax4.set_xlim(-1, 1)
                ax4.set_title(f'Sentiment Score: {score:.2f}')
                ax4.set_yticks([])
            else:
                ax4.text(0.5, 0.5, 'No sentiment data', ha='center', va='center')
                ax4.axis('off')

            plt.tight_layout()
            output_path = self.output_dir / f"{analysis.get('ticker', 'dashboard')}_summary.png"
            plt.savefig(output_path, dpi=150)
            plt.close()
            logger.info(f"Saved: {output_path}")

        except Exception as e:
            logger.error(f"Dashboard error: {e}")
