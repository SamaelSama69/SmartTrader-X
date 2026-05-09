"""Tests for sentiment analysis failover resilience."""
import pytest
from unittest.mock import patch, MagicMock
from utils.multilingual_sentiment import (
    MultilingualSentimentEngine, SentimentResult, Language,
)


class TestSentimentFailover:
    """Verify 3-tier failover: server → local FinBERT → keyword analysis."""

    def test_server_down_uses_keyword_fallback(self):
        """When server is unreachable and no local model, keyword analysis should work."""
        engine = MultilingualSentimentEngine()

        # Force server to fail (connection refused)
        with patch('requests.post', side_effect=ConnectionError("refused")):
            # Force local FinBERT to be unavailable
            engine._local_analyzer = MagicMock()
            engine._local_analyzer.model = None
            engine._local_analyzer.ov_model = None

            results = engine.analyze_batch(["RELIANCE stock crashed heavily today"])

        assert len(results) == 1
        assert isinstance(results[0], SentimentResult)
        # Keyword "crashed" should produce negative sentiment
        assert results[0].sentiment_score < 0, \
            "Keyword fallback should detect 'crashed' as negative"

    def test_server_down_with_positive_keywords(self):
        """Keyword fallback should detect positive sentiment."""
        engine = MultilingualSentimentEngine()

        with patch('requests.post', side_effect=ConnectionError("refused")):
            engine._local_analyzer = MagicMock()
            engine._local_analyzer.model = None
            engine._local_analyzer.ov_model = None

            results = engine.analyze_batch(["NIFTY surged on bullish rally gains"])

        assert len(results) == 1
        assert results[0].sentiment_score > 0, \
            "Keyword fallback should detect 'surged/bullish/rally' as positive"

    def test_all_backends_produce_valid_results(self):
        """Even with all model backends unavailable, results should have valid structure."""
        engine = MultilingualSentimentEngine()

        with patch('requests.post', side_effect=ConnectionError("refused")):
            engine._local_analyzer = MagicMock()
            engine._local_analyzer.model = None
            engine._local_analyzer.ov_model = None

            results = engine.analyze_batch(["Neutral test article about markets"])

        assert len(results) == 1
        r = results[0]
        assert hasattr(r, 'sentiment_score')
        assert hasattr(r, 'confidence')
        assert hasattr(r, 'label')
        assert r.label in ('POSITIVE', 'NEGATIVE', 'NEUTRAL')

    def test_empty_input_returns_empty(self):
        """Empty input should return empty list without errors."""
        engine = MultilingualSentimentEngine()
        assert engine.analyze_batch([]) == []
