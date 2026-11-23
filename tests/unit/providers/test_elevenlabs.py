import asyncio

from nexqa.providers.elevenlabs import ElevenLabsProvider

from ._fakes import FakeSession, make_spec

AGENT = {
    "agent_id": "ag_1",
    "name": "Front desk",
    "platform_settings": {"widget": {"x": 1}},
    "conversation_config": {
        "tts": {"voice_id": "v1"},
        "agent": {
            "first_message": "Hi there",
            "prompt": {"prompt": "OLD", "llm": "gemini", "tool_ids": ["t1"]},
        },
    },
}


def _provider(routes, **config):
    return ElevenLabsProvider(config, session=FakeSession(routes), api_key="xi-test")


def test_prompt_read_and_full_config_update():
    p = _provider({("GET", "/v1/convai/agents/ag_1"): AGENT,
                   ("PATCH", "/v1/convai/agents/ag_1"): {}})
    assert p.get_prompt("ag_1") == "OLD"
    assert p.session.calls[0]["headers"]["xi-api-key"] == "xi-test"
    assert "Authorization" not in p.session.calls[0]["headers"]

    p.update_prompt("ag_1", "NEW")
    body = p.session.sent("PATCH", "/v1/convai/agents/ag_1")[0]["json"]
    assert list(body) == ["conversation_config"]  # platform_settings untouched
    cc = body["conversation_config"]
    assert cc["agent"]["prompt"] == {"prompt": "NEW", "llm": "gemini", "tool_ids": ["t1"]}
    assert cc["agent"]["first_message"] == "Hi there"
    assert cc["tts"] == {"voice_id": "v1"}
    assert AGENT["conversation_config"]["agent"]["prompt"]["prompt"] == "OLD"


def test_native_tests_end_to_end():
    created = iter([{"id": "test_1"}, {"id": "test_2"}])
    run_done = {
        "id": "inv_1",
        "test_runs": [
            {"test_id": "test_1", "status": "passed",
             "condition_result": {"result": "success", "rationale": {"summary": "booked"}},
             "agent_responses": [
                 {"role": "user", "message": "Book me", "time_in_call_secs": 1},
                 {"role": "agent", "message": None, "time_in_call_secs": 2,
                  "tool_calls": [{"request_id": "r1", "tool_name": "book",
                                  "params_as_json": '{"day": "Tue"}'}],
                  "tool_results": [{"request_id": "r1", "tool_name": "book",
                                    "result_value": "ok"}]},
                 {"role": "agent", "message": "Done, Tuesday.", "time_in_call_secs": 3},
             ]},
            {"test_id": "test_2", "status": "failed",
             "condition_result": {"result": "failure"}, "agent_responses": []},
        ],
    }
    routes = {
        ("GET", "/v1/convai/agents/ag_1"): AGENT,
        ("POST", "/v1/convai/agent-testing/create"): lambda call: next(created),
        ("POST", "/v1/convai/agents/ag_1/run-tests"): {"id": "inv_1", "test_runs": []},
        ("GET", "/v1/convai/test-invocations/inv_1"): [
            {"test_runs": [{"test_id": "test_1", "status": "pending"}]}, run_done],
    }
    p = _provider(routes, max_turns=7)
    suite = p.register_scenarios("ag_1", make_spec(2), p.resolve_target("ag_1"))
    assert suite.remote_ids == ["test_1", "test_2"]

    body = p.session.sent("POST", "/v1/convai/agent-testing/create")[0]["json"]
    assert body["type"] == "simulation"
    assert body["simulation_scenario"].startswith("You are caller 1")
    assert body["success_conditions"] == ["The agent books the appointment.", "Confirms the date"]
    assert body["simulation_max_turns"] == 7

    handle = p.start_run(suite)
    assert handle == "inv_1"
    assert p.session.sent("POST", "/run-tests")[0]["json"] == {
        "tests": [{"test_id": "test_1"}, {"test_id": "test_2"}]}

    run = asyncio.run(p.wait_for_results(suite, handle, 0, 60))
    first, second = run.conversations
    assert first.scenario_id == "s1" and first.status == "pass"
    assert first.platform_passed is True and first.platform_notes == "booked"
    assert first.transcript_text() == "User: Book me\nAgent: Done, Tuesday.\n"
    assert first.turns[0].start_s == 1
    assert first.tool_calls[0].arguments == {"day": "Tue"}
    assert first.tool_calls[0].result == "ok"
    assert second.status == "fail" and second.platform_passed is False


def test_regional_base_url():
    p = _provider({("GET", "/v1/convai/agents/a"): AGENT},
                  base_url="https://api.eu.residency.elevenlabs.io")
    p.get_prompt("a")
    assert p.session.calls[0]["url"].startswith("https://api.eu.residency.elevenlabs.io/")
