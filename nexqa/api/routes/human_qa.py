"""
NEXQA API — Human QA

Interactive testing endpoints for human testers.
"""

from typing import List

from fastapi import APIRouter, HTTPException
from nexqa.human_qa.session_manager import session_manager
from nexqa.models.human_qa_models import (
    HumanTestResult,
    HumanTestScript,
    HumanTestSession,
)

router = APIRouter()


@router.post("/session", response_model=HumanTestSession)
def start_session(
    agent_id: str,
    tester_name: str,
    scenario_ids: List[str] = [],
):
    """Start a new Human QA session."""
    try:
        session = session_manager.start_session(agent_id, tester_name, scenario_ids)
        return session
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/scripts", response_model=List[HumanTestScript])
def get_scripts(session_id: str):
    """Retrieve test scripts for a session."""
    session = session_manager.active_sessions.get(session_id)
    if not session:
        # Check completed
        for s in session_manager.completed_sessions:
            if s.session_id == session_id:
                return s.scripts
        raise HTTPException(status_code=404, detail="Session not found")
    return session.scripts


@router.post("/session/{session_id}/result", response_model=HumanTestSession)
def submit_result(
    session_id: str,
    result: HumanTestResult,
):
    """Submit a test result (pass/fail) for a script."""
    try:
        updated_session = session_manager.submit_result(session_id, result)
        if not updated_session:
            raise HTTPException(status_code=404, detail="Session not found")
        return updated_session
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
