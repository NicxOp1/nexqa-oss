"""
NEXQA v1.0 — Human QA Models

Data structures for manual testing sessions.
Human testers (you) follow generated scripts and provide pass/fail feedback.
"""

from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class TestStepType(str, Enum):
    SPEAK = "speak"
    LISTEN = "listen"
    ACTION = "action"  # e.g., "Check email", "Wait 5s"


class HumanTestStep(BaseModel):
    """A single instruction for the human tester."""
    step_id: str
    type: TestStepType
    instruction: str
    expected_response: Optional[str] = None
    criteria: Optional[str] = None  # What defines success?


class HumanTestScript(BaseModel):
    """A complete test script for a specific scenario."""
    scenario_id: str
    scenario_name: str
    focus_area: str  # e.g., "Objection Handling", "Identity"
    steps: List[HumanTestStep]
    estimated_duration_seconds: int = 120


class HumanTestSession(BaseModel):
    """Record of a human QA session."""
    session_id: str
    agent_id: str
    tester_name: str
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    scripts: List[HumanTestScript]
    results: List['HumanTestResult'] = []


class HumanTestResult(BaseModel):
    """Outcome of a human test script."""
    script_id: str # tied to scenario_id usually
    passed: bool
    audio_url: Optional[str] = None
    notes: Optional[str] = None
    issues_found: List[str] = []
