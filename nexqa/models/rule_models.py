from typing import List, Optional, Dict
from pydantic import BaseModel, Field

# --- Rule Models ---

class HardRule(BaseModel):
    """A strict rule that must be followed (deterministic check)"""
    id: str
    description: str
    regex_pattern: Optional[str] = None
    required_sequence: Optional[List[str]] = None
    forbidden_terms: Optional[List[str]] = None
    category: str = "general"

class SoftRule(BaseModel):
    """A stylistic or semantic guideline (LLM checked)"""
    id: str
    description: str
    evaluation_criteria: str
    category: str = "tone"

class ToolDependency(BaseModel):
    """Rule enforcing tool call order or prerequisite"""
    trigger_condition: str
    required_tool: str
    must_occur: str = "before_response"

class PronunciationRule(BaseModel):
    """Specific pronunciation guidance"""
    term: str
    phonetic_spelling: str

class TestScenario(BaseModel):
    """A specific test case extracted from the spec"""
    id: str
    name: str = "Unnamed Scenario"
    description: str = ""
    user_prompt: str  # Persona/context instructions for the AI tester
    expected_outcome: str = ""
    critical_checkpoints: List[str] = []
    # Sprint 1: tool_mocks — ideal responses for each tool during simulation
    # Key = tool_name, Value = JSON string the tool should return
    tool_mocks: Dict[str, str] = Field(default_factory=dict)
    # Sprint 2: tool_endpoints — real webhook URLs for direct validation
    # Key = tool_name, Value = full HTTP URL
    tool_endpoints: Dict[str, str] = Field(default_factory=dict)

class CompiledSpec(BaseModel):
    """The full output of the ingestion process"""
    model_config = {"extra": "ignore"}  # Ignore extra fields from the calling app spec (agent_id, workspace_id, etc.)

    hard_rules: List[HardRule] = []
    soft_rules: List[SoftRule] = []
    scenarios: List[TestScenario] = []
    tool_dependencies: List[ToolDependency] = []
    pronunciation_rules: List[PronunciationRule] = []
    raw_text: Optional[str] = None
    max_iterations: Optional[int] = None
    max_scenarios: Optional[int] = None
    prompt: Optional[str] = None
