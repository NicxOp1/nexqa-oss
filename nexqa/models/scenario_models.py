from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from enum import Enum

class SimulationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    IN_PROGRESS = "in_progress"  # Retell batch test status
    COMPLETED = "completed"
    COMPLETE = "complete"        # Retell batch test status
    FAILED = "failed"
    PASS = "pass"
    FAIL_RETELL = "fail"
    ERROR = "error"

class SimulationResult(BaseModel):
    """Result of a single simulation run"""
    scenario_id: str
    transcript: str
    tool_calls: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    status: SimulationStatus
    error: Optional[str] = None

class ValidationResult(BaseModel):
    """Deterministic validation output"""
    passed: bool
    failed_rules: List[str] # List of Rule IDs
    details: Dict[str, Any]

class SemanticIssue(BaseModel):
    """Issue identified by LLM Judge"""
    section: str
    severity: str # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    root_cause_gene: Optional[str] = None  # IDENTITY, FLOW, OBJECTIONS, RULES, PERSONALITY
    recommendation: Optional[str] = None

class EvaluationResult(BaseModel):
    """Combined evaluation result"""
    scenario_id: str
    deterministic_result: ValidationResult
    semantic_score: float
    semantic_issues: List[SemanticIssue]
    overall_score: float
    subscores: Dict[str, float] = {}  # semantic, conversational, turing
    is_critical_fail: bool
