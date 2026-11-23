"""
Synthflow adapter.

Prompt
  `agent.prompt` of the assistant (GET /v2/assistants/{model_id}, which
  returns `response.assistants[]`). Updated with PUT /v2/assistants/{model_id}
  and body {"agent": {"prompt": ...}}. The docs say "Only the provided
  parameters will be updated, and others won't be removed or changed."

Tests
  Native Simulations. One simulation case per scenario
  (POST /v2/simulation_cases: the caller persona as `prompt`, the success
  criteria as `success_criteria`), one simulation per case against the agent
  (POST /v2/simulations), polled with GET /v2/simulations/{id}. The
  `timeline` becomes the transcript, `success_criteria_analysis` the
  platform verdict. Simulations may place real (billed) calls on Synthflow.

Regional base URLs (US/EU) are set with `provider_config.base_url`.

Docs:
- https://docs.synthflow.ai/authentication
- https://docs.synthflow.ai/api-reference/platform-api/agents/get-assistant
- https://docs.synthflow.ai/api-reference/platform-api/agents/update-assistant
- https://docs.synthflow.ai/api-reference/platform-api/simulations/create-simulation-case
- https://docs.synthflow.ai/api-reference/platform-api/simulations/start-simulation
- https://docs.synthflow.ai/api-reference/platform-api/simulations/get-simulation
"""

from __future__ import annotations

import asyncio
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

SIM_DONE = ("completed", "failed")

# The docs list `timeline[].sender_type` but not its values, so the mapping
# is by keyword. Unknown senders are kept as caller turns and logged.
AGENT_WORDS = ("agent", "bot", "assistant", "target")
TOOL_WORDS = ("tool", "function", "action", "webhook")


def _response(body: Any) -> Dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("response"), dict):
        return body["response"]
    return body or {}


class SynthflowProvider(HTTPProvider):
    name = "synthflow"
    display_name = "Synthflow"
    maturity = "tested-offline"
    test_mode = "native Simulations (simulation cases)"
    docs_url = "https://docs.synthflow.ai/api-reference/platform-api/simulations/start-simulation"
    api_key_env = "SYNTHFLOW_API_KEY"
    base_url = "https://api.synthflow.ai/v2"

    # --- Prompt ------------------------------------------------------

    def get_assistant(self, model_id: str) -> Dict[str, Any]:
        assistants = _response(self.get(f"/assistants/{model_id}")).get("assistants") or []
        if not assistants:
            raise ProviderError(f"Synthflow assistant {model_id} not found")
        return assistants[0]

    def get_prompt(self, agent_id: str) -> str:
        return (self.get_assistant(agent_id).get("agent") or {}).get("prompt") or ""

    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        logger.info(f"Updating Synthflow assistant {agent_id} prompt (partial PUT)")
        return self.put(f"/assistants/{agent_id}", json={"agent": {"prompt": new_prompt}})

    # --- Tests -------------------------------------------------------

    def resolve_target(self, agent_id, hint=None):
        self.get_assistant(agent_id)
        return {"target_agent_id": agent_id}

    def register_scenarios(self, agent_id: str, spec: CompiledSpec, target: Dict[str, Any]):
        suite = TestSuite(agent_id=agent_id, target=target)
        for scenario in spec.scenarios:
            body: Dict[str, Any] = {
                "name": f"nexqa: {scenario.name}",
                "prompt": scenario.user_prompt,
                "type": "custom",
                "success_criteria": scenario_metrics(scenario),
                "call_success_type": "all",
            }
            if self.config.get("suite_id"):
                body["suite_id"] = self.config["suite_id"]
            try:
                case = _response(self.post("/simulation_cases", json=body)).get("simulation_case") or {}
                case_id = case.get("simulation_case_id") or case.get("id")
                if not case_id:
                    raise ProviderError("no simulation case id returned")
                suite.items.append(SuiteItem(scenario.id, scenario.name, case_id, scenario))
            except Exception as e:
                logger.warning(f"Skipping scenario '{scenario.name}': {e}")
        return suite

    def start_run(self, suite: TestSuite) -> str:
        pairs = []
        for item in suite.items:
            try:
                sim = _response(self.post("/simulations", json={
                    "simulation_case_id": item.remote_id,
                    "target_agent_id": suite.agent_id,
                }))
                if sim.get("simulation_id"):
                    pairs.append(f"{item.remote_id}={sim['simulation_id']}")
            except Exception as e:
                logger.warning(f"Could not start Synthflow simulation '{item.name}': {e}")
        if not pairs:
            raise ProviderError("No Synthflow simulations could be started")
        return ",".join(pairs)

    async def wait_for_results(self, suite, handle, poll_interval, timeout) -> SuiteRun:
        pending = dict(p.split("=", 1) for p in handle.split(","))
        finished: Dict[str, Dict[str, Any]] = {}
        elapsed = 0
        while pending and elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            for case_id, sim_id in list(pending.items()):
                sim = _response(await asyncio.to_thread(self.get, f"/simulations/{sim_id}"))
                if sim.get("status") in SIM_DONE:
                    finished[case_id] = sim
                    del pending[case_id]
        if pending:
            logger.error(f"{len(pending)} Synthflow simulations still running after {timeout}s")
        return SuiteRun([self.normalize(suite, cid, sim) for cid, sim in finished.items()])

    @staticmethod
    def timeline_to_turns(timeline: List[Dict[str, Any]]) -> tuple:
        turns: List[Turn] = []
        calls: List[ToolCall] = []
        for event in timeline or []:
            sender = str(event.get("sender_type", "")).lower()
            kind = str(event.get("type", "")).lower()
            value = event.get("value")
            if any(w in kind for w in TOOL_WORDS) or any(w in sender for w in TOOL_WORDS):
                calls.append(ToolCall(name=kind or sender or "unknown", arguments=value))
                continue
            if not value:
                continue
            role = "agent" if any(w in sender for w in AGENT_WORDS) else "user"
            turns.append(Turn(role=role, text=str(value), start_s=event.get("timestamp")))
        return turns, calls

    @classmethod
    def normalize(cls, suite: TestSuite, case_id: str, sim: Dict[str, Any]) -> Conversation:
        item = suite.scenario_for(case_id)
        turns, calls = cls.timeline_to_turns(sim.get("timeline") or [])
        analysis = sim.get("success_criteria_analysis") or {}
        stamps = [t.start_s for t in turns if isinstance(t.start_s, (int, float))]
        return Conversation(
            scenario_id=item.scenario_id if item else case_id,
            turns=turns,
            tool_calls=calls,
            status="completed" if sim.get("status") == "completed" else "error",
            end_reason=(sim.get("error_info") or {}).get("message"),
            duration_s=(max(stamps) - min(stamps)) if len(stamps) > 1 else None,
            platform_passed=analysis.get("success"),
            platform_notes="; ".join(
                e.get("reasoning", "") for e in analysis.get("evaluations") or [] if e.get("reasoning")
            ) or None,
            raw=sim,
        )
