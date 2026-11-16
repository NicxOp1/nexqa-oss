"""
NEXQA v1.0 — Cost Meter

Tracks token usage and Retell simulation minutes to estimate run costs.
Prevents runaway usage during optimization loops.

Prices come from Config (CLAUDE_INPUT_PRICE_1M, CLAUDE_OUTPUT_PRICE_1M,
RETELL_PRICE_PER_MINUTE) and can be overridden with environment variables.
"""

from dataclasses import dataclass

from nexqa.storage.config import Config
from nexqa.storage.logger import logger


@dataclass
class CostReport:
    """Summary of accumulated costs for a run."""

    claude_input_tokens: int
    claude_output_tokens: int
    retell_minutes: float
    total_cost_usd: float
    approaching_limit: bool
    limit_exceeded: bool


class CostMeter:
    """Singleton for tracking API spend."""

    PRICE_CLAUDE_INPUT_1M = Config.CLAUDE_INPUT_PRICE_1M
    PRICE_CLAUDE_OUTPUT_1M = Config.CLAUDE_OUTPUT_PRICE_1M
    PRICE_RETELL_MINUTE = Config.RETELL_PRICE_PER_MINUTE

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset all counters to zero."""
        self._claude_input = 0
        self._claude_output = 0
        self._retell_minutes = 0.0

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Log LLM token usage."""
        self._claude_input += input_tokens
        self._claude_output += output_tokens

    def add_minutes(self, minutes: float) -> None:
        """Log Retell simulation minutes."""
        self._retell_minutes += minutes

    def get_report(self) -> CostReport:
        """Calculate current total cost."""
        claude_cost = (
            (self._claude_input / 1_000_000) * self.PRICE_CLAUDE_INPUT_1M
        ) + ((self._claude_output / 1_000_000) * self.PRICE_CLAUDE_OUTPUT_1M)

        retell_cost = self._retell_minutes * self.PRICE_RETELL_MINUTE
        total_usd = claude_cost + retell_cost

        limit = Config.COST_ALERT_THRESHOLD_USD
        return CostReport(
            claude_input_tokens=self._claude_input,
            claude_output_tokens=self._claude_output,
            retell_minutes=self._retell_minutes,
            total_cost_usd=round(total_usd, 4),
            approaching_limit=total_usd >= (limit * 0.8),
            limit_exceeded=total_usd >= limit,
        )

    def check_budget(self) -> bool:
        """Return False if budget exceeded (should stop run)."""
        report = self.get_report()
        if report.limit_exceeded:
            logger.error(
                f"BUDGET EXCEEDED: Current cost ${report.total_cost_usd:.2f} "
                f"> Limit ${Config.COST_ALERT_THRESHOLD_USD:.2f}"
            )
            return False
        if report.approaching_limit:
            logger.warning(
                f"Approaching budget limit: ${report.total_cost_usd:.2f} "
                f"/ ${Config.COST_ALERT_THRESHOLD_USD:.2f}"
            )
        return True


# Singleton
cost_meter = CostMeter()
