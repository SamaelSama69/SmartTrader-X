"""Live desk, platform costs, and the holdings book.

None of these pages places an order. A name that clears the cost of a
round trip is a screen, not a promised profit.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from recommender.costs import BROKERS, SCHEDULE_AS_OF, compare, minimum_ticket, quote
from recommender.data import DEFAULT_UNIVERSE, as_ohlcv, demo_frames, fetch_closes, fetch_history
from recommender.funds import SCHEMES, fee_hurdle, fetch_nav, fund_exit
from recommender.indicators import review
from recommender.ledger import Holding, load_book, sample_book, save_book

BOOK_PATH = Path("output") / "holdings.json"
DISCLAIMER = (
    "Research screen only. Costs are a working schedule, not a broker contract. "
    "No ticket size and no indicator makes a profit certain. This page does not place an order."
)


def render_live_desk() -> None:
    st.subheader("Live desk")
    st.caption(DISCLAIMER)

    sample_names = sorted({key.replace(".NS", "") for key in demo_frames()})
    symbol, platform, product, ticket, live = st.columns([1.4, 1, 1, 1, 0.8])
    with live:
        use_live = st.checkbox("Live NSE prices", value=False)
    names = list(DEFAULT_UNIVERSE) if use_live else sample_names
    with symbol:
        ticker = st.selectbox("Symbol", names, index=0)
    with platform:
        desk = st.selectbox("Platform", list(BROKERS), format_func=lambda key: BROKERS[key].name)
    with product:
        kind = st.selectbox("Product", ["delivery", "intraday"], format_func=str.title)
    with ticket:
        amount = st.number_input("Ticket (INR)", min_value=500.0, value=25_000.0, step=1_000.0)

    if not st.button("Open chart", type="primary"):
        st.info("Pick a symbol and a platform, then open the chart. Leave live prices off for the sample market.")
        return

    trip = quote(desk, float(amount), product=kind)
    frames = _panel(use_live)
    chosen = _frame_for(frames, ticker, use_live)
    if chosen is None or chosen.empty:
        st.error("No prices for that symbol. Uncheck live prices to use the sample market.")
        return

    candles = chosen if {"Open", "High", "Low"}.issubset(chosen.columns) else as_ohlcv(chosen["Close"])
    reading = review(candles["Close"], trip.cost_share)
    if reading is None:
        st.error("That history is shorter than 60 sessions, so the indicators are not drawn.")
        return

    _metrics(reading, trip)
    st.plotly_chart(_chart(candles, reading), width="stretch")
    if reading["cleared"]:
        st.success(reading["note"])
    else:
        st.warning(reading["note"])

    rows = []
    for name, frame in frames.items():
        item = review(frame["Close"], trip.cost_share)
        if item is None:
            continue
        rows.append(
            {
                "Ticker": name,
                "Last": item["last"],
                "RSI": item["rsi"],
                "20-day move": f"{item['ret_20']:.1%}",
                "Clears cost": "Yes" if item["cleared"] else "No",
            }
        )
    if rows:
        st.caption(f"Same ticket on {BROKERS[desk].name}, {kind}. A yes means the recent swing beat the round trip.")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_costs() -> None:
    st.subheader("What the platforms charge")
    st.caption(DISCLAIMER)
    st.caption(SCHEDULE_AS_OF)

    platform, product, amount_col, move_col, share_col = st.columns([1, 1, 1, 1, 1])
    with platform:
        desk = st.selectbox("Platform", list(BROKERS), format_func=lambda key: BROKERS[key].name, key="cost_platform")
    with product:
        kind = st.selectbox("Product", ["delivery", "intraday"], format_func=str.title, key="cost_product")
    with amount_col:
        amount = st.number_input("Buy value (INR)", min_value=500.0, value=100_000.0, step=5_000.0)
    with move_col:
        move = st.slider("Illustrated rise", min_value=0.0, max_value=0.20, value=0.05, step=0.01)
    with share_col:
        share = st.slider("Cost limit (share of the ticket)", min_value=0.002, max_value=0.02, value=0.005, step=0.001)

    sell = float(amount) * (1 + float(move))
    trip = quote(desk, float(amount), sell, kind)
    gross = sell - float(amount)
    net = gross - trip.total
    floor = minimum_ticket(desk, kind, float(share))

    charges, net_col, floor_col, amc_col = st.columns(4)
    charges.metric("Round trip", f"INR {trip.total:,.0f}", f"{trip.cost_share:.2%} of the buy")
    net_col.metric("Left after that rise", f"INR {net:,.0f}", f"gross INR {gross:,.0f}")
    floor_col.metric(
        "Smallest ticket under the limit",
        "Not reachable" if floor is None else f"INR {floor:,.0f}",
    )
    amc_col.metric("Yearly AMC", f"INR {BROKERS[desk].amc_yearly:,.0f}")
    st.caption(BROKERS[desk].note)
    st.caption(
        "The rise is an illustration of a price you already chose. "
        "The smallest ticket is where a flat exit stays inside the cost limit. "
        "Below it, fees take a larger share. Above it, they take a smaller share. "
        "Neither side is a gain you can count on. "
        f"At this ticket the price has to rise about {trip.cost_share:.2%} before a sale returns the cash you put in."
    )

    lines = pd.DataFrame(
        [{"Side": line.side.title(), "Charge": line.label, "INR": round(line.amount, 2)} for line in trip.lines if line.amount]
    )
    st.dataframe(lines, hide_index=True, width="stretch")

    board = []
    for other in compare(float(amount), sell, kind):
        board.append(
            {
                "Platform": BROKERS[other.platform].name,
                "Charges": round(other.total, 2),
                "Share": f"{other.cost_share:.2%}",
                "Left after the rise": round(gross - other.total, 2),
            }
        )
    st.dataframe(pd.DataFrame(board), hide_index=True, width="stretch")

    st.divider()
    st.subheader("Mutual fund minimums")
    st.caption(
        "A direct plan on Groww, Zerodha Coin, Upstox, Angel One, Shoonya, or the fund house "
        "uses the same expense ratio. The SIP floor is the smallest amount the AMC will take. "
        "Paying it does not create a profit. The expense ratio is already inside the NAV."
    )
    code = st.selectbox("Scheme", list(SCHEMES), format_func=lambda key: SCHEMES[key].name)
    early = st.checkbox("Redeem inside the exit-load window", value=True)
    item = SCHEMES[code]
    hurdle = fee_hurdle(code, early)
    sip, lump, drag, load = st.columns(4)
    sip.metric("Minimum SIP", f"INR {item.min_sip:,.0f}")
    lump.metric("Minimum lump sum", f"INR {item.min_lumpsum:,.0f}")
    drag.metric("Expense ratio", f"{item.expense_ratio:.2%}")
    load.metric("Rise that clears stamp and load", f"{hurdle['rise_to_clear_fees']:.2%}")
    window = "no exit load" if item.exit_days == 0 else f"{item.exit_load:.0%} if sold within {item.exit_days} days"
    st.caption(f"{item.category}. Riskometer: {item.risk}. Exit: {window}. Check the latest factsheet before you send money.")


def render_holdings() -> None:
    st.subheader("Holdings")
    st.caption(
        "A book of what each person holds on each platform. It stays in output/holdings.json on this machine. "
        "It does not place an order."
    )
    if "holdings" not in st.session_state:
        st.session_state.holdings = load_book(BOOK_PATH)

    live, early = st.columns(2)
    with live:
        use_live = st.checkbox("Live marks", value=False)
    with early:
        inside_load = st.checkbox("Value fund exits inside the load window", value=True)

    with st.form("add_holding"):
        holder, platform, kind = st.columns(3)
        with holder:
            person = st.text_input("Holder", value="Primary")
        with platform:
            desk = st.selectbox("Platform", [*BROKERS.keys(), "amc"], format_func=_platform_name)
        with kind:
            asset = st.selectbox("Kind", ["equity", "fund"], format_func=str.title)
        symbol, units, average = st.columns(3)
        with symbol:
            if asset == "fund":
                picked = st.selectbox("Scheme", list(SCHEMES), format_func=lambda key: SCHEMES[key].name)
                name = SCHEMES[picked].name
                token = picked
            else:
                token = st.text_input("Ticker", value="RELIANCE")
                name = token
                picked = token
        with units:
            count = st.number_input("Units", min_value=0.001, value=1.0, step=1.0)
        with average:
            paid = st.number_input("Average price", min_value=0.01, value=100.0, step=1.0)
        add, sample, clear = st.columns(3)
        with add:
            submitted = st.form_submit_button("Add holding", type="primary")
        with sample:
            use_sample = st.form_submit_button("Load sample book")
        with clear:
            wipe = st.form_submit_button("Clear book")

    holdings: list[Holding] = list(st.session_state.holdings)
    if submitted:
        try:
            holdings.append(Holding(person, desk, asset, token if asset == "equity" else picked, name, float(count), float(paid)))
            _store(holdings)
        except ValueError as exc:
            st.error(str(exc))
    if use_sample:
        holdings = sample_book()
        _store(holdings)
    if wipe:
        holdings = []
        _store(holdings)

    if not holdings:
        st.info("The book is empty. Add a holding or load the sample.")
        return

    marks = _marks(holdings, use_live)
    rows = []
    by_holder: dict[str, float] = {}
    for item in holdings:
        mark = marks.get((item.kind, item.symbol), item.average_price)
        value = item.market_value(mark)
        exit_cost = _exit_cost(item, value, inside_load)
        by_holder[item.holder] = by_holder.get(item.holder, 0.0) + value
        rows.append(
            {
                "Holder": item.holder,
                "Platform": _platform_name(item.platform),
                "Name": item.name,
                "Units": item.units,
                "Invested": item.invested(),
                "Mark": round(mark, 2),
                "Value": value,
                "Open P&L": item.unrealized(mark),
                "Exit cost": exit_cost,
                "After exit": round(value - exit_cost, 2),
            }
        )
    frame = pd.DataFrame(rows)
    invested, current, people = st.columns(3)
    invested.metric("Invested", f"INR {frame['Invested'].sum():,.0f}")
    current.metric("Marked value", f"INR {frame['Value'].sum():,.0f}", f"INR {frame['Open P&L'].sum():,.0f}")
    people.metric("Holders", str(frame["Holder"].nunique()))
    st.dataframe(frame, hide_index=True, width="stretch")
    chart = go.Figure(go.Bar(x=list(by_holder), y=list(by_holder.values()), marker_color="#00D1FF"))
    chart.update_layout(template="plotly_dark", height=320, margin=dict(l=10, r=10, t=30, b=10), title="Marked value by holder")
    st.plotly_chart(chart, width="stretch")

    labels = [f"{row.holder} · {row.name}" for row in holdings]
    drop = st.selectbox("Remove", labels)
    if st.button("Remove selected"):
        holdings.pop(labels.index(drop))
        _store(holdings)
        st.rerun()


def _metrics(reading: dict, trip) -> None:
    last, rsi, move, cost = st.columns(4)
    last.metric("Last", f"{reading['last']:,.2f}")
    rsi.metric("RSI", f"{reading['rsi']:.1f}")
    move.metric("20-day move", f"{reading['ret_20']:.1%}")
    cost.metric("Round trip", f"{trip.cost_share:.2%}", f"INR {trip.total:,.0f}")


def _chart(frame: pd.DataFrame, reading: dict) -> go.Figure:
    figure = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.5, 0.16, 0.17, 0.17],
    )
    figure.add_trace(
        go.Candlestick(
            x=frame.index,
            open=frame["Open"],
            high=frame["High"],
            low=frame["Low"],
            close=frame["Close"],
            name="Price",
            increasing_line_color="#00FFA3",
            decreasing_line_color="#FF4B4B",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(go.Scatter(x=frame.index, y=reading["sma20_series"], name="SMA 20", line=dict(color="#00D1FF", width=1)), row=1, col=1)
    figure.add_trace(go.Scatter(x=frame.index, y=reading["sma50_series"], name="SMA 50", line=dict(color="#FFA500", width=1)), row=1, col=1)
    if "Volume" in frame.columns:
        figure.add_trace(go.Bar(x=frame.index, y=frame["Volume"], name="Volume", marker_color="#445"), row=2, col=1)
    figure.add_trace(go.Scatter(x=frame.index, y=reading["rsi_series"], name="RSI", line=dict(color="#00FFA3", width=1)), row=3, col=1)
    figure.add_trace(go.Scatter(x=frame.index, y=reading["macd_series"], name="MACD", line=dict(color="#FF4B4B", width=1)), row=4, col=1)
    figure.update_layout(template="plotly_dark", height=720, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=20, b=10))
    return figure


def _panel(use_live: bool) -> dict[str, pd.DataFrame]:
    try:
        frames = fetch_closes() if use_live else demo_frames()
    except Exception as exc:
        st.error(f"Price download failed: {exc}")
        return {}
    return frames


def _frame_for(frames: dict[str, pd.DataFrame], ticker: str, use_live: bool) -> pd.DataFrame | None:
    if ticker in frames:
        return frames[ticker]
    bare = ticker.replace(".NS", "").replace(".BO", "")
    for key, frame in frames.items():
        if key.replace(".NS", "").replace(".BO", "") == bare:
            return frame
    if not use_live:
        return None
    history = fetch_history(ticker)
    return history if not history.empty else None


def _marks(holdings: list[Holding], use_live: bool) -> dict[tuple[str, str], float]:
    marks: dict[tuple[str, str], float] = {}
    equities = [item.symbol for item in holdings if item.kind == "equity"]
    live_prices: dict[str, float] = {}
    if use_live and equities:
        try:
            downloaded = fetch_closes(equities)
            live_prices = {key: float(frame["Close"].iloc[-1]) for key, frame in downloaded.items() if not frame.empty}
        except Exception as exc:
            st.warning(f"Live equity marks failed: {exc}")
    sample = {key: float(frame["Close"].iloc[-1]) for key, frame in demo_frames().items()}
    for item in holdings:
        if item.kind == "equity":
            marks[(item.kind, item.symbol)] = live_prices.get(item.symbol, sample.get(item.symbol, item.average_price))
            continue
        if use_live:
            fetched = fetch_nav(item.symbol)
            if fetched is not None:
                marks[(item.kind, item.symbol)] = fetched[0]
                continue
        sample_nav = SCHEMES[item.symbol].sample_nav if item.symbol in SCHEMES else None
        marks[(item.kind, item.symbol)] = sample_nav if sample_nav is not None else item.average_price
    return marks


def _exit_cost(item: Holding, value: float, inside_load: bool) -> float:
    if item.kind == "fund":
        if item.symbol not in SCHEMES:
            return 0.0
        return fund_exit(item.symbol, value, inside_load)
    if item.platform not in BROKERS:
        return 0.0
    return quote(item.platform, value).side_total("sell")


def _store(holdings: list[Holding]) -> None:
    st.session_state.holdings = holdings
    save_book(BOOK_PATH, holdings)


def _platform_name(key: str) -> str:
    if key in BROKERS:
        return BROKERS[key].name
    if key == "amc":
        return "AMC direct"
    return key
