"""Round-trip costs on Indian equity desks.

The schedules follow brokerage cards published in early 2026. Statutory
rates are the same at every broker. Delivery STT here is 0.1% on both
sides. Exchange transaction charge is the NSE equity rate from March 2026.
Confirm the card before sending money. A ticket that clears a cost limit
is not a guaranteed profit.
"""

from __future__ import annotations

from dataclasses import dataclass


STT_DELIVERY = 0.001
STT_INTRADAY_SELL = 0.00025
STAMP_DELIVERY = 0.00015
STAMP_INTRADAY = 0.00003
TXN = 0.0000307
SEBI = 0.000001
GST = 0.18
STAMP_FUND = 0.00005

SCHEDULE_AS_OF = "Equity cards as published in early 2026. Delivery and intraday only."


@dataclass(frozen=True)
class BrokerSchedule:
    key: str
    name: str
    delivery_rate: float
    delivery_cap: float | None
    delivery_floor: float
    intraday_rate: float
    intraday_cap: float | None
    intraday_floor: float
    dp_per_scrip: float
    dp_includes_gst: bool
    amc_yearly: float
    note: str


BROKERS: dict[str, BrokerSchedule] = {
    "zerodha": BrokerSchedule(
        key="zerodha",
        name="Zerodha",
        delivery_rate=0.0,
        delivery_cap=None,
        delivery_floor=0.0,
        intraday_rate=0.0003,
        intraday_cap=20.0,
        intraday_floor=0.0,
        dp_per_scrip=15.34,
        dp_includes_gst=True,
        amc_yearly=300.0,
        note="Delivery brokerage is zero. DP is ₹15.34 per scrip on a sell, GST included. AMC is ₹300 a year before GST unless the account qualifies as a basic services demat account.",
    ),
    "groww": BrokerSchedule(
        key="groww",
        name="Groww",
        delivery_rate=0.001,
        delivery_cap=20.0,
        delivery_floor=5.0,
        intraday_rate=0.001,
        intraday_cap=20.0,
        intraday_floor=5.0,
        dp_per_scrip=20.0,
        dp_includes_gst=False,
        amc_yearly=0.0,
        note="Delivery brokerage is 0.1% or ₹20, whichever is lower, with a ₹5 floor. Groww waives its own DP slice on a sell under ₹100. This schedule still counts the full DP charge.",
    ),
    "upstox": BrokerSchedule(
        key="upstox",
        name="Upstox",
        delivery_rate=0.0,
        delivery_cap=None,
        delivery_floor=20.0,
        intraday_rate=0.001,
        intraday_cap=20.0,
        intraday_floor=0.0,
        dp_per_scrip=20.0,
        dp_includes_gst=False,
        amc_yearly=300.0,
        note="Delivery is a flat ₹20 per executed order. AMC is commonly ₹300 plus GST after the first year, unless the account is a basic services demat account.",
    ),
    "angel_one": BrokerSchedule(
        key="angel_one",
        name="Angel One",
        delivery_rate=0.001,
        delivery_cap=20.0,
        delivery_floor=5.0,
        intraday_rate=0.001,
        intraday_cap=20.0,
        intraday_floor=5.0,
        dp_per_scrip=20.0,
        dp_includes_gst=False,
        amc_yearly=240.0,
        note="Delivery brokerage is 0.1% or ₹20, whichever is lower, with a ₹5 floor. AMC on the common plan is about ₹240 a year. Check the plan on the app.",
    ),
    "shoonya": BrokerSchedule(
        key="shoonya",
        name="Shoonya",
        delivery_rate=0.0,
        delivery_cap=None,
        delivery_floor=0.0,
        intraday_rate=0.0003,
        intraday_cap=5.0,
        intraday_floor=0.0,
        dp_per_scrip=20.0,
        dp_includes_gst=False,
        amc_yearly=0.0,
        note="Delivery brokerage is zero for an individual. The pricing page lists a ₹20 DP instruction. The FAQ lists ₹9 plus GST for some clients. This schedule uses ₹20 plus GST so the ticket is not understated.",
    ),
}


@dataclass(frozen=True)
class CostLine:
    side: str
    label: str
    amount: float


@dataclass(frozen=True)
class RoundTrip:
    platform: str
    product: str
    buy_value: float
    sell_value: float
    lines: tuple[CostLine, ...]

    @property
    def total(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)

    @property
    def cost_share(self) -> float:
        if self.buy_value <= 0:
            return 0.0
        return self.total / self.buy_value

    def side_total(self, side: str) -> float:
        return round(sum(line.amount for line in self.lines if line.side == side), 2)


def brokerage(value: float, rate: float, cap: float | None, floor: float) -> float:
    """Rupee brokerage for one order. A zero rate with a floor is a flat fee."""
    if value < 0:
        raise ValueError("order value must be positive")
    if rate <= 0:
        return float(floor)
    amount = value * rate
    if cap is not None:
        amount = min(amount, cap)
    return max(amount, floor)


def quote(
    platform: str,
    buy_value: float,
    sell_value: float | None = None,
    product: str = "delivery",
    scrips: int = 1,
) -> RoundTrip:
    """Price a buy and a sell. `sell_value` defaults to the buy, a flat exit."""
    schedule = _schedule(platform)
    if product not in ("delivery", "intraday"):
        raise ValueError(f"unknown product: {product}")
    if buy_value <= 0:
        raise ValueError("buy value must be positive")
    if scrips < 1:
        raise ValueError("scrips must be at least 1")
    sell_value = buy_value if sell_value is None else sell_value
    if sell_value <= 0:
        raise ValueError("sell value must be positive")

    lines: list[CostLine] = []
    lines.extend(_leg(schedule, buy_value, product, "buy", scrips))
    lines.extend(_leg(schedule, sell_value, product, "sell", scrips))
    return RoundTrip(schedule.key, product, float(buy_value), float(sell_value), tuple(lines))


def minimum_ticket(platform: str, product: str = "delivery", cost_share: float = 0.005) -> float | None:
    """Smallest buy, sold flat, whose round trip is within `cost_share` of the ticket.

    Returns None when even a very large ticket stays above the limit. That
    happens when stamp duty and STT alone exceed the share you allowed.
    """
    if cost_share <= 0:
        raise ValueError("cost share must be positive")
    hi = 5_000_000.0
    if quote(platform, hi, product=product).cost_share > cost_share:
        return None
    lo = 100.0
    if quote(platform, lo, product=product).cost_share <= cost_share:
        return lo
    for _ in range(40):
        mid = (lo + hi) / 2
        if quote(platform, mid, product=product).cost_share <= cost_share:
            hi = mid
        else:
            lo = mid
    return round(hi, 2)


def compare(buy_value: float, sell_value: float | None = None, product: str = "delivery") -> list[RoundTrip]:
    return [quote(key, buy_value, sell_value, product) for key in BROKERS]


def _schedule(platform: str) -> BrokerSchedule:
    key = platform.strip().lower().replace(" ", "_")
    if key not in BROKERS:
        raise ValueError(f"unknown platform: {platform}")
    return BROKERS[key]


def _leg(schedule: BrokerSchedule, value: float, product: str, side: str, scrips: int) -> list[CostLine]:
    if product == "delivery":
        rate, cap, floor = schedule.delivery_rate, schedule.delivery_cap, schedule.delivery_floor
        stt = value * STT_DELIVERY
        stamp = value * STAMP_DELIVERY if side == "buy" else 0.0
    else:
        rate, cap, floor = schedule.intraday_rate, schedule.intraday_cap, schedule.intraday_floor
        stt = value * STT_INTRADAY_SELL if side == "sell" else 0.0
        stamp = value * STAMP_INTRADAY if side == "buy" else 0.0

    brok = brokerage(value, rate, cap, floor)
    txn = value * TXN
    sebi = value * SEBI
    gst = GST * (brok + txn + sebi)
    lines = [
        CostLine(side, "Brokerage", brok),
        CostLine(side, "STT", stt),
        CostLine(side, "Stamp duty", stamp),
        CostLine(side, "Exchange fee", txn),
        CostLine(side, "SEBI fee", sebi),
        CostLine(side, "GST", gst),
    ]
    if product == "delivery" and side == "sell":
        dp = schedule.dp_per_scrip * scrips
        lines.append(CostLine(side, "DP charge", dp))
        if not schedule.dp_includes_gst:
            lines.append(CostLine(side, "GST on DP", dp * GST))
    return lines
