"""
NEXQA v1.0 — Regression Tracker

Tracks per-scenario performance over iterations to detect and block backsliding.
If any scenario drops more than REGRESSION_THRESHOLD (e.g. 0.15), the optimization
must be rejected (or flagged).

Thread-safe: uses asyncio.Lock per scenario_id to prevent cross-agent iteration mixing.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

from nexqa.models.scenario_models import EvaluationResult
from nexqa.storage.config import Config
from nexqa.storage.logger import logger


@dataclass
class RegressionIncident:
    """A detected regression in a specific scenario."""

    scenario_id: str
    previous_score: float
    current_score: float
    delta: float
    iteration: int


class RegressionTracker:
    """Core logic to track scores and detect negative trends.

    Uses per-scenario asyncio.Lock to prevent concurrent agents
    from interleaving iteration data for the same scenario.
    """

    def __init__(self) -> None:
        # History format: { scenario_id: { iteration_num: score, ... }, ... }
        self.history: Dict[str, Dict[int, float]] = {}
        # Per-scenario locks to prevent cross-agent mixing
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def log_result_async(self, iteration: int, result: EvaluationResult) -> None:
        """Record the score for a scenario in an iteration (async-safe)."""
        async with self._locks[result.scenario_id]:
            if result.scenario_id not in self.history:
                self.history[result.scenario_id] = {}
            self.history[result.scenario_id][iteration] = result.overall_score

    def log_result(self, iteration: int, result: EvaluationResult) -> None:
        """Record the score for a scenario in an iteration (sync fallback).

        For use in synchronous contexts. For async, prefer log_result_async().
        """
        if result.scenario_id not in self.history:
            self.history[result.scenario_id] = {}
        self.history[result.scenario_id][iteration] = result.overall_score

    async def check_regressions_async(
        self,
        current_iteration: int,
        results: List[EvaluationResult],
        threshold: Optional[float] = None,
    ) -> List[RegressionIncident]:
        """Identify significant drops (async-safe)."""
        if threshold is None:
            threshold = Config.REGRESSION_THRESHOLD

        regressions: List[RegressionIncident] = []
        prev_iter = current_iteration - 1

        if prev_iter < 0:
            return []

        for res in results:
            async with self._locks[res.scenario_id]:
                scenario_hist = self.history.get(res.scenario_id, {})
                prev_score = scenario_hist.get(prev_iter)

            if prev_score is None:
                continue

            delta = res.overall_score - prev_score

            if delta < -threshold:
                incident = RegressionIncident(
                    scenario_id=res.scenario_id,
                    previous_score=prev_score,
                    current_score=res.overall_score,
                    delta=delta,
                    iteration=current_iteration,
                )
                logger.error(
                    f"REGRESSION DETECTED: {incident.scenario_id} "
                    f"dropped {delta:.2f} (from {prev_score:.2f} to {res.overall_score:.2f})"
                )
                regressions.append(incident)

        return regressions

    def check_regressions(
        self,
        current_iteration: int,
        results: List[EvaluationResult],
        threshold: Optional[float] = None,
    ) -> List[RegressionIncident]:
        """Identify significant drops in performance (sync fallback)."""
        if threshold is None:
            threshold = Config.REGRESSION_THRESHOLD

        regressions: List[RegressionIncident] = []
        prev_iter = current_iteration - 1

        if prev_iter < 0:
            return []

        for res in results:
            scenario_hist = self.history.get(res.scenario_id, {})
            prev_score = scenario_hist.get(prev_iter)

            if prev_score is None:
                continue

            delta = res.overall_score - prev_score

            if delta < -threshold:
                incident = RegressionIncident(
                    scenario_id=res.scenario_id,
                    previous_score=prev_score,
                    current_score=res.overall_score,
                    delta=delta,
                    iteration=current_iteration,
                )
                logger.error(
                    f"REGRESSION DETECTED: {incident.scenario_id} "
                    f"dropped {delta:.2f} (from {prev_score:.2f} to {res.overall_score:.2f})"
                )
                regressions.append(incident)

        return regressions


# Singleton
regression_tracker = RegressionTracker()
