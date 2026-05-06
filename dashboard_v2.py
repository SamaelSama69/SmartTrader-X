"""
SmartTrader Pro Dashboard v2.0
A high-performance, beautiful GUI for Indian Market Analysis.
Built with Streamlit, Plotly, and real-time news integration.
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from pathlib import Path
import sys
import os
import json
import threading
import time
import difflib

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.multilingual_sentiment import get_news_aggregator
from utils.market_regime import IndianMarketRegime
from strategies.indian_momentum import IndianMomentumStrategy
from strategies.stocks import SectorRotationStrategy
from utils.paper_trade_manager import PaperTradeManager
from utils.shoonya_broker import ShoonyaBroker
from utils.nse_data import get_nifty_universe
from utils.performance_tracker import StrategyPerformanceTracker
from utils.risk_manager import RiskManager
from utils.performance_report import PerformanceReport
from utils.trends_fetcher import TrendingFetcher
from utils.sentiment_db import SentimentDB

# --- CONFIGURATION ---
st.set_page_config(
    page_title="SmartTrader Pro | Indian Markets",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- SESSION STATE INITIALIZATION ---
def init_session_state():
    if 'shoonya' not in st.session_state:
        st.session_state.shoonya = ShoonyaBroker()
    if 'risk_mgr' not in st.session_state:
        st.session_state.risk_mgr = RiskManager()
    if 'paper_mgr' not in st.session_state:
        try:
            st.session_state.paper_mgr = PaperTradeManager()
        except Exception as e:
            st.error(f"Failed to initialize PaperTradeManager: {e}")
            
    # Persistent Analysis State
    if 'analysis_result' not in st.session_state:
        st.session_state.analysis_result = None
    if 'analysis_ticker' not in st.session_state:
        st.session_state.analysis_ticker = ""

init_session_state()

# --- PERSISTENT DATA LINKS ---
BOT_SCAN_FILE = Path("memory/latest_scan_results.json")

def load_shared_bot_data():
    """Loads all market data pre-fetched by the background bot."""
    if BOT_SCAN_FILE.exists():
        try:
            with open(BOT_SCAN_FILE, 'r') as f:
                return json.load(f)
        except: return {}
    return {}

# --- CACHED DATA FETCHERS ---
@st.cache_data(ttl=300)
def fetch_stock_data(ticker, period="1y"):
    if not ticker.startswith("^") and not ticker.endswith((".NS", ".BO")):
        ticker += ".NS"
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df.empty: return pd.DataFrame()
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_convert(None)
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=900)
def fetch_sector_sentiment():
    try:
        agg = get_news_aggregator()
        sectors = SectorRotationStrategy().SECTOR_TICKERS
        return agg.get_sector_sentiment_map(sectors)
    except: return {}

def repair_missing_targets(trade):
    """Calculate and save SL/TP for trades that are missing them."""
    ticker = trade['ticker']
    df = fetch_stock_data(ticker, period="1y")
    if df.empty or len(df) < 14: return
    high_low = df['High'] - df['Low']; high_close = np.abs(df['High'] - df['Close'].shift()); low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]; curr_price = df['Close'].iloc[-1]
    if trade['signal'] == 'BUY':
        sl = round(curr_price - 2.5 * atr, 2); tp = round(curr_price + 5.0 * atr, 2)
    else:
        sl = round(curr_price + 2.5 * atr, 2); tp = round(curr_price - 5.0 * atr, 2)
    st.session_state.paper_mgr.update_trade_targets(trade['id'], sl, tp, source='USER')
    return sl, tp

# --- CUSTOM CSS ---
st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #E0E0E0; }
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: 700 !important; color: #00FFA3 !important; }
    .main-title { font-size: 2.2rem; font-weight: 800; background: linear-gradient(90deg, #00FFA3 0%, #00D1FF 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .metric-card { background-color: #1A1C24; padding: 15px; border-radius: 10px; border: 1px solid #2A2D35; }
    .pos-val { color: #00FFA3 !important; }
    .neg-val { color: #FF4B4B !important; }
    .news-card { background-color: #1A1C24; padding: 12px; border-radius: 8px; border-left: 4px solid #00FFA3; margin-bottom: 10px; }
    .sentiment-tag { font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; text-transform: uppercase; font-weight: bold; }
    .sent-pos { background-color: #00FFA3; color: #0E1117; }
    .sent-neg { background-color: #FF4B4B; color: #FFFFFF; }
    .sent-neu { background-color: #555; color: #FFFFFF; }
</style>
""", unsafe_allow_html=True)

def render_profit_metric(label, value, delta=None):
    """Render a metric that turns red when negative, else uses the default green."""
    is_neg = False
    try:
        v_str = str(value).replace('₹', '').replace('%', '').replace(',', '').strip()
        is_neg = float(v_str) < 0
    except: pass
    
    val_class = "neg-val" if is_neg else "pos-val"
    delta_html = ""
    if delta:
        d_color = "#FF4B4B" if is_neg else "#00FFA3"
        delta_html = f'<div style="color: {d_color}; font-size: 0.8rem; font-weight: 500;">{delta}</div>'

    st.markdown(f"""
        <div class="metric-card">
            <div style="color: #888; font-size: 0.8rem; margin-bottom: 5px;">{label}</div>
            <div class="{val_class}" style="font-size: 1.8rem; font-weight: 700; line-height: 1.2;">{value}</div>
            {delta_html}
        </div>
    """, unsafe_allow_html=True)

# --- COMPONENTS ---
def render_sidebar(bot_data):
    with st.sidebar:
        st.title("SmartTrader Pro")
        menu = st.radio("Navigation", ["Market Pulse", "News Hub", "Strategy Scanner", "Deep Analysis", "Portfolio Hub", "Performance Report", "Actions Hub", "Log Viewer", "Help & Guides"])
        st.divider()
        st.subheader("Broker (Shoonya)")
        if not st.session_state.shoonya.is_logged_in:
            if st.button("Login 🔑"):
                if st.session_state.shoonya.login(): st.rerun()
        else:
            st.success(f"Connected: {st.session_state.shoonya.user_id}")
            if st.button("Logout"): st.session_state.shoonya.is_logged_in = False; st.rerun()
        st.subheader("🛡️ Risk Monitor")
        risk = st.session_state.risk_mgr.get_drawdown_stats(); dd = risk['drawdown_pct']
        color = "#00FFA3" if dd < 3 else "#FFA500" if dd < 5 else "#FF4B4B"
        st.markdown(f"Drawdown: <span style='color:{color}; font-weight:bold;'>{dd:.2f}%</span>", unsafe_allow_html=True)
        if st.button("Sync Risk Monitor 🔄", width="stretch"):
            pos = st.session_state.paper_mgr.get_open_positions()
            if not hasattr(st.session_state.risk_mgr, 'sync_with_manager'):
                from utils.risk_manager import RiskManager
                st.session_state.risk_mgr = RiskManager()
            st.session_state.risk_mgr.sync_with_manager(pos)
            st.success("Synced!")
            st.rerun()

        st.subheader("Bot Status")
        # --- HEARTBEAT CHECK ---
        last_updated_str = bot_data.get('last_updated', 'Pending')
        is_active = False
        if last_updated_str != 'Pending':
            try:
                # Get file modification time
                mtime = BOT_SCAN_FILE.stat().st_mtime
                # Consider active if updated in last 20 minutes (allowing for deep scans)
                if (time.time() - mtime) < 1200:
                    is_active = True
            except: pass

        if is_active:
            st.markdown(f"Auto Bot: <span style='color:#00FFA3;'>● RUNNING</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"Auto Bot: <span style='color:#FF4B4B;'>● OFFLINE</span>", unsafe_allow_html=True)
            st.caption("Last activity over 20m ago.")
        st.caption(f"Last Scan: {last_updated_str}")

        if st.button("Refresh Market Data 🔄", width="stretch"):
            st.cache_data.clear()
            st.success("Cache cleared! Fetching fresh data...")
            time.sleep(1)
            st.rerun()
        
        st.subheader("Market Regime")
        regime = bot_data.get('regime', 'BEAR_TREND').upper()
        r_color = "#00FFA3" if "BULL" in regime else "#FF4B4B" if "BEAR" in regime else "#00D1FF"
        st.markdown(f"""
            <div style="background-color: {r_color}22; padding: 10px; border-radius: 5px; border-left: 5px solid {r_color};">
                <span style="color: {r_color}; font-weight: bold; font-size: 1.1em;">{regime.replace('_', ' ')}</span>
            </div>
        """, unsafe_allow_html=True)
        
        metrics = bot_data.get('regime_metrics', {})
        if metrics and isinstance(metrics, dict):
            st.caption(f"**NIFTY Trend**: {metrics.get('trend', 'UNKNOWN')}")
            st.caption(f"**Realized Vol (20d)**: {metrics.get('volatility', 0):.1%}")
            
        vix_val = bot_data.get('indices', {}).get('INDIA VIX', {}).get('price', 0)
        if vix_val:
            st.caption(f"**India VIX**: {vix_val:.2f}")
    return menu

def render_top_bar(bot_data):
    cols = st.columns([2, 1, 1, 1, 1.5])
    with cols[0]: st.markdown('<div class="main-title">SmartTrader Pro</div>', unsafe_allow_html=True)
    idx = bot_data.get('indices', {})
    for i, name in enumerate(["NIFTY 50", "BANK NIFTY", "INDIA VIX"]):
        val = idx.get(name, {"price":0, "pct":0})
        cols[i+1].metric(name, f"{val['price']:,.0f}", f"{val['pct']:+.2f}%", delta_color="inverse" if name=="INDIA VIX" else "normal")
    sent = bot_data.get('market_sentiment', {}).get('aggregate_sentiment', 0.0)
    s_color = "#00FFA3" if sent > 0 else "#FF4B4B" if sent < 0 else "#888"
    with cols[4]: st.markdown(f"**Market Sentiment** <h2 style='color:{s_color}; margin:0;'>{sent:+.2f}</h2>", unsafe_allow_html=True)

def render_market_pulse(bot_data):
    st.divider(); col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("📈 Nifty 50 Trend")
        df = fetch_stock_data("^NSEI")
        if not df.empty:
            fig = px.line(df, y='Close', template="plotly_dark", color_discrete_sequence=["#00FFA3"])
            fig.update_layout(height=350, margin=dict(l=0,r=0,t=0,b=0)); st.plotly_chart(fig, width="stretch")
        st.subheader("🔥 Top Opportunities")
        results = bot_data.get('results', [])
        if results:
            df_res = pd.DataFrame(results[:5])
            display_cols = ['ticker', 'signal', 'confidence', 'momentum']
            for c in display_cols:
                if c not in df_res.columns: df_res[c] = None
            def color_sig_pulse(val): 
                if val == 'BUY': return 'color: #00FFA3'
                if val == 'SHORT': return 'color: #FF4B4B'
                if val == 'SELL': return 'color: #FF9E9E'
                if val == 'WATCH': return 'color: #00D1FF'
                return ''
            try: styled_df_pulse = df_res[display_cols].style.map(color_sig_pulse, subset=['signal'])
            except AttributeError: styled_df_pulse = df_res[display_cols].style.applymap(color_sig_pulse, subset=['signal'])
            st.dataframe(styled_df_pulse, width="stretch", hide_index=True)
    with col2:
        st.subheader("🔍 Local Buzz")
        mkt = bot_data.get('market_sentiment', {}); topics = mkt.get('topics', {}); links = mkt.get('topic_links', {})
        for t, count in list(topics.items())[:5]:
            with st.expander(f"**{t.capitalize()}** ({count} mentions)"):
                for link in links.get(t, [])[:3]: st.markdown(f"🔗 [{link['title'][:50]}...]({link['link']})")
        st.subheader("📰 Market Intelligence")
        for item in bot_data.get('all_news', [])[:6]:
            l = "POS" if item['sentiment'] > 0.05 else "NEG" if item['sentiment'] < -0.05 else "NEU"
            c = "sent-pos" if l == "POS" else "sent-neg" if l == "NEG" else "sent-neu"
            st.markdown(f'<div class="news-card"><div style="display:flex;justify-content:space-between;"><span class="sentiment-tag {c}">{l}</span><span style="font-size:0.6rem;color:#555;">{item["published"][:16]}</span></div><a href="{item["link"]}" style="color:#E0E0E0;text-decoration:none;">{item["title"][:70]}...</a></div>', unsafe_allow_html=True)

def render_news_hub(bot_data):
    st.subheader("📰 Market Intelligence Hub")
    sector_sent = fetch_sector_sentiment()
    if sector_sent:
        scores = list(sector_sent.values()); sectors = list(sector_sent.keys())
        fig = go.Figure(data=go.Heatmap(z=[scores], x=sectors, y=['Sentiment'], colorscale='RdYlGn', zmin=-1, zmax=1, text=[[f"{s:+.2f}" for s in scores]], texttemplate="%{text}"))
        fig.update_layout(height=180, margin=dict(l=0,r=0,t=30,b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis=dict(showticklabels=False), xaxis=dict(side="top"))
        st.plotly_chart(fig, width="stretch")
    for item in bot_data.get('all_news', []):
        label = "POSITIVE" if item['sentiment'] > 0.05 else "NEGATIVE" if item['sentiment'] < -0.05 else "NEUTRAL"
        color = "#00FFA3" if label == "POSITIVE" else "#FF4B4B" if label == "NEGATIVE" else "#888"
        st.markdown(f'<div style="background-color:#1A1C24;padding:15px;border-radius:8px;margin-bottom:15px;border-left:5px solid {color};"><div style="display:flex;justify-content:space-between;"><span style="font-size:0.7rem;color:{color};font-weight:bold;">{label}</span><span style="font-size:0.7rem;color:#555;">{item["source"].upper()} • {item["published"][:16]}</span></div><a href="{item["link"]}" style="color:#E0E0E0;text-decoration:none;font-size:1.1rem;font-weight:600;">{item["title"]}</a><div style="font-size:0.85rem;color:#888;margin-top:5px;">{item["description"]}</div></div>', unsafe_allow_html=True)

def render_deep_analysis():
    col1, col2 = st.columns([1.2, 3]); universe = get_nifty_universe(); discovery_idx = int(time.time() / 30) % len(universe)
    with col1:
        st.subheader("Ticker Analysis")
        ticker = st.selectbox("Search or Select Ticker", options=universe, index=universe.index(st.session_state.analysis_ticker) if st.session_state.analysis_ticker in universe else discovery_idx)
        st.session_state.analysis_ticker = ticker
        analyze_btn = st.button("Deep Scan ⚡", type="primary", width="stretch")
        st.divider(); st.subheader("Execute Trade")
        trade_mode = st.radio("Mode", ["Paper Trading", "Live Trading (Shoonya)"])
        trending_ticker = universe[discovery_idx]
        if st.button(f"💡 Discovery: {trending_ticker} is trending. Analyze?"):
            st.session_state.analysis_ticker = trending_ticker; st.rerun()
    if analyze_btn:
        with st.spinner(f"Analyzing {ticker}..."):
            df = fetch_stock_data(ticker)
            if not df.empty:
                news_sent = get_news_aggregator().get_aggregate_sentiment(ticker)
                result = IndianMomentumStrategy().analyze_ticker(ticker, df, fetch_stock_data("^NSEI"), news_sent['aggregate_sentiment'])
                st.session_state.analysis_result = (result, df)
    if st.session_state.analysis_result:
        result, df = st.session_state.analysis_result
        if result['ticker'] == ticker:
            with col2:
                h_cols = st.columns(5); sig = result['signal']
                sig_c = "#00FFA3" if sig == 'BUY' else "#FF4B4B" if sig in ('SELL', 'SHORT') else "#888"
                h_cols[0].markdown(f"<div style='text-align:center;'><span style='color:#888;font-size:0.8rem;'>SIGNAL</span><br><span style='color:{sig_c};font-size:1.8rem;font-weight:bold;'>{sig}</span></div>", unsafe_allow_html=True)
                h_cols[1].metric("Conviction", f"{result['confidence']:.1%}" if sig != 'HOLD' else "NEUTRAL")
                c_score = result['factors'].get('contrarian_score', 0)
                if c_score is None or pd.isna(c_score): c_score = 0.0
                
                sent_raw = result['factors'].get('sentiment_score', 0)

                # Colour based on BOTH the divergence AND what's driving it
                if c_score > 0.5:
                    # Underdog — good/neutral news but price lagging
                    if sent_raw > 0.2:
                        c_color = "#00FFA3"   # Green — positive sentiment is the driver
                        c_label = "🟢 Underdog (Positive News)"
                    else:
                        c_color = "#FFD700"   # Gold — neutral news, momentum just weak
                        c_label = "🟡 Underdog (Neutral News)"
                elif c_score < -0.5:
                    # Overextended — price running hard despite bad/neutral news
                    if sent_raw < -0.2:
                        c_color = "#FF4B4B"   # Red — negative sentiment driving divergence
                        c_label = "🔴 Overextended (Negative News)"
                    else:
                        c_color = "#FF8C00"   # Orange — momentum just running far ahead
                        c_label = "🟠 Overextended (Momentum Only)"
                else:
                    c_color = "#888888"
                    c_label = "⚪ Aligned"

                h_cols[2].markdown(
                    f"""<div style='text-align:center;'>
                        <span style='color:#888;font-size:0.8rem;'>CONTRARIAN</span><br>
                        <span style='color:{c_color};font-size:1.5rem;font-weight:bold;'>{c_score:+.2f}</span><br>
                        <span style='color:{c_color};font-size:0.75rem;'>{c_label}</span>
                    </div>""",
                    unsafe_allow_html=True
                )
                pt = result.get('price_target'); sl = result.get('stop_loss')
                h_cols[3].metric("Target", f"₹{pt:.2f}" if pt else "N/A")
                h_cols[4].metric("Stop Loss", f"₹{sl:.2f}" if sl else "N/A")
                st.markdown(f"<div style='padding:10px;border-radius:5px;background:rgba(255,255,255,0.05);border-left:4px solid {sig_c};'><b>Status:</b> {result['reason']}</div>", unsafe_allow_html=True)
                with st.expander("💼 Trade Execution Hub", expanded=True):
                    try: exec_price = float(df['Close'].dropna().iloc[-1])
                    except: exec_price = result.get('current_price', 1.0)
                    kelly = int(st.session_state.risk_mgr.size_position_kelly(exec_price, result.get('confidence', 0.0)))
                    shares = st.number_input("Order Quantity", min_value=1, value=kelly if kelly > 0 else 1)
                    b1, b2 = st.columns(2)
                    if b1.button("MANUAL BUY (Long)", type="primary", width="stretch"):
                        if trade_mode == "Paper Trading":
                            tid = st.session_state.paper_mgr.open_trade(ticker, 'BUY', exec_price, shares, sl, pt, source='USER')
                            st.success(f"Paper BUY Executed! ID: {tid}")
                    if b2.button("MANUAL SHORT (Sell)", type="secondary", width="stretch"):
                        if trade_mode == "Paper Trading":
                            tid = st.session_state.paper_mgr.open_trade(ticker, 'SHORT', exec_price, shares, sl, pt, source='USER')
                            st.success(f"Paper SHORT Executed! ID: {tid}")
                fig = make_subplots(rows=1, cols=1); fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name=ticker))
                fig.update_layout(template="plotly_dark", height=450, xaxis_rangeslider_visible=False); st.plotly_chart(fig, width="stretch")

def render_portfolio_hub():
    st.subheader("💼 Portfolio Management")
    tabs = st.tabs(["Paper Portfolio", "Shoonya (Live)", "Trade History"])
    with tabs[0]:
        summary = st.session_state.paper_mgr.get_portfolio_summary()
        st.subheader("Live Portfolio Health")
        pnl_amt = 0.0; total_inv = 0.0
        if summary['open_positions']:
            for pos in summary['open_positions']:
                try:
                    curr = yf.Ticker(pos['ticker']).fast_info['lastPrice']
                    pos['current_price'] = curr
                    entry = pos['entry_price']
                    pos['pnl_pct'] = ((curr - entry) / entry) if pos['signal'] == 'BUY' else ((entry - curr) / entry)
                    pnl_amt += pos['pnl_pct'] * entry * pos['shares']; total_inv += entry * pos['shares']
                except: 
                    pos['current_price'] = pos['entry_price']; pos['pnl_pct'] = 0.0
            growth = (pnl_amt / total_inv) * 100 if total_inv > 0 else 0
            h1, h2, h3 = st.columns(3)
            with h1: render_profit_metric("Live Growth", f"{growth:+.2f}%", delta=f"{'↑' if growth >= 0 else '↓'} INR {abs(pnl_amt):,.2f} MTM")
            h2.metric("At Risk", f"INR {total_inv:,.2f}"); h3.metric("Open Pos", summary['open_count'])
            
            # --- RESTORED: Open Positions Table ---
            st.divider(); st.subheader("📂 Active Positions")
            df_open = pd.DataFrame(summary['open_positions'])[['ticker', 'signal', 'entry_price', 'current_price', 'pnl_pct', 'shares', 'stop_loss', 'target']]
            def color_pnl(val): return 'color: #00FFA3' if val > 0 else 'color: #FF4B4B' if val < 0 else ''
            try: styled_open = df_open.style.map(color_pnl, subset=['pnl_pct'])
            except AttributeError: styled_open = df_open.style.applymap(color_pnl, subset=['pnl_pct'])
            st.dataframe(styled_open, width="stretch", hide_index=True)
            
        else: st.info("No open positions.")
        st.divider(); st.subheader("Realized Performance")
        c1, c2 = st.columns(2)
        with c1: render_profit_metric("Realized P&L", f"{summary['realized_pnl_pct']:+.2f}%")
        c2.metric("Win Rate", f"{summary['win_rate']:.1f}%")
        if summary['open_positions']:
            st.divider(); st.subheader("🔍 Position Inspector")
            sel_str = st.selectbox("Select position", options=[f"{p['ticker']} ({p['id'][:8]})" for p in summary['open_positions']])
            trade = next(p for p in summary['open_positions'] if f"{p['ticker']} ({p['id'][:8]})" == sel_str)
            hist = fetch_stock_data(trade['ticker'], period="3mo")
            if not hist.empty:
                curr = float(hist['Close'].dropna().iloc[-1])
                if st.button(f"FORCE CLOSE {trade['ticker']} 🏁", type="primary", width="stretch"):
                    st.session_state.paper_mgr.close_trade(trade['id'], curr, reason="MANUAL_EXIT", source='USER'); st.rerun()
                entry = float(trade['entry_price']); pt = trade.get('target'); sl = trade.get('stop_loss')
                pnl_pct = (curr - entry) / entry if trade['signal'] == 'BUY' else (entry - curr) / entry
                
                # --- ENHANCED: Added Quantity ---
                s_col1, s_col2, s_col3, s_col4, s_col5 = st.columns(5)
                with s_col1: st.metric("Current Price", f"₹{curr:.2f}")
                with s_col2: st.metric("Entry Price", f"₹{entry:.2f}")
                with s_col3: st.metric("Quantity", f"{trade['shares']} 📦")
                with s_col4: render_profit_metric("Live P&L", f"{pnl_pct:+.2%}")
                if pt and curr > 0: 
                    dist = ((pt - curr) / curr) if trade['signal'] == 'BUY' else ((curr - pt) / curr)
                    with s_col5: st.metric("Dist. to Target", f"{dist:+.1%}")
    with tabs[2]:
        cursor = st.session_state.paper_mgr.conn.execute("SELECT ticker, signal, entry_price, exit_price, pnl_pct, closed_at FROM paper_trades WHERE status='CLOSED' ORDER BY closed_at DESC")
        history = [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]
        if history: st.dataframe(pd.DataFrame(history), width="stretch", hide_index=True)

def render_performance_report():
    st.subheader("📊 Strategy Performance Hub")
    cursor = st.session_state.paper_mgr.conn.execute("SELECT * FROM paper_trades")
    cols = [d[0] for d in cursor.description]
    trades = [dict(zip(cols, row)) for row in cursor.fetchall()]
    
    if not trades:
        st.info("No trade data available yet. Start trading to see performance reports.")
        return
        
    metrics = PerformanceReport.generate_metrics(trades)
    if metrics and "status" not in metrics:
        m_cols = st.columns(4)
        with m_cols[0]: render_profit_metric("Total Return", metrics['total_return'])
        m_cols[1].metric("Win Rate", metrics['win_rate'])
        m_cols[2].metric("Sharpe Ratio", metrics['sharpe_ratio'])
        m_cols[3].metric("Max Drawdown", metrics['max_drawdown'])
        
        st.divider()
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("📈 Equity Curve")
            fig = PerformanceReport.plot_equity_curve(trades)
            if fig:
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Equity curve will appear after more closed trades.")
                
        with col2:
            st.subheader("📋 Performance Breakdown")
            st.markdown(f"""
            - **Total Trades:** {metrics['total_trades']}
            - **Closed Trades:** {metrics['closed_trades']}
            - **Average Return:** {metrics['avg_return']}
            - **Profit Factor:** {metrics['profit_factor']}
            """)
            
            # Simple Trade Distribution
            df = pd.DataFrame(trades)
            if not df.empty and 'pnl_pct' in df.columns:
                closed = df[df['status'] == 'CLOSED']
                if not closed.empty:
                    st.subheader("🎯 Signal Accuracy")
                    sig_counts = closed.groupby('signal').size().reset_index(name='count')
                    fig_pie = px.pie(sig_counts, values='count', names='signal', 
                                    template="plotly_dark", color_discrete_sequence=["#00FFA3", "#FF4B4B"])
                    fig_pie.update_layout(height=250, margin=dict(l=20,r=20,t=20,b=20))
                    st.plotly_chart(fig_pie, width="stretch")
    else:
        st.warning(metrics.get("status", "Insufficient data for detailed performance reporting."))

def render_strategy_scanner(bot_data):
    st.subheader("⚡ Bot-Powered High-Conviction Scanner")
    results = bot_data.get('results', [])
    if results:
        df = pd.DataFrame(results); display_cols = ['ticker', 'signal', 'confidence', 'momentum', 'sentiment', 'reason']
        def color_sig(val): return 'color: #00FFA3' if val == 'BUY' else 'color: #FF4B4B' if val in ('SELL', 'SHORT') else 'color: #00D1FF' if val == 'WATCH' else ''
        try: styled_df = df[display_cols].style.map(color_sig, subset=['signal'])
        except AttributeError: styled_df = df[display_cols].style.applymap(color_sig, subset=['signal'])
        st.dataframe(styled_df, width="stretch", hide_index=True)
    else: st.warning("Scanning... Ensure auto_bot.py is running.")

def render_actions_hub():
    st.subheader("🕵️ Actions Hub: Audit Trail")
    logs = st.session_state.paper_mgr.get_action_logs(limit=100)
    if logs:
        df = pd.DataFrame(logs); df['Time'] = pd.to_datetime(df['timestamp']).dt.strftime('%H:%M:%S')
        st.dataframe(df[['Time', 'ticker', 'action_type', 'details', 'source']], width="stretch", hide_index=True)

def render_help_guides():
    st.subheader("📚 Help Guides")
    st.markdown("### 🚀 Strategy & Risk\nKelly Criterion sizing and ATR-based stops.")

def render_log_viewer():
    st.subheader("📋 System Log Viewer")
    log_file = Path("logs/smart_trader.log")
    if log_file.exists():
        with open(log_file, "r") as f:
            log_text = "".join(f.readlines()[-200:])
            st.code(log_text, language="log")

def main():
    bot_data = load_shared_bot_data(); menu = render_sidebar(bot_data); render_top_bar(bot_data)
    if menu == "Market Pulse": render_market_pulse(bot_data)
    elif menu == "News Hub": render_news_hub(bot_data)
    elif menu == "Deep Analysis": render_deep_analysis()
    elif menu == "Portfolio Hub": render_portfolio_hub()
    elif menu == "Performance Report": render_performance_report()
    elif menu == "Strategy Scanner": render_strategy_scanner(bot_data)
    elif menu == "Actions Hub": render_actions_hub()
    elif menu == "Log Viewer": render_log_viewer()
    elif menu == "Help & Guides": render_help_guides()

if __name__ == "__main__": main()
