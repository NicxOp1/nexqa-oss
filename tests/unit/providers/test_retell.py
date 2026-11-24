"""Retell must behave exactly as before the provider refactor."""

import asyncio

from nexqa.models.scenario_models import SimulationResult
from nexqa.providers.retell import RetellProvider

from ._fakes import make_spec


def _old_evaluate_parse(res):
    """The transcript parsing that lived in QAEngine._evaluate before 0.3.0."""
    scenario_id = (
        res.get("test_case_id")
        or res.get("test_case_definition_snapshot", {}).get("testCaseDefinitionId")
        or "unknown"
    )
    transcript_list = res.get("transcript_snapshot", {}).get("transcript", [])
    transcript_str = ""
    tool_calls = []
    for msg in transcript_list:
        role = str(msg.get("role", "")).lower()
        content = msg.get("content", "")
        m_type = msg.get("type", "")
        if role in ("agent", "assistant", "user") and content:
            display_role = "Agent" if role in ("agent", "assistant") else "User"
            transcript_str += f"{display_role}: {content}\n"
        if m_type in ("tool_call_invocation", "tool_call"):
            tool_name = msg.get("name") or msg.get("tool_name", "unknown")
            tool_calls.append({
                "name": tool_name,
                "arguments": msg.get("arguments") or msg.get("params") or msg.get("input", {}),
                "result": msg.get("result") or msg.get("output"),
            })
    if not transcript_str:
        transcript_str = res.get("transcript", "")
    return SimulationResult(
        scenario_id=scenario_id,
        transcript=transcript_str.strip(),
        tool_calls=tool_calls,
        metadata=res,
        status={"complete": "completed", "in_progress": "running"}.get(
            res.get("status", "completed"), res.get("status", "completed")
        ),
    )


RUNS = [
    {
        "test_case_id": "tc_1",
        "status": "pass",
        "transcript_snapshot": {"transcript": [
            {"role": "agent", "content": "Hi, this is the clinic."},
            {"role": "user", "content": "I need a cleaning."},
            {"role": "tool_call_invocation", "type": "tool_call_invocation",
             "name": "check_availability", "arguments": {"date": "2026-12-01"}},
            {"role": "assistant", "content": "Tuesday at nine works."},
        ]},
    },
    {
        "test_case_definition_snapshot": {"testCaseDefinitionId": "tc_2"},
        "status": "fail",
        "transcript": "Agent: plain text fallback",
        "transcript_snapshot": {"transcript": []},
    },
    {"status": "complete", "transcript_snapshot": {"transcript": [
        {"role": "user", "content": "hello"},
        {"type": "tool_call", "tool_name": "end_call", "params": {"reason": "done"},
         "output": "ok"},
    ]}},
]


def test_normalized_runs_match_pre_refactor_parsing():
    for res in RUNS:
        new = RetellProvider.normalize_run(res).to_simulation_result()
        assert new == _old_evaluate_parse(res)


def test_pending_runs_are_skipped():
    runs = RUNS + [{"status": "in_progress"}, {"status": "pending"}]
    assert len(RetellProvider.normalize_runs(runs)) == len(RUNS)


class FakeRetellClient:
    def __init__(self):
        self.calls = []
        self.batch_polls = [{"status": "in_progress"},
                            {"status": "complete",
                             "batch_test_summary": {"total_duration_seconds": 120}}]

    def get_agent(self, agent_id):
        self.calls.append(("get_agent", agent_id))
        return {"response_engine": {"type": "retell-llm", "llm_id": "llm_1"}}

    def create_test_case_definition(self, **kw):
        self.calls.append(("create_tc", kw))
        if kw["name"] == "Scenario 2":
            raise RuntimeError("boom")
        return "tc_" + kw["name"][-1]

    def create_batch_test(self, ids, engine):
        self.calls.append(("batch", ids, engine))
        return "batch_1"

    def get_batch_test(self, batch_id):
        return self.batch_polls.pop(0)

    def list_test_runs(self, batch_id):
        return RUNS[:1]

    def get_current_prompt(self, agent_id):
        return "PROMPT"

    def update_prompt(self, agent_id, prompt):
        self.calls.append(("update_prompt", agent_id, prompt))


def test_retell_flow_uses_same_client_calls(monkeypatch):
    client = FakeRetellClient()
    p = RetellProvider(client=client)

    target = p.resolve_target("agent_1")
    assert target == {"type": "retell-llm", "llm_id": "llm_1"}

    suite = p.register_scenarios("agent_1", make_spec(2), target)
    assert suite.remote_ids == ["tc_1"]  # the failing scenario is skipped
    kw = client.calls[1][1]
    assert kw["llm_id"] == "llm_1"
    assert kw["metrics"] == ["The agent books the appointment.", "Confirms the date"]
    assert "tool_mocks" not in kw  # the engine never sent tool mocks

    assert p.start_run(suite) == "batch_1"
    assert client.calls[-1] == ("batch", ["tc_1"], target)

    run = asyncio.run(p.wait_for_results(suite, "batch_1", poll_interval=0, timeout=10))
    assert run.billed_minutes == 2.0
    assert [c.scenario_id for c in run.conversations] == ["tc_1"]

    assert p.get_prompt("agent_1") == "PROMPT"
    p.update_prompt("agent_1", "NEW")
    assert client.calls[-1] == ("update_prompt", "agent_1", "NEW")


def test_resolve_target_falls_back_to_llm_id():
    class C(FakeRetellClient):
        def get_agent(self, agent_id):
            return {"llm_id": "llm_9"}

    assert RetellProvider(client=C()).resolve_target("a") == {
        "type": "retell-llm", "llm_id": "llm_9"}
