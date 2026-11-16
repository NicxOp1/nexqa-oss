"""Shared pytest setup: no test may reach a real API or write outside tmp."""

from pathlib import Path

import pytest

SPECS_DIR = Path(__file__).parent / "specs"


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from nexqa.storage.config import Config

    monkeypatch.setattr(Config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(Config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(Config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(Config, "PROMPT_VERSIONS_DIR", tmp_path / "prompt_versions")


@pytest.fixture
def example_spec_path() -> Path:
    return SPECS_DIR / "example_agent_spec.yaml"
