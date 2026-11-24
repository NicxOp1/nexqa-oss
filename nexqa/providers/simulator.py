"""
Simulated caller, for platforms without a native test runner.

When a platform has no API to run a scripted test call, NEXQA plays the caller
itself: Claude reads the scenario's `user_prompt` (the persona and goal), and
NEXQA exchanges text turns with the agent through the platform's text channel
(a chat API, a text-only call, or an in-process framework session).

This tests the prompt and the tool logic, not audio (STT/TTS, latency,
interruptions). The README says so for every adapter that uses it.
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from nexqa.models.rule_models import CompiledSpec, TestScenario
from nexqa.providers.base import (
    Conversation,
    SuiteItem,
    SuiteRun,
    TestSuite,
    ToolCall,
    Turn,
    VoiceProvider,
)
from nexqa.storage.config import Config
from nexqa.storage.logger import logger

END_TOKEN = "[END_CALL]"

CALLER_SYSTEM_PROMPT = """You are role-playing a phone CALLER in a QA test of a voice AI agent.

Your persona and goal:
{persona}

Rules:
- Write only what the caller says next, as one short spoken turn. No stage directions,
  no quotes, no labels, no markdown.
- Stay in character. Do not help the agent, and do not reveal that this is a test.
- When your goal is reached, the agent ends the call, or the conversation is clearly
  over, reply with exactly {end_token}"""


class SimulatedCaller:
    """Generates the caller's next line with Claude (or any `complete()` client)."""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    @property
    def llm(self) -> Any:
        if self._llm is None:
            from nexqa.integrations.claude_client import claude_client

            self._llm = claude_client
        return self._llm

    def next_line(self, persona: str, turns: List[Turn]) -> Optional[str]:
        """Return the caller's next utterance, or None to hang up."""
        history = "\n".join(
            f"{'Agent' if t.role == 'agent' else 'Caller'}: {t.text}" for t in turns if t.text
        )
        user_prompt = (
            f"Conversation so far:\n{history or '(the call just connected)'}\n\n"
            "Your next line as the caller:"
        )
        system = CALLER_SYSTEM_PROMPT.format(persona=persona, end_token=END_TOKEN)
        text = self.llm.complete(
            system, user_prompt, effort=Config.SIMULATOR_EFFORT, model=Config.SIMULATOR_MODEL
        )
        text = (text or "").strip()
        if not text or END_TOKEN in text:
            return None
        return text


@dataclass
class AgentReply:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    ended: bool = False  # the agent hung up


@dataclass
class SessionOutcome:
    """What a session reports after it closes (platform transcript if it has one)."""

    turns: Optional[List[Turn]] = None
    tool_calls: Optional[List[ToolCall]] = None
    end_reason: Optional[str] = None
    duration_s: Optional[float] = None
    billed_minutes: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


class TextSession(ABC):
    """One text conversation with the agent under test."""

    @abstractmethod
    async def start(self) -> Optional[str]:
        """Open the conversation. Return the agent's greeting, if it speaks first."""

    @abstractmethod
    async def send(self, text: str) -> AgentReply:
        """Send one caller turn and return the agent's reply."""

    async def close(self) -> SessionOutcome:
        """End the conversation and return the platform's own record of it."""
        return SessionOutcome()


class SimulatedCallerProvider(VoiceProvider):
    """Runs every scenario as a Claude-driven text conversation."""

    default_max_turns: int = 12
    _caller: Any = None

    @property
    def caller(self) -> Any:
        """The simulated caller (Claude by default). Tests assign a fake."""
        if self._caller is None:
            self._caller = SimulatedCaller()
        return self._caller

    @caller.setter
    def caller(self, value: Any) -> None:
        self._caller = value

    @abstractmethod
    def open_session(self, agent_id: str, scenario: TestScenario) -> TextSession:
        """Create (but do not start) a text session for one scenario."""

    # The scenarios stay local: there is nothing to register on the platform.
    def register_scenarios(
        self, agent_id: str, spec: CompiledSpec, target: Dict[str, Any]
    ) -> TestSuite:
        items = [
            SuiteItem(scenario_id=s.id, name=s.name, remote_id=s.id, scenario=s)
            for s in spec.scenarios
        ]
        return TestSuite(agent_id=agent_id, target=target, items=items)

    def start_run(self, suite: TestSuite) -> str:
        return f"sim_{uuid.uuid4().hex[:12]}"

    async def wait_for_results(
        self, suite: TestSuite, handle: str, poll_interval: int, timeout: int
    ) -> SuiteRun:
        run = SuiteRun()
        for item in suite.items:
            conv, minutes = await self.simulate(suite.agent_id, item)
            run.conversations.append(conv)
            run.billed_minutes += minutes
        return run

    async def simulate(self, agent_id: str, item: SuiteItem) -> tuple:
        """Run one scenario. Errors become an "error" conversation, not a crash."""
        scenario = item.scenario
        assert scenario is not None
        max_turns = int(self.config.get("max_turns", self.default_max_turns))
        turns: List[Turn] = []
        tool_calls: List[ToolCall] = []
        end_reason = "max_turns"
        session = self.open_session(agent_id, scenario)
        try:
            greeting = await session.start()
            if greeting:
                turns.append(Turn(role="agent", text=greeting))
            for _ in range(max_turns):
                line = await asyncio.to_thread(self.caller.next_line, scenario.user_prompt, turns)
                if line is None:
                    end_reason = "caller_hangup"
                    break
                turns.append(Turn(role="user", text=line))
                reply = await session.send(line)
                tool_calls.extend(reply.tool_calls)
                if reply.text:
                    turns.append(Turn(role="agent", text=reply.text))
                if reply.ended:
                    end_reason = "agent_hangup"
                    break
        except Exception as e:  # one broken scenario must not stop the run
            logger.error(f"[{self.name}] scenario '{scenario.name}' failed: {e}")
            try:
                await session.close()
            except Exception:
                pass
            return (
                Conversation(
                    scenario_id=scenario.id,
                    turns=turns,
                    tool_calls=tool_calls,
                    status="error",
                    end_reason=f"error: {e}",
                ),
                0.0,
            )

        outcome = await session.close()
        conv = Conversation(
            scenario_id=scenario.id,
            turns=outcome.turns if outcome.turns else turns,
            tool_calls=outcome.tool_calls if outcome.tool_calls is not None else tool_calls,
            status="completed",
            end_reason=outcome.end_reason or end_reason,
            duration_s=outcome.duration_s,
            raw=outcome.raw,
        )
        return conv, outcome.billed_minutes
