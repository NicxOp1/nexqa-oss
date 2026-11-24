"""
NEXQA v1.0 — QA Engine (Main Orchestrator)

Shared by CLI + API. Extracts the orchestration loop from cli/main.py
into a reusable, testable class.

Pipeline: Ingest → Compile → Simulate → Validate → Score → Optimize → Lint → Deploy/Reject

Iteration logic (from CLAUDE.md):
  - Iter 1-2: normal test → score → optimize
  - Iter 3: auto-approve if 0 errors, review if ≥3 errors
  - Iter 4-5: last chances, then forced review

Async: engine.run_async() uses asyncio for non-blocking execution.
Polling uses asyncio.sleep() instead of time.sleep().

Platforms: the engine never calls a voice platform directly. It talks to a
`VoiceProvider` (nexqa/providers), picked by the spec's `provider:` key
(default: retell) or passed in explicitly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from nexqa.core.cost_meter import cost_meter
from nexqa.core.deterministic_validator import deterministic_validator
from nexqa.core.ingest import spec_ingestor
from nexqa.core.regression_tracker import regression_tracker
from nexqa.core.rule_compiler import CompiledRules, rule_compiler
from nexqa.core.score_engine import score_engine
from nexqa.genetics.gene_parser import gene_parser
from nexqa.providers import (
    VoiceProvider,
    get_provider,
    load_provider_settings,
    normalize_name,
)
from nexqa.providers.base import Conversation, TestSuite
from nexqa.models.gene_models import GeneSet
from nexqa.models.rule_models import CompiledSpec
from nexqa.models.scenario_models import EvaluationResult, SimulationResult
from nexqa.optimizer.gene_optimizer import gene_optimizer
from nexqa.optimizer.linter import linter
from nexqa.api.airtable_reporter import airtable_reporter
from nexqa.core.email_notifier import email_notifier
from nexqa.storage.config import Config
from nexqa.storage.logger import logger
from nexqa.storage.prompt_history import prompt_history


# ─── Result Models ──────────────────────────────────────────────────

@dataclass
class IterationResult:
    """Result of a single QA iteration."""

    iteration: int
    avg_score: float
    evaluations: List[EvaluationResult]
    error_count: int
    action: str  # "continue", "approve", "review", "block"
    prompt_updated: bool = False
    prompt_version: str = ""
    regressions: List[Any] = field(default_factory=list)


@dataclass
class RunResult:
    """Complete result of a QA run across all iterations."""

    agent_id: str
    success: bool
    final_score: float
    total_iterations: int
    iterations: List[IterationResult] = field(default_factory=list)
    action: str = ""  # "approved", "review_needed", "blocked", "failed"
    error: Optional[str] = None
    gene_set: Optional[GeneSet] = None
    cost_metrics: Dict[str, Any] = field(default_factory=dict)


# ─── QA Engine ──────────────────────────────────────────────────────

class QAEngine:
    """Main orchestrator for the NEXQA pipeline.

    Usage (async — preferred for API):
        result = await engine.run_async(agent_id="...", spec_path=Path("spec.txt"))

    Usage (sync — for CLI):
        result = engine.run(agent_id="...", spec_path=Path("spec.txt"))
    """

    def __init__(self) -> None:
        self.poll_interval: int = 5  # seconds between batch test polls
        self._pre_optimization_prompt: Optional[str] = None  # rollback safety
        self.provider: Optional[VoiceProvider] = None  # set at the start of each run
        # Optional human gate, called with (old_prompt, new_prompt) before a
        # rewrite is deployed. Return False to stop. None = apply automatically.
        self.confirm_update: Optional[Callable[[str, str], bool]] = None

    def _resolve_provider(
        self, provider: Union[VoiceProvider, str, None], spec_path: Path
    ) -> VoiceProvider:
        if isinstance(provider, VoiceProvider):
            return provider
        spec_name, config = load_provider_settings(spec_path)
        name = normalize_name(provider) if provider else spec_name
        # The spec's provider_config only applies to the provider it was written for.
        return get_provider(name, config if name == spec_name else {})

    # ─── Sync entry point (CLI) ──────────────────────────────────────

    def run(
        self,
        agent_id: str,
        spec_path: Path,
        response_engine: Optional[Dict[str, Any]] = None,
        provider: Union[VoiceProvider, str, None] = None,
    ) -> RunResult:
        """Synchronous run — blocks until completion. Use for CLI."""
        return asyncio.get_event_loop().run_until_complete(
            self.run_async(agent_id, spec_path, response_engine, provider=provider)
        )

    # ─── Async entry point (API) ─────────────────────────────────────

    async def run_async(
        self,
        agent_id: str,
        spec_path: Path,
        response_engine: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        provider: Union[VoiceProvider, str, None] = None,
    ) -> RunResult:
        """Execute the full QA pipeline asynchronously with configurable timeout.

        Args:
            agent_id: ID of the agent on the platform under test.
            spec_path: Path to QA specification file.
            response_engine: Test target. Retell: the agent's response_engine.
                If None, the provider resolves it from the agent.
            timeout: Max seconds for entire run. Defaults to Config.ENGINE_TIMEOUT.
            provider: A VoiceProvider instance, a provider name, or None to use
                the spec's `provider:` key (default "retell").

        Returns:
            RunResult with all iteration details.
        """
        timeout = timeout or Config.ENGINE_TIMEOUT
        try:
            self.provider = self._resolve_provider(provider, spec_path)
        except Exception as e:
            return self._finalize_run(RunResult(
                agent_id=agent_id,
                success=False,
                final_score=0.0,
                total_iterations=0,
                action="failed",
                error=f"Provider setup failed: {e}",
            ))
        try:
            return await asyncio.wait_for(
                self._run_pipeline(agent_id, spec_path, response_engine),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Engine run timed out after {timeout}s for agent {agent_id}")
            return self._finalize_run(RunResult(
                agent_id=agent_id,
                success=False,
                final_score=0.0,
                total_iterations=0,
                action="failed",
                error=f"Engine run timed out after {timeout}s",
                cost_metrics=cost_meter.get_report().__dict__,
            ))

    async def _run_pipeline(
        self,
        agent_id: str,
        spec_path: Path,
        response_engine: Optional[Dict[str, Any]] = None,
    ) -> RunResult:
        """Core pipeline logic (extracted for timeout wrapping)."""
        provider = self.provider
        assert provider is not None
        logger.info(f"Starting QA run for agent {agent_id} on provider '{provider.name}'")
        cost_meter.reset()

        # ── Step 1: Resolve the test target (Retell: the response engine) ──
        if not response_engine:
            try:
                response_engine = provider.resolve_target(agent_id)
            except Exception as e:
                return self._finalize_run(RunResult(
                    agent_id=agent_id,
                    success=False,
                    final_score=0.0,
                    total_iterations=0,
                    action="failed",
                    error=f"Failed to fetch agent: {e}",
                ))

        if not response_engine:
            return self._finalize_run(RunResult(
                agent_id=agent_id,
                success=False,
                final_score=0.0,
                total_iterations=0,
                action="failed",
                error="No response_engine found for agent",
            ))

        # ── Step 2: Ingest spec ──
        try:
            spec = spec_ingestor.ingest(spec_path)
            rules = rule_compiler.compile(spec)
            logger.info(
                f"Ingested {len(spec.scenarios)} scenarios, "
                f"{len(spec.hard_rules)} rules"
            )
        except Exception as e:
            return self._finalize_run(RunResult(
                agent_id=agent_id,
                success=False,
                final_score=0.0,
                total_iterations=0,
                action="failed",
                error=f"Ingestion failed: {e}",
            ))

        # ── Step 3: Register test cases ──
        suite = provider.register_scenarios(agent_id, spec, response_engine)
        if not suite.items:
            return self._finalize_run(RunResult(
                agent_id=agent_id,
                success=False,
                final_score=0.0,
                total_iterations=0,
                action="failed",
                error="No test cases could be registered",
            ))

        # ── Step 4: Iteration loop ──
        iterations: List[IterationResult] = []
        current_gene_set: Optional[GeneSet] = None

        # Allow spec to override max iterations (default from config)
        max_iters = getattr(spec, 'max_iterations', None) or Config.MAX_ITERATIONS
        logger.info(f"Max iterations: {max_iters}")

        for iteration in range(max_iters):
            logger.info(f"--- Iteration {iteration} ---")

            if not cost_meter.check_budget():
                logger.error("Stopping due to budget overrun")
                break

            iter_result = await self._run_iteration_async(
                iteration=iteration,
                agent_id=agent_id,
                suite=suite,
                rules=rules,
                spec=spec,
            )
            iterations.append(iter_result)

            # Decision logic
            if iter_result.action == "approve":
                logger.info("✓ Auto-approved — threshold met")
                return self._finalize_run(RunResult(
                    agent_id=agent_id,
                    success=True,
                    final_score=iter_result.avg_score,
                    total_iterations=iteration + 1,
                    iterations=iterations,
                    action="approved",
                    gene_set=current_gene_set,
                    cost_metrics=cost_meter.get_report().__dict__,
                ))

            if iter_result.action == "review":
                logger.info("Sending to human review")
                return self._finalize_run(RunResult(
                    agent_id=agent_id,
                    success=False,
                    final_score=iter_result.avg_score,
                    total_iterations=iteration + 1,
                    iterations=iterations,
                    action="review_needed",
                    gene_set=current_gene_set,
                    cost_metrics=cost_meter.get_report().__dict__,
                ))

            if iter_result.action == "block":
                logger.error("Blocked — regression detected")
                return self._finalize_run(RunResult(
                    agent_id=agent_id,
                    success=False,
                    final_score=iter_result.avg_score,
                    total_iterations=iteration + 1,
                    iterations=iterations,
                    action="blocked",
                    gene_set=current_gene_set,
                    cost_metrics=cost_meter.get_report().__dict__,
                ))

            # Continue to next iteration (optimize prompt)
            if iter_result.action == "continue" and iteration < max_iters - 1:
                new_gene_set = self._optimize(
                    agent_id, iter_result.evaluations, spec
                )
                if new_gene_set:
                    current_gene_set = new_gene_set
                else:
                    # No optimization changes — stop early
                    logger.info("No prompt changes generated. Stopping early.")
                    final = iterations[-1] if iterations else None
                    return self._finalize_run(RunResult(
                        agent_id=agent_id,
                        success=final.avg_score >= 0.7 if final else False,
                        final_score=final.avg_score if final else 0.0,
                        total_iterations=len(iterations),
                        iterations=iterations,
                        action="approved" if (final and final.avg_score >= 0.7) else "review_needed",
                        gene_set=current_gene_set,
                        cost_metrics=cost_meter.get_report().__dict__,
                    ))

        # Max iterations reached
        final = iterations[-1] if iterations else None
        return self._finalize_run(RunResult(
            agent_id=agent_id,
            success=False,
            final_score=final.avg_score if final else 0.0,
            total_iterations=len(iterations),
            iterations=iterations,
            action="review_needed",
            gene_set=current_gene_set,
            error="Max iterations reached",
            cost_metrics=cost_meter.get_report().__dict__,
        ))

    # ─── Private Methods ────────────────────────────────────────────

    async def _run_iteration_async(
        self,
        iteration: int,
        agent_id: str,
        suite: TestSuite,
        rules: CompiledRules,
        spec: CompiledSpec,
    ) -> IterationResult:
        """Execute a single QA iteration asynchronously."""
        assert self.provider is not None

        # ── Batch test ──
        try:
            batch_id = self.provider.start_run(suite)
            logger.info(f"Batch test started: {batch_id}")
        except Exception as e:
            logger.error(f"Failed to start batch test: {e}")
            return IterationResult(
                iteration=iteration,
                avg_score=0.0,
                evaluations=[],
                error_count=99,
                action="review",
            )

        # ── Poll for completion (async) ──
        completed_results = await self._poll_batch_test_async(suite, batch_id)
        if not completed_results:
            return IterationResult(
                iteration=iteration,
                avg_score=0.0,
                evaluations=[],
                error_count=99,
                action="review",
            )

        # ── Evaluate ──
        evaluations = self._evaluate(completed_results, rules)

        # ── Score ──
        avg_score = (
            sum(e.overall_score for e in evaluations) / len(evaluations)
            if evaluations
            else 0.0
        )
        error_count = sum(1 for e in evaluations if e.is_critical_fail)

        # ── Check Regressions ──
        regressions = regression_tracker.check_regressions(
            iteration, evaluations
        )
        if regressions:
            logger.error(f"Caught {len(regressions)} regressions")
            # Rollback prompt to pre-optimization state if we mutated last iteration
            if self._pre_optimization_prompt:
                self._rollback_prompt(agent_id)
            return IterationResult(
                iteration=iteration,
                avg_score=avg_score,
                evaluations=evaluations,
                error_count=error_count,
                action="block",
                regressions=regressions,
            )

        # ── Log Results ──
        for ev in evaluations:
            regression_tracker.log_result(iteration, ev)

        # ── Decision ──
        action = self._decide_action(iteration, avg_score, error_count)

        return IterationResult(
            iteration=iteration,
            avg_score=avg_score,
            evaluations=evaluations,
            error_count=error_count,
            action=action,
            regressions=[],
        )

    async def _poll_batch_test_async(
        self, suite: TestSuite, batch_id: str, timeout: Optional[int] = None
    ) -> List[Conversation]:
        """Wait for the provider's run; return its normalized conversations."""
        timeout = timeout or Config.ENGINE_TIMEOUT
        assert self.provider is not None
        run = await self.provider.wait_for_results(
            suite, batch_id, poll_interval=self.poll_interval, timeout=timeout
        )
        if run.billed_minutes:
            cost_meter.add_minutes(run.billed_minutes)
        return run.conversations

    def _evaluate(
        self,
        results: List[Conversation],
        rules: CompiledRules,
    ) -> List[EvaluationResult]:
        """Run deterministic + semantic evaluation on normalized conversations."""
        evaluations: List[EvaluationResult] = []

        for conv in results:
            # Skip runs that haven't completed yet
            if conv.status in ("in_progress", "pending", "running"):
                logger.info(f"Skipping test run with status '{conv.status}'")
                continue

            sim_result: SimulationResult = conv.to_simulation_result()
            logger.info(f"DEBUG_HISTORY: Final transcript size: {len(sim_result.transcript)}")

            det_result = deterministic_validator.validate(sim_result, rules)
            eval_result = score_engine.evaluate(
                sim_result.scenario_id, sim_result.transcript, det_result
            )
            evaluations.append(eval_result)

        return evaluations

    def _decide_action(
        self, iteration: int, avg_score: float, error_count: int
    ) -> str:
        """Decide what to do based on iteration number and results."""
        if avg_score >= Config.DEFAULT_THRESHOLD:
            return "approve"

        if self._should_auto_approve(iteration, error_count):
            return "approve"

        if self._should_send_to_review(iteration, error_count):
            return "review"

        if iteration >= Config.MAX_ITERATIONS - 1:
            return "review"

        return "continue"

    def _should_auto_approve(self, iteration: int, error_count: int) -> bool:
        return iteration >= Config.AUTO_APPROVE_CLEAN_AT and error_count == 0

    def _should_send_to_review(self, iteration: int, error_count: int) -> bool:
        return (
            iteration >= Config.AUTO_APPROVE_CLEAN_AT
            and error_count >= Config.ERROR_THRESHOLD_FOR_REVIEW
        )

    def _optimize(
        self,
        agent_id: str,
        evaluations: List[EvaluationResult],
        spec: CompiledSpec,
    ) -> Optional[GeneSet]:
        """Optimize the prompt using gene-level mutation.

        Saves the original prompt before updating so that _rollback_prompt()
        can restore it if a subsequent iteration detects regression.
        """
        try:
            current_prompt = self.provider.get_prompt(agent_id)
        except Exception as e:
            logger.error(f"Failed to fetch current prompt: {e}")
            return None

        current_gene_set = gene_parser.parse(current_prompt)

        logger.info(f"Invoking gene_optimizer for {len(evaluations)} evaluations...")
        new_gene_set = gene_optimizer.optimize(
            current_gene_set, evaluations, spec.raw_text
        )

        if not new_gene_set:
            logger.info("No optimization changes generated")
            return None

        new_prompt = gene_parser.serialize(new_gene_set)

        if not linter.lint(current_prompt, new_prompt):
            logger.error("Lint failed — optimization rejected")
            return None

        if self.confirm_update is not None and not self.confirm_update(current_prompt, new_prompt):
            logger.info("Prompt update rejected by reviewer")
            return None

        # Save original prompt for rollback before deploying mutation
        self._pre_optimization_prompt = current_prompt

        try:
            self.provider.update_prompt(agent_id, new_prompt)
            logger.info(f"Prompt updated successfully (new length: {len(new_prompt)})")
        except Exception as e:
            logger.error(f"Failed to apply prompt update: {e}")
            self._pre_optimization_prompt = None
            return None

        try:
            prompt_history.save_version(
                agent_id=agent_id,
                prompt_text=new_prompt,
                gene_set=new_gene_set,
                change_type="gene_rewrite",
                description=f"Optimized {len(evaluations)} evaluations",
                deployed=True,
            )
        except Exception as e:
            logger.warning(f"Failed to save prompt version (non-blocking): {e}")

        return new_gene_set

    def _rollback_prompt(self, agent_id: str) -> bool:
        """Restore the prompt saved before the last optimization.

        Called when a regression is detected after a mutation was deployed.
        Returns True if rollback succeeded, False otherwise.
        """
        if not self._pre_optimization_prompt:
            logger.warning("No pre-optimization prompt saved — cannot rollback")
            return False

        try:
            self.provider.update_prompt(agent_id, self._pre_optimization_prompt)
            logger.info("Rollback successful — restored pre-optimization prompt")
            self._pre_optimization_prompt = None
            return True
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    def _finalize_run(self, result: RunResult) -> RunResult:
        """Log result, sync to Airtable, and send notifications."""
        try:
            airtable_reporter.sync_run(result.__dict__)
        except Exception as e:
            logger.error(f"Failed to sync run to Airtable: {e}")

        if result.action in ("review_needed", "blocked"):
            try:
                email_notifier.send_review_request(
                    agent_id=result.agent_id,
                    score=result.final_score,
                    reason=f"Action: {result.action} after {result.total_iterations} iterations"
                )
                logger.info("Review email notification sent")
            except Exception as e:
                logger.warning(f"Email notification failed (non-blocking): {e}")

        logger.info(f"Run finished: Action={result.action}, Score={result.final_score}")
        return result


# Module-level singleton
engine = QAEngine()
