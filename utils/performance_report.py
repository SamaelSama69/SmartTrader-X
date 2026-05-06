"""
Performance Report Generator
Calculates advanced metrics like Sharpe Ratio, Drawdowns, and Equity Curve.
"""
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px

class PerformanceReport:
    @staticmethod
    def generate_metrics(trades: list, initial_capital: float = 100000.0):
        if not trades:
            return None
            
        df = pd.DataFrame(trades)
        if 'pnl_pct' not in df.columns:
            return None

        # Basic Stats
        closed_trades = df[df['status'] == 'CLOSED'].copy()
        if closed_trades.empty:
            return {"status": "No closed trades yet"}

        win_rate = len(closed_trades[closed_trades['pnl_pct'] > 0]) / len(closed_trades)
        total_pnl_pct = closed_trades['pnl_pct'].sum()
        avg_pnl_pct = closed_trades['pnl_pct'].mean()
        
        # Risk Metrics
        returns = closed_trades['pnl_pct']
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        # Drawdown
        equity_curve = (1 + returns).cumprod()
        running_max = equity_curve.cummax()
        drawdown = (equity_curve - running_max) / running_max
        max_drawdown = drawdown.min()

        return {
            "total_trades": len(df),
            "closed_trades": len(closed_trades),
            "win_rate": f"{win_rate:.1%}",
            "total_return": f"{total_pnl_pct:.2%}",
            "avg_return": f"{avg_pnl_pct:.2%}",
            "sharpe_ratio": f"{sharpe:.2f}",
            "max_drawdown": f"{max_drawdown:.2%}",
            "profit_factor": f"{abs(returns[returns > 0].sum() / returns[returns < 0].sum()):.2f}" if returns[returns < 0].sum() != 0 else "Inf"
        }

    @staticmethod
    def plot_equity_curve(trades: list, initial_capital: float = 100000.0):
        if not trades: return None
        df = pd.DataFrame(trades)
        closed = df[df['status'] == 'CLOSED'].sort_values('closed_at')
        if closed.empty: return None
        
        closed['cumulative_pnl'] = closed['pnl_pct'].cumsum()
        closed['equity'] = initial_capital * (1 + closed['cumulative_pnl'])
        
        fig = px.line(closed, x='closed_at', y='equity', title="Equity Curve (Paper Portfolio)",
                     template="plotly_dark", color_discrete_sequence=["#00FFA3"])
        fig.update_layout(xaxis_title="Date", yaxis_title="Portfolio Value (INR)")
        return fig
