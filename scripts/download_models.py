"""
Utility to download and export FinBERT model for local offline use.
Ensures SmartTrader is independent of HuggingFace Hub during runtime.
Run this once while connected to the internet.
"""
import os
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def download_finbert():
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        from optimum.intel.openvino import OVModelForSequenceClassification
        
        model_id = "ProsusAI/finbert"
        local_dir = Path("models/finbert")
        local_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading {model_id} and saving to {local_dir}...")
        
        # 1. Download standard PyTorch model
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForSequenceClassification.from_pretrained(model_id)
        
        tokenizer.save_pretrained(local_dir)
        model.save_pretrained(local_dir)
        
        logger.info("Standard PyTorch model saved locally.")
        
        # 2. Export to OpenVINO format (optional but recommended for iGPU acceleration)
        logger.info("Exporting to OpenVINO format for local iGPU acceleration...")
        ov_model = OVModelForSequenceClassification.from_pretrained(model_id, export=True)
        ov_model.save_pretrained(local_dir)
        
        logger.info(f"SUCCESS: Model fully downloaded and exported to {local_dir}")
        logger.info("SmartTrader will now work offline for sentiment analysis.")
        
    except ImportError as e:
        logger.error(f"Required libraries missing: {e}")
        logger.info("Please run: pip install transformers optimum[openvino] openvino-dev")
    except Exception as e:
        logger.error(f"Failed to download model: {e}")

if __name__ == "__main__":
    download_finbert()
