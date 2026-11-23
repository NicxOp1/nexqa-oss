"""
Retell AI adapter.

Wraps the existing `RetellClient` (nexqa/integrations/retell_client.py) with
no change in behavior: the code below is the logic that lived in
`nexqa/core/engine.py` before 0.3.0, moved behind the provider interface.

- Prompt: GET agent -> response_engine.llm_id, then GET/PATCH
  /get-retell-llm, /update-retell-llm (`general_prompt`). Only
  `general_prompt` is sent, so tools, states and voice settings stay.
- Tests: native batch testing. /create-test-case-definition per scenario,
  /create-batch-test, poll /get-batch-test, then /list-test-runs.

Docs:
- https://docs.retellai.com/api-references/get-agent
- https://docs.retellai.com/api-references/update-retell-llm
- https://docs.retellai.com/api-references/create-test-case-definition
- https://docs.retellai.com/api-references/create-batch-test
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from nexqa.integrations.retell_client import RetellClient, retell_client
from nexqa.models.rule_models import CompiledSpec
from nexqa.providers.base import (
    Conversation,
    SuiteItem,
    SuiteRun,
    TestSuite,
    ToolCall,
    Turn,
    VoiceProvider,
    scenario_metrics,
)
from nexqa.storage.logger import logger

PENDING = ("in_progress", "pending", "running")


class RetellProvider(VoiceProvider):
    name = "retell"
    display_name = "Retell AI"
    maturity = "verified-live"
    test_mode = "native batch tests (simulated caller run by Retell)"
    docs_url = "https://docs.retellai.com/api-references/create-batch-test"
    api_key_env = "RETELL_API_KEY"

    def __init__(
        self, config: Optional[Dict[str, Any]] = None, client: Optional[RetellClient] = None
    ) -> None:
        super().__init__(config)
        self.client = client or retell_client

    # --- Prompt ------------------------------------------------------

    def get_prompt(self, agent_id: str) -> str:
        return self.client.get_current_prompt(agent_id)

    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        return self.client.update_prompt(agent_id, new_prompt)

    # --- Tests -------------------------------------------------------

    def resolve_target(
        self, agent_id: str, hint: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Return the agent's response_engine (raises if the agent fetch fails)."""
        if hint:
            return hint
        agent_details = self.client.get_agent(agent_id)
        response_engine = agent_details.get("response_engine")
        if not response_engine and agent_details.get("llm_id"):
            response_engine = {
                "type": "retell-llm",
                "llm_id": agent_details.get("llm_id"),
            }
        return response_engine or None

    def register_scenarios(
        self, agent_id: str, spec: CompiledSpec, target: Dict[str, Any]
    ) -> TestSuite:
        """Register scenarios as Retell test case definitions."""
        suite = TestSuite(agent_id=agent_id, target=target)
        llm_id = target.get("llm_id")

        for scenario in spec.scenarios:
            try:
                tc_id = self.client.create_test_case_definition(
                    name=scenario.name,
                    user_prompt=scenario.user_prompt,
                    llm_id=llm_id,
                    metrics=scenario_metrics(scenario),
                )
                suite.items.append(
                    SuiteItem(
                        scenario_id=scenario.id,
                        name=scenario.name,
                        remote_id=tc_id,
                        scenario=scenario,
                    )
                )
            except Exception as e:
                logger.warning(f"Skipping scenario '{scenario.name}': {e}")
                print(f"FAILED TO CREATE TEST CASE {scenario.name}: {e}")

        return suite

    def start_run(self, suite: TestSuite) -> str:
        return self.client.create_batch_test(suite.remote_ids, suite.target)

    async def wait_for_results(
        self, suite: TestSuite, handle: str, poll_interval: int, timeout: int
    ) -> SuiteRun:
        """Poll a batch test until completion using asyncio.sleep()."""
        batch_id = handle
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            batch_status = self.client.get_batch_test(batch_id)
            status = batch_status.get("status")

            if status in ("completed", "complete"):
                summary = batch_status.get("batch_test_summary", {})
                minutes = summary.get("total_duration_seconds", 0) / 60.0

                logger.info(
                    f"Batch {batch_id} completed. Waiting for individual runs to finalize..."
                )
                # Wait for individual test runs to have transcripts
                for retry in range(12):  # Max 60s extra wait
                    runs = self.client.list_test_runs(batch_id)
                    pending = [r for r in runs if r.get("status") in PENDING]
                    if not pending:
                        logger.info(f"All {len(runs)} test runs finalized.")
                        return SuiteRun(self.normalize_runs(runs), minutes)
                    logger.info(
                        f"Waiting for {len(pending)}/{len(runs)} runs to finalize "
                        f"(retry {retry+1})..."
                    )
                    await asyncio.sleep(5)
                # Return whatever we have
                logger.warning(
                    "Some test runs still pending after retries. Returning available results."
                )
                done = [r for r in runs if r.get("status") not in PENDING]
                return SuiteRun(self.normalize_runs(done), minutes)
            elif status == "failed":
                logger.error("Batch test reported failure status")
                return SuiteRun(self.normalize_runs(self.client.list_test_runs(batch_id)))

        logger.error(f"Batch test timed out after {timeout}s")
        return SuiteRun()

    # --- Normalization -----------------------------------------------

    @staticmethod
    def normalize_runs(results: List[Dict[str, Any]]) -> List[Conversation]:
        conversations = []
        for res in results:
            run_status = res.get("status", "")
            if run_status in PENDING:
                logger.info(f"Skipping test run with status '{run_status}'")
                continue
            conversations.append(RetellProvider.normalize_run(res))
        return conversations

    @staticmethod
    def normalize_run(res: Dict[str, Any]) -> Conversation:
        """Turn one /list-test-runs item into a Conversation."""
        scenario_id = (
            res.get("test_case_id")
            or res.get("test_case_definition_snapshot", {}).get("testCaseDefinitionId")
            or "unknown"
        )

        ts_snapshot = res.get("transcript_snapshot", {})
        transcript_list = ts_snapshot.get("transcript", [])
        logger.info(
            f"DEBUG_HISTORY: Scenario {scenario_id} - Transcript items: {len(transcript_list)}"
        )

        turns: List[Turn] = []
        tool_calls: List[ToolCall] = []
        for msg in transcript_list:
            role = str(msg.get("role", "")).lower()
            content = msg.get("content", "")
            m_type = msg.get("type", "")

            if role in ("agent", "assistant", "user") and content:
                turns.append(Turn(role="agent" if role in ("agent", "assistant") else "user",
                                  text=content))

            if m_type in ("tool_call_invocation", "tool_call"):
                tool_calls.append(ToolCall(
                    name=msg.get("name") or msg.get("tool_name", "unknown"),
                    arguments=msg.get("arguments") or msg.get("params") or msg.get("input", {}),
                    result=msg.get("result") or msg.get("output"),
                ))

        raw_status = res.get("status", "completed")
        status = {"complete": "completed", "in_progress": "running"}.get(raw_status, raw_status)
        return Conversation(
            scenario_id=scenario_id,
            turns=turns,
            tool_calls=tool_calls,
            status=status,
            platform_passed={"pass": True, "fail": False}.get(raw_status),
            platform_notes=res.get("result_explanation"),
            fallback_transcript=res.get("transcript", ""),
            raw=res,
        )
