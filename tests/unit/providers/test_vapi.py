import asyncio

import pytest

from nexqa.providers.base import ProviderError
from nexqa.providers.vapi import VapiProvider

from ._fakes import FakeCaller, FakeSession, make_spec

ASSISTANT = {
    "id": "asst_1",
    "name": "Front desk",
    "voice": {"provider": "11labs", "voiceId": "v1"},
    "model": {
        "provider": "openai",
        "model": "gpt-4.1",
        "toolIds": ["tool_a"],
        "tools": [{"type": "function", "function": {"name": "book"}}],
        "messages": [
            {"role": "system", "content": "OLD PROMPT"},
            {"role": "assistant", "content": "seed"},
        ],
    },
}


def _provider(routes, **config):
    return VapiProvider(config, session=FakeSession(routes), api_key="test-key")


def test_get_prompt_reads_system_message():
    p = _provider({("GET", "/assistant/asst_1"): ASSISTANT})
    assert p.get_prompt("asst_1") == "OLD PROMPT"
    assert p.session.calls[0]["headers"]["Authorization"] == "Bearer test-key"


def test_update_prompt_resends_full_model_only():
    p = _provider({("GET", "/assistant/asst_1"): ASSISTANT, ("PATCH", "/assistant/asst_1"): {}})
    p.update_prompt("asst_1", "NEW PROMPT")
    body = p.session.sent("PATCH", "/assistant/asst_1")[0]["json"]
    assert list(body) == ["model"]  # voice, name, etc. are not touched
    model = body["model"]
    assert model["provider"] == "openai" and model["model"] == "gpt-4.1"
    assert model["toolIds"] == ["tool_a"] and model["tools"][0]["function"]["name"] == "book"
    assert model["messages"] == [
        {"role": "system", "content": "NEW PROMPT"},
        {"role": "assistant", "content": "seed"},
    ]
    assert ASSISTANT["model"]["messages"][0]["content"] == "OLD PROMPT"  # no mutation


def test_update_prompt_inserts_missing_system_message():
    bare = {"model": {"provider": "openai", "model": "gpt-4.1"}}
    p = _provider({("GET", "/assistant/a"): bare, ("PATCH", "/assistant/a"): {}})
    p.update_prompt("a", "P")
    assert p.session.sent("PATCH", "/assistant/a")[0]["json"]["model"]["messages"] == [
        {"role": "system", "content": "P"}]


def test_chat_mode_runs_simulated_caller_with_previous_chat_id():
    replies = [
        {"id": "chat_1", "output": [{"role": "assistant", "content": "Sure, which day?"}]},
        {"id": "chat_2", "cost": 0.01, "output": [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "book", "arguments": '{"day": "Tuesday"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "booked"},
            {"role": "assistant", "content": "You are booked for Tuesday."},
        ]},
    ]
    p = _provider({("GET", "/assistant/asst_1"): ASSISTANT, ("POST", "/chat"): replies})
    p.caller = FakeCaller(["Hi, I need a cleaning.", "Tuesday please."])

    target = p.resolve_target("asst_1")
    suite = p.register_scenarios("asst_1", make_spec(1), target)
    run = asyncio.run(p.wait_for_results(suite, p.start_run(suite), 0, 60))

    conv = run.conversations[0]
    assert conv.scenario_id == "s1" and conv.status == "completed"
    assert conv.end_reason == "caller_hangup"
    assert [t.role for t in conv.turns] == ["user", "agent", "user", "agent"]
    assert conv.tool_calls[0].name == "book"
    assert conv.tool_calls[0].arguments == {"day": "Tuesday"}
    assert conv.tool_calls[0].result == "booked"

    posts = p.session.sent("POST", "/chat")
    assert posts[0]["json"] == {"assistantId": "asst_1", "input": "Hi, I need a cleaning."}
    assert posts[1]["json"]["previousChatId"] == "chat_1"


def test_chat_error_becomes_error_conversation():
    p = _provider({("POST", "/chat"): {"x": 1}})
    p.session.routes = {}  # every call 404s
    p.caller = FakeCaller(["hello"])
    suite = p.register_scenarios("a", make_spec(1), {})
    run = asyncio.run(p.wait_for_results(suite, "h", 0, 60))
    assert run.conversations[0].status == "error"


def test_simulation_mode_requires_personality():
    p = _provider({}, mode="simulation")
    with pytest.raises(ProviderError, match="personality_id"):
        p.register_scenarios("a", make_spec(1), {})


def test_simulation_mode_end_to_end():
    routes = {
        ("POST", "/eval/simulation/scenario"): {"id": "scn_1"},
        ("POST", "/eval/simulation"): {"id": "sim_1"},
        ("POST", "/eval/simulation/run"): {"id": "run_1", "status": "queued"},
        ("GET", "/eval/simulation/run/run_1"): [{"status": "running"}, {"status": "ended"}],
        ("GET", "/eval/simulation/run/run_1/item"): {"results": [{
            "simulationId": "sim_1",
            "status": "passed",
            "results": {"passed": True},
            "metadata": {"call": {"messages": [
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "Book me"},
            ]}},
        }]},
    }
    p = _provider(routes, mode="simulation", personality_id="pers_1")
    suite = p.register_scenarios("asst_1", make_spec(1), {"assistantId": "asst_1"})
    assert suite.remote_ids == ["sim_1"]

    scenario_body = p.session.sent("POST", "/eval/simulation/scenario")[0]["json"]
    assert scenario_body["instructions"].startswith("You are caller 1")
    assert len(scenario_body["evaluations"]) == 2
    assert scenario_body["evaluations"][0]["comparator"] == "="
    sim_body = p.session.sent("POST", "/eval/simulation")[0]["json"]
    assert sim_body["scenarioId"] == "scn_1" and sim_body["personalityId"] == "pers_1"

    handle = p.start_run(suite)
    run_body = p.session.sent("POST", "/eval/simulation/run")[0]["json"]
    assert run_body["target"] == {"type": "assistant", "assistantId": "asst_1"}
    assert run_body["simulations"] == [{"type": "simulation", "simulationId": "sim_1"}]

    run = asyncio.run(p.wait_for_results(suite, handle, 0, 60))
    conv = run.conversations[0]
    assert conv.scenario_id == "s1" and conv.status == "pass" and conv.platform_passed
    assert conv.transcript_text() == "Agent: Hello\nUser: Book me\n"
