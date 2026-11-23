import asyncio

from nexqa.providers.synthflow import SynthflowProvider

from ._fakes import FakeSession, make_spec

ASSISTANT = {"status": "ok", "response": {"assistants": [
    {"model_id": "m_1", "name": "Desk", "agent": {"prompt": "OLD", "voice_id": "v"}}]}}


def _provider(routes, **config):
    return SynthflowProvider(config, session=FakeSession(routes), api_key="sf-key")


def test_prompt_read_and_partial_put():
    p = _provider({("GET", "/assistants/m_1"): ASSISTANT, ("PUT", "/assistants/m_1"): {}})
    assert p.get_prompt("m_1") == "OLD"
    assert p.session.calls[0]["url"] == "https://api.synthflow.ai/v2/assistants/m_1"
    assert p.session.calls[0]["headers"]["Authorization"] == "Bearer sf-key"
    p.update_prompt("m_1", "NEW")
    assert p.session.sent("PUT", "/assistants/m_1")[0]["json"] == {"agent": {"prompt": "NEW"}}


def test_simulations_end_to_end():
    cases = iter([
        {"response": {"simulation_case": {"simulation_case_id": "case_1"}}},
        {"response": {"simulation_case": {"id": "case_2"}}},  # docs example shape
    ])
    sims = iter(["sim_1", "sim_2"])
    done = {"response": {
        "status": "completed",
        "timeline": [
            {"sender_type": "agent", "type": "message", "value": "Hi, Desk here.", "timestamp": 0.5},
            {"sender_type": "simulated_user", "type": "message", "value": "Book me",
             "timestamp": 2.0},
            {"sender_type": "agent", "type": "tool_call", "value": {"name": "book"},
             "timestamp": 3.0},
            {"sender_type": "agent", "type": "message", "value": "Booked.", "timestamp": 4.5},
        ],
        "success_criteria_analysis": {"success": True, "evaluations": [
            {"success": True, "reasoning": "Booked the slot"}]},
    }}
    routes = {
        ("GET", "/assistants/m_1"): ASSISTANT,
        ("POST", "/simulation_cases"): lambda call: next(cases),
        ("POST", "/simulations"): lambda call: {"response": {"simulation_id": next(sims)}},
        ("GET", "/simulations/sim_1"): [{"response": {"status": "in-progress"}}, done],
        ("GET", "/simulations/sim_2"): {"response": {"status": "failed",
                                                     "error_info": {"message": "no answer"}}},
    }
    p = _provider(routes, suite_id="suite_9")
    suite = p.register_scenarios("m_1", make_spec(2), p.resolve_target("m_1"))
    assert suite.remote_ids == ["case_1", "case_2"]
    case_body = p.session.sent("POST", "/simulation_cases")[0]["json"]
    assert case_body["type"] == "custom" and case_body["call_success_type"] == "all"
    assert case_body["suite_id"] == "suite_9"
    assert case_body["success_criteria"] == ["The agent books the appointment.", "Confirms the date"]

    handle = p.start_run(suite)
    sim_body = p.session.sent("POST", "/simulations")[0]["json"]
    assert sim_body == {"simulation_case_id": "case_1", "target_agent_id": "m_1"}

    run = asyncio.run(p.wait_for_results(suite, handle, 0, 60))
    by_id = {c.scenario_id: c for c in run.conversations}
    ok = by_id["s1"]
    assert ok.transcript_text() == "Agent: Hi, Desk here.\nUser: Book me\nAgent: Booked.\n"
    assert ok.tool_calls[0].arguments == {"name": "book"}
    assert ok.platform_passed is True and ok.platform_notes == "Booked the slot"
    assert ok.duration_s == 4.0
    assert by_id["s2"].status == "error" and by_id["s2"].end_reason == "no answer"
