from nexqa.core.cost_meter import CostMeter
from nexqa.models.gene_models import Gene, GeneSet, GeneType
from nexqa.optimizer.linter import PromptLinter
from nexqa.storage.config import Config
from nexqa.storage.prompt_history import PromptHistory

BASE = "You are Ana, the receptionist for Bright Smile Dental. " * 10


def test_linter_accepts_small_edit():
    assert PromptLinter().lint(BASE, BASE + " Always confirm the date.") is True


def test_linter_rejects_prompt_explosion():
    assert PromptLinter().lint(BASE, BASE * 3) is False


def test_linter_rejects_prompt_collapse():
    assert PromptLinter().lint(BASE, "You are Ana.") is False


def test_linter_rejects_leaked_internal_terms():
    assert PromptLinter().lint(BASE, BASE.replace("Ana,", "Ana function_call,", 1)) is False


def test_cost_meter_totals_and_budget(monkeypatch):
    monkeypatch.setattr(Config, "COST_ALERT_THRESHOLD_USD", 1.0)
    meter = CostMeter()
    meter.PRICE_CLAUDE_INPUT_1M = 4.0
    meter.PRICE_CLAUDE_OUTPUT_1M = 20.0
    meter.PRICE_RETELL_MINUTE = 0.10

    meter.add_tokens(1_000_000, 0)
    meter.add_minutes(5)
    report = meter.get_report()
    assert report.total_cost_usd == 4.5
    assert report.limit_exceeded is True
    assert meter.check_budget() is False

    meter.reset()
    assert meter.get_report().total_cost_usd == 0
    assert meter.check_budget() is True


def test_prompt_history_versions(tmp_path):
    history = PromptHistory(storage_dir=tmp_path)
    genes = GeneSet(genes=[Gene(type=GeneType.IDENTITY, content="You are Ana.")])

    v1 = history.save_version("agent_1", "prompt one", genes)
    v2 = history.save_version("agent_1", "prompt two", genes, change_type="patch")

    assert v1.version == "1.0.0"
    assert v2.version == "1.0.1"
    assert history.get_latest("agent_1").prompt_text == "prompt two"

    # A fresh instance reads what the first one persisted.
    assert len(PromptHistory(storage_dir=tmp_path).get_history("agent_1")) == 2
