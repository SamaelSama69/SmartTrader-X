"""Investor profile and the recommendation book returned to the dashboard and CLI."""

from dataclasses import asdict, dataclass, field
from typing import Literal


RiskLevel = Literal["conservative", "balanced", "growth"]
Horizon = Literal["trading", "investment", "both"]
Sleeve = Literal["trade", "invest"]
Action = Literal["buy", "watch", "avoid"]


@dataclass
class InvestorProfile:
    capital: float = 500_000.0
    risk: RiskLevel = "balanced"
    horizon: Horizon = "both"
    max_names: int = 6

    def __post_init__(self) -> None:
        if self.capital <= 0:
            raise ValueError("capital must be positive")
        if self.risk not in ("conservative", "balanced", "growth"):
            raise ValueError(f"unknown risk level: {self.risk}")
        if self.horizon not in ("trading", "investment", "both"):
            raise ValueError(f"unknown horizon: {self.horizon}")
        if self.max_names < 1:
            raise ValueError("max_names must be at least 1")


@dataclass
class NameScore:
    ticker: str
    sector: str
    last_price: float
    ret_20: float
    ret_60: float
    vol_20: float
    trend: float
    drawdown: float
    trade_score: float
    invest_score: float


@dataclass
class Recommendation:
    ticker: str
    sector: str
    sleeve: Sleeve
    action: Action
    score: float
    weight: float
    amount: float
    shares: int
    horizon_days: int
    last_price: float
    stop: float | None
    target: float | None
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecommendationBook:
    as_of: str
    regime: str
    profile: InvestorProfile
    cash_weight: float
    cash_amount: float
    recommendations: list[Recommendation]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["profile"] = asdict(self.profile)
        return payload
