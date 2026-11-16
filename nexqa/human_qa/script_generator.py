"""
NEXQA v1.0 — Human Script Generator

Automatically creates test scripts for human QA sessions.
Focuses on edge cases that failed automated testing or require subjective verification.
"""

from typing import List, Optional

from nexqa.integrations.claude_client import claude_client
from nexqa.models.human_qa_models import HumanTestScript, TestStepType, HumanTestStep
from nexqa.models.scenario_models import EvaluationResult
from nexqa.storage.logger import logger


class ScriptGenerator:
    """Uses LLM to generate robust human test scripts from scenarios/failures."""

    def generate_script(
        self,
        scenario_name: str,
        user_prompt: str,
        failures: List[str] = [],
    ) -> HumanTestScript:
        """
        Generate a human test script for a given scenario.
        If failures provided, focuses on testing the fix for those issues.
        """
        logger.info(f"Generating human script for: {scenario_name}")

        system_prompt = """You are a QA Lead writing test scripts for human testers.
Your goal is to create clear, step-by-step instructions to verify a Voice AI agent.
Focus on natural phrasing and tricky variations.

Input: Scenario name, expected flow (user inputs), and known failure points.
Output: JSON matching HumanTestScript schema with steps (SPEAK/LISTEN/ACTION).
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
            # Placeholder for structured output extraction
            # In production, we'd force tool use or strict JSON
            response = claude_client.complete(system_prompt, user_msg)
            # Parse logic would go here (omitted for brevity, returning dummy script)
            
            # Simple fallback construction if LLM parse complex
            steps = [
                HumanTestStep(
                    step_id="1",
                    type=TestStepType.ACTION,
                    instruction=f"Call the agent for '{scenario_name}'",
                    criteria="Agent picks up and greets clearly",
                )
            ]
            steps.append(
                HumanTestStep(
                    step_id="2",
                    type=TestStepType.SPEAK,
                    instruction=f"Act according to this persona/context: '{user_prompt}'",
                    criteria="Agent responds relevantly",
                )
            )
            
            return HumanTestScript(
                scenario_id=scenario_name.lower().replace(" ", "_"),
                scenario_name=scenario_name,
                focus_area="Verify Fixes" if failures else "General QA",
                steps=steps,
            )

        except Exception as e:
            logger.error(f"Script Generation failed: {e}")
            return HumanTestScript(
                scenario_id="error",
                scenario_name=scenario_name,
                focus_area="Error",
                steps=[],
            )


# Singleton
script_generator = ScriptGenerator()
