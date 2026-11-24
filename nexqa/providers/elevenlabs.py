"""
ElevenLabs Agents (Conversational AI) adapter.

Prompt
  `conversation_config.agent.prompt.prompt` on GET /v1/convai/agents/{id}.
  The docs do not say whether PATCH /v1/convai/agents/{id} deep-merges a
  partial `conversation_config`, so `update_prompt` sends back the WHOLE
  `conversation_config` it just read, with only the prompt text changed.
  `platform_settings`, `workflow`, name and tags are not sent, so they stay.

Tests
  Native agent testing. One "simulation" test per scenario
  (POST /v1/convai/agent-testing/create, `simulation_scenario` = the
  scenario's caller persona, `success_conditions` = its success criteria),
  then POST /v1/convai/agents/{id}/run-tests and poll
  GET /v1/convai/test-invocations/{id}. Each test run's `agent_responses`
  becomes the transcript, and `condition_result` the platform verdict.
  (The legacy simulate-conversation endpoint is deprecated and is not used.)

Regional base URLs (EU/US/IN/SG residency) are set with `provider_config.base_url`.

Docs:
- https://elevenlabs.io/docs/api-reference/authentication.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/agents/get.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/agents/update.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/tests/create.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/tests/run-tests.md
- https://elevenlabs.io/docs/eleven-agents/api-reference/tests/test-invocations/get.md
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any, Dict, List

from nexqa.models.rule_models import CompiledSpec
from nexqa.providers.base import (
    Conversation,
    HTTPProvider,
    ProviderError,
    SuiteItem,
    SuiteRun,
    TestSuite,
    ToolCall,
    Turn,
    scenario_metrics,
)
from nexqa.storage.logger import logger

RUN_PENDING = ("pending",)


class ElevenLabsProvider(HTTPProvider):
    name = "elevenlabs"
    display_name = "ElevenLabs Agents"
    maturity = "tested-offline"
    test_mode = "native agent tests (simulation type)"
    docs_url = "https://elevenlabs.io/docs/eleven-agents/api-reference/tests/run-tests.md"
    api_key_env = "ELEVENLABS_API_KEY"
    base_url = "https://api.elevenlabs.io"

    def auth_headers(self) -> Dict[str, str]:
        return {"xi-api-key": self.api_key}

    # --- Prompt ------------------------------------------------------

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        return self.get(f"/v1/convai/agents/{agent_id}") or {}

    def get_prompt(self, agent_id: str) -> str:
        cc = self.get_agent(agent_id).get("conversation_config") or {}
        return ((cc.get("agent") or {}).get("prompt") or {}).get("prompt") or ""

    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        cc = self.get_agent(agent_id).get("conversation_config")
        if not cc:
            raise ProviderError(f"ElevenLabs agent {agent_id} has no conversation_config")
        cc = copy.deepcopy(cc)
        cc.setdefault("agent", {}).setdefault("prompt", {})["prompt"] = new_prompt
        logger.info(f"Updating ElevenLabs agent {agent_id} prompt (full conversation_config resent)")
        return self.patch(f"/v1/convai/agents/{agent_id}", json={"conversation_config": cc})

    # --- Tests -------------------------------------------------------

    def resolve_target(self, agent_id, hint=None):
        self.get_agent(agent_id)  # fail fast on a wrong id or key
        return {"agent_id": agent_id}

    def register_scenarios(self, agent_id: str, spec: CompiledSpec, target: Dict[str, Any]):
        suite = TestSuite(agent_id=agent_id, target=target)
        for scenario in spec.scenarios:
            body: Dict[str, Any] = {
                "type": "simulation",
                "name": f"nexqa: {scenario.name}",
                "simulation_scenario": scenario.user_prompt,
                "success_conditions": scenario_metrics(scenario),
                "simulation_max_turns": int(self.config.get("max_turns", 10)),
            }
            if self.config.get("tool_mock_config"):
                body["tool_mock_config"] = self.config["tool_mock_config"]
            try:
                created = self.post("/v1/convai/agent-testing/create", json=body) or {}
                if not created.get("id"):
                    raise ProviderError("no test id returned")
                suite.items.append(SuiteItem(scenario.id, scenario.name, created["id"], scenario))
            except Exception as e:
                logger.warning(f"Skipping scenario '{scenario.name}': {e}")
        return suite

    def start_run(self, suite: TestSuite) -> str:
        body = {"tests": [{"test_id": tid} for tid in suite.remote_ids]}
        invocation = self.post(f"/v1/convai/agents/{suite.agent_id}/run-tests", json=body) or {}
        if not invocation.get("id"):
            raise ProviderError("ElevenLabs did not return a test invocation id")
        return invocation["id"]

    async def wait_for_results(self, suite, handle, poll_interval, timeout) -> SuiteRun:
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            inv = await asyncio.to_thread(self.get, f"/v1/convai/test-invocations/{handle}") or {}
            runs = inv.get("test_runs") or []
            if runs and not any(r.get("status") in RUN_PENDING for r in runs):
                return SuiteRun([self.normalize_run(suite, r) for r in runs])
        logger.error(f"ElevenLabs test invocation {handle} timed out after {timeout}s")
        return SuiteRun()

    # --- Normalization -----------------------------------------------

    @staticmethod
    def transcript_to_turns(items: List[Dict[str, Any]]) -> tuple:
        turns: List[Turn] = []
        calls: Dict[str, ToolCall] = {}
        ordered: List[ToolCall] = []
        for msg in items or []:
            if msg.get("message"):
                turns.append(Turn(
                    role="agent" if msg.get("role") == "agent" else "user",
                    text=msg["message"],
                    start_s=msg.get("time_in_call_secs"),
                ))
            for tc in msg.get("tool_calls") or []:
                args = tc.get("params_as_json")
                try:
                    args = json.loads(args) if isinstance(args, str) else (args or {})
                except ValueError:
                    pass
                call = ToolCall(name=tc.get("tool_name", "unknown"), arguments=args,
                                call_id=tc.get("request_id"))
                ordered.append(call)
                if call.call_id:
                    calls[call.call_id] = call
            for tr in msg.get("tool_results") or []:
                call = calls.get(tr.get("request_id") or "")
                if call is not None:
                    call.result = tr.get("result_value")
                else:
                    ordered.append(ToolCall(name=tr.get("tool_name", "unknown"),
                                            result=tr.get("result_value")))
        return turns, ordered

    @classmethod
    def normalize_run(cls, suite: TestSuite, run: Dict[str, Any]) -> Conversation:
        item = suite.scenario_for(run.get("test_id", ""))
        turns, calls = cls.transcript_to_turns(run.get("agent_responses") or [])
        condition = run.get("condition_result") or {}
        rationale = condition.get("rationale") or {}
        status = run.get("status", "")
        return Conversation(
            scenario_id=item.scenario_id if item else run.get("test_id", "unknown"),
            turns=turns,
            tool_calls=calls,
            status={"passed": "pass", "failed": "fail", "cancelled": "error"}.get(status, "completed"),
            platform_passed={"success": True, "failure": False}.get(condition.get("result")),
            platform_notes=rationale.get("summary") if isinstance(rationale, dict) else None,
            raw=run,
        )
