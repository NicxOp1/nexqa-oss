from nexqa.human_qa.feedback_processor import FeedbackProcessor
from nexqa.human_qa.script_generator import ScriptGenerator
from nexqa.models.human_qa_models import TestStepType


def test_feedback_parses_claude_issues():
    response = """```json
[
  {"section": "Greeting", "severity": "high", "description": "Said the wrong clinic name",
   "root_cause_gene": "identity", "recommendation": "Fix the name"},
  {"section": "Booking"}
]
```"""
    issues = FeedbackProcessor._parse_issues(response)
    assert len(issues) == 1  # the malformed second item is skipped
    assert issues[0].severity == "HIGH"
    assert issues[0].root_cause_gene == "IDENTITY"


def test_feedback_falls_back_when_claude_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr("nexqa.human_qa.feedback_processor.claude_client.complete", boom)
    issues = FeedbackProcessor().process_feedback("Agent talked over me")
    assert len(issues) == 1
    assert issues[0].description == "Agent talked over me"


def test_script_steps_are_parsed_and_numbered():
    response = '[{"type": "SPEAK", "instruction": "Ask for Tuesday"}, {"type": "listen", "instruction": "Wait"}]'
    steps = ScriptGenerator._parse_steps(response)
    assert [s.step_id for s in steps] == ["1", "2"]
    assert steps[0].type == TestStepType.SPEAK


def test_script_uses_basic_steps_when_claude_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr("nexqa.human_qa.script_generator.claude_client.complete", boom)
    script = ScriptGenerator().generate_script("Reschedule", "Caller wants Friday")
    assert len(script.steps) == 2
    assert script.focus_area == "General QA"
