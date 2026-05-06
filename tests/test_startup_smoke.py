"""
Smoke tests — verify all modules import and core classes instantiate without
crashing. No real API calls are made.
"""
import pytest
from unittest.mock import patch, MagicMock


def test_config_imports():
    import config
    assert hasattr(config, 'OUTPUT_DIR')
    assert hasattr(config, 'MEMORY_DIR')
    assert hasattr(config, 'CONFIDENCE_THRESHOLD')


def test_risk_manager_instantiates():
    from utils.risk_manager import RiskManager
    rm = RiskManager(initial_capital=100_000)
    assert rm.initial_capital == 100_000
    assert rm.trading_enabled is True


def test_paper_trade_manager_instantiates():
    from utils.paper_trade_manager import PaperTradeManager
    pt = PaperTradeManager()
    positions = pt.get_open_positions()
    assert isinstance(positions, list)


def test_market_regime_instantiates():
    from utils.market_regime import IndianMarketRegime
    regime = IndianMarketRegime()
    assert regime is not None


def test_screener_instantiates():
    from utils.screener import SmartScreener
    screener = SmartScreener()
    assert len(screener.major_tickers) > 0


def test_strategies_import():
    from strategies.stocks import StockStrategy, MomentumBreakoutStrategy
    from strategies.indian_momentum import IndianMomentumStrategy
    from strategies.algorithms import AlgorithmSelector
    # Mocking dependencies for strategies that might try to load models
    with patch('utils.multilingual_sentiment.AdvancedTransformerAnalyzer'):
        assert StockStrategy() is not None
        assert MomentumBreakoutStrategy() is not None
        assert IndianMomentumStrategy() is not None
        assert AlgorithmSelector() is not None


def test_notifier_instantiates():
    from utils.notifier import Notifier
    n = Notifier()
    assert hasattr(n, 'send')


def test_sebi_compliance_instantiates():
    from utils.sebi_compliance import get_compliance_manager
    cm = get_compliance_manager()
    assert cm is not None
