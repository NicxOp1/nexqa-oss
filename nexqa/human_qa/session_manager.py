"""
NEXQA v1.0 — Human Session Manager

Orchestrates human QA sessions:
1. Generates scripts for testers
2. Tracks session progress (started, completed)
3. Ingests feedback from testers
4. Triggers automatic optimization based on feedback
"""

from datetime import datetime
from typing import Dict, List, Optional

from nexqa.human_qa.feedback_processor import feedback_processor
from nexqa.human_qa.script_generator import script_generator
from nexqa.models.human_qa_models import HumanTestResult, HumanTestScript, HumanTestSession
from nexqa.optimizer.gene_optimizer import gene_optimizer
from nexqa.storage.logger import logger


class SessionManager:
    """Manages lifecycle of human testing sessions."""

    def __init__(self) -> None:
        self.active_sessions: Dict[str, HumanTestSession] = {}
        self.completed_sessions: List[HumanTestSession] = []

    def start_session(
        self,
        agent_id: str,
        tester_name: str,
        scenarios: List[str] = [],
    ) -> HumanTestSession:
        """Create a new testing session for an agent."""
        session_id = f"{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"Starting session {session_id} for {tester_name}")

        scripts = []
        for scenario_name in scenarios:
            script = script_generator.generate_script(scenario_name, [])
            scripts.append(script)

        session = HumanTestSession(
            session_id=session_id,
            agent_id=agent_id,
            tester_name=tester_name,
            scripts=scripts,
            started_at=datetime.now(),
        )
        self.active_sessions[session_id] = session
        return session

    def submit_result(
        self,
        session_id: str,
        result: HumanTestResult,
    ) -> Optional[HumanTestSession]:
        """Record the outcome of a single test script within a session."""
        session = self.active_sessions.get(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            return None

        session.results.append(result)
        logger.info(
            f"Result submitted for {result.script_id}: Passed={result.passed}"
        )

        # Trigger immediate optimization if failed?
        if not result.passed and result.notes:
            issues = feedback_processor.process_feedback(result.notes, result.script_id)
            if issues:
                logger.info(
                    f"Found {len(issues)} semantic issues from feedback based on notes: {result.notes}"
                )
                # Ideally queue this for gene_optimizer, but maybe async?
                # gene_optimizer.optimize(..., issues, ...) requires current gene set context

        return session

    def close_session(self, session_id: str) -> Optional[HumanTestSession]:
        """Mark a session as completed."""
        session = self.active_sessions.pop(session_id, None)
        if session:
            session.completed_at = datetime.now()
            self.completed_sessions.append(session)
            logger.info(f"Session {session_id} completed")
        return session


# Singleton
session_manager = SessionManager()
