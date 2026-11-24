"""Self-hosted harnesses: custom respond(), Pipecat and LiveKit (all faked)."""

import asyncio
from types import SimpleNamespace

import pytest

from nexqa.providers import get_provider
from nexqa.providers.base import ProviderError
from nexqa.providers.livekit import LiveKitProvider

from ._fakes import FakeCaller, make_spec


@pytest.fixture
def prompt_file(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("You are the front desk.", encoding="utf-8")
    return path


@pytest.mark.parametrize("name", ["custom", "pipecat"])
def test_callable_harness(name, prompt_file):
    seen = []

    async def respond(system_prompt, messages):
        seen.append((system_prompt, messages))
        if len(messages) == 1:
            return "Which day?"
        return {"text": "Booked.", "tool_calls": [{"name": "book", "arguments": {"d": 1}}],
                "ended": True}

    p = get_provider(name, {"prompt_file": str(prompt_file), "respond": respond})
    p.caller = FakeCaller(["I need a cleaning", "Tuesday", "never sent"])
    assert p.resolve_target("desk")["prompt_file"] == str(prompt_file)

    suite = p.register_scenarios("desk", make_spec(1), {})
    conv = asyncio.run(p.wait_for_results(suite, p.start_run(suite), 0, 60)).conversations[0]

    assert conv.end_reason == "agent_hangup"
    assert conv.transcript_text() == (
        "User: I need a cleaning\nAgent: Which day?\nUser: Tuesday\nAgent: Booked.\n")
    assert conv.tool_calls[0].name == "book"
    assert seen[0][0] == "You are the front desk."
    assert seen[1][1][-1] == {"role": "user", "content": "Tuesday"}


def test_prompt_file_round_trip(prompt_file):
    p = get_provider("custom", {"prompt_file": str(prompt_file), "respond": lambda s, m: ""})
    assert p.get_prompt("desk") == "You are the front desk."
    p.update_prompt("desk", "NEW")
    assert prompt_file.read_text(encoding="utf-8") == "NEW"


def test_missing_config_is_explicit(tmp_path):
    with pytest.raises(ProviderError, match="prompt_file"):
        get_provider("custom", {}).get_prompt("x")
    with pytest.raises(ProviderError, match="not found"):
        get_provider("pipecat", {"prompt_file": str(tmp_path / "nope.txt")}).get_prompt("x")


def test_respond_can_be_a_module_reference(prompt_file):
    p = get_provider("custom", {"prompt_file": str(prompt_file), "respond": "json:dumps"})
    import json
    assert p.responder() is json.dumps


class FakeAgentSession:
    instances = []

    def __init__(self, llm):
        self.llm = llm
        self.started_with = None
        self.exited = False
        FakeAgentSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.exited = True

    async def start(self, agent):
        self.started_with = agent

    async def run(self, user_input):
        ev = SimpleNamespace
        return ev(events=[
            ev(type="function_call", item=ev(name="lookup", arguments={"q": user_input},
                                             call_id="c1")),
            ev(type="function_call_output", item=ev(output="found", call_id="c1", is_error=False)),
            ev(type="message", item=ev(role="assistant", content=[f"Echo: {user_input}"])),
        ])


def test_livekit_text_mode(prompt_file):
    built = []
    p = LiveKitProvider({
        "prompt_file": str(prompt_file),
        "llm": "openai/gpt-4.1-mini",
        "agent_factory": lambda instructions: built.append(instructions) or "AGENT",
    })
    p.session_cls = FakeAgentSession
    p.caller = FakeCaller(["hello"])

    suite = p.register_scenarios("desk", make_spec(1), {})
    conv = asyncio.run(p.wait_for_results(suite, p.start_run(suite), 0, 60)).conversations[0]

    session = FakeAgentSession.instances[-1]
    assert built == ["You are the front desk."]
    assert session.llm == "openai/gpt-4.1-mini" and session.started_with == "AGENT"
    assert session.exited
    assert conv.transcript_text() == "User: hello\nAgent: Echo: hello\n"
    assert conv.tool_calls[0].arguments == {"q": "hello"} and conv.tool_calls[0].result == "found"


def test_livekit_requires_llm(prompt_file):
    p = LiveKitProvider({"prompt_file": str(prompt_file), "agent_factory": lambda i: i})
    p.caller = FakeCaller(["hi"])
    suite = p.register_scenarios("desk", make_spec(1), {})
    with pytest.raises(ProviderError, match="llm"):
        asyncio.run(p.wait_for_results(suite, "h", 0, 60))
