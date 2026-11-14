"""Rank an NSE price panel into a trade sleeve and an investment sleeve.

The engine does not place orders. It turns recent closes into a capital
allocation that matches the investor's risk and horizon.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from recommender.models import (
    InvestorProfile,
    NameScore,
    Recommendation,
    RecommendationBook,
)

POLICIES = {
    "conservative": {"cash": 0.45, "max_weight": 0.10, "trade_budget": 0.20, "min_score": 0.60},
    "balanced": {"cash": 0.25, "max_weight": 0.16, "trade_budget": 0.40, "min_score": 0.50},
    "growth": {"cash": 0.10, "max_weight": 0.22, "trade_budget": 0.65, "min_score": 0.45},
}


def score_frame(ticker: str, frame: pd.DataFrame, sector: str = "other") -> NameScore | None:
    """Score one symbol. Returns None when there are fewer than 60 closes."""
    if frame is None or frame.empty or "Close" not in frame.columns:
        return None
    close = frame["Close"].dropna()
    if len(close) < 60:
        return None

    last = float(close.iloc[-1])
    if last <= 0:
        return None
    ret_20 = float(close.iloc[-1] / close.iloc[-21] - 1)
    ret_60 = float(close.iloc[-1] / close.iloc[-61] - 1)
    returns = close.pct_change().dropna()
    vol_20 = float(returns.tail(20).std() * np.sqrt(252))
    if np.isnan(vol_20):
        vol_20 = 0.0
    average = float(close.tail(50).mean())
    trend = last / average - 1 if average else 0.0
    peak = float(close.tail(60).max())
    drawdown = last / peak - 1 if peak else 0.0
    return NameScore(
        ticker=ticker,
        sector=sector,
        last_price=round(last, 2),
        ret_20=ret_20,
        ret_60=ret_60,
        vol_20=vol_20,
        trend=trend,
        drawdown=drawdown,
        trade_score=_trade_score(ret_20, vol_20, trend),
        invest_score=_invest_score(ret_60, vol_20, drawdown, trend),
    )


def recommend(
    frames: dict[str, pd.DataFrame],
    profile: InvestorProfile,
    sectors: dict[str, str] | None = None,
    regime: str | None = None,
) -> RecommendationBook:
    """Build a recommendation book from close-price frames."""
    sectors = sectors or {}
    scored = []
    for ticker, frame in frames.items():
        row = score_frame(ticker, frame, sectors.get(ticker, sectors.get(_bare(ticker), "other")))
        if row is not None:
            scored.append(row)

    if not scored:
        raise ValueError("no symbol had 60 closes to score")

    regime = regime or _infer_regime(scored)
    policy = dict(POLICIES[profile.risk])
    if profile.horizon == "trading":
        policy["trade_budget"] = 0.85
    elif profile.horizon == "investment":
        policy["trade_budget"] = 0.0
    if regime == "BEAR_TREND":
        policy["cash"] = min(0.70, policy["cash"] + 0.15)
        policy["trade_budget"] *= 0.5

    chosen = _select(scored, profile, policy)
    recommendations = [_size(row, sleeve, profile, policy, regime) for row, sleeve in chosen]
    recommendations.extend(_avoids(scored, {row.ticker for row, _ in chosen}, regime))
    cash_amount = _allocate(recommendations, profile, policy["cash"])

    notes = [
        "Research ranking only. This book does not place a broker order.",
        f"Regime used for sizing: {regime.replace('_', ' ').title()}.",
    ]
    if regime == "BEAR_TREND":
        notes.append("A falling market raises cash and cuts the trading sleeve.")
    return RecommendationBook(
        as_of=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        regime=regime,
        profile=profile,
        cash_weight=round(cash_amount / profile.capital, 4),
        cash_amount=round(cash_amount, 2),
        recommendations=recommendations,
        notes=notes,
    )


def _trade_score(ret_20: float, vol_20: float, trend: float) -> float:
    score = 0.0
    if ret_20 > 0.02:
        score += 0.35
    if 0.03 <= ret_20 <= 0.18:
        score += 0.25
    if trend > 0:
        score += 0.25
    if 0.12 <= vol_20 <= 0.50:
        score += 0.15
    return round(score, 4)


def _invest_score(ret_60: float, vol_20: float, drawdown: float, trend: float) -> float:
    score = 0.0
    if ret_60 > 0.05:
        score += 0.35
    if trend > -0.02:
        score += 0.25
    if vol_20 < 0.30:
        score += 0.25
    if drawdown > -0.15:
        score += 0.15
    return round(score, 4)


def _infer_regime(scored: list[NameScore]) -> str:
    median = float(np.median([row.ret_20 for row in scored]))
    if median > 0.03:
        return "BULL_TREND"
    if median < -0.03:
        return "BEAR_TREND"
    return "SIDEWAYS"


def _select(scored: list[NameScore], profile: InvestorProfile, policy: dict) -> list[tuple[NameScore, str]]:
    min_score = policy["min_score"]
    trade_slots = int(round(profile.max_names * policy["trade_budget"]))
    invest_slots = profile.max_names - trade_slots
    if profile.horizon == "trading":
        invest_slots = max(0, profile.max_names - trade_slots)
    chosen: list[tuple[NameScore, str]] = []
    used_sectors: set[str] = set()

    def take(pool: list[NameScore], sleeve: str, slots: int) -> None:
        if slots <= 0:
            return
        ordered = sorted(pool, key=lambda row: row.trade_score if sleeve == "trade" else row.invest_score, reverse=True)
        for row in ordered:
            if len([item for item in chosen if item[1] == sleeve]) >= slots:
                return
            if any(picked.ticker == row.ticker for picked, _ in chosen):
                continue
            if row.sector in used_sectors and row.sector != "other":
                continue
            score = row.trade_score if sleeve == "trade" else row.invest_score
            if score < min_score:
                continue
            chosen.append((row, sleeve))
            used_sectors.add(row.sector)

    traders = [
        row for row in scored
        if _preferred(row, profile.horizon) == "trade" and row.trade_score >= min_score
    ]
    investors = [
        row for row in scored
        if _preferred(row, profile.horizon) == "invest" and row.invest_score >= min_score
    ]
    if profile.horizon != "investment":
        take(traders, "trade", trade_slots)
    if profile.horizon != "trading":
        take(investors, "invest", invest_slots)

    # Fill unused slots from the other sleeve when the preferred sleeve is thin.
    short = profile.max_names - len(chosen)
    if short > 0 and profile.horizon == "both":
        rest = [row for row in scored if not any(picked.ticker == row.ticker for picked, _ in chosen)]
        rest.sort(key=lambda row: max(row.trade_score, row.invest_score), reverse=True)
        for row in rest:
            if len(chosen) >= profile.max_names:
                break
            sleeve = "trade" if row.trade_score >= row.invest_score else "invest"
            score = row.trade_score if sleeve == "trade" else row.invest_score
            if score < min_score:
                continue
            chosen.append((row, sleeve))
    return chosen


def _preferred(row: NameScore, horizon: str) -> str:
    if horizon == "investment":
        return "invest"
    if horizon == "trading":
        return "trade"
    if row.trade_score > row.invest_score:
        return "trade"
    return "invest"


def _size(row: NameScore, sleeve: str, profile: InvestorProfile, policy: dict, regime: str) -> Recommendation:
    score = row.trade_score if sleeve == "trade" else row.invest_score
    daily = row.vol_20 / np.sqrt(252) if row.vol_20 else 0.02
    if sleeve == "trade":
        distance = float(np.clip(2 * daily, 0.04, 0.12))
        horizon = 15
        target = round(row.last_price * (1 + 2 * distance), 2)
    else:
        distance = float(np.clip(3 * daily, 0.08, 0.20))
        horizon = 180
        target = round(row.last_price * 1.20, 2)
    stop = round(row.last_price * (1 - distance), 2)
    return Recommendation(
        ticker=row.ticker,
        sector=row.sector,
        sleeve=sleeve,
        action="buy",
        score=score,
        weight=0.0,
        amount=0.0,
        shares=0,
        horizon_days=horizon,
        last_price=row.last_price,
        stop=stop,
        target=target,
        reasons=_reasons(row, sleeve, regime),
        risks=_risks(row, sleeve),
    )


def _allocate(recommendations: list[Recommendation], profile: InvestorProfile, cash_floor: float) -> float:
    buys = [item for item in recommendations if item.action == "buy"]
    if buys:
        raw = np.array([max(item.score, 0.01) for item in buys], dtype=float)
        weights = raw / raw.sum() * (1 - cash_floor)
        cap = POLICIES[profile.risk]["max_weight"]
        weights = np.minimum(weights, cap)
        for item, weight in zip(buys, weights):
            amount = profile.capital * float(weight)
            shares = int(amount // item.last_price) if item.last_price else 0
            item.shares = shares
            item.amount = round(shares * item.last_price, 2)
            item.weight = round(item.amount / profile.capital, 4)
    return profile.capital - sum(item.amount for item in buys)


def _avoids(scored: list[NameScore], held: set[str], regime: str) -> list[Recommendation]:
    weak = [row for row in scored if row.ticker not in held and row.ret_60 < -0.08 and row.drawdown < -0.12]
    weak.sort(key=lambda row: row.ret_60)
    avoided = []
    for row in weak[:3]:
        avoided.append(
            Recommendation(
                ticker=row.ticker,
                sector=row.sector,
                sleeve="invest",
                action="avoid",
                score=round(max(row.trade_score, row.invest_score), 4),
                weight=0.0,
                amount=0.0,
                shares=0,
                horizon_days=0,
                last_price=row.last_price,
                stop=None,
                target=None,
                reasons=[
                    f"60-day return is {row.ret_60:.1%}.",
                    f"Price is {abs(row.drawdown):.1%} under its 60-day high.",
                ],
                risks=[f"Adding this name fights the {regime.replace('_', ' ').lower()} tape."],
            )
        )
    return avoided


def _reasons(row: NameScore, sleeve: str, regime: str) -> list[str]:
    lines = [f"Market regime is {regime.replace('_', ' ').lower()}."]
    if sleeve == "trade":
        lines.append(f"20-day return is {row.ret_20:.1%}.")
        if row.trend > 0:
            lines.append("Price is above its 50-day average.")
        if 0.12 <= row.vol_20 <= 0.50:
            lines.append(f"Annualized volatility is {row.vol_20:.0%}, inside the swing band.")
    else:
        lines.append(f"60-day return is {row.ret_60:.1%}.")
        if row.vol_20 < 0.30:
            lines.append(f"Annualized volatility is {row.vol_20:.0%}, suitable for a longer hold.")
        if row.drawdown > -0.15:
            lines.append(f"Drawdown from the 60-day high is only {abs(row.drawdown):.1%}.")
    return lines


def _risks(row: NameScore, sleeve: str) -> list[str]:
    risks = ["A stop-loss does not protect against a gap through that price."]
    if row.vol_20 >= 0.35:
        risks.append(f"Volatility is elevated at {row.vol_20:.0%} annualized.")
    if row.ret_20 > 0.15 and sleeve == "trade":
        risks.append("The 20-day run is already extended, so the stop is closer.")
    if sleeve == "invest":
        risks.append("Review this holding around the 180-day horizon rather than trading it.")
    return risks


def _bare(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "")

