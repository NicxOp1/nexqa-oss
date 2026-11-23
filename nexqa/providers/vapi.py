"""
Vapi adapter.

Prompt
  The system prompt is the `role: "system"` entry of `model.messages` on the
  assistant (GET /assistant/{id}). The docs do not say whether
  PATCH /assistant/{id} merges or replaces `model`, so `update_prompt` always
  sends the FULL model object it just read (provider, model, tools, toolIds,
  every message), with only the system message changed. Nothing else on the
  assistant is sent, so voice, transcriber and the rest stay as they are.

Tests, two modes (`provider_config.mode`):
  - "chat" (default): Claude plays the caller and talks to the assistant
    through the Chat API (POST /chat, chained with `previousChatId`). Text
    only: tests prompt and tool logic, not audio.
  - "simulation": Vapi's native Simulations. Needs `personality_id` (the
    simulated-caller personality, created once in the Vapi dashboard). NEXQA
    creates one scenario + simulation per spec scenario, runs them with
    POST /eval/simulation/run against the assistant, polls the run and reads
    the run items (transcript in `metadata.call.messages`).

Docs:
- https://docs.vapi.ai/api-reference/assistants/get
- https://docs.vapi.ai/api-reference/assistants/update
- https://docs.vapi.ai/assistants/quickstart.md (model.messages system prompt)
- https://docs.vapi.ai/api-reference/chats/create.md
- https://docs.vapi.ai/api-reference/simulation-scenarios/scenario-controller-create.md
- https://docs.vapi.ai/api-reference/simulations/simulation-controller-create.md
- https://docs.vapi.ai/api-reference/simulation-runs/simulation-run-controller-create
- https://docs.vapi.ai/api-reference/simulation-runs/simulation-run-controller-find-one
- https://docs.vapi.ai/api-reference/simulation-runs/simulation-run-controller-find-items.md
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any, Dict, List, Optional

from nexqa.models.rule_models import CompiledSpec, TestScenario
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
from nexqa.providers.simulator import AgentReply, SimulatedCallerProvider, TextSession
from nexqa.storage.logger import logger

RUN_DONE = ("ended",)
ITEM_DONE = ("passed", "failed", "canceled")


def _parse_args(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw if raw is not None else {}


def openai_messages_to_turns(messages: List[Dict[str, Any]]) -> tuple:
    """OpenAI-format messages (role/content/tool_calls) -> (turns, tool calls)."""
    turns: List[Turn] = []
    calls: Dict[str, ToolCall] = {}
    ordered: List[ToolCall] = []
    for msg in messages or []:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):  # content parts
            content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        if role == "assistant":
            if content:
                turns.append(Turn(role="agent", text=str(content)))
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                call = ToolCall(
                    name=fn.get("name") or tc.get("name", "unknown"),
                    arguments=_parse_args(fn.get("arguments", tc.get("arguments"))),
                    call_id=tc.get("id"),
                )
                ordered.append(call)
                if call.call_id:
                    calls[call.call_id] = call
        elif role == "user" and content:
            turns.append(Turn(role="user", text=str(content)))
        elif role == "tool":
            call = calls.get(msg.get("tool_call_id") or "")
            if call is not None:
                call.result = content
            else:
                ordered.append(ToolCall(name=msg.get("name", "unknown"), result=content))
    return turns, ordered


class VapiProvider(SimulatedCallerProvider, HTTPProvider):
    name = "vapi"
    display_name = "Vapi"
    maturity = "tested-offline"
    test_mode = "Chat API + simulated caller (default), or native Simulations"
    docs_url = "https://docs.vapi.ai/api-reference/chats/create"
    api_key_env = "VAPI_API_KEY"
    base_url = "https://api.vapi.ai"

    # ─── Prompt ──────────────────────────────────────────────────────

    def get_assistant(self, agent_id: str) -> Dict[str, Any]:
        return self.get(f"/assistant/{agent_id}") or {}

    def get_prompt(self, agent_id: str) -> str:
        model = self.get_assistant(agent_id).get("model") or {}
        for msg in model.get("messages") or []:
            if msg.get("role") == "system":
                return msg.get("content") or ""
        return ""

    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        model = self.get_assistant(agent_id).get("model")
        if not model:
            raise ProviderError(f"Vapi assistant {agent_id} has no model to update")
        model = copy.deepcopy(model)
        messages = model.get("messages") or []
        for msg in messages:
            if msg.get("role") == "system":
                msg["content"] = new_prompt
                break
        else:
            messages.insert(0, {"role": "system", "content": new_prompt})
        model["messages"] = messages
        logger.info(f"Updating Vapi assistant {agent_id} prompt (full model object resent)")
        return self.patch(f"/assistant/{agent_id}", json={"model": model})

    # ─── Mode switch ─────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return str(self.config.get("mode", "chat")).lower()

    def resolve_target(self, agent_id, hint=None):
        self.get_assistant(agent_id)  # fail fast on a wrong id or key
        return {"assistantId": agent_id}

    def register_scenarios(self, agent_id: str, spec: CompiledSpec, target: Dict[str, Any]):
        if self.mode != "simulation":
            return super().register_scenarios(agent_id, spec, target)
        personality_id = self.config.get("personality_id")
        if not personality_id:
            raise ProviderError(
                "Vapi simulation mode needs provider_config.personality_id "
                "(create a simulated-caller personality in the Vapi dashboard)."
            )
        suite = TestSuite(agent_id=agent_id, target=target)
        for scenario in spec.scenarios:
            try:
                sim_id = self._create_simulation(scenario, personality_id)
                suite.items.append(SuiteItem(scenario.id, scenario.name, sim_id, scenario))
            except Exception as e:
                logger.warning(f"Skipping scenario '{scenario.name}': {e}")
        return suite

    def _create_simulation(self, scenario: TestScenario, personality_id: str) -> str:
        evaluations = [
            {
                "structuredOutput": {
                    "name": f"nexqa_check_{i + 1}",
                    "description": criterion,
                    "schema": {"type": "boolean", "description": criterion},
                },
                "comparator": "=",
                "value": True,
            }
            for i, criterion in enumerate(scenario_metrics(scenario))
        ]
        created = self.post(
            "/eval/simulation/scenario",
            json={
                "name": f"nexqa: {scenario.name}",
                "instructions": scenario.user_prompt,
                "evaluations": evaluations,
            },
        ) or {}
        sim = self.post(
            "/eval/simulation",
            json={
                "name": f"nexqa: {scenario.name}",
                "scenarioId": created.get("id"),
                "personalityId": personality_id,
            },
        ) or {}
        if not sim.get("id"):
            raise ProviderError("Vapi did not return a simulation id")
        return sim["id"]

    def start_run(self, suite: TestSuite) -> str:
        if self.mode != "simulation":
            return super().start_run(suite)
        body = {
            "simulations": [{"type": "simulation", "simulationId": i} for i in suite.remote_ids],
            "target": {"type": "assistant", "assistantId": suite.agent_id},
            "transport": {"provider": self.config.get("transport", "vapi.webchat")},
        }
        run = self.post("/eval/simulation/run", json=body) or {}
        if not run.get("id"):
            raise ProviderError("Vapi did not return a simulation run id")
        return run["id"]

    async def wait_for_results(self, suite, handle, poll_interval, timeout) -> SuiteRun:
        if self.mode != "simulation":
            return await super().wait_for_results(suite, handle, poll_interval, timeout)
        elapsed = 0
        while elapsed < timeout:
            run = await asyncio.to_thread(self.get, f"/eval/simulation/run/{handle}") or {}
            if run.get("status") in RUN_DONE:
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        else:
            logger.error(f"Vapi simulation run {handle} timed out after {timeout}s")
            return SuiteRun()

        data = await asyncio.to_thread(self.get, f"/eval/simulation/run/{handle}/item")
        items = data.get("results", []) if isinstance(data, dict) else (data or [])
        return SuiteRun([self.normalize_item(suite, it) for it in items])

    @staticmethod
    def normalize_item(suite: TestSuite, item: Dict[str, Any]) -> Conversation:
        suite_item = suite.scenario_for(item.get("simulationId", ""))
        call = (item.get("metadata") or {}).get("call") or {}
        turns, calls = openai_messages_to_turns(call.get("messages") or [])
        results = item.get("results") or {}
        status = item.get("status", "")
        return Conversation(
            scenario_id=suite_item.scenario_id if suite_item else item.get("simulationId", "unknown"),
            turns=turns,
            tool_calls=calls,
            status={"passed": "pass", "failed": "fail", "canceled": "error"}.get(status, "completed"),
            end_reason=item.get("failureReason"),
            platform_passed=results.get("passed"),
            fallback_transcript=call.get("transcript") or "",
            raw=item,
        )

    # ─── Chat mode session ───────────────────────────────────────────

    def open_session(self, agent_id: str, scenario: TestScenario) -> TextSession:
        return VapiChatSession(self, agent_id)


class VapiChatSession(TextSession):
    """A multi-turn text chat: each turn is a new chat linked by previousChatId."""

    def __init__(self, provider: VapiProvider, assistant_id: str) -> None:
        self.provider = provider
        self.assistant_id = assistant_id
        self.previous_chat_id: Optional[str] = None
        self.cost = 0.0

    async def start(self) -> Optional[str]:
        return None  # the Chat API answers input; the caller speaks first

    async def send(self, text: str) -> AgentReply:
        body: Dict[str, Any] = {"assistantId": self.assistant_id, "input": text}
        if self.previous_chat_id:
            body["previousChatId"] = self.previous_chat_id
        chat = await asyncio.to_thread(self.provider.post, "/chat", json=body) or {}
        self.previous_chat_id = chat.get("id") or self.previous_chat_id
        self.cost += float(chat.get("cost") or 0)
        turns, calls = openai_messages_to_turns(chat.get("output") or [])
        text_out = " ".join(t.text for t in turns if t.role == "agent")
        return AgentReply(text=text_out, tool_calls=calls)
