"""A local watchlist with a price above and a price below.

An alert is checked when the desk is opened. Nothing is emailed, and
nothing is sent to a broker.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Watch:
    symbol: str
    above: float | None = None
    below: float | None = None

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()
        if not self.symbol:
            raise ValueError("symbol is required")
        if not (self.symbol.endswith(".NS") or self.symbol.endswith(".BO")):
            self.symbol = f"{self.symbol}.NS"
        if self.above is not None and self.above <= 0:
            raise ValueError("above must be positive")
        if self.below is not None and self.below <= 0:
            raise ValueError("below must be positive")
        if self.above is not None and self.below is not None and self.below >= self.above:
            raise ValueError("below must be under above")

    def status(self, price: float) -> str:
        if price <= 0:
            return "no mark"
        if self.above is not None and price >= self.above:
            return "above"
        if self.below is not None and price <= self.below:
            return "below"
        return "inside"


def load_watch(path: Path) -> list[Watch]:
    if not path.exists():
        return []
    return [Watch(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def save_watch(path: Path, rows: list[Watch]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(row) for row in rows], indent=2), encoding="utf-8")
