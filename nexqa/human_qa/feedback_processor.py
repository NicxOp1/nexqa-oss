"""
NEXQA v1.0 — Feedback Processor

Ingests structured or unstructured feedback from human QA sessions
and converts it into actionable Semantic Issues for the Gene Optimizer.
"""

from typing import List, Optional

from nexqa.integrations.claude_client import claude_client
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

Output JSON list of objects matching SemanticIssue schema.
"""

        user_msg = f"""
FEEDBACK:
{feedback_text}

SCENARIO CONTEXT:
{scenario_context or "General Testing"}

Categorize all issues found.
"""

        try:
            # Again, we'd use structured output or strict JSON tool if available
            response = claude_client.complete(system_prompt, user_msg)
            
            # Mock parsing logic here (assuming LLM returns JSON)
            # In real implementation: json.loads(response) -> [SemanticIssue(**item) for item in list]
            
            # Simple fallback for now
            return [
                SemanticIssue(
                    section="General",
                    severity="MEDIUM",
                    description=feedback_text,
                    root_cause_gene="PERSONALITY",  # Guess
                    recommendation="Review feedback manually",
                )
            ]

        except Exception as e:
            logger.error(f"Feedback processing failed: {e}")
            return []


# Singleton
feedback_processor = FeedbackProcessor()
