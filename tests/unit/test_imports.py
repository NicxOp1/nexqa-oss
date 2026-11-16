"""Importing NEXQA must work with no API keys set (CI, `nexqa --help`)."""

import os
import subprocess
import sys

MODULES = [
    "nexqa.cli.main",
    "nexqa.core.engine",
    "nexqa.core.score_engine",
    "nexqa.optimizer.gene_optimizer",
    "nexqa.builder.agent_builder",
]


def _env_without_keys():
    env = dict(os.environ)
    for key in ("RETELL_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    return env


def test_import_without_api_keys(tmp_path):
    code = "import importlib\n" + "\n".join(
        f"importlib.import_module('{m}')" for m in MODULES
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=_env_without_keys(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr


def test_cli_help_runs_without_keys(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "nexqa.cli.main", "--help"],
        env=_env_without_keys(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert "run" in result.stdout
