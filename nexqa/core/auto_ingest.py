"""
NEXQA v1.0 — Auto Ingestor

Generates QA specs from real conversation transcripts using Claude.
Analyzes transcript patterns to identify rules, scenarios, and quality criteria.

Usage:
    from nexqa.core.auto_ingest import auto_ingestor

    spec = auto_ingestor.ingest_transcripts(
        transcripts=["transcript 1...", "transcript 2..."],
        agent_context="Outbound sales agent for dental clinics",
    )
    auto_ingestor.generate_spec_yaml(spec, Path("output_spec.yaml"))
"""

import json
from pathlib import Path
from typing import List

import yaml

from nexqa.models.rule_models import (
    CompiledSpec,
    HardRule,
    SoftRule,
    TestScenario,
)
from nexqa.storage.logger import logger


class AutoIngestor:
    """Generates QA specifications from conversation transcripts."""

    ANALYSIS_PROMPT = """\
You are a voice AI QA specialist. Analyze these real conversation transcripts
and extract a structured QA specification.

AGENT CONTEXT: {agent_context}

TRANSCRIPTS:
{transcripts}

Extract the following as JSON:

{{
  "hard_rules": [
    {{"id": "HR-001", "description": "...", "check_type": "keyword|regex|semantic", "check_value": "..."}}
  ],
  "soft_rules": [
    {{"id": "SR-001", "description": "...", "weight": 0.0-1.0, "category": "tone|flow|accuracy|compliance"}}
  ],
  "test_scenarios": [
    {{"id": "TS-001", "name": "...", "user_prompt": "...", "expected_behavior": "...", "tags": ["happy_path|edge_case|adversarial"]}}
  ],
  "raw_text": "A concise summary of the agent's purpose and behavior patterns observed."
}}

Rules to follow:
- Hard rules are binary pass/fail checks (e.g., "Agent must identify itself by name")
- Soft rules are quality scores (e.g., "Agent should use empathetic language")
- Test scenarios are realistic user inputs that test specific behaviors
- Extract at least 3 hard rules, 3 soft rules, and 5 test scenarios
- Base everything on OBSERVED patterns in the transcripts
"""

    def ingest_transcripts(
        self,
        transcripts: List[str],
        agent_context: str = "",
    ) -> CompiledSpec:
        """Analyze transcripts via Claude and generate a CompiledSpec.

        Args:
            transcripts: List of conversation transcript strings.
            agent_context: Brief description of the agent's purpose.

        Returns:
            CompiledSpec with extracted rules and scenarios.
        """
        from nexqa.integrations.claude_client import claude_client

        # Format transcripts with indices
        formatted = "\n\n".join(
            f"--- Transcript {i+1} ---\n{t}"
            for i, t in enumerate(transcripts)
        )

        prompt = self.ANALYSIS_PROMPT.format(
            agent_context=agent_context,
            transcripts=formatted,
        )

        try:
            logger.info(
                f"Auto-ingesting {len(transcripts)} transcripts "
                f"({sum(len(t) for t in transcripts)} chars)"
            )
            response = claude_client.call(prompt)

            # Parse JSON from response
            data = self._extract_json(response)

            return self._build_spec(data)

        except Exception as e:
            logger.error(f"Auto-ingest failed: {e}")
            # Return minimal spec on failure
            return CompiledSpec(
                hard_rules=[],
                soft_rules=[],
                test_scenarios=[],
                raw_text=f"Auto-ingest failed: {e}",
            )

    def ingest_from_retell(
        self,
        agent_id: str,
        limit: int = 10,
    ) -> CompiledSpec:
        """Fetch transcripts from Retell and generate a spec.

        Note: This depends on Retell's call listing API.
        Falls back gracefully if the endpoint is unavailable.
        """
        try:
            from nexqa.integrations.retell_client import retell_client
            import requests

            resp = requests.get(
                f"{retell_client.BASE_URL}/v2/list-calls",
                headers=retell_client.headers,
                params={
                    "filter_criteria": json.dumps({
                        "agent_id": [agent_id],
                    }),
                    "limit": limit,
                    "sort_order": "descending",
                },
            )
            resp.raise_for_status()
            calls = resp.json()

            transcripts = []
            for call in calls:
                transcript = call.get("transcript", "")
                if transcript:
                    transcripts.append(transcript)

            if not transcripts:
                logger.warning(f"No transcripts found for agent {agent_id}")
                return CompiledSpec(
                    hard_rules=[],
                    soft_rules=[],
                    test_scenarios=[],
                    raw_text=f"No transcripts found for agent {agent_id}",
                )

            return self.ingest_transcripts(
                transcripts=transcripts,
                agent_context=f"Retell agent {agent_id}",
            )

        except Exception as e:
            logger.error(f"Failed to ingest from Retell: {e}")
            return CompiledSpec(
                hard_rules=[],
                soft_rules=[],
                test_scenarios=[],
                raw_text=f"Retell ingest failed: {e}",
            )

    def generate_spec_yaml(
        self,
        spec: CompiledSpec,
        output_path: Path,
    ) -> Path:
        """Serialize a CompiledSpec to a YAML file.

        Args:
            spec: The compiled spec to serialize.
            output_path: Where to write the YAML file.

        Returns:
            The path of the written file.
        """
        data = {
            "hard_rules": [r.model_dump() for r in spec.hard_rules],
            "soft_rules": [r.model_dump() for r in spec.soft_rules],
            "test_scenarios": [s.model_dump() for s in spec.test_scenarios],
            "raw_text": spec.raw_text,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info(f"Spec YAML written to {output_path}")
        return output_path

    # ─── Private Helpers ─────────────────────────────────────────────

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from Claude's response (handles code fences)."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from code fence
        import re
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # Try finding JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))

        raise ValueError(f"Could not extract JSON from response: {text[:200]}")

    def _build_spec(self, data: dict) -> CompiledSpec:
        """Build a CompiledSpec from parsed JSON data."""
        hard_rules = []
        for r in data.get("hard_rules", []):
            hard_rules.append(HardRule(
                id=r.get("id", "HR-???"),
                description=r.get("description", ""),
                check_type=r.get("check_type", "semantic"),
                check_value=r.get("check_value", ""),
            ))

        soft_rules = []
        for r in data.get("soft_rules", []):
            soft_rules.append(SoftRule(
                id=r.get("id", "SR-???"),
                description=r.get("description", ""),
                weight=float(r.get("weight", 0.5)),
                category=r.get("category", "accuracy"),
            ))

        test_scenarios = []
        for s in data.get("test_scenarios", []):
            test_scenarios.append(TestScenario(
                id=s.get("id", "TS-???"),
                name=s.get("name", ""),
                user_prompt=s.get("user_prompt", ""),
                expected_behavior=s.get("expected_behavior", ""),
                tags=s.get("tags", []),
            ))

        return CompiledSpec(
            hard_rules=hard_rules,
            soft_rules=soft_rules,
            test_scenarios=test_scenarios,
            raw_text=data.get("raw_text", ""),
        )


# Module-level singleton
auto_ingestor = AutoIngestor()
