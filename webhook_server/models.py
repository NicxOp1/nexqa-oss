from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum


class RetellWebhookEvent(str, Enum):
    """Events Retell sends to webhooks."""
    FUNCTION_CALL = "function_call"
    call_started = "call_started"
    call_ended = "call_ended"
    call_analyzed = "call_analyzed"


class RetellFunctionCall(BaseModel):
    """Incoming webhook payload from Retell when agent calls a function."""
    call_id: str
    agent_id: str
    event: RetellWebhookEvent = RetellWebhookEvent.FUNCTION_CALL
    function_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_type: Optional[str] = None
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    direction: Optional[str] = None
    metadata: Optional[dict] = None


class FunctionResponse(BaseModel):
    """Response back to Retell."""
    result: str  # MUST be natural language — Retell feeds this to the LLM


class ConnectorType(str, Enum):
    """Available connector types."""
    CALCOM = "calcom"
    AIRTABLE = "airtable"
    RETELL_SMS = "retell_sms"
    RETELL_NATIVE = "retell_native"


class FunctionConfig(BaseModel):
    """Configuration for a single function in the registry."""
    connector: ConnectorType
    config: dict[str, Any] = Field(default_factory=dict)


class AgentRegistry(BaseModel):
    """Full agent configuration in the registry."""
    agent_id: str
    agent_name: str
    company_name: str
    phone_number: str = ""  # The Retell number assigned to this agent
    functions: dict[str, FunctionConfig]
    credentials: dict[str, dict[str, str]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = True
