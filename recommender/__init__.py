"""End-to-end trade and investment recommendations for an NSE book."""

from recommender.engine import recommend
from recommender.models import InvestorProfile, RecommendationBook

__all__ = ["InvestorProfile", "RecommendationBook", "recommend"]
