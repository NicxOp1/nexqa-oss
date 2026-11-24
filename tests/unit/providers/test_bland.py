import asyncio

import pytest

from nexqa.providers.base import ProviderError
from nexqa.providers.bland import BlandProvider

from ._fakes import FakeSession, make_spec

PERSONA = {"data": {"id": "per_1", "name": "Front desk",
                    "current_draft_version": {"personality_prompt": "OLD",
                                              "orchestration_prompt": "ORCH"}}}


def _provider(routes, **config):
    return BlandProvider(config, session=FakeSession(routes), api_key="bland-key")


def test_persona_prompt_and_update_sends_only_name_and_prompt():
    p = _provider({("GET", "/v1/personas/per_1"): PERSONA,
                   ("PATCH", "/v1/personas/per_1"): {"data": {}}})
    assert p.get_prompt("per_1") == "OLD"
    assert p.session.calls[0]["headers"]["authorization"] == "bland-key"  # no Bearer

    p.update_prompt("per_1", "NEW")
    body = p.session.sent("PATCH", "/v1/personas/per_1")[0]["json"]
    assert body == {"name": "Front desk", "personality_prompt": "NEW"}


def test_v2_agent_update_saves_full_snapshot_version():
    latest = {"data": {"id": "ver_3", "revision": 3, "snapshot": {
        "behavior": {"nodes": [{"id": "n1"}], "edges": []},
        "settings": {"displayName": "Desk", "systemPrompt": "OLD", "voice": "x"},
        "contact": {"inboundNumbers": ["+10000000000"]},
    }}}
    p = _provider({("GET", "/v2/agents/ag_1/versions/latest"): latest,
                   ("POST", "/v2/agents/ag_1/versions"): {"data": {"id": "ver_4"}}},
                  target="agent_v2")
    assert p.get_prompt("ag_1") == "OLD"
    p.update_prompt("ag_1", "NEW")
    body = p.session.sent("POST", "/v2/agents/ag_1/versions")[0]["json"]
    assert body["parent_version_id"] == "ver_3" and body["parent_revision"] == 3
    snap = body["snapshot"]
    assert snap["settings"] == {"displayName": "Desk", "systemPrompt": "NEW", "voice": "x"}
    assert snap["behavior"]["nodes"] == [{"id": "n1"}]
    assert snap["contact"] == {"inboundNumbers": ["+10000000000"]}


def test_v2_agent_tests_need_persona_or_pathway():
    p = _provider({}, target="agent_v2")
    with pytest.raises(ProviderError, match="persona"):
        p.resolve_target("ag_1")
    assert _provider({}, target="agent_v2", pathway_id="pw_1").resolve_target("ag_1") == {
        "pathway_id": "pw_1"}


def test_agent_testing_end_to_end():
    ids = iter(["sc_1", "sc_2"])
    runs = {"sc_1": "run_1", "sc_2": "run_2"}
    routes = {
        ("POST", "/v1/agent-testing/scenarios"): lambda call: {"data": {"id": next(ids)}},
        ("POST", "/v1/agent-testing/scenarios/sc_1/run"): {"run_id": "run_1", "status": "RUNNING"},
        ("POST", "/v1/agent-testing/scenarios/sc_2/run"): {"run_id": "run_2", "status": "RUNNING"},
        ("GET", "/v1/agent-testing/runs/run_1"): [{"status": "RUNNING"}, {
            "status": "PASSED", "overall_score": 0.9,
            "chat_history": [{"role": "user", "content": "Book me"},
                             {"role": "assistant", "content": "Done."},
                             {"role": "system", "content": "ignored"}]}],
        ("GET", "/v1/agent-testing/runs/run_2"): {"status": "ERROR", "chat_history": []},
    }
    p = _provider(routes)
    target = p.resolve_target("per_1")
    assert target == {"persona_id": "per_1"}
    suite = p.register_scenarios("per_1", make_spec(2), target)
    body = p.session.sent("POST", "/v1/agent-testing/scenarios")[0]["json"]
    assert body["persona_id"] == "per_1"
    assert body["tester_persona_prompt"].startswith("You are caller 1")
    assert body["max_turns"] == 20

    handle = p.start_run(suite)
    assert sorted(handle.split(",")) == sorted(f"{k}={v}" for k, v in runs.items())

    run = asyncio.run(p.wait_for_results(suite, handle, 0, 60))
    by_id = {c.scenario_id: c for c in run.conversations}
    assert by_id["s1"].status == "pass" and by_id["s1"].platform_passed is True
    assert by_id["s1"].transcript_text() == "User: Book me\nAgent: Done.\n"
    assert by_id["s2"].status == "error"
