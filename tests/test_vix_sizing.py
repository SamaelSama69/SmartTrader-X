"""Tests for VIX-based position sizing multiplier."""
import pytest
from utils.risk_manager import RiskManager


class TestVixRiskMultiplier:
    """Boundary tests for vix_risk_multiplier()."""

    def test_vix_none_returns_1(self):
        assert RiskManager.vix_risk_multiplier(None) == 1.0

    def test_vix_zero_returns_1(self):
        assert RiskManager.vix_risk_multiplier(0) == 1.0

    def test_vix_negative_returns_1(self):
        assert RiskManager.vix_risk_multiplier(-5) == 1.0

    def test_vix_complacency_below_13(self):
        assert RiskManager.vix_risk_multiplier(10) == 0.80
        assert RiskManager.vix_risk_multiplier(12.99) == 0.80

    def test_vix_normal_13_to_20(self):
        assert RiskManager.vix_risk_multiplier(13) == 1.00
        assert RiskManager.vix_risk_multiplier(15) == 1.00
        assert RiskManager.vix_risk_multiplier(20) == 1.00

    def test_vix_fear_20_to_30(self):
        assert RiskManager.vix_risk_multiplier(20.01) == 0.60
        assert RiskManager.vix_risk_multiplier(25) == 0.60
        assert RiskManager.vix_risk_multiplier(30) == 0.60

    def test_vix_crisis_above_30(self):
        assert RiskManager.vix_risk_multiplier(30.01) == 0.30
        assert RiskManager.vix_risk_multiplier(45) == 0.30
        assert RiskManager.vix_risk_multiplier(80) == 0.30


class TestKellyWithVix:
    """Test that size_position_kelly integrates VIX multiplier correctly."""

    def test_kelly_no_vix_unchanged(self):
        rm = RiskManager(initial_capital=100_000)
        shares_no_vix = rm.size_position_kelly(100.0, 0.8)
        shares_none_vix = rm.size_position_kelly(100.0, 0.8, vix=None)
        assert shares_no_vix == shares_none_vix

    def test_kelly_normal_vix_unchanged(self):
        rm = RiskManager(initial_capital=100_000)
        shares_base = rm.size_position_kelly(100.0, 0.8, vix=None)
        shares_normal = rm.size_position_kelly(100.0, 0.8, vix=15.0)
        assert shares_normal == shares_base

    def test_kelly_crisis_vix_reduces_shares(self):
        rm = RiskManager(initial_capital=500_000)
        shares_normal = rm.size_position_kelly(100.0, 0.8, vix=15.0)
        shares_crisis = rm.size_position_kelly(100.0, 0.8, vix=35.0)
        assert shares_crisis < shares_normal, (
            f"Crisis VIX should produce fewer shares: {shares_crisis} >= {shares_normal}"
        )

    def test_kelly_complacency_vix_slightly_reduces(self):
        rm = RiskManager(initial_capital=500_000)
        shares_normal = rm.size_position_kelly(100.0, 0.8, vix=15.0)
        shares_complacent = rm.size_position_kelly(100.0, 0.8, vix=10.0)
        assert shares_complacent <= shares_normal
