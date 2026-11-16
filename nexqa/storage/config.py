"""
NEXQA v1.0 Configuration

All environment variables and application constants.
"""

import os
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application Configuration — NEVER hardcode values elsewhere."""

    # ─── API Keys ───────────────────────────────────────────────────

    RETELL_API_KEY: str = os.getenv("RETELL_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    AIRTABLE_API_KEY: str = os.getenv("AIRTABLE_API_KEY", "")
    AIRTABLE_BASE_ID: str = os.getenv("AIRTABLE_BASE_ID", "")

    # ─── LLM Config ────────────────────────────────────────────────

    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-4-6-sonnet-latest")
    CLAUDE_MAX_TOKENS: int = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))
    
    # Pricing (USD per 1M tokens) - Updated for Sonnet 4.6
    CLAUDE_INPUT_PRICE_1M: float = 3.00
    CLAUDE_OUTPUT_PRICE_1M: float = 15.00

    # ─── Email / Alerts ────────────────────────────────────────────

    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    REVIEW_EMAIL_TO: str = os.getenv("REVIEW_EMAIL_TO", "")

    # ─── MongoDB ──────────────────────────────────────────────────

    MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "nexqa")

    # ─── CORS / Security ─────────────────────────────────────────

    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "")  # comma-separated
    NEXQA_API_KEY: str = os.getenv("NEXQA_API_KEY", "")  # shared secret with the calling app

    # ─── Webhooks ─────────────────────────────────────────────────

    # Public base URL of the deployed webhook_server (tools call <base>/webhook/<agent_id>)
    WEBHOOK_BASE_URL: str = os.getenv("NEXQA_WEBHOOK_BASE_URL", "http://localhost:8080")

    # ─── Engine ───────────────────────────────────────────────────

    ENGINE_TIMEOUT: int = int(os.getenv("ENGINE_TIMEOUT", "1200"))  # seconds

    # ─── Logging ────────────────────────────────────────────────────

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ─── Paths ──────────────────────────────────────────────────────

    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    LOGS_DIR: Path = STORAGE_DIR / "logs"
    REPORTS_DIR: Path = STORAGE_DIR / "reports"
    PROMPTS_DIR: Path = STORAGE_DIR / "prompts"
    CACHE_DIR: Path = STORAGE_DIR / "cache"
    GENETICS_DIR: Path = STORAGE_DIR / "genetics"
    VOICE_CORPUS_DIR: Path = BASE_DIR / "corpus"

    # ─── QA Engine Constants ────────────────────────────────────────

    MAX_ITERATIONS: int = 5
    MAX_OPTIMIZATION_ITERATIONS: int = 5    # alias used by run command
    AUTO_APPROVE_CLEAN_AT: int = 3       # 0 errors at iter 3 → auto approve
    ERROR_THRESHOLD_FOR_REVIEW: int = 3  # ≥3 errors → email review
    REGRESSION_THRESHOLD: float = 0.15   # any scenario drops >0.15 → BLOCK
    DEFAULT_THRESHOLD: float = 0.95      # overall pass threshold

    # ─── Scoring Weights (4-axis) ───────────────────────────────────

    SCORING_WEIGHTS: Dict[str, float] = {
        "deterministic": 0.30,
        "semantic": 0.30,
        "conversational": 0.25,
        "turing": 0.15,
    }

    # ─── Cost Tracking ──────────────────────────────────────────────

    COST_ALERT_THRESHOLD_USD: float = float(
        os.getenv("COST_ALERT_THRESHOLD_USD", "10.0")
    )

    # ─── Validation ─────────────────────────────────────────────────

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration — raises ValueError if missing."""
        missing = []
        if not cls.RETELL_API_KEY:
            missing.append("RETELL_API_KEY")
        if not cls.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

    @classmethod
    def validate_full(cls) -> None:
        """Validate ALL config including optional services."""
        cls.validate()
        warnings = []
        if not cls.AIRTABLE_API_KEY:
            warnings.append("AIRTABLE_API_KEY (Airtable reporting disabled)")
        if not cls.SMTP_HOST:
            warnings.append("SMTP_HOST (Email alerts disabled)")
        if not cls.REVIEW_EMAIL_TO:
            warnings.append("REVIEW_EMAIL_TO (Review notifications disabled)")

        if warnings:
            from nexqa.storage.logger import logger
            for w in warnings:
                logger.warning(f"Optional config missing: {w}")

    @classmethod
    def ensure_directories(cls) -> None:
        """Ensure all storage directories exist."""
        dirs = [
            cls.LOGS_DIR,
            cls.REPORTS_DIR,
            cls.PROMPTS_DIR,
            cls.CACHE_DIR,
            cls.GENETICS_DIR,
        ]
        for path in dirs:
            path.mkdir(parents=True, exist_ok=True)


# Initialize directories on import
Config.ensure_directories()
