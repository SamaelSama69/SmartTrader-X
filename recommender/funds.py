"""Direct-plan mutual funds the holdings page can mark.

Expense ratios and exit loads are working figures from scheme documents,
not a live factsheet. The AMC minimum is the smallest amount the fund will
accept. It is not an amount that locks in a profit. Direct plans on Groww,
Zerodha Coin, Upstox, Angel One, Shoonya, and the AMC site carry the same
expense ratio. A regular plan costs more and is not listed here.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from recommender.costs import STAMP_FUND


@dataclass(frozen=True)
class FundScheme:
    code: str
    name: str
    category: str
    expense_ratio: float
    exit_load: float
    exit_days: int
    min_sip: float
    min_lumpsum: float
    risk: str
    sample_nav: float | None = None


SCHEMES: dict[str, FundScheme] = {
    "122639": FundScheme(
        code="122639",
        name="Parag Parikh Flexi Cap Fund - Direct Growth",
        category="Flexi cap",
        expense_ratio=0.0063,
        exit_load=0.01,
        exit_days=365,
        min_sip=1000,
        min_lumpsum=1000,
        risk="Very high",
        sample_nav=94.26,
    ),
    "120716": FundScheme(
        code="120716",
        name="UTI Nifty 50 Index Fund - Direct Growth",
        category="Index",
        expense_ratio=0.0018,
        exit_load=0.0,
        exit_days=0,
        min_sip=500,
        min_lumpsum=500,
        risk="Very high",
        sample_nav=177.16,
    ),
    "120465": FundScheme(
        code="120465",
        name="Axis Bluechip Fund - Direct Growth",
        category="Large cap",
        expense_ratio=0.0055,
        exit_load=0.01,
        exit_days=365,
        min_sip=500,
        min_lumpsum=500,
        risk="Very high",
    ),
    "125354": FundScheme(
        code="125354",
        name="Axis Small Cap Fund - Direct Growth",
        category="Small cap",
        expense_ratio=0.0052,
        exit_load=0.01,
        exit_days=365,
        min_sip=500,
        min_lumpsum=500,
        risk="Very high",
    ),
}


def scheme(code: str) -> FundScheme:
    if code not in SCHEMES:
        raise ValueError(f"unknown scheme: {code}")
    return SCHEMES[code]


def fee_hurdle(code: str, early_exit: bool = True) -> dict:
    """What a redemption has to clear before the cash out exceeds the cash in.

    The expense ratio is already inside the published NAV, so it is reported
    on its own and is not added again on top of the exit load.
    """
    item = scheme(code)
    load = item.exit_load if early_exit else 0.0
    rise = STAMP_FUND + load
    return {
        "stamp": STAMP_FUND,
        "exit_load": load,
        "expense_ratio": item.expense_ratio,
        "rise_to_clear_fees": rise,
        "min_sip": item.min_sip,
        "min_lumpsum": item.min_lumpsum,
    }


def fund_exit(code: str, value: float, early_exit: bool = True) -> float:
    if value < 0:
        raise ValueError("value must be positive")
    return round(value * fee_hurdle(code, early_exit)["exit_load"], 2)


def fetch_nav(code: str) -> tuple[float, str] | None:
    """Latest NAV from the public mfapi.in feed. None when the feed is down."""
    for url in (f"https://api.mfapi.in/mf/{code}/latest", f"https://api.mfapi.in/mf/{code}"):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "SmartTrader-X"})
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            row = payload["data"][0]
            return float(row["nav"]), str(row["date"])
        except (OSError, KeyError, ValueError, IndexError, TypeError):
            continue
    return None
