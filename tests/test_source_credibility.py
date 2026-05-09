"""Tests for sentiment source credibility weighting."""
import pytest
from dataclasses import dataclass
from utils.multilingual_sentiment import (
    SOURCE_CREDIBILITY, DEFAULT_CREDIBILITY,
    IndianNewsAggregator, SentimentResult, Language,
)


def _make_news(title, source, sentiment_score=0.5, confidence=0.8):
    """Helper: create a fake news article with pre-attached SentimentResult."""
    return {
        'title': title,
        'link': f'https://{source}.com/article',
        'published': '2025-01-01',
        'source': source,
        'description': title,
        'sentiment': SentimentResult(
            text=title, language=Language.ENGLISH,
            sentiment_score=sentiment_score, confidence=confidence,
            label='POSITIVE' if sentiment_score > 0 else 'NEGATIVE',
            entities=[], topics=[], source=source,
        ),
    }


class TestSourceCredibility:
    """Verify source credibility weights are applied correctly."""

    def test_known_sources_have_higher_weight(self):
        """MoneyControl (1.4x) should outweigh an unknown blog (0.7x)."""
        agg = IndianNewsAggregator()

        # Two articles: same sentiment, but one from moneycontrol, one unknown
        news = [
            _make_news("RELIANCE surges", "moneycontrol", sentiment_score=0.8, confidence=0.9),
            _make_news("RELIANCE surges", "randomblog", sentiment_score=-0.8, confidence=0.9),
        ]
        result = agg.get_aggregate_sentiment_from_news("RELIANCE.NS", news)

        # MoneyControl's weight: 0.9 * 1.4 = 1.26
        # Unknown's weight:      0.9 * 0.7 = 0.63
        # Weighted: (0.8*1.26 + -0.8*0.63) / (1.26 + 0.63) = (1.008 - 0.504) / 1.89 ≈ 0.267
        assert result['aggregate_sentiment'] > 0, \
            "MoneyControl positive should outweigh unknown negative"

        assert 'moneycontrol' in result['source_credibility']
        assert result['source_credibility']['moneycontrol'] == 1.4

    def test_unknown_source_gets_default_weight(self):
        """Unrecognized source domains should get DEFAULT_CREDIBILITY (0.7)."""
        agg = IndianNewsAggregator()
        news = [_make_news("Test article", "unknownblog123", sentiment_score=0.5)]
        result = agg.get_aggregate_sentiment_from_news("TCS.NS", news)

        assert 'unknownblog123' in result['source_credibility']
        assert result['source_credibility']['unknownblog123'] == DEFAULT_CREDIBILITY

    def test_empty_news_returns_zero(self):
        """Empty news list should return 0.0 aggregate."""
        agg = IndianNewsAggregator()
        result = agg.get_aggregate_sentiment_from_news("INFY.NS", [])
        assert result['aggregate_sentiment'] == 0.0
        assert result['article_count'] == 0
        assert result['source_credibility'] == {}

    def test_credibility_dict_completeness(self):
        """Verify all major Indian sources are in the credibility dict."""
        expected_sources = ['moneycontrol', 'economictimes', 'livemint',
                           'business-standard', 'news18']
        for src in expected_sources:
            assert src in SOURCE_CREDIBILITY, f"Missing source: {src}"
