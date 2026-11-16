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

    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    CLAUDE_MAX_TOKENS: int = int(os.getenv("CLAUDE_MAX_TOKENS", "16000"))
    # low | medium | high | xhigh | max. Mutation and judging work well at "high".
    CLAUDE_EFFORT: str = os.getenv("CLAUDE_EFFORT", "high")

    # Pricing (USD per 1M tokens) used by the cost meter. Known models are looked
    # up in CLAUDE_PRICES; override with CLAUDE_INPUT_PRICE_1M / CLAUDE_OUTPUT_PRICE_1M.
    CLAUDE_PRICES: Dict[str, tuple] = {
        "claude-opus-5-5": (4.00, 20.00),
        "claude-sonnet-5-5": (2.00, 10.00),
        "claude-haiku-5-5": (0.10, 0.50),
    }
    _default_price = CLAUDE_PRICES.get(CLAUDE_MODEL, (4.00, 20.00))
    CLAUDE_INPUT_PRICE_1M: float = float(
        os.getenv("CLAUDE_INPUT_PRICE_1M", str(_default_price[0]))
    )
    CLAUDE_OUTPUT_PRICE_1M: float = float(
        os.getenv("CLAUDE_OUTPUT_PRICE_1M", str(_default_price[1]))
    )
    RETELL_PRICE_PER_MINUTE: float = float(os.getenv("RETELL_PRICE_PER_MINUTE", "0.12"))

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

    # Runtime files (logs, reports, cache, prompt history) go to NEXQA_STORAGE_DIR,
    # or ./storage under the directory you run nexqa from.
    STORAGE_DIR: Path = Path(
        os.getenv("NEXQA_STORAGE_DIR", str(Path.cwd() / "storage"))
    ).resolve()
    LOGS_DIR: Path = STORAGE_DIR / "logs"
    REPORTS_DIR: Path = STORAGE_DIR / "reports"
    PROMPTS_DIR: Path = STORAGE_DIR / "prompts"
    CACHE_DIR: Path = STORAGE_DIR / "cache"
    GENETICS_DIR: Path = STORAGE_DIR / "genetics"
    PROMPT_VERSIONS_DIR: Path = STORAGE_DIR / "prompt_versions"

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
    def validate(cls, retell: bool = True, anthropic: bool = True) -> None:
        """Validate required configuration — raises ValueError if missing."""
        missing = []
        if retell and not cls.RETELL_API_KEY:
            missing.append("RETELL_API_KEY")
        if anthropic and not cls.ANTHROPIC_API_KEY:
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
            cls.PROMPT_VERSIONS_DIR,
        ]
        for path in dirs:
            path.mkdir(parents=True, exist_ok=True)

