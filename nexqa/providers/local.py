"""
Self-hosted agents: the prompt lives in a file you own.

For frameworks you run yourself (LiveKit Agents, Pipecat, or your own code)
there is no platform API to read or write the prompt. NEXQA reads it from
`provider_config.prompt_file`, writes rewrites back to that file, and drives
a text conversation through a harness:

- `custom` (this module): you give NEXQA a reply function,
  `provider_config.respond: "package.module:function"`, called as
  `respond(system_prompt, messages)` where `messages` is a list of
  {"role": "user"|"assistant", "content": str}. It returns the agent's reply
  as a string, or a dict {"text": str, "tool_calls": [...], "ended": bool}.
  It may be sync or async.
- `pipecat` (pipecat.py) and `livekit` (livekit.py) build on this.

The `agent_id` you pass to NEXQA is only a label for logs and prompt history.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nexqa.models.rule_models import TestScenario
from nexqa.providers.base import ProviderError, ToolCall
from nexqa.providers.simulator import AgentReply, SimulatedCallerProvider, TextSession
from nexqa.storage.logger import logger


def load_object(ref: Any) -> Any:
    """Import "package.module:attr" (or "package.module.attr").

    A callable is returned as is, so Python callers can pass functions directly.
    """
    if callable(ref):
        return ref
    if not isinstance(ref, str):
        raise ProviderError(f"Expected 'module:attribute' or a callable, got {ref!r}")
    if ":" in ref:
        module_name, attr = ref.split(":", 1)
    else:
        module_name, _, attr = ref.rpartition(".")
    if not module_name or not attr:
        raise ProviderError(f"Expected 'module:attribute', got {ref!r}")
    module = importlib.import_module(module_name)
    obj = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def to_tool_calls(raw: Any) -> List[ToolCall]:
    calls = []
    for tc in raw or []:
        if isinstance(tc, ToolCall):
            calls.append(tc)
        elif isinstance(tc, dict):
            calls.append(ToolCall(name=tc.get("name", "unknown"),
                                  arguments=tc.get("arguments", {}),
                                  result=tc.get("result")))
    return calls


class PromptFileProvider(SimulatedCallerProvider):
    """Prompt read from / written to `provider_config.prompt_file`."""

    @property
    def prompt_path(self) -> Path:
        path = self.config.get("prompt_file")
        if not path:
            raise ProviderError(f"provider '{self.name}' needs provider_config.prompt_file")
        return Path(path)

    def get_prompt(self, agent_id: str) -> str:
        path = self.prompt_path
        if not path.exists():
            raise ProviderError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8")

    def update_prompt(self, agent_id: str, new_prompt: str) -> Any:
        path = self.prompt_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_prompt, encoding="utf-8")
        logger.info(f"Wrote new prompt for '{agent_id}' to {path}")
        return {"prompt_file": str(path)}

    def resolve_target(self, agent_id, hint=None):
        self.get_prompt(agent_id)  # fail fast if the file is missing
        return {"agent_id": agent_id, "prompt_file": str(self.prompt_path)}


class CustomHarnessProvider(PromptFileProvider):
    name = "custom"
    display_name = "Custom (your reply function)"
    maturity = "tested-offline"
    test_mode = "your respond() function + simulated caller"
    docs_url = ""

    respond_fn: Optional[Callable[..., Any]] = None  # tests may set this directly

    def responder(self) -> Callable[..., Any]:
        if self.respond_fn is not None:
            return self.respond_fn
        ref = self.config.get("respond")
        if not ref:
            raise ProviderError(f"provider '{self.name}' needs provider_config.respond")
        self.respond_fn = load_object(ref)
        return self.respond_fn

    def open_session(self, agent_id: str, scenario: TestScenario) -> TextSession:
        return CallableSession(self.responder(), self.get_prompt(agent_id))


class CallableSession(TextSession):
    def __init__(self, respond: Callable[..., Any], system_prompt: str) -> None:
        self.respond = respond
        self.system_prompt = system_prompt
        self.messages: List[Dict[str, str]] = []

    async def start(self) -> Optional[str]:
        return None

    async def send(self, text: str) -> AgentReply:
        self.messages.append({"role": "user", "content": text})
        out = self.respond(self.system_prompt, list(self.messages))
        if inspect.isawaitable(out):
            out = await out
        if isinstance(out, dict):
            reply = AgentReply(text=str(out.get("text") or ""),
                               tool_calls=to_tool_calls(out.get("tool_calls")),
                               ended=bool(out.get("ended")))
        else:
            reply = AgentReply(text=str(out or ""))
        self.messages.append({"role": "assistant", "content": reply.text})
        return reply
