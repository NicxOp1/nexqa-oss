"""
NEXQA v1.0 — Feedback Processor

Ingests structured or unstructured feedback from human QA sessions
and converts it into actionable Semantic Issues for the Gene Optimizer.
"""

from typing import List, Optional

from nexqa.integrations.claude_client import claude_client, extract_json
from nexqa.models.scenario_models import SemanticIssue
from nexqa.storage.logger import logger


class FeedbackProcessor:
    """Classifies human feedback into structured semantic issues."""

    def process_feedback(
        self,
        feedback_text: str,
        scenario_context: Optional[str] = None,
    ) -> List[SemanticIssue]:
        """Convert raw feedback text into structured SemanticIssue objects."""
        logger.info(f"Processing feedback: {feedback_text[:50]}...")

        system_prompt = """You are a QA Triage Specialist.
Analyze the human tester feedback and categorize the issues.

For each distinct problem, extract:
1. Section: What part of the conversation failed? (Greeting, Qualification, Objections)
2. Severity: CRITICAL (calls dropped, offensive), HIGH (wrong info), MEDIUM (awkward), LOW (minor)
3. Root Cause Gene: IDENTITY, FLOW, PERSONALITY, RULES, OBJECTIONS, TOOLS
4. Description: Detailed explanation.
5. Recommendation: How to fix the prompt.

Return ONLY a JSON array. Each item has the keys "section", "severity",
"description", "root_cause_gene" and "recommendation".
"""

        user_msg = f"""
FEEDBACK:
{feedback_text}

SCENARIO CONTEXT:
{scenario_context or "General Testing"}

Categorize all issues found.
"""

        try:
            response = claude_client.complete(system_prompt, user_msg)
            return self._parse_issues(response)
        except Exception as e:
            logger.error(f"Feedback processing failed: {e}")
            return [self._fallback_issue(feedback_text)]

    @staticmethod
    def _fallback_issue(feedback_text: str) -> SemanticIssue:
        return SemanticIssue(
            section="General",
            severity="MEDIUM",
            description=feedback_text,
            recommendation="Review this feedback manually",
        )

    @staticmethod
    def _parse_issues(response: str) -> List[SemanticIssue]:
        data = extract_json(response)
        if isinstance(data, dict):
            data = data.get("issues", [data])
        issues = []
        for item in data:
            try:
                issue = SemanticIssue(**item)
            except (TypeError, ValueError):
                logger.warning(f"Skipping malformed issue from Claude: {item}")
                continue
            issue.severity = issue.severity.upper()
            if issue.root_cause_gene:
                issue.root_cause_gene = issue.root_cause_gene.upper()
            issues.append(issue)
        return issues


# Singleton
feedback_processor = FeedbackProcessor()
