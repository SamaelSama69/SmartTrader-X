"""
Centralized Sentiment Server for SmartTrader Pro.
Hosts the FinBERT model once and serves requests from both the Bot and Dashboard.
Reduces iGPU memory footprint and ensures consistent analysis.
"""
import os
import sys
import logging
from typing import List
import logging.handlers
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from contextlib import asynccontextmanager

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.multilingual_sentiment import AdvancedTransformerAnalyzer

# Configure logging
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "sentiment_server.log")

logger = logging.getLogger("SentimentServer")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Rotating File Handler
file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE, when="midnight", interval=1, backupCount=7, encoding='utf-8'
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Console Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Global analyzer instance
analyzer = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global analyzer
    logger.info("Initializing FinBERT model...")
    try:
        analyzer = AdvancedTransformerAnalyzer()
        logger.info("Model loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
    yield
    # Cleanup if needed
    logger.info("Shutting down Sentiment Server...")

app = FastAPI(title="SmartTrader Sentiment API", lifespan=lifespan)

class SentimentRequest(BaseModel):
    texts: List[str]

class SentimentResponse(BaseModel):
    results: List[List[float]] # List of (score, confidence)

@app.post("/analyze", response_model=SentimentResponse)
async def analyze_sentiment(request: SentimentRequest):
    if not analyzer:
        raise HTTPException(status_code=503, detail="Model not initialized")
    
    try:
        # Use the existing batch analysis logic
        results = analyzer.analyze_batch(request.texts)
        # Convert tuples to lists for JSON serialization
        return {"results": [list(r) for r in results]}
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "ready", "model": analyzer.model_id if analyzer else "none"}

if __name__ == "__main__":
    port = int(os.getenv("SENTIMENT_SERVER_PORT", 8005))
    uvicorn.run(app, host="127.0.0.1", port=port)
