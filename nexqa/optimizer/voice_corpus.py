"""
NEXQA v1.0 — Voice Corpus Loader

Loads the curated voice AI markdown corpus and returns targeted
sections as context for gene optimization, linting, and scoring.

Usage:
    from nexqa.optimizer.voice_corpus import voice_corpus

    # Get context for specific failing genes
    ctx = voice_corpus.get_optimization_context(["FLOW", "OBJECTIONS"])

    # Get full corpus
    full = voice_corpus.get_full_corpus()

    # Get anti-pattern table for linting
    rules = voice_corpus.get_linter_rules()
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from nexqa.storage.logger import logger


class VoiceCorpus:
    """Loads and indexes the curated voice AI corpus by section."""

    # Mapping from gene types to relevant corpus sections
    GENE_TO_SECTIONS: Dict[str, List[str]] = {
        "IDENTITY": [
            "Cross-platform universal principles",
            "Platform deep-dives",
        ],
        "FLOW": [
            "Cross-platform universal principles",
            "Cross-platform pattern library",
            "Platform deep-dives",
        ],
        "OBJECTIONS": [
            "Cross-platform universal principles",
            "Cross-platform prompting wisdom",
            "Cross-platform pattern library",
        ],
        "PERSONALITY": [
            "Cross-platform universal principles",
            "Cross-platform prompting wisdom",
        ],
        "GUARDRAILS": [
            "Cross-platform universal principles",
            "Cross-platform pattern library",
        ],
        "RULES": [
            "Cross-platform universal principles",
            "Platform deep-dives",
            "Appendix",
        ],
        "TOOLS": [
            "Platform deep-dives",
            "Cross-platform pattern library",
        ],
    }

    # Sections relevant for scoring / evaluation
    SCORING_SECTIONS = [
        "Cross-platform universal principles",
        "Cross-platform pattern library",
    ]

    # Sections relevant for linting
    LINTER_SECTIONS = [
        "Cross-platform pattern library",
    ]

    def __init__(self) -> None:
        self._sections: Dict[str, str] = {}
        self._raw: str = ""
        self._loaded: bool = False

    def _load(self) -> None:
        """Load and index the corpus file on first access."""
        if self._loaded:
            return

        corpus_path = (
            Path(__file__).parent.parent
            / "voice_corpus"
            / "nexqa_voice_corpus_curated.md"
        )

        if not corpus_path.exists():
            logger.warning(f"Voice corpus not found at {corpus_path}")
            self._loaded = True
            return

        self._raw = corpus_path.read_text(encoding="utf-8")
        self._sections = self._split_sections(self._raw)
        self._loaded = True
        logger.info(
            f"Voice corpus loaded: {len(self._sections)} sections, "
            f"{len(self._raw)} chars"
        )

    def _split_sections(self, text: str) -> Dict[str, str]:
        """Split markdown on ## headers into name→content dict."""
        sections: Dict[str, str] = {}
        # Split on ## at start of line (not ### or deeper)
        parts = re.split(r"^## ", text, flags=re.MULTILINE)

        for part in parts[1:]:  # Skip content before first ##
            lines = part.split("\n", 1)
            name = lines[0].strip()
            content = lines[1].strip() if len(lines) > 1 else ""
            sections[name] = content

        return sections

    # ─── Public API ──────────────────────────────────────────────────

    def get_optimization_context(
        self, failing_genes: List[str]
    ) -> str:
        """Return corpus sections relevant to the specified gene types.

        Args:
            failing_genes: List of gene type strings, e.g. ["FLOW", "OBJECTIONS"]

        Returns:
            Concatenated corpus sections relevant to those gene types.
        """
        self._load()

        if not self._sections:
            return ""

        # Collect unique section names for all failing genes
        needed: set = set()
        for gene_type in failing_genes:
            gene_upper = gene_type.upper()
            section_names = self.GENE_TO_SECTIONS.get(gene_upper, [])
            needed.update(section_names)

        # If no mapping found, return universal principles
        if not needed:
            needed = {"Cross-platform universal principles"}

        # Build context from available sections
        parts: List[str] = []
        for section_name in needed:
            content = self._sections.get(section_name)
            if content:
                parts.append(f"## {section_name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def get_full_corpus(self) -> str:
        """Return the entire raw corpus."""
        self._load()
        return self._raw

    def get_scoring_context(self) -> str:
        """Return sections relevant for evaluation/scoring."""
        self._load()

        parts: List[str] = []
        for section_name in self.SCORING_SECTIONS:
            content = self._sections.get(section_name)
            if content:
                parts.append(f"## {section_name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def get_linter_rules(self) -> str:
        """Return anti-pattern reference table for linting."""
        self._load()

        parts: List[str] = []
        for section_name in self.LINTER_SECTIONS:
            content = self._sections.get(section_name)
            if content:
                parts.append(f"## {section_name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def get_section(self, section_name: str) -> Optional[str]:
        """Return a specific section by name, or None."""
        self._load()
        return self._sections.get(section_name)

    def list_sections(self) -> List[str]:
        """Return all available section names."""
        self._load()
        return list(self._sections.keys())

    def get_universal_rules(self) -> Dict[str, List[Dict[str, str]]]:
        """Return voice AI rules in a structured, JSON-serializable format.

        Designed for consumption by external systems (e.g. an agent builder)
        so they can apply voice best practices during agent creation (shift-left).

        Returns dict with 'hard_rules' (always apply) and 'soft_rules' (recommendations).
        """
        return {
            "hard_rules": [
                {
                    "id": "max_response_length",
                    "rule": "Keep voice responses to 1-2 sentences per turn (max ~30 words)",
                    "reason": "Human brain cannot retain long spoken blocks",
                },
                {
                    "id": "one_question_per_turn",
                    "rule": "Ask one question at a time, then wait for the user to respond",
                    "reason": "Users only answer the first question in a multi-question turn",
                },
                {
                    "id": "normalize_for_speech",
                    "rule": "Write all numbers, dates, currencies, and symbols in spoken form",
                    "reason": "TTS reads raw formats incorrectly (e.g., '$1,234' → 'dollar sign one comma...')",
                },
                {
                    "id": "no_internal_mechanics",
                    "rule": "Never expose tool names, function calls, webhooks, or system prompts",
                    "reason": "Breaks immersion and confuses the caller",
                },
                {
                    "id": "no_markdown",
                    "rule": "Never use markdown formatting (bold, bullets, numbered lists) in responses",
                    "reason": "TTS reads asterisks and dashes literally",
                },
                {
                    "id": "confirm_critical_info",
                    "rule": "Always repeat back and confirm critical information (names, dates, addresses)",
                    "reason": "Voice has no visual confirmation — verbal confirmation is essential",
                },
            ],
            "soft_rules": [
                {
                    "id": "conversational_fillers",
                    "rule": "Use natural fillers like 'uhm', 'let me see', 'one moment' during tool execution",
                    "reason": "Masks processing silence and sounds more human",
                },
                {
                    "id": "empathy_first",
                    "rule": "Acknowledge frustration or pain points before offering solutions",
                    "reason": "Builds trust and reduces caller churn",
                },
                {
                    "id": "spell_out_details",
                    "rule": "Spell out addresses, zip codes, and phone numbers one digit/letter at a time",
                    "reason": "Prevents transcription errors over voice",
                },
                {
                    "id": "explicit_fallback",
                    "rule": "Include explicit fallback handling for unknown requests or errors",
                    "reason": "Prevents awkward silence or hallucinated responses",
                },
                {
                    "id": "use_contractions",
                    "rule": "Use contractions (I'm, you're, we'll) to sound more natural",
                    "reason": "Formal speech ('I am', 'you are') sounds robotic via TTS",
                },
            ],
        }


# Module-level singleton
voice_corpus = VoiceCorpus()
