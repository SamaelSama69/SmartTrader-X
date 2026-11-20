"""A local book of holdings, one row per person and platform.

The file stays on this machine. It is a record of what was bought, not an
order, and it is not sent anywhere.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Holding:
    holder: str
    platform: str
    kind: str
    symbol: str
    name: str
    units: float
    average_price: float

    def __post_init__(self) -> None:
        self.holder = self.holder.strip() or "Primary"
        self.platform = self.platform.strip().lower().replace(" ", "_")
        if self.kind not in ("equity", "fund"):
            raise ValueError(f"unknown holding kind: {self.kind}")
        if self.units <= 0:
            raise ValueError("units must be positive")
        if self.average_price <= 0:
            raise ValueError("average price must be positive")
        self.symbol = self.symbol.strip().upper()
        if self.kind == "equity" and not (self.symbol.endswith(".NS") or self.symbol.endswith(".BO")):
            self.symbol = f"{self.symbol}.NS"
        self.name = self.name.strip() or self.symbol

    def invested(self) -> float:
        return round(self.units * self.average_price, 2)

    def market_value(self, mark: float) -> float:
        return round(self.units * mark, 2)

    def unrealized(self, mark: float) -> float:
        return round(self.market_value(mark) - self.invested(), 2)


def load_book(path: Path) -> list[Holding]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Holding(**row) for row in payload]


def save_book(path: Path, holdings: list[Holding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(row) for row in holdings]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def sample_book() -> list[Holding]:
    """A book with two holders so the page is not empty on a first open."""
    return [
        Holding("Primary", "zerodha", "equity", "RELIANCE", "Reliance", 10, 1280),
        Holding("Primary", "groww", "fund", "122639", "Parag Parikh Flexi Cap Fund - Direct Growth", 40, 80),
        Holding("Family", "angel_one", "equity", "TCS", "TCS", 4, 3500),
        Holding("Family", "zerodha", "fund", "120716", "UTI Nifty 50 Index Fund - Direct Growth", 12, 160),
    ]
