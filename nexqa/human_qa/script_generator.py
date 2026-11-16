"""
NEXQA v1.0 — Human Script Generator

Automatically creates test scripts for human QA sessions.
Focuses on edge cases that failed automated testing or require subjective verification.
"""

from typing import List, Optional

from nexqa.integrations.claude_client import claude_client, extract_json
from nexqa.models.human_qa_models import HumanTestScript, TestStepType, HumanTestStep
from nexqa.storage.logger import logger


class ScriptGenerator:
    """Uses LLM to generate robust human test scripts from scenarios/failures."""

    def generate_script(
        self,
        scenario_name: str,
        user_prompt: str,
        failures: Optional[List[str]] = None,
    ) -> HumanTestScript:
        """
        Generate a human test script for a given scenario.
        If failures provided, focuses on testing the fix for those issues.
        """
        failures = failures or []
        logger.info(f"Generating human script for: {scenario_name}")

        system_prompt = """You are a QA Lead writing test scripts for human testers.
Your goal is to create clear, step-by-step instructions to verify a Voice AI agent.
Focus on natural phrasing and tricky variations.

Input: Scenario name, expected flow (user inputs), and known failure points.
Output: ONLY a JSON array of steps. Each step has the keys "step_id",
"type" (one of "speak", "listen", "action"), "instruction",
"expected_response" and "criteria".
"""

        user_msg = f"""
SCENARIO: {scenario_name}
USER PROMPT: {user_prompt}
KNOWN FAILURES: {failures}

Create a test script with:
1. Setup (call the agent)
2. Conversation steps (what to say, what to listen for)
3. Specific checks for the known failures (e.g., "Verify agent doesn't interrupt here")
4. Variations: include 1-2 alternative ways to say the user input.
"""

        try:
            response = claude_client.complete(system_prompt, user_msg)
            steps = self._parse_steps(response)
        except Exception as e:
            logger.error(f"Script generation failed, using a basic script: {e}")
            steps = []

        if not steps:
            steps = self._basic_steps(scenario_name, user_prompt)

        return HumanTestScript(
            scenario_id=scenario_name.lower().replace(" ", "_"),
            scenario_name=scenario_name,
            focus_area="Verify Fixes" if failures else "General QA",
            steps=steps,
        )

    @staticmethod
    def _parse_steps(response: str) -> List[HumanTestStep]:
        data = extract_json(response)
        if isinstance(data, dict):
            data = data.get("steps", [])
        steps = []
        for i, item in enumerate(data, start=1):
            try:
                item = {**item, "type": str(item.get("type", "speak")).lower()}
                item.setdefault("step_id", str(i))
                item["step_id"] = str(item["step_id"])
                steps.append(HumanTestStep(**item))
            except (TypeError, ValueError, AttributeError):
                logger.warning(f"Skipping malformed step from Claude: {item}")
        return steps

    @staticmethod
    def _basic_steps(scenario_name: str, user_prompt: str) -> List[HumanTestStep]:
        return [
            HumanTestStep(
                step_id="1",
                type=TestStepType.ACTION,
                instruction=f"Call the agent for '{scenario_name}'",
                criteria="Agent picks up and greets clearly",
            ),
            HumanTestStep(
                step_id="2",
                type=TestStepType.SPEAK,
                instruction=f"Act according to this persona/context: '{user_prompt}'",
                criteria="Agent responds relevantly",
            ),
        ]


# Singleton
script_generator = ScriptGenerator()
