"""
NEXQA v1.0 — Score Engine (4-Axis)

Evaluates simulation results on 4 dimensions:
1. Deterministic (30%): Did it follow hard rules? (Regex/Tool checks)
2. Semantic (30%): Did it understand the user's intent?
3. Conversational (25%): Was the flow natural? Turn-taking, latency masking?
4. Turing (15%): How human did it feel?

Weights are configurable in nexqa.storage.config.Config.
"""

import json
from typing import Any, Dict, List

from nexqa.core.deterministic_validator import ValidationResult
from nexqa.integrations.claude_client import claude_client
from nexqa.models.scenario_models import EvaluationResult, SemanticIssue
from nexqa.storage.config import Config
from nexqa.storage.logger import logger


class ScoreEngine:
    """Evaluates simulation results and computes 4-axis score."""

    def evaluate(
        self,
        scenario_id: str,
        transcript: str,
        deterministic: ValidationResult,
    ) -> EvaluationResult:
        """Compute holistic score merging deterministic + semantic metrics."""
        logger.info(f"Scoring scenario: {scenario_id}")

        # Guard: if deterministic is None (rules unavailable), use neutral score
        if deterministic is None:
            det_score = 0.5
        else:
            det_score = 1.0 if deterministic.passed else 0.0

        # Critical failure override (only if we have rules)
        if deterministic is not None and not deterministic.passed:
            logger.warning(
                f"Scenario {scenario_id} failed deterministic rules: {deterministic.failed_rules}"
            )

        # ── Axes 2, 3, 4: LLM Judge ──
        llm_metrics = self._run_llm_judge(transcript)
        sem_score = llm_metrics.get("semantic_score", 0.0)
        conv_score = llm_metrics.get("conversational_score", 0.0)
        turing_score = llm_metrics.get("turing_score", 0.0)
        issues = llm_metrics.get("issues", [])

        # ── Voice-appropriate response length check ──
        length_penalty, length_issues = self._check_response_length(transcript)
        if length_penalty > 0:
            conv_score = max(0.0, conv_score - length_penalty)
            issues.extend(length_issues)

        # Inject deterministic failures into issues for optimizer visibility
        if deterministic and not deterministic.passed:
            for rule_id in deterministic.failed_rules:
                # Add a synthetic semantic issue for each failed hard rule
                issues.append({
                    "section": f"Hard Rule Violation: {rule_id}",
                    "severity": "HIGH",
                    "description": f"Agent violated rule {rule_id}: {deterministic.details.get(rule_id, 'Rule match failed')}",
                    "root_cause_gene": "RULES",
                    "recommendation": "Explicitly instruction the agent to follow this rule in the RULES or FLOW gene."
                })

        # ── Weighted Average ──
        weights = Config.SCORING_WEIGHTS
        overall = (
            (det_score * weights["deterministic"])
            + (sem_score * weights["semantic"])
            + (conv_score * weights["conversational"])
            + (turing_score * weights["turing"])
        )

        return EvaluationResult(
            scenario_id=scenario_id,
            deterministic_result=deterministic,
            semantic_score=sem_score,
            semantic_issues=[SemanticIssue(**i) for i in issues if isinstance(i, dict) and "section" in i],
            overall_score=round(overall, 3),
            subscores={
                "deterministic": det_score,
                "semantic": sem_score,
                "conversational": conv_score,
                "turing": turing_score,
            },
            is_critical_fail=(deterministic is not None and not deterministic.passed),
        )

    def _check_response_length(
        self, transcript: str
    ) -> tuple[float, List[Dict[str, Any]]]:
        """Check agent response length — voice agents should use 1-2 sentences per turn.

        Returns (penalty, issues) where penalty is subtracted from conversational score.
        """
        agent_turns = [
            line.split(":", 1)[1].strip()
            for line in transcript.split("\n")
            if line.startswith("Agent:") and ":" in line
        ]

        if not agent_turns:
            return 0.0, []

        word_counts = [len(turn.split()) for turn in agent_turns]
        avg_words = sum(word_counts) / len(word_counts)
        max_words = max(word_counts)

        penalty = 0.0
        issues: List[Dict[str, Any]] = []

        # Avg > 40 words = more than ~2 sentences per turn
        if avg_words > 40:
            penalty = 0.2
            issues.append({
                "section": "Response Length",
                "severity": "HIGH",
                "description": (
                    f"Agent averages {avg_words:.0f} words per turn. "
                    f"Voice agents should keep responses to 1-2 sentences (~20-30 words)."
                ),
                "root_cause_gene": "FLOW",
                "recommendation": "Shorten agent responses. One idea per turn, then wait for the user.",
            })
        elif avg_words > 30:
            penalty = 0.1
            issues.append({
                "section": "Response Length",
                "severity": "MEDIUM",
                "description": (
                    f"Agent averages {avg_words:.0f} words per turn. "
                    f"Consider shortening to 1-2 sentences for voice."
                ),
                "root_cause_gene": "FLOW",
                "recommendation": "Trim filler words and split long responses into multiple turns.",
            })

        # Any single turn > 60 words is a monologue
        if max_words > 60:
            penalty = max(penalty, 0.15)
            issues.append({
                "section": "Monologue Detected",
                "severity": "HIGH",
                "description": (
                    f"Agent has a turn with {max_words} words. "
                    f"This is too long for voice — the human brain can't retain that much spoken info."
                ),
                "root_cause_gene": "FLOW",
                "recommendation": "Break long responses into conversational exchanges. Ask, confirm, then continue.",
            })

        return penalty, issues

    def _run_llm_judge(self, transcript: str) -> Dict[str, Any]:
        """Ask Claude to score on Semantic, Conversational, and Turing axes."""
        system_prompt = """You are a Master Voice AI Judge.

Analyze the transcript and score the Agent on 3 axes (0.0 to 1.0):

1. SEMANTIC (Understanding): Did the agent correctly understand user intent and answer questions accurately?
2. CONVERSATIONAL (Flow): Did the agent manage turn-taking well? Was it concise? Did it avoid awkward repetition?
3. TURING (Human-likeness): Did it sound like a helper or a robot? (Warmth, empathy, personality).

Return JSON with keys:
- "semantic_score": float
- "conversational_score": float
- "turing_score": float
- "issues": list of {
    "section": "Brief summary",
    "severity": "HIGH/MEDIUM/LOW",
    "description": "Specific feedback",
    "root_cause_gene": "One of: IDENTITY, PERSONALITY, RULES, FLOW, OBJECTIONS, CLOSING, TOOLS",
    "recommendation": "Fix"
}

Failures in understanding = LOW semantic score.
Robotic/long monologues = LOW conversational score.
Cold/generic responses = LOW turing score.

Transcript format:
User: ...
Agent: ...
"""
        # Guard: skip judge if transcript is empty (simulation errored)
        if not transcript or len(transcript.strip()) < 20:
            logger.warning("Transcript empty or too short — skipping LLM judge.")
            return {
                "semantic_score": 0.0,
                "conversational_score": 0.0,
                "turing_score": 0.0,
                "issues": [{
                    "section": "Simulation Error",
                    "severity": "CRITICAL",
                    "description": "Simulation ended in error — no transcript to evaluate. Check agent for infinite loop.",
                    "root_cause_gene": "FLOW",
                    "recommendation": "Inspect agent LLM prompt for missing end_call conditions or contradictory instructions.",
                }],
            }

        user_msg = f"Evaluate this transcript:\n\n{transcript}"

        try:
            response = claude_client.complete(
                system_prompt, user_msg, temperature=0.0
            )
            # Cleanup Markdown code blocks if present
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            return json.loads(response.strip())

        except Exception as e:
            logger.error(f"LLM Judge Judgment Failed: {e}")
            return {
                "semantic_score": 0.0,
                "conversational_score": 0.0,
                "turing_score": 0.0,
                "issues": [
                    {
                        "section": "System",
                        "severity": "CRITICAL",
                        "description": "LLM Judge failed to evaluate transcript.",
                        "recommendation": "Check logs.",
                    }
                ],
            }


# Singleton
score_engine = ScoreEngine()
