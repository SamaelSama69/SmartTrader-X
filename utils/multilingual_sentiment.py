"""
Multilingual Sentiment Analysis for Indian Markets
Supports English, Hindi, Hinglish, and regional languages
Uses iGPU-accelerated FinBERT via OpenVINO for deep context
"""

import logging
import re
import os
import sys
import io
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import feedparser
from bs4 import BeautifulSoup
from urllib.parse import quote
import requests
from datetime import datetime, timedelta
import concurrent.futures
import time
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

class Language(Enum):
    ENGLISH = "en"
    HINDI = "hi"
    HINGLISH = "hi-en"
    UNKNOWN = "unknown"

@dataclass
class SentimentResult:
    text: str
    language: Language
    sentiment_score: float
    confidence: float
    label: str
    entities: List[str]
    topics: List[str]
    source: str = ""

class LanguageDetector:
    def __init__(self):
        self._stock_names = ['reliance', 'tcs', 'hdfc', 'infosys', 'icici', 'itc', 'sbi', 'airtel', 'kotak', 'larsen', 'axis', 'bajaj', 'wipro', 'maruti']

    def detect(self, text: str) -> Tuple[Language, float]:
        text_lower = text.lower()
        hindi_chars = re.compile(r'[\u0900-\u097F]')
        if hindi_chars.search(text): return (Language.HINDI, 0.9)
        hinglish_words = {'paisa', 'kamai', 'fayda', 'mandi', 'teji', 'bhai'}
        if any(w in text_lower for w in hinglish_words): return (Language.HINGLISH, 0.8)
        return (Language.ENGLISH, 0.7)

    def extract_entities(self, text: str) -> List[str]:
        text_lower = text.lower(); entities = []
        for stock in self._stock_names:
            if stock in text_lower: entities.append(stock)
        return entities

class FinancialContextAnalyzer:
    def __init__(self):
        self.neg_keywords = {
            'crash': -0.8, 'plunged': -0.7, 'dropped': -0.5, 'fell': -0.5, 
            'down': -0.4, 'wiped out': -0.9, 'sell-off': -0.7, 'slump': -0.6,
            'low': -0.4, 'negative': -0.5, 'pressure': -0.4, 'losses': -0.6,
            'crisis': -0.9, 'warning': -0.5, 'weakened': -0.4,
            'shut': -0.2, 'remain closed': -0.2, 'holiday': -0.1, 'under pressure': -0.5
        }
        self.pos_keywords = {
            'surge': 0.8, 'soared': 0.7, 'jumped': 0.6, 'rally': 0.7,
            'up': 0.4, 'gains': 0.6, 'high': 0.4, 'positive': 0.5,
            'bullish': 0.7, 'rebound': 0.6, 'outperform': 0.5
        }

    def get_context_adjustment(self, text: str) -> float:
        score = 0.0; text_lower = text.lower()
        for kw, val in self.neg_keywords.items():
            if kw in text_lower: score += val
        for kw, val in self.pos_keywords.items():
            if kw in text_lower: score += val
        return max(-1.0, min(1.0, score))

class AdvancedTransformerAnalyzer:
    def __init__(self):
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch
            import os
            
            # Use local path if directory exists, else fallback to HF ID
            local_model_path = os.path.join("models", "finbert")
            if os.path.exists(local_model_path):
                self.model_id = local_model_path
                logger.info(f"Deep Brain: Loading model from LOCAL path: {self.model_id}")
            else:
                self.model_id = "ProsusAI/finbert"
                logger.info(f"Deep Brain: Loading model from HF Hub: {self.model_id}")
            
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model = None
            self.ov_model = None  # Always initialize to None

            # 1. CUDA path (NVIDIA)
            if self.device.type == "cuda":
                logger.info(f"Deep Brain: Initializing {self.model_id} on {self.device}...")
                self.model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
                self.model.to(self.device)
                self.model.eval()
            
            # 2. OpenVINO path (Intel iGPU)
            else:
                try:
                    from optimum.intel.openvino import OVModelForSequenceClassification
                    import openvino as ov
                    core = ov.Core()
                    if "GPU" in core.available_devices:
                        logger.info(f"Deep Brain: NVIDIA unavailable, but Intel iGPU detected. Optimizing {self.model_id} via Optimum OpenVINO...")
                        
                        # Suppress benign CISA warnings during load
                        old_stderr = sys.stderr
                        sys.stderr = io.StringIO()
                        try:
                            # Use export=True if loading from Hub, False if already exported locally
                            is_local = os.path.exists(os.path.join(self.model_id, "openvino_model.xml"))
                            self.ov_model = OVModelForSequenceClassification.from_pretrained(
                                self.model_id, 
                                device="GPU", 
                                export=not is_local,
                                local_files_only=is_local # Fix for Errno 22 on Windows
                            )
                        finally:
                            captured = sys.stderr.getvalue()
                            sys.stderr = old_stderr
                            # Only surface non-CISA errors
                            non_cisa = [l for l in captured.splitlines()
                                        if 'CISA' not in l and 'kernel' not in l.lower()]
                            if non_cisa:
                                print('\n'.join(non_cisa), file=sys.stderr)
                                
                        logger.info("Deep Brain: OpenVINO iGPU acceleration active.")
                    else:
                        logger.info(f"Deep Brain: Initializing {self.model_id} on CPU...")
                        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
                        self.model.eval()
                except Exception as ov_e:
                    logger.warning(f"OpenVINO acceleration failed: {ov_e}. Falling back to standard CPU path.")
                    self.model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
                    self.model.eval()

            self.torch = torch
        except Exception as e:
            logger.error(f"Deep Brain Init Error: {e}")
            self.model = None
            self.ov_model = None

    def analyze_batch(self, texts: List[str]) -> List[Tuple[float, float]]:
        if not texts: return []
        
        # OpenVINO Path (iGPU)
        if self.ov_model:
            try:
                inputs = self.tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512)
                outputs = self.ov_model(**inputs)
                probs = self.torch.nn.functional.softmax(outputs.logits, dim=-1)
                results = []
                for i in range(len(texts)):
                    pos, neg, neu = probs[i].tolist()
                    results.append((pos - neg, max(pos, neg, neu)))
                return results
            except Exception as e:
                logger.error(f"OpenVINO Inference Error: {e}")
                return [(0.0, 0.0)] * len(texts)

        # PyTorch Path (CUDA/CPU)
        if not self.model: return [(0.0, 0.0)] * len(texts)
        try:
            inputs = self.tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with self.torch.no_grad():
                outputs = self.model(**inputs)
            probs = self.torch.nn.functional.softmax(outputs.logits, dim=-1)
            results = []
            for i in range(len(texts)):
                pos, neg, neu = probs[i].tolist()
                results.append((pos - neg, max(pos, neg, neu)))
            return results
        except Exception as e:
            logger.error(f"Batch analysis error: {e}")
            return [(0.0, 0.0)] * len(texts)

    def analyze(self, text: str) -> Tuple[float, float]:
        res = self.analyze_batch([text])
        return res[0]

class MultilingualSentimentEngine:
    def __init__(self):
        self.language_detector = LanguageDetector()
        self.financial_context = FinancialContextAnalyzer()
        self.server_url = f"http://127.0.0.1:{os.getenv('SENTIMENT_SERVER_PORT', '8005')}/analyze"
        
        self._topic_keywords = {
            'earnings': ['earnings', 'result', 'profit', 'loss', 'quarterly'],
            'regulatory': ['sebi', 'rbi', 'policy'],
            'macro': ['inflation', 'gdp', 'budget'],
            'sector': ['banking', 'it', 'pharma', 'fmcg', 'auto'],
            'technical': ['breakout', 'breakdown', 'trend', 'rsi'],
            'options': ['options', 'call', 'put', 'oi'],
            'fundamentals': ['pe', 'pb', 'roe', 'debt', 'revenue']
        }

    def analyze_batch(self, texts: List[str]) -> List[SentimentResult]:
        """Batch analysis via centralized server."""
        if not texts: return []
        
        try:
            resp = requests.post(self.server_url, json={"texts": texts}, timeout=30)
            if resp.status_code == 200:
                batch_results = resp.json()['results']
            else:
                logger.warning(f"Sentiment Server error ({resp.status_code}): {resp.text}")
                batch_results = [(0.0, 0.0)] * len(texts)
        except Exception as e:
            logger.error(f"Failed to connect to Sentiment Server: {e}")
            batch_results = [(0.0, 0.0)] * len(texts)

        final_results = []
        for i, text in enumerate(texts):
            sent, conf = batch_results[i]
            lang, _ = self.language_detector.detect(text)
            context_adj = self.financial_context.get_context_adjustment(text)
            if abs(context_adj) > 0.2:
                sent = (sent * 0.4) + (context_adj * 0.6); conf = max(conf, 0.85)
            label = "POSITIVE" if sent >= 0.05 else "NEGATIVE" if sent <= -0.05 else "NEUTRAL"
            final_results.append(SentimentResult(
                text=text[:100], language=lang, sentiment_score=sent, 
                confidence=conf, label=label, entities=self.language_detector.extract_entities(text), 
                topics=self._detect_topics(text))
            )
        return final_results

    def analyze(self, text: str, source: str = "") -> SentimentResult:
        res = self.analyze_batch([text])
        if res:
            res[0].source = source
            return res[0]
        return SentimentResult(text=text[:100], language=Language.UNKNOWN, sentiment_score=0.0, confidence=0.0, label="NEUTRAL", entities=[], topics=[], source=source)

    def _detect_topics(self, text: str) -> List[str]:
        text_lower = text.lower()
        return [t for t, kws in self._topic_keywords.items() if any(kw in text_lower for kw in kws)]

class IndianNewsAggregator:
    def __init__(self):
        self.sentiment_engine = MultilingualSentimentEngine()
        self._cache_dir = Path("./.cache/news")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory result cache to avoid redundant analysis
        # ticker -> {hash: str, results: List[Dict], timestamp: float}
        self._result_cache: Dict[str, Dict] = {}

    def _generate_news_hash(self, news: List[Dict]) -> str:
        """Generate a stable hash for a list of news items to detect changes."""
        import hashlib
        # Use links and titles as they are stable indicators of content
        content = "|".join([f"{n['link']}_{n['title']}" for n in news])
        return hashlib.md5(content.encode()).hexdigest()

    def _fetch_full_article_text(self, url: str) -> str:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for s in soup(["script", "style"]): s.decompose()
                article_body = soup.find('article') or soup.find('div', class_='article-body') or soup.find('div', class_='content')
                if article_body: return article_body.get_text(strip=True, separator=' ')
                return soup.get_text(strip=True, separator=' ')
        except Exception: pass
        return ""

    def fetch_news(self, ticker: str, days: int = 7) -> List[Dict]:
        import concurrent.futures; import time
        from config import NEWS_API_KEY, FINNHUB_API_KEY
        start_time = time.time(); all_news = []
        search_term = ticker.replace('.NS', '').replace('.BO', '')
        
        feeds = [
            f"https://news.google.com/rss/search?q={quote(search_term)}+stock+market+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
            f"https://finance.yahoo.com/rss/headline?s={quote(ticker if ticker.startswith('^') else ticker)}",
            "https://www.moneycontrol.com/rss/marketreports.xml",
            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
            "https://www.livemint.com/rss/markets",
            "https://www.business-standard.com/rss/latest-news-1.rss",
            "https://www.news18.com/rss/business.xml"
        ]
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                limit = 30 if search_term.lower() == "indian stock market" else 10
                count = 0
                for entry in feed.entries:
                    if count >= limit: break
                    if search_term.lower() != "indian stock market" and search_term.lower() not in entry.title.lower(): continue
                    
                    # Use summary from RSS if available, else title
                    summary = entry.get('summary', '') or entry.get('description', '')
                    if summary:
                        summary = BeautifulSoup(summary, "html.parser").get_text(strip=True)[:500]
                    
                    all_news.append({
                        'title': entry.title, 
                        'link': entry.link, 
                        'published': entry.published if hasattr(entry, 'published') else entry.get('updated', datetime.now().isoformat()), 
                        'source': url.split('/')[2].replace('www.', '').split('.')[0],
                        'description': summary or entry.title
                    })
                    count += 1
            except: pass

        if NEWS_API_KEY:
            try:
                from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                url = f"https://newsapi.org/v2/everything?q={quote(search_term)}&from={from_date}&language=en&sortBy=relevancy&apiKey={NEWS_API_KEY}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    for art in resp.json().get('articles', [])[:50]:
                        all_news.append({
                            'title': art['title'], 
                            'link': art['url'], 
                            'published': art['publishedAt'], 
                            'source': art['source']['name'],
                            'description': art.get('description', '') or art['title']
                        })
            except: pass

        if FINNHUB_API_KEY:
            try:
                url = f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_API_KEY}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    for art in resp.json()[:30]:
                        if search_term.lower() in art['headline'].lower() or search_term.lower() == "indian stock market":
                            all_news.append({
                                'title': art['headline'], 
                                'link': art['url'], 
                                'published': datetime.fromtimestamp(art['datetime']).isoformat(), 
                                'source': art['source'],
                                'description': art.get('summary', '') or art['headline']
                            })
            except: pass

        seen_links = set(); unique_news = []
        for n in all_news:
            if n['link'] not in seen_links: seen_links.add(n['link']); unique_news.append(n)
        all_news = unique_news[:100]

        # --- ADVANCED CACHING ---
        current_hash = self._generate_news_hash(all_news)
        cached = self._result_cache.get(ticker)
        
        # If hash matches and cache is less than 30 mins old, return cached results
        if cached and cached['hash'] == current_hash and (time.time() - cached['timestamp']) < 1800:
            logger.info(f"CACHE HIT: News for {ticker} unchanged. Skipping analysis.")
            return cached['results']

        # Deep Scraper for high-priority news (Top 3)
        # catch details buried in full text that summaries might miss
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_url = {executor.submit(self._fetch_full_article_text, a['link']): i for i, a in enumerate(all_news[:3])}
            for future in concurrent.futures.as_completed(future_to_url):
                idx = future_to_url[future]
                try:
                    full_text = future.result()
                    if full_text:
                        all_news[idx]['description'] = (all_news[idx].get('description', '') + " " + full_text)[:2000]
                except Exception:
                    pass

        # Batch Sentiment Analysis
        texts = [f"{a['title']} {a.get('description', '')}" for a in all_news]
        sentiments = self.sentiment_engine.analyze_batch(texts)
        
        processed_articles = []
        for j, article in enumerate(all_news):
            article['sentiment'] = sentiments[j]
            article['key_snippets'] = []
            processed_articles.append(article)

        # Update cache
        self._result_cache[ticker] = {
            'hash': current_hash,
            'results': processed_articles,
            'timestamp': time.time()
        }

        duration = time.time() - start_time
        logger.info(f"PERFORMANCE: Analyzed {len(processed_articles)} summaries in {duration:.2f}s using batch pipeline.")
        return processed_articles

    def get_market_sentiment(self) -> Dict:
        return self.get_aggregate_sentiment("Indian Stock Market Nifty 50")

    def get_macro_sentiment(self) -> float:
        """Get aggregate sentiment for the entire Indian market"""
        res = self.get_market_sentiment()
        return res.get('aggregate_sentiment', 0.0)

    def get_sector_sentiment_map(self, sector_tickers: Dict[str, List[str]]) -> Dict[str, float]:
        sector_map = {}
        for sector, tickers in sector_tickers.items():
            scores = [self.get_aggregate_sentiment(t, days=3)['aggregate_sentiment'] for t in tickers[:1]]
            sector_map[sector] = sum(scores)/len(scores) if scores else 0.0
        return sector_map

    def get_aggregate_sentiment_from_news(self, ticker: str, news: List[Dict]) -> Dict:
        if not news: return {'ticker': ticker, 'aggregate_sentiment': 0.0, 'confidence': 0.0, 'article_count': 0, 'topics': {}, 'topic_links': {}}
        
        weighted_sum = 0.0
        total_weight = 0.0
        topics = {}; topic_links = {}
        
        for n in news:
            # sentiments[j] is a SentimentResult object
            res = n['sentiment']
            weighted_sum += res.sentiment_score * res.confidence
            total_weight += res.confidence
            
            # Use topics already detected by the engine
            for t in res.topics:
                topics[t] = topics.get(t, 0) + 1
                if t not in topic_links: topic_links[t] = []
                topic_links[t].append({'title': n['title'], 'link': n['link']})
                
        return {
            'ticker': ticker, 
            'aggregate_sentiment': weighted_sum / total_weight if total_weight > 0 else 0.0, 
            'confidence': min(total_weight / len(news), 1.0) if news else 0.0, 
            'article_count': len(news), 
            'topics': topics, 
            'topic_links': topic_links
        }
    def get_aggregate_sentiment(self, ticker: str, days: int = 7) -> Dict:
        news = self.fetch_news(ticker, days)
        return self.get_aggregate_sentiment_from_news(ticker, news)

_sentiment_engine: Optional[MultilingualSentimentEngine] = None
def get_sentiment_engine() -> MultilingualSentimentEngine:
    global _sentiment_engine
    if _sentiment_engine is None: _sentiment_engine = MultilingualSentimentEngine()
    return _sentiment_engine

_news_aggregator: Optional[IndianNewsAggregator] = None
def get_news_aggregator() -> IndianNewsAggregator:
    global _news_aggregator
    if _news_aggregator is None: _news_aggregator = IndianNewsAggregator()
    return _news_aggregator
