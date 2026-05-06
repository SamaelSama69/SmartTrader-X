import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from strategies.indian_momentum import MomentumScorer, VCPPatternDetector, IndianMomentumStrategy

@pytest.fixture
def sample_data():
    """Create a sample price dataframe with a clear upward trend"""
    dates = pd.date_range(start='2024-01-01', periods=300, freq='D')
    # Price starts at 100 and grows steadily to 200 (100% gain)
    prices = np.linspace(100, 250, 300)
    # Add some small noise
    prices += np.random.normal(0, 0.5, 300)
    
    df = pd.DataFrame({
        'Date': dates,
        'Close': prices,
        'High': prices + 1,
        'Low': prices - 1,
        'Volume': np.random.randint(1000, 5000, 300)
    })
    return df

def test_indian_momentum_strategy_buy_signal(sample_data):
    """Should generate BUY signal for a strong uptrend"""
    strategy = IndianMomentumStrategy()
    # Create benchmark data (NIFTY) - slower growth
    bench_prices = np.linspace(100, 150, 300)
    bench_df = pd.DataFrame({
        'Close': bench_prices
    })
    
    # Manually inject VCP pattern into last 60 days of sample_data to ensure strong buy
    # Divide last 60 days into 3 windows of 20
    # Window 1: 10% range
    # Window 2: 5% range
    # Window 3: 2% range
    for i in range(240, 300):
        if i < 260: range_pct = 0.10
        elif i < 280: range_pct = 0.05
        else: range_pct = 0.02
        
        mid = sample_data.iloc[i]['Close']
        sample_data.at[i, 'High'] = mid * (1 + range_pct)
        sample_data.at[i, 'Low'] = mid * (1 - range_pct)

    # Ensure volume confirmation for BUY signal
    sample_data.at[299, 'Volume'] = 10000 

    result = strategy.analyze_ticker("RELIANCE.NS", sample_data, bench_df)
    
    assert result['signal'] == 'BUY'
    assert result['factors']['vcp_pattern'] is True
    assert result['factors']['rs_score'] > 0
    assert result['confidence'] >= 0.6

def test_momentum_scorer_calculates_positive_score(sample_data):
    """Score should be highly positive for a clear uptrend"""
    scorer = MomentumScorer(window_short=90, window_long=180)
    score = scorer.calculate_score(sample_data)
    assert score > 0
    assert isinstance(score, float)

def test_momentum_scorer_handles_empty_data():
    """Should return 0 for empty dataframe"""
    scorer = MomentumScorer()
    df = pd.DataFrame()
    assert scorer.calculate_score(df) == 0.0

def test_momentum_scorer_ranking(sample_data):
    """A stock with 100% gain should rank higher than a stock with 10% gain"""
    # High momentum data (100 -> 250)
    high_mom_df = sample_data
    
    # Low momentum data (100 -> 110)
    low_mom_prices = np.linspace(100, 110, len(sample_data))
    # Add same amount of noise
    low_mom_prices += np.random.normal(0, 0.5, len(sample_data))
    low_mom_df = high_mom_df.copy()
    low_mom_df['Close'] = low_mom_prices
    
    scorer = MomentumScorer()
    high_score = scorer.calculate_score(high_mom_df)
    low_score = scorer.calculate_score(low_mom_df)
    
    assert high_score > low_score
    
def test_vcp_detector_identifies_tightening():
    """VCP should detect when price range is contracting (20% -> 10% -> 5% -> 2%)"""
    # Create 100 days of data for the new detector requirement
    dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
    highs, lows, closes, volumes = [], [], [], []
    
    for i in range(100):
        # 4 windows of 20 days each starting from the back
        if i >= 80:   range_pct = 0.02 # Last 20 days
        elif i >= 60: range_pct = 0.05
        elif i >= 40: range_pct = 0.10
        else:         range_pct = 0.20 # Early days
        
        base_price = 100
        highs.append(base_price * (1 + range_pct/2))
        lows.append(base_price * (1 - range_pct/2))
        closes.append(base_price)
        volumes.append(1000) # Constant volume for this test
        
    df = pd.DataFrame({
        'Date': dates, 'High': highs, 'Low': lows, 'Close': closes, 'Volume': volumes
    })
    
    detector = VCPPatternDetector(max_contractions=4)
    # The new analyze_vcp returns a dict, is_tightening is for legacy compat
    assert detector.is_tightening(df)

def test_vcp_detector_rejects_widening():
    """VCP should return False if range is widening"""
    dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
    highs, lows, closes, volumes = [], [], [], []
    
    for i in range(100):
        if i >= 80:   range_pct = 0.20 # Widening
        elif i >= 60: range_pct = 0.10
        elif i >= 40: range_pct = 0.05
        else:         range_pct = 0.02
        
        base_price = 100
        highs.append(base_price * (1 + range_pct/2))
        lows.append(base_price * (1 - range_pct/2))
        closes.append(base_price)
        volumes.append(1000)
        
    df = pd.DataFrame({
        'Date': dates, 'High': highs, 'Low': lows, 'Close': closes, 'Volume': volumes
    })
    
    detector = VCPPatternDetector()
    assert not detector.is_tightening(df)
