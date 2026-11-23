from typer.testing import CliRunner

from nexqa.cli.main import app

runner = CliRunner()


def test_providers_command_lists_every_platform():
    result = runner.invoke(app, ["providers"], terminal_width=200)
    assert result.exit_code == 0, result.output
    for name in ("retell", "vapi", "elevenlabs", "bland", "synthflow", "ultravox",
                 "livekit", "pipecat", "custom"):
        assert name in result.output


def test_run_rejects_unknown_provider(example_spec_path):
    result = runner.invoke(app, ["run", "--spec-path", str(example_spec_path),
                                 "--provider", "not-a-platform"])
    assert result.exit_code == 1
    assert "Unknown provider" in result.output


def test_non_retell_run_needs_agent_id(example_spec_path):
    result = runner.invoke(app, ["run", "--spec-path", str(example_spec_path),
                                 "--provider", "vapi"])
    assert result.exit_code == 1
    assert "--agent-id" in result.output
