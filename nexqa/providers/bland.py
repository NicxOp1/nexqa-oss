"""
Bland AI adapter.

Bland's API testing feature (Agent Testing) runs scenarios against a PERSONA
or a PATHWAY. The docs show no way to test a V2 agent (/v2/agents) by API, so
this adapter works on personas by default, where the prompt and the tests
address the same object:

target: "persona" (default)  -- agent_id is a persona id
  Prompt: `personality_prompt` of the persona's current draft version
          (GET /v1/personas/{id}); update with PATCH /v1/personas/{id},
          sending only `name` (required by the endpoint) and
          `personality_prompt`, so the orchestration prompt, voice and the
          rest are not touched.
  Tests:  one Agent Testing scenario per spec scenario
          (POST /v1/agent-testing/scenarios with `persona_id` and the
          caller persona as `tester_persona_prompt`), started with
          POST /v1/agent-testing/scenarios/{id}/run and polled with
          GET /v1/agent-testing/runs/{run_id} (`chat_history` transcript).

target: "agent_v2"  -- agent_id is a V2 agent id
  Prompt only: `snapshot.settings.systemPrompt` of
  GET /v2/agents/{id}/versions/latest. A prompt change saves a NEW version
  (POST /v2/agents/{id}/versions) with the full snapshot and
  `parent_version_id` as a compare-and-set guard. Promoting that version to
  an environment is left to you. Test runs need `provider_config.persona_id`
  or `pathway_id`, because Agent Testing does not take a V2 agent.

Auth: `authorization: <api key>` header (no "Bearer" prefix).

Docs:
- https://docs.bland.ai/api-v1/patch/personas-id.md
- https://docs.bland.ai/api-v2/get/agents-id-versions-latest.md
- https://docs.bland.ai/api-v2/post/agents-id-versions.md
- https://docs.bland.ai/tutorials/scenarios.md
- https://docs.bland.ai/api-v1/post/agent-testing-scenarios.md
- https://docs.bland.ai/api-v1/post/agent-testing-scenarios-run.md
- https://docs.bland.ai/api-v1/get/agent-testing-runs-id.md
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict, Optional

from nexqa.models.rule_models import CompiledSpec
from nexqa.providers.base import (
    Conversation,
    HTTPProvider,
    ProviderError,
    SuiteItem,
    SuiteRun,
    TestSuite,
    Turn,
)
from nexqa.storage.logger import logger

RUN_DONE = ("PASSED", "FAILED", "ERROR", "CANCELLED")


def _unwrap(body: Any) -> Dict[str, Any]:
    """Bland wraps most responses in {"data": ...}; accept both shapes."""
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body or {}


class BlandProvider(HTTPProvider):
    name = "bland"
    display_name = "Bland AI"
    maturity = "tested-offline"
    test_mode = "native Agent Testing scenarios (persona or pathway)"
    docs_url = "https://docs.bland.ai/tutorials/scenarios.md"
    api_key_env = "BLAND_API_KEY"
    base_url = "https://api.bland.ai"

    def auth_headers(self) -> Dict[str, str]:
        return {"authorization": self.api_key}

    @property
    def target_kind(self) -> str:
        return str(self.config.get("target", "persona")).lower()

    # --- Prompt ------------------------------------------------------

    def get_persona(self, persona_id: str) -> Dict[str, Any]:
        return _unwrap(self.get(f"/v1/personas/{persona_id}"))

    def latest_version(self, agent_id: str) -> Dict[str, Any]:
        params = {"branch": self.config["branch"]} if self.config.get("branch") else None
        return _unwrap(self.get(f"/v2/agents/{agent_id}/versions/latest", params=params))

    def get_prompt(self, agent_id: str) -> str:
        if self.target_kind == "agent_v2":
            snapshot = self.latest_version(agent_id).get("snapshot") or {}
            return (snapshot.get("settings") or {}).get("systemPrompt") or ""
        persona = self.get_persona(agent_id)
        draft = persona.get("current_draft_version") or {}
        return draft.get("personality_prompt") or persona.get("personality_prompt") or ""

    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        if self.target_kind == "agent_v2":
            latest = self.latest_version(agent_id)
            snapshot = copy.deepcopy(latest.get("snapshot") or {})
            if not snapshot:
                raise ProviderError(f"Bland agent {agent_id} has no version snapshot")
            snapshot.setdefault("settings", {})["systemPrompt"] = new_prompt
            body: Dict[str, Any] = {"snapshot": snapshot}
            if latest.get("id"):
                body["parent_version_id"] = latest["id"]
            if latest.get("revision") is not None:
                body["parent_revision"] = latest["revision"]
            logger.info(f"Saving new Bland V2 version for agent {agent_id}")
            return self.post(f"/v2/agents/{agent_id}/versions", json=body)

        persona = self.get_persona(agent_id)
        name = persona.get("name")
        if not name:
            raise ProviderError(f"Bland persona {agent_id} has no name (PATCH requires it)")
        logger.info(f"Updating Bland persona {agent_id} personality_prompt")
        return self.patch(
            f"/v1/personas/{agent_id}", json={"name": name, "personality_prompt": new_prompt}
        )

    # --- Tests -------------------------------------------------------

    def resolve_target(self, agent_id, hint=None) -> Optional[Dict[str, Any]]:
        if self.config.get("pathway_id"):
            return {"pathway_id": self.config["pathway_id"]}
        if self.config.get("persona_id"):
            return {"persona_id": self.config["persona_id"]}
        if self.target_kind == "agent_v2":
            raise ProviderError(
                "Bland Agent Testing runs against a persona or pathway, not a V2 agent. "
                "Set provider_config.persona_id or provider_config.pathway_id."
            )
        return {"persona_id": agent_id}

    def register_scenarios(self, agent_id: str, spec: CompiledSpec, target: Dict[str, Any]):
        suite = TestSuite(agent_id=agent_id, target=target)
        for scenario in spec.scenarios:
            body: Dict[str, Any] = {
                **target,
                "name": f"nexqa: {scenario.name}",
                "tester_persona_prompt": scenario.user_prompt,
                "max_turns": min(int(self.config.get("max_turns", 20)), 50),
            }
            if scenario.expected_outcome:
                body["description"] = scenario.expected_outcome
            try:
                created = _unwrap(self.post("/v1/agent-testing/scenarios", json=body))
                if not created.get("id"):
                    raise ProviderError("no scenario id returned")
                suite.items.append(SuiteItem(scenario.id, scenario.name, created["id"], scenario))
            except Exception as e:
                logger.warning(f"Skipping scenario '{scenario.name}': {e}")
        return suite

    def start_run(self, suite: TestSuite) -> str:
        """Start every scenario. The handle is "scenario_id=run_id,..."."""
        pairs = []
        for item in suite.items:
            try:
                run = _unwrap(self.post(f"/v1/agent-testing/scenarios/{item.remote_id}/run", json={}))
                if run.get("run_id"):
                    pairs.append(f"{item.remote_id}={run['run_id']}")
            except Exception as e:
                logger.warning(f"Could not start Bland scenario '{item.name}': {e}")
        if not pairs:
            raise ProviderError("No Bland test runs could be started")
        return ",".join(pairs)

    async def wait_for_results(self, suite, handle, poll_interval, timeout) -> SuiteRun:
        pending = dict(p.split("=", 1) for p in handle.split(","))  # scenario -> run
        finished: Dict[str, Dict[str, Any]] = {}
        elapsed = 0
        while pending and elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            for remote_id, run_id in list(pending.items()):
                run = _unwrap(await asyncio.to_thread(self.get, f"/v1/agent-testing/runs/{run_id}"))
                if run.get("status") in RUN_DONE:
                    finished[remote_id] = run
                    del pending[remote_id]
        if pending:
            logger.error(f"{len(pending)} Bland test runs still pending after {timeout}s")
        return SuiteRun([self.normalize_run(suite, rid, run) for rid, run in finished.items()])

    @staticmethod
    def normalize_run(suite: TestSuite, remote_id: str, run: Dict[str, Any]) -> Conversation:
        item = suite.scenario_for(remote_id)
        turns = [
            Turn(role="agent" if m.get("role") == "assistant" else "user", text=m.get("content", ""))
            for m in run.get("chat_history") or []
            if m.get("role") in ("assistant", "user")
        ]
        status = run.get("status", "")
        return Conversation(
            scenario_id=item.scenario_id if item else remote_id,
            turns=turns,
            status={"PASSED": "pass", "FAILED": "fail"}.get(status, "error"),
            platform_passed={"PASSED": True, "FAILED": False}.get(status),
            raw=run,
        )
