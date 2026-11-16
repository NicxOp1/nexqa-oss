"""
NEXQA v1.0 — Prompt Linter

Pre-flight safety checks for new prompts before they are deployed.
Ensures critical identity anchors are preserved, length doesn't explode,
and internal tool names are not exposed to the user.
"""

import re
from typing import List

from nexqa.storage.logger import logger


class PromptLinter:
    """Checks the new prompt for structural integrity and forbidden patterns."""

    FORBIDDEN_TERMS = [
        "function_call",
        "json_format",
        "tool_use",
        "system_prompt",
        "internal_thought",
    ]

    def lint(self, old_prompt: str, new_prompt: str) -> bool:
        """
        Returns True if the new prompt is safe to publish.
        Returns False if it violates safety constraints.
        """
        logger.info("Linting new prompt...")
        passed = True

        # 1. Length Check (Explosion/Implosion)
        old_len = len(old_prompt)
        new_len = len(new_prompt)
        
        # Allow massive growth if starting from scratch (empty prompt)
        if old_len < 100:
            logger.info(f"Initial prompt empty/short ({old_len} chars). Allowing full rewrite.")
            
        elif new_len > old_len * 1.5:  # Increased threshold to 50% growth allowed
            # If prompt was tiny, ignore percentage rules
            logger.error(
                f"Lint Fail: Prompt length increased by > 50% ({old_len} → {new_len})"
            )
            passed = False
        elif new_len < old_len * 0.5:
            logger.error(
                f"Lint Fail: Prompt length decreased by > 50% ({old_len} → {new_len})"
            )
            passed = False

        # 2. Variable Preservation (e.g., {{name}}, {address})
        # Simple heuristic: count braces
        # A more robust check would parse them, but this catches major deletions
        if new_prompt.count("{") < old_prompt.count("{") * 0.5:
            logger.warning("Lint Warning: Significant loss of variable placeholders '{}'")

        # 3. Forbidden Terms Check
        for term in self.FORBIDDEN_TERMS:
            if term in new_prompt and term not in old_prompt:
                logger.error(
                    f"Lint Fail: Exposed internal term '{term}' to user prompt."
                )
                passed = False

        # 4. Identity Anchor Check
        # Ensure the agent still knows who it is (heuristic)
        if not self._check_identity_anchor(old_prompt, new_prompt):
            # This is a warning for now, could be an error if strict
            logger.warning("Lint Warning: Identity anchor phrase may apply been lost.")

        # 5. Voice AI Anti-Pattern Check
        anti_pattern_issues = self._check_corpus_anti_patterns(new_prompt)
        for issue in anti_pattern_issues:
            logger.warning(f"Lint Warning (voice anti-pattern): {issue}")

        return passed

    def _check_identity_anchor(self, old: str, new: str) -> bool:
        """Check if crucial identity phrases are preserved."""
        # Heuristic: Find the first sentence of the old prompt
        # and see if similar words exist in the new one.
        # Or look for "You are [Name]" pattern
        anchors = ["You are", "Your name is", "You act as"]
        
        old_anchor = next((a for a in anchors if a in old), None)
        if old_anchor:
            if old_anchor not in new:
                return False
        return True

    def _check_corpus_anti_patterns(self, prompt: str) -> List[str]:
        """Check the prompt against voice AI anti-patterns from the corpus."""
        issues: List[str] = []

        # Pattern: raw numbers that should be normalized
        if re.search(r'\$[\d,]+\.\d{2}', prompt):
            issues.append(
                "Raw currency format detected (e.g. '$1,234.56'). "
                "Use spoken-form normalization for voice."
            )

        # Pattern: markdown formatting in response instructions
        if re.search(r'\*\*.*?\*\*', prompt) and '## ' not in prompt[:20]:
            issues.append(
                "Bold markdown detected in prompt body. "
                "TTS may read asterisks literally."
            )

        # Pattern: multiple questions in example responses
        if re.search(r'\?[^"]*\?[^"]*\?', prompt):
            issues.append(
                "Multiple questions in a single turn detected. "
                "Voice agents should ask one question at a time."
            )

        # Pattern: exposing tool internals
        tool_terms = ["function_call", "tool_use", "json_format", "webhook"]
        for term in tool_terms:
            if term.lower() in prompt.lower():
                issues.append(
                    f"Internal term '{term}' found in prompt. "
                    "Don't expose internal mechanics to the user."
                )

        # Pattern: long sentences (>30 words without period)
        sentences = prompt.split('.')
        for sentence in sentences:
            word_count = len(sentence.strip().split())
            if word_count > 40:
                issues.append(
                    f"Very long sentence ({word_count} words). "
                    "Voice AI prompts should use short, direct sentences."
                )
                break  # Only report once

        return issues


# Singleton
linter = PromptLinter()
