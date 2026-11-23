"""Provider registry, spec settings, simulated caller and the engine wiring."""

import asyncio
import json
from pathlib import Path

import pytest

from nexqa.core import engine as engine_module
from nexqa.core.engine import QAEngine
from nexqa.models.scenario_models import EvaluationResult, ValidationResult
from nexqa.providers import (
    REGISTRY,
    ProviderError,
    get_provider,
    list_providers,
    load_provider_settings,
    normalize_name,
)
from nexqa.providers.base import Conversation, SuiteRun, TestSuite, Turn, VoiceProvider
from nexqa.providers.simulator import END_TOKEN, SimulatedCaller

from ._fakes import make_spec

SPECS = Path(__file__).resolve().parents[2] / "specs"


def test_every_provider_is_importable_and_described():
    rows = list_providers()
    assert {r["name"] for r in rows} == set(REGISTRY)
    for row in rows:
        assert row["maturity"] in ("verified-live", "tested-offline")
        assert row["test_mode"]


def test_aliases_and_unknown_names():
    assert normalize_name(None) == "retell"
    assert normalize_name("ElevenLabs") == "elevenlabs"
    assert normalize_name("11labs") == "elevenlabs"
    assert normalize_name("livekit-agents") == "livekit"
    with pytest.raises(ProviderError, match="Unknown provider"):
        normalize_name("nope")


@pytest.mark.parametrize("spec", sorted(SPECS.glob("*.yaml")))
def test_existing_specs_default_to_retell(spec):
    assert load_provider_settings(spec) == ("retell", {})


def test_spec_provider_keys(tmp_path):
    yaml_spec = tmp_path / "s.yaml"
    yaml_spec.write_text("provider: Vapi\nprovider_config:\n  mode: chat\n  max_turns: 4\n")
    assert load_provider_settings(yaml_spec) == ("vapi", {"mode": "chat", "max_turns": 4})

    json_spec = tmp_path / "s.json"
    json_spec.write_text(json.dumps({"provider": "ultravox"}))
    assert load_provider_settings(json_spec) == ("ultravox", {})

    assert load_provider_settings(tmp_path / "notes.txt") == ("retell", {})

    bad = tmp_path / "bad.yaml"
    bad.write_text("provider: vapi\nprovider_config: [1, 2]\n")
    with pytest.raises(ProviderError):
        load_provider_settings(bad)


def test_http_provider_needs_its_key(monkeypatch):
    monkeypatch.delenv("VAPI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="VAPI_API_KEY"):
        get_provider("vapi").get_prompt("a")


class _FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.kwargs = None

    def complete(self, system, user, **kwargs):
        self.kwargs = kwargs
        self.system, self.user = system, user
        return self.answer


def test_simulated_caller_uses_cheap_settings_and_end_token():
    llm = _FakeLLM("  Hi, I want a cleaning.  ")
    caller = SimulatedCaller(llm)
    line = caller.next_line("A busy parent", [Turn("agent", "Hello!")])
    assert line == "Hi, I want a cleaning."
    assert "A busy parent" in llm.system and "Agent: Hello!" in llm.user
    assert set(llm.kwargs) == {"effort", "model"}

    assert SimulatedCaller(_FakeLLM(f"Thanks, bye {END_TOKEN}")).next_line("p", []) is None
    assert SimulatedCaller(_FakeLLM("")).next_line("p", []) is None


# ─── Engine wiring ────────────────────────────────────────────────────


class FakeProvider(VoiceProvider):
    name = "fake"
    test_mode = "fake"

    def __init__(self):
        super().__init__({})
        self.prompt = "<IDENTITY>You are Sam.</IDENTITY>"
        self.updates = []

    def get_prompt(self, agent_id):
        return self.prompt

    def update_prompt(self, agent_id, new_prompt):
        self.updates.append(new_prompt)
        self.prompt = new_prompt

    def register_scenarios(self, agent_id, spec, target):
        suite = TestSuite(agent_id, target)
        from nexqa.providers.base import SuiteItem
        suite.items = [SuiteItem(s.id, s.name, s.id, s) for s in spec.scenarios]
        return suite

    def start_run(self, suite):
        return "run_1"

    async def wait_for_results(self, suite, handle, poll_interval, timeout):
        return SuiteRun([Conversation(scenario_id=i.scenario_id,
                                      turns=[Turn("agent", "Hello"), Turn("user", "Hi")])
                         for i in suite.items], billed_minutes=1.0)


def _evaluation(scenario_id, score):
    return EvaluationResult(
        scenario_id=scenario_id,
        deterministic_result=ValidationResult(passed=True, failed_rules=[], details={}),
        semantic_score=score, semantic_issues=[], overall_score=score, is_critical_fail=False,
    )


@pytest.fixture
def offline_engine(monkeypatch):
    monkeypatch.setattr(engine_module.spec_ingestor, "ingest", lambda path: make_spec(2))
    monkeypatch.setattr(engine_module.airtable_reporter, "sync_run", lambda run: None)
    scores = []
    monkeypatch.setattr(
        engine_module.score_engine, "evaluate",
        lambda sid, transcript, det: scores.append(transcript) or _evaluation(sid, 0.99),
    )
    eng = QAEngine()
    eng.poll_interval = 0
    return eng, scores


def test_engine_runs_any_provider(offline_engine, tmp_path):
    eng, transcripts = offline_engine
    provider = FakeProvider()
    result = asyncio.run(eng.run_async("agent_1", tmp_path / "spec.yaml", provider=provider))
    assert result.action == "approved" and result.success
    assert transcripts == ["Agent: Hello\nUser: Hi"] * 2
    assert result.cost_metrics["retell_minutes"] == 1.0


def test_engine_reports_bad_provider(offline_engine, tmp_path):
    eng, _ = offline_engine
    spec = tmp_path / "spec.yaml"
    spec.write_text("provider: not-a-platform\n")
    result = asyncio.run(eng.run_async("agent_1", spec))
    assert result.action == "failed" and "Unknown provider" in result.error


def test_engine_picks_provider_from_spec(offline_engine, tmp_path, monkeypatch):
    eng, _ = offline_engine
    spec = tmp_path / "spec.yaml"
    spec.write_text("provider: vapi\nprovider_config:\n  mode: chat\n")
    picked = eng._resolve_provider(None, spec)
    assert picked.name == "vapi" and picked.config == {"mode": "chat"}
    # An explicit provider wins, and the spec's config is not applied to it.
    other = eng._resolve_provider("retell", spec)
    assert other.name == "retell" and other.config == {}


def test_engine_confirm_gate_blocks_update(offline_engine, monkeypatch):
    eng, _ = offline_engine
    provider = FakeProvider()
    eng.provider = provider
    new_set = engine_module.gene_parser.parse("<IDENTITY>You are Sam, kind.</IDENTITY>")
    monkeypatch.setattr(engine_module.gene_optimizer, "optimize", lambda *a: new_set)
    monkeypatch.setattr(engine_module.linter, "lint", lambda old, new: True)

    eng.confirm_update = lambda old, new: False
    assert eng._optimize("a", [], make_spec(1)) is None
    assert provider.updates == []

    eng.confirm_update = lambda old, new: True
    assert eng._optimize("a", [], make_spec(1)) is not None
    assert len(provider.updates) == 1
    assert eng._rollback_prompt("a") and provider.prompt == "<IDENTITY>You are Sam.</IDENTITY>"
