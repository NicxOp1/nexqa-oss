"""
Retell AI API Client — V2 Endpoints

CRITICAL: To update a prompt on Retell's NATIVE LLM:
  1. GET /v2/get-agent/{agent_id} → extract response_engine.llm_id
  2. PATCH /update-retell-llm/{llm_id} with { "general_prompt": "new prompt" }

  DO NOT set llm_websocket_url — that's for custom LLM servers ONLY.

Connection pooling: uses requests.Session() singleton to reuse TCP connections
across 100+ API calls per run instead of opening a new connection each time.
"""

import requests
from typing import Dict, Any, List, Optional
from nexqa.storage.config import Config
from nexqa.storage.logger import logger


class RetellClient:
    """Wrapper for Retell AI API — V2 Batch Testing + Agent Management."""

    BASE_URL = "https://api.retellai.com"

    def __init__(self) -> None:
        # The HTTP session is created on first use so importing NEXQA never
        # needs RETELL_API_KEY. Connection-pooled: reuses TCP connections.
        self.__session: Optional[requests.Session] = None

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {Config.RETELL_API_KEY}",
            "Content-Type": "application/json",
        }

    @property
    def _session(self) -> requests.Session:
        if self.__session is None:
            Config.validate(anthropic=False)
            self.__session = requests.Session()
            self.__session.headers.update(self.headers)
        return self.__session

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        """GET with connection pooling."""
        return self._session.get(f"{self.BASE_URL}{path}", **kwargs)

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        """POST with connection pooling."""
        return self._session.post(f"{self.BASE_URL}{path}", **kwargs)

    def _patch(self, path: str, **kwargs: Any) -> requests.Response:
        """PATCH with connection pooling."""
        return self._session.patch(f"{self.BASE_URL}{path}", **kwargs)

    # ─── Agent Endpoints ────────────────────────────────────────────

    def list_agents(self) -> List[Dict[str, Any]]:
        """GET /list-agents — Fetch all available agents."""
        try:
            resp = self._get("/list-agents")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("agents", [])
        except Exception as e:
            logger.error(f"Retell List Agents Error: {e}")
            raise

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """GET /get-agent/{agent_id} — Get agent details."""
        try:
            resp = self._get(f"/get-agent/{agent_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Retell Get Agent Error: {e}")
            raise

    def update_agent(
        self,
        agent_id: str,
        llm_id: Optional[str] = None,
        voice_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        webhook_url: Optional[str] = None,
        webhook_events: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """PATCH /update-agent/{agent_id} — Update agent configuration.

        Use this for agent-level settings (voice, language, webhooks, etc).
        For prompt updates, use update_prompt() instead.
        """
        payload: Dict[str, Any] = {}

        if llm_id:
            payload["response_engine"] = {"type": "retell-llm", "llm_id": llm_id}
        if voice_id:
            payload["voice_id"] = voice_id
        if agent_name:
            payload["agent_name"] = agent_name
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if webhook_events:
            payload["webhook_events"] = webhook_events

        payload.update(kwargs)

        try:
            logger.info(f"Updating Retell agent {agent_id}")
            resp = self._patch(f"/update-agent/{agent_id}", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to update Retell agent {agent_id}: {e}")
            raise

    # ─── LLM Prompt Management ──────────────────────────────────────

    def get_llm_id(self, agent_id: str) -> str:
        """Extract llm_id from an agent's response_engine.

        If agent_id already starts with 'llm_', it is returned as-is.
        """
        if agent_id.startswith("llm_"):
            return agent_id

        agent = self.get_agent(agent_id)
        llm_id = (
            agent.get("response_engine", {}).get("llm_id")
            or agent.get("llm_id")
        )
        if not llm_id:
            raise ValueError(
                f"Could not find llm_id for agent {agent_id}. "
                "Agent may be using a custom LLM (llm_websocket_url), "
                "which is not supported for prompt updates via this method."
            )
        return llm_id

    def get_retell_llm(self, llm_id: str, version: Optional[int] = 0) -> Dict[str, Any]:
        """GET /get-retell-llm/{llm_id} — Get current LLM config including prompt."""
        try:
            url = f"/get-retell-llm/{llm_id}"
            if version is not None:
                url += f"?version={version}"

            resp = self._get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Retell Get LLM Error: {e}")
            raise

    def update_retell_llm(
        self,
        llm_id: str,
        general_prompt: Optional[str] = None,
        general_tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """PATCH /update-retell-llm/{llm_id} — Update LLM prompt/tools."""
        payload = {}
        if general_prompt is not None:
            payload["general_prompt"] = general_prompt
        if general_tools is not None:
            payload["general_tools"] = general_tools
        payload.update(kwargs)

        try:
            resp = self._patch(f"/update-retell-llm/{llm_id}", json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Retell Update LLM Error: {e}")
            raise

    def update_prompt(self, agent_id: str, new_prompt: str) -> Dict[str, Any]:
        """High-level: update an agent's prompt via the correct 2-step flow.

        1. GET agent → extract llm_id
        2. PATCH /update-retell-llm/{llm_id} with { "general_prompt": new_prompt }
        """
        llm_id = self.get_llm_id(agent_id)
        logger.info(f"Updating prompt for agent {agent_id} (llm_id={llm_id})")
        return self.update_retell_llm(llm_id, new_prompt)

    def get_current_prompt(self, agent_id: str) -> str:
        """Get the current general_prompt for an agent."""
        llm_id = self.get_llm_id(agent_id)
        llm_config = self.get_retell_llm(llm_id)
        return llm_config.get("general_prompt", "")

    # ─── Test Case Definition Endpoints ─────────────────────────────

    def create_test_case_definition(
        self,
        name: str,
        user_prompt: str,
        llm_id: str,
        metrics: Optional[List[str]] = None,
        tool_mocks: Optional[Dict[str, str]] = None,
    ) -> str:
        """POST /create-test-case-definition — Register a test scenario.

        Docs: https://docs.retellai.com/api-references/create-test-case-definition
        Required fields: name, response_engine, user_prompt

        tool_mocks: dict of {tool_name: json_output_string} — Retell will return
        these fixed responses when the agent calls the tool during simulation.
        This isolates prompt behavior from webhook availability.
        """
        payload: Dict[str, Any] = {
            "name": name,
            "user_prompt": user_prompt,
            "response_engine": {
                "type": "retell-llm",
                "llm_id": llm_id,
                "version": 0,
            },
            "metrics": metrics or ["correctness"],
        }

        if tool_mocks:
            payload["tool_mocks"] = [
                {
                    "tool_name": tool_name,
                    "input_match_rule": {"type": "any"},
                    "output": output_json,
                    "result": True,
                }
                for tool_name, output_json in tool_mocks.items()
            ]

        try:
            logger.info(f"create_test_case_definition payload: {payload}")
            resp = self._post("/create-test-case-definition", json=payload)
            if not resp.ok:
                with open("retell_error.txt", "w", encoding="utf-8") as _err_f:
                    _err_f.write(resp.text)
                logger.error(f"Retell response body: {resp.text}")
                print(f"RETELL API ERROR: {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            return data.get("test_case_definition_id", "")
        except Exception as e:
            logger.error(f"Failed to create test case definition: {e}")
            raise

    def list_test_case_definitions(self) -> List[Dict[str, Any]]:
        """GET /v2/list-test-case-definitions — List all registered test cases."""
        try:
            resp = self._get("/v2/list-test-case-definitions")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("test_case_definitions", [])
        except Exception as e:
            logger.error(f"Failed to list test case definitions: {e}")
            raise

    # ─── Agent + LLM Creation ────────────────────────────────────────

    def create_retell_llm(
        self,
        general_prompt: str,
        begin_message: Optional[str] = None,
        model: str = "gpt-4.1",
        model_temperature: float = 0,
        general_tools: Optional[List[Dict[str, Any]]] = None,
        states: Optional[List[Dict[str, Any]]] = None,
        starting_state: Optional[str] = None,
        start_speaker: str = "agent",
        default_dynamic_variables: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """POST /create-retell-llm — Create a Retell LLM Response Engine."""
        payload: Dict[str, Any] = {
            "model": model,
            "model_temperature": model_temperature,
            "general_prompt": general_prompt,
            "start_speaker": start_speaker,
        }

        if begin_message is not None:
            payload["begin_message"] = begin_message
        if general_tools:
            payload["general_tools"] = general_tools
        if states:
            payload["states"] = states
        if starting_state:
            payload["starting_state"] = starting_state
        if default_dynamic_variables:
            payload["default_dynamic_variables"] = default_dynamic_variables

        payload.update(kwargs)

        try:
            logger.info(
                f"Creating Retell LLM (model={model}, "
                f"tools={len(general_tools) if general_tools else 0})"
            )
            resp = self._post("/create-retell-llm", json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Retell LLM created: llm_id={data.get('llm_id')}")
            return data
        except Exception as e:
            logger.error(f"Failed to create Retell LLM: {e}")
            raise

    def create_agent(
        self,
        llm_id: str,
        voice_id: str,
        agent_name: Optional[str] = None,
        language: str = "en-US",
        voice_model: Optional[str] = None,
        voice_speed: float = 1,
        voice_temperature: float = 1,
        responsiveness: float = 1,
        interruption_sensitivity: float = 1,
        enable_backchannel: bool = False,
        ambient_sound: Optional[str] = None,
        normalize_for_speech: bool = True,
        boosted_keywords: Optional[List[str]] = None,
        stt_mode: str = "fast",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """POST /v2/create-agent — Create a voice agent shell."""
        payload: Dict[str, Any] = {
            "response_engine": {
                "type": "retell-llm",
                "llm_id": llm_id,
            },
            "voice_id": voice_id,
            "language": language,
            "voice_speed": voice_speed,
            "voice_temperature": voice_temperature,
            "responsiveness": responsiveness,
            "interruption_sensitivity": interruption_sensitivity,
            "enable_backchannel": enable_backchannel,
            "normalize_for_speech": normalize_for_speech,
            "stt_mode": stt_mode,
        }

        if agent_name:
            payload["agent_name"] = agent_name
        if voice_model:
            payload["voice_model"] = voice_model
        if ambient_sound:
            payload["ambient_sound"] = ambient_sound
        if boosted_keywords:
            payload["boosted_keywords"] = boosted_keywords

        payload.update(kwargs)

        try:
            logger.info(
                f"Creating Retell agent (voice={voice_id}, llm={llm_id})"
            )
            resp = self._post("/create-agent", json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Retell agent created: agent_id={data.get('agent_id')}")
            return data
        except Exception as e:
            logger.error(f"Failed to create Retell agent: {e}")
            raise

    def create_full_agent(
        self,
        general_prompt: str,
        voice_id: str,
        agent_name: Optional[str] = None,
        begin_message: Optional[str] = None,
        model: str = "gpt-4.1",
        general_tools: Optional[List[Dict[str, Any]]] = None,
        **agent_kwargs: Any,
    ) -> Dict[str, Any]:
        """Convenience: create LLM + Agent in one call."""
        llm_data = self.create_retell_llm(
            general_prompt=general_prompt,
            begin_message=begin_message,
            model=model,
            general_tools=general_tools,
        )
        llm_id = llm_data["llm_id"]

        agent_data = self.create_agent(
            llm_id=llm_id,
            voice_id=voice_id,
            agent_name=agent_name,
            **agent_kwargs,
        )

        return {
            "llm_id": llm_id,
            "agent_id": agent_data.get("agent_id"),
            "llm_data": llm_data,
            "agent_data": agent_data,
        }

    def list_phone_numbers(self) -> List[Dict[str, Any]]:
        """GET /list-phone-numbers — Fetch all purchased phone numbers."""
        try:
            resp = self._get("/list-phone-numbers")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("phone_numbers", [])
        except Exception as e:
            logger.error(f"Failed to list phone numbers: {e}")
            raise

    # ─── Custom Tools Endpoints ─────────────────────────────────────────

    def create_custom_tool(
        self,
        name: str,
        description: str,
        url: str,
        parameters: Optional[Dict[str, Any]] = None,
        speak_during_execution: bool = False,
        speak_after_execution: bool = False,
        custom_headers: Optional[Dict[str, str]] = None,
        timeout_ms: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """POST /create-custom-tool — Create a new custom tool. Returns tool_id."""
        payload: Dict[str, Any] = {
            "type": "custom",
            "name": name,
            "description": description,
            "url": url,
        }

        if parameters:
            payload["parameters"] = parameters
        if speak_during_execution:
            payload["speak_during_execution"] = speak_during_execution
        if speak_after_execution:
            payload["speak_after_execution"] = speak_after_execution
        if custom_headers:
            payload["custom_headers"] = custom_headers
        if timeout_ms:
            payload["timeout_ms"] = timeout_ms

        payload.update(kwargs)

        try:
            logger.info(f"Creating Custom Tool: {name}")
            resp = self._post("/create-retell-custom-tool", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("tool_id", "")
        except Exception as e:
            logger.error(f"Failed to create Custom Tool {name}: {e}")
            raise

    def update_phone_number(self, phone_number: str, agent_id: str) -> Dict[str, Any]:
        """PATCH /update-phone-number/{phone_number} — Assign agent to number."""
        try:
            resp = self._patch(
                f"/update-phone-number/{phone_number}",
                json={"inbound_agent_id": agent_id},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to update phone number {phone_number}: {e}")
            raise

    # ─── Batch Testing ────────────────────────────────────────────────

    def create_batch_test(
        self,
        test_case_ids: List[str],
        response_engine: Dict[str, Any],
    ) -> str:
        """POST /create-batch-test — Start a batch simulation.

        Docs: https://docs.retellai.com/api-references/create-batch-test
        Returns: test_case_batch_job_id
        """
        payload = {
            "test_case_definition_ids": test_case_ids,
            "response_engine": response_engine,
        }

        try:
            resp = self._post("/create-batch-test", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("test_case_batch_job_id", "")
        except Exception as e:
            logger.error(f"Failed to start batch test: {e}")
            raise

    def get_batch_test(self, batch_test_id: str) -> Dict[str, Any]:
        """GET /get-batch-test/{id} — Poll status & summary counts.

        Response: { status: 'in_progress'|'complete', pass_count, fail_count,
                    error_count, total_count }
        NOTE: does NOT contain individual results — use list_test_runs() for that.
        """
        try:
            resp = self._get(f"/get-batch-test/{batch_test_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get batch test {batch_test_id}: {e}")
            raise

    def list_test_runs(self, batch_test_id: str) -> List[Dict[str, Any]]:
        """GET /list-test-runs/{batch_test_id} — Get individual results per test case."""
        try:
            resp = self._get(f"/list-test-runs/{batch_test_id}")
            if not resp.ok:
                logger.error(f"list_test_runs error body: {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("items", [])
        except Exception as e:
            logger.error(f"Failed to list test runs for {batch_test_id}: {e}")
            raise

    def list_batch_tests(self, llm_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """GET /list-batch-tests — List recent batch test jobs for a given LLM."""
        try:
            resp = self._get(
                "/list-batch-tests",
                params={"type": "retell-llm", "llm_id": llm_id},
            )
            if not resp.ok:
                logger.error(f"list_batch_tests error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            batches = data if isinstance(data, list) else data.get("items", [])
            completed = [b for b in batches if b.get("status") == "complete"]
            completed.sort(key=lambda b: b.get("creation_timestamp", 0), reverse=True)
            return completed[:limit]
        except Exception as e:
            logger.error(f"Failed to list batch tests for llm_id={llm_id}: {e}")
            raise


# Module-level singleton
retell_client = RetellClient()
