"""
SmartTrader Pro Dashboard v2.0
A high-performance, beautiful GUI for Indian Market Analysis.
Built with Streamlit, Plotly, and real-time news integration.
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import traceback
import logging

logger = logging.getLogger(__name__)

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
from utils.sentiment_db import SentimentDB
from utils.testing_engine import TestingEngine
from utils.strategy_gatekeeper import StrategyGatekeeper

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
        st.session_state.shoonya = None  # Only init when user explicitly connects
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
        
    if 'testing_engine' not in st.session_state:
        st.session_state.testing_engine = TestingEngine()
    if 'gatekeeper' not in st.session_state:
        st.session_state.gatekeeper = StrategyGatekeeper()
    if 'test_result' not in st.session_state:
        st.session_state.test_result = None
    if 'momentum_strategy' not in st.session_state:
        from strategies.indian_momentum import IndianMomentumStrategy
        st.session_state.momentum_strategy = IndianMomentumStrategy()

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
        # Use auto_adjust=True for consistent pricing
        df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df.empty: return pd.DataFrame()
        # Clean data: drop rows where Close is NaN
        df = df.dropna(subset=['Close'])
        if df.empty: return pd.DataFrame()
        
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_convert(None)
        return df
    except Exception as e:
        logger.error(f"Error fetching data for {ticker}: {e}")
        return pd.DataFrame()

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
        menu = st.radio("Navigation", [
            "Market Pulse", "News Hub", "Strategy Scanner", "Deep Analysis",
            "Portfolio Hub", "Performance Report",
            "🧪 Testing Lab",
            "Actions Hub", "Log Viewer", "Help & Guides"
        ])
        st.divider()
        st.subheader("Broker (Shoonya)")
        if st.session_state.shoonya is None:
            if st.button("Connect Shoonya 🔌"):
                st.session_state.shoonya = ShoonyaBroker()
                st.rerun()
        elif not st.session_state.shoonya.is_logged_in:
            if st.button("Login 🔑"):
                if st.session_state.shoonya.login(): st.rerun()
        else:
            st.success(f"Connected: {st.session_state.shoonya.user_id}")
            if st.button("Logout"): st.session_state.shoonya.is_logged_in = False; st.rerun()
        st.subheader("🛡️ Risk Monitor")
        risk = st.session_state.risk_mgr.get_drawdown_stats(); dd = risk['drawdown_pct']
        color = "#00FFA3" if dd < 3 else "#FFA500" if dd < 5 else "#FF4B4B"
        st.markdown(f"Drawdown: <span style='color:{color}; font-weight:bold;'>{dd:.2f}%</span>", unsafe_allow_html=True)
        
        st.subheader("🔬 Strategy Validation")
        gk = st.session_state.get('gatekeeper')
        if gk:
            gk_sum = gk.summary()
            st.metric("Tests Passed", f"{gk_sum['passed']}/{gk_sum['total_tests']}")
            if gk_sum['failed'] > 0:
                st.warning(f"{gk_sum['failed']} strategy/ticker pairs failed validation")
            if st.button("Go to Testing Lab", key="sidebar_goto_lab"):
                st.info("Select '🧪 Testing Lab' in the menu above")

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
    for i, name in enumerate(["NIFTY 50", "BANK NIFTY"]):
        val = idx.get(name, {"price":0, "pct":0})
        cols[i+1].metric(name, f"{val['price']:,.0f}", f"{val['pct']:+.2f}%")

    # --- VIX with regime-aware colour coding ---
    vix_data = idx.get("INDIA VIX", {"price": 0, "pct": 0})
    vix_val = vix_data.get('price', 0)
    vix_pct = vix_data.get('pct', 0)
    if vix_val < 13:
        vix_label = "🟡 COMPLACENCY"
        vix_color = "#FFD700"
    elif vix_val <= 20:
        vix_label = "⚪ NORMAL"
        vix_color = "#E0E0E0"
    elif vix_val <= 30:
        vix_label = "🟠 FEAR"
        vix_color = "#FF8C00"
    else:
        vix_label = "🔴 CRISIS"
        vix_color = "#FF4B4B"

    with cols[3]:
        st.markdown(
            f"""<div style='text-align:center;'>
                <span style='color:#888;font-size:0.7rem;'>INDIA VIX</span><br>
                <span style='color:{vix_color};font-size:1.6rem;font-weight:bold;'>{vix_val:,.2f}</span><br>
                <span style='color:{vix_color};font-size:0.7rem;'>{vix_label}</span>
            </div>""",
            unsafe_allow_html=True
        )

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
                nifty_df = fetch_stock_data("^NSEI")
                result = st.session_state.momentum_strategy.analyze_ticker(
                    ticker, df, nifty_df, news_sent['aggregate_sentiment']
                )
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
        # --- ALWAYS VISIBLE: Manual Order Ticket ---
        with st.expander("📝 Manual Order Ticket", expanded=False):
            t_col1, t_col2, t_col3, t_col4 = st.columns(4)
            m_ticker = t_col1.text_input("Ticker Symbol", placeholder="e.g. RELIANCE", key="manual_tk").upper()
            m_action = t_col2.selectbox("Action", ["BUY", "SHORT"], key="manual_act")
            m_mode = t_col3.radio("Trade Mode", ["INTRADAY", "SWING"], horizontal=True, key="manual_mode")
            m_qty = t_col4.number_input("Quantity (Shares)", min_value=1, value=10, key="manual_qty")
            
            if st.button("🚀 Execute Manual Trade", type="primary", use_container_width=True, key="manual_exec"):
                if m_ticker:
                    tick_ns = m_ticker if (m_ticker.startswith("^") or m_ticker.endswith((".NS", ".BO"))) else f"{m_ticker}.NS"
                    try:
                        with st.spinner(f"Fetching current price for {tick_ns}..."):
                            df_t = fetch_stock_data(tick_ns, period="5d")
                            if not df_t.empty:
                                curr_p = float(df_t['Close'].iloc[-1])
                                st.session_state.paper_mgr.open_trade(
                                    ticker=tick_ns, signal=m_action, entry_price=curr_p,
                                    shares=m_qty, stop_loss=None, target=None,
                                    trade_mode=m_mode, is_manual=True, source='USER'
                                )
                                st.success(f"Executed {m_action} {m_qty} shares of {tick_ns} at ₹{curr_p:.2f} ({m_mode})")
                                st.rerun()
                            else:
                                st.error("Could not fetch price. Check ticker symbol.")
                    except Exception as e:
                        st.error(f"Execution failed: {e}")
                else:
                    st.warning("Please enter a ticker symbol.")

        summary = st.session_state.paper_mgr.get_portfolio_summary()
        st.subheader("Live Portfolio Health")
        pnl_amt = 0.0; total_inv = 0.0

        if summary['open_positions']:
            # --- FIX: Batched Price Fetching for Accuracy ---
            raw_tickers = [p['ticker'] for p in summary['open_positions']]
            # Normalize for yfinance
            tickers = [t if (t.startswith("^") or t.endswith((".NS", ".BO"))) else f"{t}.NS" for t in raw_tickers]
            
            try:
                # Use download() for robust batched prices
                batch_data = yf.download(tickers, period='1d', progress=False, auto_adjust=True, group_by='ticker', threads=True)

                for pos in summary['open_positions']:
                    tk = pos['ticker']
                    tk_lookup = tk if (tk.startswith("^") or tk.endswith((".NS", ".BO"))) else f"{tk}.NS"
                    try:
                        if len(tickers) == 1:
                            curr = float(batch_data['Close'].iloc[-1])
                        else:
                            curr = float(batch_data[tk_lookup]['Close'].iloc[-1])

                        if pd.isna(curr) or curr <= 0:
                            # Fallback if Close is NaN (market open)
                            curr = pos['entry_price']
                    except:
                        curr = pos['entry_price']

                    pos['current_price'] = round(curr, 2)
                    entry = pos['entry_price']
                    # Calculate P&L % as a fraction (for internal use)
                    pnl_fraction = ((curr - entry) / entry) if pos['signal'] == 'BUY' else ((entry - curr) / entry)
                    pos['pnl_pct'] = round(pnl_fraction * 100, 2) # Now storing as percentage for display
                    pnl_amt += pnl_fraction * entry * pos['shares']
                    total_inv += entry * pos['shares']
            except Exception as e:
                st.error(f"Error fetching live prices: {e}")
                for pos in summary['open_positions']:
                    pos['current_price'] = pos['entry_price']
                    pos['pnl_pct'] = 0.0

            growth = (pnl_amt / total_inv) * 100 if total_inv > 0 else 0
            h1, h2, h3 = st.columns(3)
            with h1: render_profit_metric("Live Growth", f"{growth:+.2f}%", delta=f"{'↑' if growth >= 0 else '↓'} INR {abs(pnl_amt):,.2f} MTM")
            h2.metric("At Risk", f"INR {total_inv:,.2f}"); h3.metric("Open Pos", summary['open_count'])

            # --- RESTORED: Open Positions Table ---
            st.divider(); st.subheader("📂 Active Positions")
            df_open = pd.DataFrame(summary['open_positions'])[['ticker', 'signal', 'trade_mode', 'is_manual', 'entry_price', 'current_price', 'pnl_pct', 'shares', 'stop_loss', 'target']]
            # Format manual flag
            df_open['is_manual'] = df_open['is_manual'].apply(lambda x: '🙋‍♂️ Yes' if x else '🤖 Bot')
            # Rename for display
            df_open.columns = ['Ticker', 'Signal', 'Mode', 'Manual?', 'Entry ₹', 'Current ₹', 'P&L %', 'Qty', 'Stop Loss', 'Target']

            def color_pnl(val): 
                try:
                    v = float(val)
                    return 'color: #00FFA3' if v > 0 else 'color: #FF4B4B' if v < 0 else ''
                except: return ''

            try: styled_open = df_open.style.map(color_pnl, subset=['P&L %']).format({'P&L %': '{:+.2f}%', 'Entry ₹': '{:,.2f}', 'Current ₹': '{:,.2f}'})
            except AttributeError: styled_open = df_open.style.applymap(color_pnl, subset=['P&L %']).format({'P&L %': '{:+.2f}%', 'Entry ₹': '{:,.2f}', 'Current ₹': '{:,.2f}'})
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
    with tabs[1]:
        # --- Shoonya Live Trading Tab ---
        st.subheader("🔗 Shoonya Live Trading")
        shoonya_user = os.getenv('SHOONYA_USER_ID')
        if not shoonya_user:
            st.warning("⚠️ Shoonya credentials not configured.")
            st.markdown("""
            ### Setup Guide
            Add these environment variables to your `.env` file:
            ```
            SHOONYA_USER_ID=your_user_id
            SHOONYA_PASSWORD=your_password
            SHOONYA_TOTP_KEY=your_totp_secret
            SHOONYA_VENDOR_CODE=your_vendor_code
            SHOONYA_API_KEY=your_api_key
            ```
            Then restart the dashboard.
            """)
        else:
            broker = st.session_state.shoonya
            if broker is None:
                st.info(f"Shoonya user `{shoonya_user}` configured but not connected.")
                if st.button("🔌 Connect to Shoonya", key="shoonya_live_connect"):
                    st.session_state.shoonya = ShoonyaBroker()
                    st.rerun()
            elif not broker.is_logged_in:
                st.warning("Shoonya initialized but not logged in.")
                if st.button("🔑 Login", key="shoonya_live_login"):
                    if broker.login():
                        st.success("Login successful!")
                        st.rerun()
                    else:
                        st.error("Login failed. Check credentials.")
            else:
                st.success(f"✅ Connected as **{broker.user_id}**")
                st.divider()
                st.subheader("📊 Live Positions")
                positions = broker.get_positions_summary()
                if positions:
                    df_pos = pd.DataFrame(positions)
                    # Clean up Shoonya headers for display
                    rename_map = {
                        'tsym': 'Symbol', 'netqty': 'Qty', 'lp': 'LTP',
                        'rpnl': 'Realized P&L', 'urpnl': 'Unrealized P&L',
                        'mproid': 'Product', 'actid': 'Account'
                    }
                    df_pos = df_pos.rename(columns=rename_map)
                    # Show only relevant columns if they exist
                    cols_to_show = [c for c in rename_map.values() if c in df_pos.columns]
                    if not cols_to_show: cols_to_show = df_pos.columns
                    st.dataframe(df_pos[cols_to_show], width="stretch", hide_index=True)
                else:
                    st.info("No open live positions.")
                if st.button("🔄 Refresh Positions", key="refresh_live_pos"):
                    st.rerun()
    with tabs[2]:
        cursor = st.session_state.paper_mgr.conn.execute("SELECT ticker, signal, entry_price, exit_price, pnl_pct, closed_at FROM paper_trades WHERE status='CLOSED' ORDER BY closed_at DESC")
        history = [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]
        if history: 
            df_hist = pd.DataFrame(history)
            df_hist['pnl_pct'] = df_hist['pnl_pct'] * 100
            df_hist.columns = ['Ticker', 'Signal', 'Entry ₹', 'Exit ₹', 'P&L %', 'Closed At']
            st.dataframe(df_hist.style.format({'P&L %': '{:+.2f}%', 'Entry ₹': '{:,.2f}', 'Exit ₹': '{:,.2f}'}), width="stretch", hide_index=True)

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

# Regime-aware advice for the Strategy Scanner
REGIME_ADVICE = {
    'BULL_TREND': '🚀 Trend following — ride momentum, trail stops wide',
    'BULL_VOLATILE': '⚡ Volatile uptrend — take profits early, use hedges',
    'BEAR_TREND': '🐻 Sustained downtrend — short or sit in cash',
    'BEAR_VOLATILE': '💀 High-risk bear — reduce size, avoid overnight',
    'SIDEWAYS_LOW_VOL': '😴 Range-bound — mean reversion, sell premium',
    'SIDEWAYS_HIGH_VOL': '🌊 Choppy — avoid trend-following, tight stops',
    'CRISIS': '🔴 CRISIS MODE — capital preservation only',
    'UNKNOWN': '❓ Regime unknown — use default risk parameters',
}
REGIME_COLOR = {
    'BULL_TREND': '#00FFA3', 'BULL_VOLATILE': '#FFD700',
    'BEAR_TREND': '#FF6B6B', 'BEAR_VOLATILE': '#FF4B4B',
    'SIDEWAYS_LOW_VOL': '#888', 'SIDEWAYS_HIGH_VOL': '#FF8C00',
    'CRISIS': '#FF0000', 'UNKNOWN': '#555',
}

def render_strategy_scanner(bot_data):
    st.subheader("⚡ Bot-Powered High-Conviction Scanner")

    # --- Regime Advice Banner ---
    regime = bot_data.get('regime', 'UNKNOWN')
    advice = REGIME_ADVICE.get(regime, REGIME_ADVICE['UNKNOWN'])
    color = REGIME_COLOR.get(regime, '#555')
    st.markdown(
        f"""<div style='background:linear-gradient(90deg, {color}22, {color}11);
            border-left:4px solid {color}; padding:12px 18px; border-radius:6px;
            margin-bottom:16px; font-size:1.05rem;'>
            <b style='color:{color};'>Market Regime: {regime.replace('_',' ').title()}</b>
            &nbsp;—&nbsp; {advice}
        </div>""",
        unsafe_allow_html=True
    )

    results = bot_data.get('results', [])
    if results:
        df = pd.DataFrame(results); display_cols = ['ticker', 'signal', 'confidence', 'momentum', 'sentiment', 'reason']
        def color_sig(val):
            if val == 'BUY': return 'color: #00FFA3; font-weight: bold'
            if val in ('SELL', 'SHORT'): return 'color: #FF4B4B; font-weight: bold'
            if val == 'WATCH': return 'color: #00D1FF'
            if val == 'HOLD': return 'color: #888'
            return ''
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

def render_testing_lab():
    """Testing Lab: Backtest, Walk-Forward, Portfolio Sim, Monte Carlo, Compare."""
    import plotly.graph_objects as go
    import plotly.express as px
    from indian_config import POPULAR_INDIAN_STOCKS

    engine: TestingEngine = st.session_state.testing_engine
    gatekeeper: StrategyGatekeeper = st.session_state.gatekeeper

    st.subheader("🧪 Strategy Testing Lab")

    # --- Gatekeeper summary banner ---
    gk_summary = gatekeeper.summary()
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Tests Run", gk_summary["total_tests"])
    b2.metric("✅ Passed", gk_summary["passed"], delta=None)
    b3.metric("❌ Failed", gk_summary["failed"], delta=None)
    b4.metric("Pass Rate", f"{gk_summary['pass_rate']:.0f}%")

    st.divider()

    # --- Controls ---
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 2, 1, 1])

    with ctrl1:
        STRATEGY_OPTIONS = {
            "indian_momentum":    "Indian Momentum (Normalized)",
            "bulls_ai_momentum":  "Bulls AI Momentum",
            "buffett_value":      "Buffett Value",
            "momentum_breakout":  "Momentum Breakout",
            "sector_rotation":    "Sector Rotation",
            "mean_reversion":     "Mean Reversion (BB)",
            "nifty_options_writer": "Nifty Options Writer",
        }
        selected_strategy = st.selectbox(
            "Strategy", options=list(STRATEGY_OPTIONS.keys()),
            format_func=lambda k: STRATEGY_OPTIONS[k]
        )

    with ctrl2:
        # Ticker: Dropdown with full Nifty 500 universe
        ticker_options = get_nifty_universe()
        # Fallback if universe is empty
        if not ticker_options:
            from indian_config import POPULAR_INDIAN_STOCKS
            ticker_list = sorted(list(set(
                POPULAR_INDIAN_STOCKS.get("large_cap", []) + 
                POPULAR_INDIAN_STOCKS.get("mid_cap", [])
            )))
            ticker_options = [t + ".NS" for t in ticker_list]
            
        ticker = st.selectbox("Ticker", options=ticker_options, index=ticker_options.index("RELIANCE.NS") if "RELIANCE.NS" in ticker_options else 0)

    with ctrl3:
        days_options = {"6 months": 180, "1 year": 365, "2 years": 730, "3 years": 1095}
        selected_period = st.selectbox("Period", list(days_options.keys()), index=1)
        days = days_options[selected_period]

    with ctrl4:
        capital = st.number_input("Capital (₹)", min_value=10000,
                                   max_value=10_000_000,
                                   value=100000, step=10000)
        # Propagate capital to engine
        engine.initial_capital = float(capital)

    # FIX BUG-7: Reset rendered results if controls change
    current_controls = f"{selected_strategy}_{ticker}_{days}"
    if st.session_state.get('last_controls') != current_controls:
        st.session_state.test_result = None
        st.session_state.wf_result = None
        st.session_state.port_result = None
        st.session_state.mc_result = None
        st.session_state.cmp_result = None
        st.session_state.last_controls = current_controls

    # --- Test type tabs ---
    tabs = st.tabs([
        "📈 Single Backtest",
        "🔁 Walk-Forward",
        "💼 Portfolio Sim",
        "🎲 Monte Carlo",
        "⚖️ Compare All",
        "📋 Results History",
    ])

    # ─────────────────────────────────────────────────────────── TAB 1
    with tabs[0]:
        st.markdown("**Single-ticker historical backtest.** Tests one strategy on one stock.")
        force = st.checkbox("Force re-run (ignore cache)", key="force_single")
        if st.button("▶ Run Backtest", type="primary", key="run_single"):
            with st.spinner(f"Backtesting {selected_strategy} on {ticker}..."):
                result = engine.run_single_backtest(selected_strategy, ticker, days, force=force)
                st.session_state.test_result = result

        result = st.session_state.get("test_result")
        if result and "_test_type" in result and result["_test_type"] == "single":
            if "error" in result:
                st.error(f"Backtest Failed: {result['error']}")
            else:
                _render_single_result(result)

    # ─────────────────────────────────────────────────────────── TAB 2
    with tabs[1]:
        st.markdown("**Walk-forward validation.** Out-of-sample testing across multiple folds. The most reliable overfitting check.")
        c1, c2 = st.columns(2)
        train_bars = c1.number_input("Training bars", min_value=60, max_value=500, value=180)
        test_bars  = c2.number_input("Test bars",     min_value=20, max_value=180,  value=60)
        force_wf = st.checkbox("Force re-run", key="force_wf")
        if st.button("▶ Run Walk-Forward", type="primary", key="run_wf"):
            with st.spinner("Running walk-forward validation..."):
                result = engine.run_walk_forward(
                    selected_strategy, ticker, days,
                    train_bars=int(train_bars), test_bars=int(test_bars),
                    force=force_wf
                )
                st.session_state.wf_result = result

        wf_result = st.session_state.get("wf_result")
        if wf_result:
            if "error" in wf_result:
                st.error(f"Walk-Forward Failed: {wf_result['error']}")
            else:
                _render_walk_forward_result(wf_result)

    # ─────────────────────────────────────────────────────────── TAB 3
    with tabs[2]:
        st.markdown("**Portfolio simulation.** Runs the strategy on a basket of stocks simultaneously with capital constraints.")
        portfolio_tickers = st.multiselect(
            "Portfolio tickers",
            options=[t + ".NS" for t in (POPULAR_INDIAN_STOCKS.get("large_cap", []) + POPULAR_INDIAN_STOCKS.get("mid_cap", []))[:30]],
            default=["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS"],
            max_selections=20,
        )
        max_pos = st.slider("Max simultaneous positions", 3, 15, 8)
        force_port = st.checkbox("Force re-run", key="force_port")
        if st.button("▶ Run Portfolio Sim", type="primary", key="run_port") and portfolio_tickers:
            with st.spinner(f"Simulating portfolio ({len(portfolio_tickers)} stocks)..."):
                result = engine.run_portfolio_sim(
                    selected_strategy, portfolio_tickers, days,
                    max_positions=max_pos, force=force_port
                )
                st.session_state.port_result = result

        port_result = st.session_state.get("port_result")
        if port_result:
            if "error" in port_result:
                st.error(f"Portfolio Sim Failed: {port_result['error']}")
            else:
                _render_portfolio_result(port_result)

    # ─────────────────────────────────────────────────────────── TAB 4
    with tabs[3]:
        st.markdown("**Monte Carlo simulation.** Shuffles trade order 500 times to show return distribution. Requires a completed single backtest first.")
        n_sims = st.slider("Number of simulations", 100, 2000, 500, step=100)
        force_mc = st.checkbox("Force re-run", key="force_mc")
        if st.button("▶ Run Monte Carlo", type="primary", key="run_mc"):
            with st.spinner("Running Monte Carlo..."):
                result = engine.run_monte_carlo(
                    selected_strategy, ticker, days,
                    n_simulations=n_sims, force=force_mc
                )
                st.session_state.mc_result = result

        mc_result = st.session_state.get("mc_result")
        if mc_result:
            if "error" in mc_result:
                st.error(f"Monte Carlo Failed: {mc_result['error']}")
            else:
                _render_monte_carlo_result(mc_result)

    # ─────────────────────────────────────────────────────────── TAB 5
    with tabs[4]:
        st.markdown("**Compare all strategies** on the same ticker. Ranks by Sharpe ratio.")
        force_cmp = st.checkbox("Force re-run all", key="force_cmp")
        if st.button("▶ Compare All Strategies", type="primary", key="run_cmp"):
            # PERF-5: Clear individual cache entries for this ticker before comparing if forced
            if force_cmp:
                keys_to_delete = []
                for k in engine.results_cache.keys():
                    if k.endswith(f"::{ticker}"):
                        keys_to_delete.append(k)
                for k in keys_to_delete:
                    del engine.results_cache[k]
                engine._save_results()

            with st.spinner("Running all strategies... this takes 30–60 seconds."):
                result = engine.run_strategy_comparison(ticker, days, force=force_cmp)
                st.session_state.cmp_result = result

        cmp_result = st.session_state.get("cmp_result")
        if cmp_result:
            if "error" in cmp_result:
                st.error(f"Comparison Failed: {cmp_result['error']}")
            else:
                _render_comparison_result(cmp_result)

    # ─────────────────────────────────────────────────────────── TAB 6
    with tabs[5]:
        st.markdown("**All previous test results** stored on disk.")
        all_results = engine.list_results()
        if not all_results:
            st.info("No test results yet. Run a test above.")
        else:
            rows = []
            for r in all_results:
                verdict = r.get("verdict", {})
                rows.append({
                    "Type":     r.get("_test_type", "—"),
                    "Strategy": r.get("_strategy", "—"),
                    "Ticker":   r.get("_ticker", "—"),
                    "Return %": r.get("return_pct") or r.get("summary", {}).get("return_pct", 0) or 0,
                    "Sharpe":   r.get("sharpe_ratio") or r.get("summary", {}).get("sharpe", 0) or 0,
                    "Pass":     "✅" if verdict.get("pass") else "❌",
                    "Cached":   r.get("_cached_at", "")[:16],
                })
            st.dataframe(pd.DataFrame(rows), width='stretch')


# ─────────────────────────────────────────────────────────────────────────────
#  RESULT RENDERERS (private helpers for render_testing_lab)
# ─────────────────────────────────────────────────────────────────────────────

def _verdict_badge(verdict: dict):
    """Display a green ✅ PASS or red ❌ FAIL badge with details."""
    if not verdict:
        return
    passed = verdict.get("pass", False)
    score  = verdict.get("score", "?")
    reason = verdict.get("reason", "")
    checks = verdict.get("checks", {})

    if passed:
        st.success(f"✅ **VALIDATED** ({score} checks passed)")
    else:
        st.error(f"❌ **FAILED VALIDATION** ({score} checks passed) — {reason}")

    if checks:
        cols = st.columns(len(checks))
        for col, (label, ok) in zip(cols, checks.items()):
            col.metric(label, "✅ Pass" if ok else "❌ Fail")


def _render_single_result(r: dict):
    import plotly.graph_objects as go

    st.divider()
    _verdict_badge(r.get("verdict", {}))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Return",      f"{r.get('return_pct', 0):.1f}%")
    m2.metric("Sharpe",      f"{r.get('sharpe_ratio', 0):.2f}")
    m3.metric("Max Drawdown",f"{r.get('max_drawdown_pct', 0):.1f}%")
    m4.metric("Win Rate",    f"{r.get('win_rate', 0)*100:.1f}%")
    m5.metric("Trades",      r.get("total_trades", 0))

    # Equity curve
    curve = r.get("capital_curve") or r.get("equity_curve")
    if curve:
        if isinstance(curve[0], dict):
            dates  = [c["date"] for c in curve]
            values = [c["value"] for c in curve]
        else:
            dates  = list(range(len(curve)))
            values = curve

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dates, y=values, mode="lines",
                                  name="Portfolio", line=dict(color="#00D4AA", width=2)))
        fig.update_layout(
            title="Equity Curve", height=350,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"), xaxis=dict(color="white"),
            yaxis=dict(color="white", tickprefix="₹"),
        )
        st.plotly_chart(fig, width='stretch')

    # Trade log
    trades = r.get("trades", [])
    if trades:
        with st.expander(f"📋 Trade Log ({len(trades)} trades)"):
            rows = []
            for t in trades:
                action = t.get("action") or t.get("type", "")
                if action == "BUY":
                    continue  # Skip entry rows; only show closed trades
                rows.append({
                    "Date":    str(t.get("date", ""))[:10],
                    "Action":  action,
                    "Entry ₹": round(float(t.get("entry_price", 0)), 2) if t.get("entry_price") else 0.0,
                    "Exit ₹":  round(float(t.get("exit_price", 0)), 2) if t.get("exit_price") else round(float(t.get("price", 0)), 2),
                    "P&L %":   round(float(t.get("profit_pct", 0)), 2),
                    "P&L ₹":   round(float(t.get("profit", 0)), 2),
                })
            st.dataframe(pd.DataFrame(rows), width='stretch')


def _render_walk_forward_result(r: dict):
    import plotly.graph_objects as go

    if "error" in r:
        st.error(r["error"]); return

    st.divider()
    _verdict_badge(r.get("verdict", {}))

    summary = r.get("summary", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Folds",               summary.get("fold_count", 0))
    m2.metric("Median Return",        f"{summary.get('median_return_pct', 0):.1f}%")
    m3.metric("Profitable Fold Rate", f"{summary.get('profitable_fold_rate', 0)*100:.0f}%")
    m4.metric("Robust Score",         f"{summary.get('robust_score', 0):.2f}")

    folds = r.get("folds", [])
    if folds:
        fold_returns = [f.get("return_pct", 0) for f in folds]
        fig = go.Figure()
        fig.add_bar(
            x=[f"Fold {i+1}" for i in range(len(fold_returns))],
            y=fold_returns,
            marker_color=["#00D4AA" if v > 0 else "#FF4B4B" for v in fold_returns],
        )
        fig.update_layout(
            title="Return Per Out-of-Sample Fold", height=300,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"), yaxis=dict(ticksuffix="%", color="white"),
            xaxis=dict(color="white"),
        )
        st.plotly_chart(fig, width='stretch')


def _render_portfolio_result(r: dict):
    import plotly.graph_objects as go

    if "error" in r:
        st.error(r["error"]); return

    st.divider()
    _verdict_badge(r.get("verdict", {}))

    summary = r.get("summary", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Return",  f"{summary.get('return_pct', 0):.1f}%")
    m2.metric("Sharpe",        f"{summary.get('sharpe', 0):.2f}")
    m3.metric("Final Value",   f"₹{summary.get('final', 0):,.0f}")
    m4.metric("Total Trades",  summary.get("total_trades", 0))

    curve = r.get("capital_curve", [])
    if curve:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[c["date"] for c in curve], y=[c["value"] for c in curve],
            mode="lines", line=dict(color="#7B61FF", width=2), name="Portfolio"
        ))
        fig.update_layout(title="Portfolio Equity Curve", height=330,
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font=dict(color="white"), yaxis=dict(tickprefix="₹", color="white"),
                           xaxis=dict(color="white"))
        st.plotly_chart(fig, width='stretch')

    trade_log = r.get("trade_log", [])
    if trade_log:
        with st.expander(f"📋 Trade Log ({len(trade_log)} events)"):
            st.dataframe(pd.DataFrame(trade_log), width='stretch')


def _render_monte_carlo_result(r: dict):
    import plotly.graph_objects as go

    if "error" in r:
        st.error(r["error"]); return

    st.divider()
    _verdict_badge(r.get("verdict", {}))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Worst 5%",    f"{r['p5_return_pct']:.1f}%")
    m2.metric("25th pct",    f"{r['p25_return_pct']:.1f}%")
    m3.metric("Median",      f"{r['median_return_pct']:.1f}%")
    m4.metric("75th pct",    f"{r['p75_return_pct']:.1f}%")
    m5.metric("Best 95%",    f"{r['p95_return_pct']:.1f}%")

    st.metric("% of simulations profitable", f"{r['pct_profitable']:.0f}%")

    all_returns = r.get("all_returns", [])
    if all_returns:
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=all_returns, nbinsx=60,
            marker_color="#F5A623", opacity=0.8,
            name="Simulated Returns"
        ))
        fig.add_vline(x=r["median_return_pct"], line_dash="dash",
                       line_color="white", annotation_text="Median")
        fig.add_vline(x=0, line_dash="solid", line_color="#FF4B4B")
        fig.update_layout(
            title=f"Return Distribution ({r['n_simulations']} simulations)",
            height=340, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"), xaxis=dict(ticksuffix="%", color="white"),
            yaxis=dict(color="white"),
        )
        st.plotly_chart(fig, width='stretch')


def _render_comparison_result(r: dict):
    import plotly.graph_objects as go

    if "error" in r:
        st.error(r["error"]); return

    st.divider()
    lb = r.get("leaderboard", [])
    if not lb:
        st.warning("No results to compare."); return

    best = r.get("best_strategy", "—")
    st.success(f"🏆 Best strategy for {r.get('ticker', '')}: **{best}**")

    df = pd.DataFrame(lb)
    df["verdict"] = df["verdict"].map({True: "✅", False: "❌"})
    df["win_rate"] = (df["win_rate"] * 100).round(1).astype(str) + "%"
    st.dataframe(df, width='stretch')

    fig = go.Figure()
    colors = ["#00D4AA" if v == "✅" else "#FF4B4B" for v in df["verdict"]]
    fig.add_bar(x=df["strategy"], y=df["return_pct"], marker_color=colors, name="Return %")
    fig.update_layout(
        title="Strategy Return Comparison", height=320,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"), yaxis=dict(ticksuffix="%", color="white"),
        xaxis=dict(color="white"),
    )
    st.plotly_chart(fig, width='stretch')

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
    elif menu == "🧪 Testing Lab": render_testing_lab()
    elif menu == "Strategy Scanner": render_strategy_scanner(bot_data)
    elif menu == "Actions Hub": render_actions_hub()
    elif menu == "Log Viewer": render_log_viewer()
    elif menu == "Help & Guides": render_help_guides()

if __name__ == "__main__": main()
