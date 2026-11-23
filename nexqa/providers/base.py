"""
Provider adapter contract.

NEXQA's scoring, genes, linter, guardrails and voice corpus never talk to a
voice platform directly. They talk to a `VoiceProvider`, which does four jobs:

1. Read the agent's current prompt (`get_prompt`).
2. Replace ONLY the prompt, keeping every other agent setting (`update_prompt`).
3. Run the spec's scenarios as test conversations
   (`resolve_target` -> `register_scenarios` -> `start_run` -> `wait_for_results`).
4. Return each test conversation as a normalized `Conversation`
   (turns, tool calls, timings, end reason), whatever the platform's own shape.

Each adapter module cites the official docs it was written from in its
docstring, and declares its `maturity`:

- "verified-live":  used against the real platform.
- "tested-offline": written from the official docs and covered by mocked-HTTP
                    tests, but not yet run against a live account.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional

import requests

from nexqa.models.rule_models import CompiledSpec, TestScenario
from nexqa.models.scenario_models import SimulationResult
from nexqa.storage.logger import logger


class ProviderError(RuntimeError):
    """A provider could not do what the engine asked (bad config, API error)."""


# --- Normalized conversation -------------------------------------------


@dataclass
class Turn:
    """One spoken (or typed) turn. `role` is "agent" or "user"."""

    role: str
    text: str
    start_s: Optional[float] = None
    end_s: Optional[float] = None


@dataclass
class ToolCall:
    name: str
    arguments: Any = field(default_factory=dict)
    result: Any = None
    call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        # Exactly the keys the deterministic validator reads.
        return {"name": self.name, "arguments": self.arguments, "result": self.result}


@dataclass
class Conversation:
    """A finished test conversation in a platform-neutral shape."""

    scenario_id: str
    turns: List[Turn] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    status: str = "completed"
    end_reason: Optional[str] = None
    duration_s: Optional[float] = None
    # The platform's own verdict, when it has one (informational only:
    # NEXQA always scores the conversation itself).
    platform_passed: Optional[bool] = None
    platform_notes: Optional[str] = None
    # Used only when the platform returned no structured turns.
    fallback_transcript: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def transcript_text(self) -> str:
        lines = []
        for turn in self.turns:
            if not turn.text:
                continue
            label = "Agent" if turn.role == "agent" else "User"
            lines.append(f"{label}: {turn.text}\n")
        text = "".join(lines)
        return text if text else (self.fallback_transcript or "")

    def to_simulation_result(self) -> SimulationResult:
        return SimulationResult(
            scenario_id=self.scenario_id,
            transcript=self.transcript_text().strip(),
            tool_calls=[tc.to_dict() for tc in self.tool_calls],
            metadata=self.raw,
            status=self.status,
        )


# --- Test suite bookkeeping ---------------------------------------------


@dataclass
class SuiteItem:
    scenario_id: str
    name: str
    remote_id: str  # the platform's id for this test (or the scenario id)
    scenario: Optional[TestScenario] = None


@dataclass
class TestSuite:
    __test__ = False  # not a pytest class

    agent_id: str
    target: Dict[str, Any]
    items: List[SuiteItem] = field(default_factory=list)

    @property
    def remote_ids(self) -> List[str]:
        return [i.remote_id for i in self.items]

    def scenario_for(self, remote_id: str) -> Optional[SuiteItem]:
        for item in self.items:
            if item.remote_id == remote_id:
                return item
        return None


@dataclass
class SuiteRun:
    conversations: List[Conversation] = field(default_factory=list)
    billed_minutes: float = 0.0


def scenario_metrics(scenario: TestScenario) -> List[str]:
    """Success criteria for a scenario, as plain sentences (never empty)."""
    metrics: List[str] = []
    if scenario.expected_outcome:
        metrics.append(scenario.expected_outcome)
    metrics.extend(scenario.critical_checkpoints)
    if not metrics:
        metrics = [f"Agent handles '{scenario.name}' correctly and professionally."]
    return metrics


# --- Provider interface -------------------------------------------------


class VoiceProvider(ABC):
    """Base class for every platform adapter."""

    name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    maturity: ClassVar[str] = "tested-offline"
    test_mode: ClassVar[str] = ""  # short description for the provider matrix
    docs_url: ClassVar[str] = ""
    api_key_env: ClassVar[Optional[str]] = None

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = dict(config or {})

    # Prompt management
    @abstractmethod
    def get_prompt(self, agent_id: str) -> str:
        """Return the agent's current system prompt ("" if it has none)."""

    @abstractmethod
    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        """Replace the system prompt. Every other agent setting must survive."""

    # Test runs
    def resolve_target(
        self, agent_id: str, hint: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Return what the test runner needs to address the agent.

        Raise on API errors; return None when the agent cannot be tested.
        """
        return hint or {"agent_id": agent_id}

    @abstractmethod
    def register_scenarios(
        self, agent_id: str, spec: CompiledSpec, target: Dict[str, Any]
    ) -> TestSuite:
        """Create the platform-side tests (if any). Skip, don't raise, per scenario."""

    @abstractmethod
    def start_run(self, suite: TestSuite) -> str:
        """Start one pass over the suite and return a run handle."""

    @abstractmethod
    async def wait_for_results(
        self, suite: TestSuite, handle: str, poll_interval: int, timeout: int
    ) -> SuiteRun:
        """Wait for the run to finish and return normalized conversations."""

    # Helpers
    @classmethod
    def describe(cls) -> Dict[str, str]:
        return {
            "name": cls.name,
            "display_name": cls.display_name or cls.name,
            "maturity": cls.maturity,
            "test_mode": cls.test_mode,
            "docs_url": cls.docs_url,
            "api_key_env": cls.api_key_env or "",
        }


# --- HTTP base for hosted platforms -------------------------------------


class HTTPProvider(VoiceProvider):
    """Shared plumbing for REST platforms: lazy session, auth, GET retries.

    Tests pass a fake `session`; nothing here opens a connection on import.
    """

    base_url: ClassVar[str] = ""
    retry_statuses: ClassVar[tuple] = (429, 502, 503, 504)

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        session: Optional[Any] = None,
        api_key: Optional[str] = None,
    ) -> None:
        super().__init__(config)
        self._session = session
        self._api_key = api_key
        self._base = str(self.config.get("base_url") or self.base_url).rstrip("/")

    @property
    def api_key(self) -> str:
        key = self._api_key or (os.getenv(self.api_key_env, "") if self.api_key_env else "")
        if not key:
            raise ProviderError(f"{self.api_key_env} is not set (needed for provider '{self.name}')")
        return key

    def auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @property
    def session(self) -> Any:
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send a request and return the decoded JSON body (or None).

        Only GETs are retried, so a retry can never create a duplicate test.
        """
        url = path if path.startswith("http") else f"{self._base}{path}"
        headers = {"Content-Type": "application/json", **self.auth_headers()}
        headers.update(kwargs.pop("headers", {}) or {})
        attempts = 3 if method.upper() == "GET" else 1
        for attempt in range(attempts):
            resp = self.session.request(method, url, headers=headers, timeout=60, **kwargs)
            if resp.status_code in self.retry_statuses and attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        if not resp.ok:
            body = (resp.text or "")[:500]
            logger.error(f"{self.name} {method} {path} -> {resp.status_code}: {body}")
            raise ProviderError(f"{self.name} {method} {path} failed ({resp.status_code}): {body}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)
