"""Streamlit page for the recommendation book."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from recommender.brief import BriefError, write_notes
from recommender.costs import BROKERS, quote
from recommender.data import demo_frames, fetch_closes, sector_map
from recommender.engine import recommend
from recommender.ledger import load_book
from recommender.llm import configured, reachable
from recommender.models import InvestorProfile
from recommender.performance import summarize


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

    if st.button("Build book", type="primary"):
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
        st.session_state.rec_book = recommend(frames, profile, sectors=sector_map(list(frames)))
        st.session_state.rec_capital = float(amount)

    book = st.session_state.get("rec_book")
    if book is None:
        st.info("Set the profile, then build the book. Leave live prices off to use the sample market. A local model is not required.")
        return
    capital_used = float(st.session_state.get("rec_capital", amount))
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

    _ask_model(book, capital_used)


def _ask_model(book, capital: float) -> None:
    st.divider()
    st.caption("Asking the local model is optional. A note is not a change to the book, and this page does not place an order.")
    desk = st.selectbox(
        "Cost platform for the note",
        list(BROKERS),
        format_func=lambda key: BROKERS[key].name,
        key="note_platform",
    )
    if not st.button("Ask the local model"):
        return
    if not configured():
        st.info("No model is configured. The book is already complete. Set QWEN_MODEL only if you want a note.")
        return
    if not reachable():
        st.error("The model server was not reached. The book is unchanged.")
        return
    trip = quote(desk, capital)
    try:
        notes = write_notes(
            book.to_dict(),
            {
                "platform": trip.platform,
                "product": trip.product,
                "buy_value": trip.buy_value,
                "total": trip.total,
                "cost_share": round(trip.cost_share, 6),
            },
            mix=_holdings_mix(),
        )
    except BriefError as exc:
        st.error(str(exc))
        return
    for title in ("trend", "cost", "news"):
        st.subheader(title.title())
        st.write(notes[title])


def _holdings_mix() -> dict | None:
    path = Path("output") / "holdings.json"
    if not path.exists():
        return None
    rows = []
    for item in load_book(path):
        rows.append(
            {
                "name": item.name,
                "platform": item.platform,
                "kind": item.kind,
                "invested": item.invested(),
                "value": item.market_value(item.average_price),
            }
        )
    if not rows:
        return None
    return summarize(rows)

