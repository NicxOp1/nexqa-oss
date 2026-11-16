import logging
import sys
from rich.logging import RichHandler
from nexqa.storage.config import Config

def setup_logger():
    """Configure structured logging with Rich"""
    
    from rich.console import Console
    # safe_box=True prevents tricky box characters, force_terminal=True ensures consistent behavior
    console = Console(force_terminal=True, safe_box=True, color_system="standard")
    
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
