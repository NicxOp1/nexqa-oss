"""
LiveKit Agents adapter (in-process text mode).

Uses LiveKit's documented text-mode test API: an `AgentSession` with an LLM,
`await session.start(agent)`, then `result = await session.run(user_input=...)`
for every caller turn. No room, no audio. Claude plays the caller.

provider_config:
  prompt_file: prompts/agent_instructions.txt
  agent_factory: my_agent.agent:build_agent   # build_agent(instructions: str) -> Agent
  llm: openai/gpt-4.1-mini                    # anything AgentSession(llm=...) accepts

`agent_factory` must build your Agent with the given instructions
(e.g. `Agent(instructions=instructions, tools=[...])`), so the prompt NEXQA
rewrites is the one under test. Keep your production entrypoint reading the
same `prompt_file`.

Events are read from `RunResult.events`: messages (`item.role`,
`item.content`), function calls (`item.name`, `item.arguments`) and function
call outputs (`item.output`, `item.call_id`), as shown in the testing guide.

Needs `livekit-agents` (and the plugin for your LLM) installed in the same
environment as NEXQA.

Docs:
- https://docs.livekit.io/testing/unit-tests.md
- https://docs.livekit.io/agents/logic/sessions.md
- https://docs.livekit.io/agents/logic/agents-handoffs.md
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from nexqa.models.rule_models import TestScenario
from nexqa.providers.base import ProviderError, ToolCall
from nexqa.providers.local import PromptFileProvider, load_object
from nexqa.providers.simulator import AgentReply, SessionOutcome, TextSession


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return " ".join(_text(c) for c in content if isinstance(c, str) or hasattr(c, "text"))
    return str(getattr(content, "text", content))


class LiveKitProvider(PromptFileProvider):
    name = "livekit"
    display_name = "LiveKit Agents"
    maturity = "tested-offline"
    test_mode = "in-process AgentSession text mode + simulated caller"
    docs_url = "https://docs.livekit.io/testing/unit-tests.md"

    # Tests replace this with a fake AgentSession class.
    session_cls: Optional[Callable[..., Any]] = None

    def session_factory(self) -> Callable[..., Any]:
        if self.session_cls is not None:
            return self.session_cls
        try:
            from livekit.agents import AgentSession
        except ImportError as e:  # pragma: no cover - optional dependency
            raise ProviderError("provider 'livekit' needs livekit-agents installed") from e
        return AgentSession

    def agent_factory(self) -> Callable[[str], Any]:
        ref = self.config.get("agent_factory")
        if not ref:
            raise ProviderError("provider 'livekit' needs provider_config.agent_factory")
        return load_object(ref)

    def open_session(self, agent_id: str, scenario: TestScenario) -> TextSession:
        llm = self.config.get("llm")
        if not llm:
            raise ProviderError("provider 'livekit' needs provider_config.llm")
        agent = self.agent_factory()(self.get_prompt(agent_id))
        return LiveKitTextSession(self.session_factory(), llm, agent)


class LiveKitTextSession(TextSession):
    def __init__(self, session_cls: Callable[..., Any], llm: Any, agent: Any) -> None:
        self.session = session_cls(llm=llm)
        self.agent = agent
        self._entered = False

    async def start(self) -> Optional[str]:
        await self.session.__aenter__()
        self._entered = True
        await self.session.start(self.agent)
        return None

    async def send(self, text: str) -> AgentReply:
        result = await self.session.run(user_input=text)
        replies: List[str] = []
        calls: List[ToolCall] = []
        by_id: Dict[str, ToolCall] = {}
        for event in getattr(result, "events", []) or []:
            kind = getattr(event, "type", "")
            item = getattr(event, "item", None)
            if item is None:
                continue
            if kind == "message" and getattr(item, "role", "") == "assistant":
                replies.append(_text(getattr(item, "content", "")))
            elif kind == "function_call":
                call = ToolCall(name=getattr(item, "name", "unknown"),
                                arguments=getattr(item, "arguments", {}),
                                call_id=getattr(item, "call_id", None))
                calls.append(call)
                if call.call_id:
                    by_id[call.call_id] = call
            elif kind == "function_call_output":
                call = by_id.get(getattr(item, "call_id", "") or "")
                if call is not None:
                    call.result = getattr(item, "output", None)
        return AgentReply(text=" ".join(r for r in replies if r), tool_calls=calls)

    async def close(self) -> SessionOutcome:
        if self._entered:
            await self.session.__aexit__(None, None, None)
        return SessionOutcome()
