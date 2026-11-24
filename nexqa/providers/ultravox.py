"""
Ultravox adapter.

Prompt
  `callTemplate.systemPrompt` of the agent (GET /api/agents/{id}). Updated
  with PATCH /api/agents/{id} and body {"callTemplate": {"systemPrompt": ...}}.
  The endpoint is documented as "Allows partial modifications to the agent",
  and the agents guide shows exactly this partial body ("Only fields you want
  to change"). Agent changes only affect new calls.

Tests
  Ultravox has no testing API (its testing page is "under construction"), so
  Claude plays the caller over a TEXT-ONLY call:
  POST /api/agents/{id}/calls with a `serverWebSocket` medium,
  `mediumRestriction.allowedMediums = ["MESSAGE_MEDIUM_TEXT"]` and
  `initialOutputMedium = "MESSAGE_MEDIUM_TEXT"`. NEXQA joins `joinUrl`, sends
  `user_text_message` data messages, reads `transcript` messages
  (role "agent", `final` true), and ends with `hang_up`. It then reads the
  authoritative record from GET /api/calls/{id}/messages (tool calls and
  results included) and GET /api/calls/{id} (`endReason`, `billedDuration`).

Needs the `websockets` package: pip install "nexqa[ultravox]".

Docs:
- https://docs.ultravox.ai/api-reference/introduction.md
- https://docs.ultravox.ai/api-reference/agents/agents-get.md
- https://docs.ultravox.ai/api-reference/agents/agents-patch.md
- https://docs.ultravox.ai/agents/building-and-editing-agents.md
- https://docs.ultravox.ai/api-reference/agents/agents-calls-post.md
- https://docs.ultravox.ai/agents/making-calls.md
- https://docs.ultravox.ai/apps/websockets.md
- https://docs.ultravox.ai/apps/datamessages.md
- https://docs.ultravox.ai/api-reference/calls/calls-messages-list.md
- https://docs.ultravox.ai/api-reference/calls/calls-get.md
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional

from nexqa.models.rule_models import TestScenario
from nexqa.providers.base import HTTPProvider, ProviderError, ToolCall, Turn
from nexqa.providers.simulator import (
    AgentReply,
    SessionOutcome,
    SimulatedCallerProvider,
    TextSession,
)
from nexqa.storage.logger import logger


def parse_seconds(value: Any) -> Optional[float]:
    """"1.5s" -> 1.5 (the API returns durations as strings with an "s")."""
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("s"))
    except ValueError:
        return None


def messages_to_turns(messages: List[Dict[str, Any]]) -> tuple:
    turns: List[Turn] = []
    calls: Dict[str, ToolCall] = {}
    ordered: List[ToolCall] = []
    for msg in messages:
        role = msg.get("role")
        span = msg.get("timespan") or {}
        if role in ("MESSAGE_ROLE_AGENT", "MESSAGE_ROLE_USER") and msg.get("text"):
            turns.append(Turn(
                role="agent" if role == "MESSAGE_ROLE_AGENT" else "user",
                text=msg["text"],
                start_s=parse_seconds(span.get("start")),
                end_s=parse_seconds(span.get("end")),
            ))
        elif role == "MESSAGE_ROLE_TOOL_CALL":
            try:
                args = json.loads(msg.get("text") or "{}")
            except ValueError:
                args = msg.get("text")
            call = ToolCall(name=msg.get("toolName", "unknown"), arguments=args,
                            call_id=msg.get("invocationId"))
            ordered.append(call)
            if call.call_id:
                calls[call.call_id] = call
        elif role == "MESSAGE_ROLE_TOOL_RESULT":
            call = calls.get(msg.get("invocationId") or "")
            if call is not None:
                call.result = msg.get("text")
            else:
                ordered.append(ToolCall(name=msg.get("toolName", "unknown"), result=msg.get("text")))
    return turns, ordered


class UltravoxProvider(SimulatedCallerProvider, HTTPProvider):
    name = "ultravox"
    display_name = "Ultravox"
    maturity = "tested-offline"
    test_mode = "text-only call over WebSocket + simulated caller"
    docs_url = "https://docs.ultravox.ai/apps/datamessages.md"
    api_key_env = "ULTRAVOX_API_KEY"
    base_url = "https://api.ultravox.ai/api"

    # Tests replace this with a fake; by default it is websockets' sync client.
    ws_connect: Optional[Callable[..., Any]] = None

    def auth_headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key}

    # --- Prompt ------------------------------------------------------

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        return self.get(f"/agents/{agent_id}") or {}

    def get_prompt(self, agent_id: str) -> str:
        return (self.get_agent(agent_id).get("callTemplate") or {}).get("systemPrompt") or ""

    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        logger.info(f"Updating Ultravox agent {agent_id} systemPrompt (partial PATCH)")
        return self.patch(f"/agents/{agent_id}", json={"callTemplate": {"systemPrompt": new_prompt}})

    def resolve_target(self, agent_id, hint=None):
        self.get_agent(agent_id)
        return {"agent_id": agent_id}

    # --- Text session ------------------------------------------------

    def connector(self) -> Callable[..., Any]:
        if self.ws_connect is not None:
            return self.ws_connect
        try:
            from websockets.sync.client import connect
        except ImportError as e:  # pragma: no cover - depends on the extra
            raise ProviderError('Ultravox needs websockets: pip install "nexqa[ultravox]"') from e
        return connect

    def open_session(self, agent_id: str, scenario: TestScenario) -> TextSession:
        return UltravoxTextSession(self, agent_id)


class UltravoxTextSession(TextSession):
    def __init__(self, provider: UltravoxProvider, agent_id: str) -> None:
        self.p = provider
        self.agent_id = agent_id
        self.call_id: Optional[str] = None
        self.ws: Any = None
        self.reply_timeout = float(provider.config.get("reply_timeout_s", 30))
        self.greeting_timeout = float(provider.config.get("greeting_timeout_s", 8))
        self.agent_hung_up = False

    # Blocking helpers (run in a worker thread)
    def _start(self) -> Optional[str]:
        body: Dict[str, Any] = {
            "medium": {"serverWebSocket": {"inputSampleRate": 48000, "outputSampleRate": 48000}},
            "mediumRestriction": {"allowedMediums": ["MESSAGE_MEDIUM_TEXT"]},
            "initialOutputMedium": "MESSAGE_MEDIUM_TEXT",
        }
        if self.p.config.get("max_duration"):
            body["maxDuration"] = self.p.config["max_duration"]
        call = self.p.post(f"/agents/{self.agent_id}/calls", json=body) or {}
        self.call_id, join_url = call.get("callId"), call.get("joinUrl")
        if not join_url:
            raise ProviderError("Ultravox did not return a joinUrl")
        self.ws = self.p.connector()(join_url)
        return self._read_agent_turn(self.greeting_timeout) or None

    def _read_agent_turn(self, timeout: float) -> str:
        """Read data messages until the agent finishes one turn (or timeout)."""
        deadline = time.monotonic() + timeout
        text, deltas = "", []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return text or "".join(deltas)
            try:
                frame = self.ws.recv(timeout=remaining)
            except TimeoutError:
                return text or "".join(deltas)
            except Exception:  # connection closed: the agent hung up
                self.agent_hung_up = True
                return text or "".join(deltas)
            if isinstance(frame, bytes):
                continue  # audio frames; a text-only call should not send any
            try:
                msg = json.loads(frame)
            except ValueError:
                continue
            if msg.get("type") != "transcript" or msg.get("role") != "agent":
                continue
            if msg.get("text") is not None:
                text = msg["text"]
            elif msg.get("delta"):
                deltas.append(msg["delta"])
            if msg.get("final"):
                return text or "".join(deltas)

    def _send(self, text: str) -> AgentReply:
        self.ws.send(json.dumps({"type": "user_text_message", "text": text}))
        reply = self._read_agent_turn(self.reply_timeout)
        return AgentReply(text=reply, ended=self.agent_hung_up)

    def _close(self) -> SessionOutcome:
        if self.ws is not None:
            try:
                self.ws.send(json.dumps({"type": "hang_up"}))
            except Exception:
                pass
            try:
                self.ws.close()
            except Exception:
                pass
        if not self.call_id:
            return SessionOutcome()
        try:
            messages: List[Dict[str, Any]] = []
            page = self.p.get(f"/calls/{self.call_id}/messages") or {}
            messages.extend(page.get("results") or [])
            while page.get("next"):
                page = self.p.get(page["next"]) or {}
                messages.extend(page.get("results") or [])
            call = self.p.get(f"/calls/{self.call_id}") or {}
        except Exception as e:
            logger.warning(f"Ultravox call record unavailable, using local transcript: {e}")
            return SessionOutcome()
        turns, calls = messages_to_turns(messages)
        billed = parse_seconds(call.get("billedDuration"))
        return SessionOutcome(
            turns=turns or None,
            tool_calls=calls,
            end_reason=call.get("endReason"),
            duration_s=billed,
            billed_minutes=(billed or 0.0) / 60.0,
            raw={"call": call, "messages": messages},
        )

    # Async interface
    async def start(self) -> Optional[str]:
        return await asyncio.to_thread(self._start)

    async def send(self, text: str) -> AgentReply:
        return await asyncio.to_thread(self._send, text)

    async def close(self) -> SessionOutcome:
        return await asyncio.to_thread(self._close)
