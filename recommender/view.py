"""Streamlit page for the recommendation book."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from recommender.data import demo_frames, fetch_closes, sector_map
from recommender.engine import recommend
from recommender.models import InvestorProfile


def render_recommendations() -> None:
    st.subheader("Recommendations")
    st.caption("Ranks an NSE book into a trading sleeve and an investment sleeve. It does not place orders.")

    capital, risk, horizon, use_live = st.columns([1.2, 1, 1, 1])
    with capital:
        amount = st.number_input("Capital (INR)", min_value=10_000.0, value=500_000.0, step=50_000.0)
    with risk:
        risk_level = st.selectbox("Risk", ["conservative", "balanced", "growth"], index=1)
    with horizon:
        horizon_choice = st.selectbox("Horizon", ["both", "investment", "trading"], index=0)
    with use_live:
        live = st.checkbox("Live NSE prices", value=False)
        max_names = st.number_input("Names", min_value=1, max_value=12, value=6)

    if not st.button("Build book", type="primary"):
        st.info("Set the profile, then build the book. Leave live prices off to use the sample market.")
        return

    profile = InvestorProfile(
        capital=float(amount),
        risk=risk_level,
        horizon=horizon_choice,
        max_names=int(max_names),
    )
    try:
        frames = fetch_closes() if live else demo_frames()
    except Exception as exc:
        st.error(f"Price download failed: {exc}")
        return
    if not frames:
        st.error("No prices came back. Uncheck live prices to use the sample market.")
        return

    book = recommend(frames, profile, sectors=sector_map(list(frames)))
    cash_col, regime_col, count_col = st.columns(3)
    cash_col.metric("Cash left", f"INR {book.cash_amount:,.0f}", f"{book.cash_weight:.0%}")
    regime_col.metric("Regime", book.regime.replace("_", " ").title())
    buys = [item for item in book.recommendations if item.action == "buy"]
    count_col.metric("Buys", str(len(buys)))

    table = pd.DataFrame(
        [
            {
                "Ticker": item.ticker,
                "Action": item.action.upper(),
                "Sleeve": item.sleeve,
                "Sector": item.sector,
                "Weight": f"{item.weight:.0%}",
                "Amount": item.amount,
                "Shares": item.shares,
                "Stop": item.stop if item.stop is not None else "",
                "Target": item.target if item.target is not None else "",
                "Days": item.horizon_days,
            }
            for item in book.recommendations
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch")

    for item in book.recommendations:
        label = f"{item.action.upper()} {item.ticker} — {item.sleeve}"
        with st.expander(label):
            for line in item.reasons:
                st.write(line)
            for line in item.risks:
                st.caption(line)

    for note in book.notes:
        st.caption(note)
