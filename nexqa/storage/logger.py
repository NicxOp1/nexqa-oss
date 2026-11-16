import logging
import sys
from nexqa.storage.config import Config

def setup_logger():
    """Configure structured logging with Rich"""
    
    # Use standard StreamHandler to avoid UnicodeEncodeError with Rich icons on Windows
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%X"))
    
    logging.basicConfig(
        level=Config.LOG_LEVEL,
        handlers=[handler]
    )
    
    logger = logging.getLogger("nexqa")
    return logger

logger = setup_logger()
