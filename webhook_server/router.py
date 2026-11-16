from fastapi import APIRouter, Depends, HTTPException, Request
import logging
import json
from webhook_server.auth import read_verified_body, require_admin
from webhook_server.models import RetellFunctionCall, FunctionResponse
from webhook_server.registry import get_agent_config, refresh_cache
from webhook_server.executor import execute_function

def _ensure_dict(obj) -> dict:
    """Safely convert potential string from Retell to dict."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_json(raw: str) -> dict:
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return body


@router.post("/webhook/{agent_id}", response_model=FunctionResponse)
async def handle_webhook(agent_id: str, request: Request):
    """
    Main webhook endpoint. Retell sends function calls here.
    Each agent has a unique URL: /webhook/{agent_id}
    """
    # 1. Verify the Retell signature, then parse. Payloads can hold caller PII,
    #    so they are only logged at DEBUG.
    body = _parse_json(await read_verified_body(request))
    logger.debug(f"Raw webhook payload for agent {agent_id}: {body}")

    # 2. Normalize Payload for Model
    normalized_body = body.copy()
    
    # Handle 'tool_call' nesting (Newer Retell API)
    if "tool_call" in body and isinstance(body["tool_call"], dict):
        tool_call = body["tool_call"]
        normalized_body["function_name"] = tool_call.get("name")
        normalized_body["arguments"] = _ensure_dict(tool_call.get("arguments", tool_call.get("args", {})))
        if "call_id" not in normalized_body and "call" in body:
             normalized_body["call_id"] = body["call"].get("call_id")
    
    # Handle interaction_type
    if normalized_body.get("interaction_type") == "tool_call":
        if "args" in normalized_body:
             normalized_body["arguments"] = _ensure_dict(normalized_body.get("args", {}))
        elif "arguments" in normalized_body:
             normalized_body["arguments"] = _ensure_dict(normalized_body.get("arguments", {}))
             
    # Default missing fields
    if "agent_id" not in normalized_body:
        normalized_body["agent_id"] = agent_id
    if "call_id" not in normalized_body:
        normalized_body["call_id"] = "unknown"

    # 3. Check for Non-Function Events (e.g., call_analyzed)
    if "event" in normalized_body and normalized_body["event"] != "function_call":
        event_type = normalized_body["event"]
        logger.info(f"Received event '{event_type}' for agent {agent_id}")
        # Return 204 or simple OK for events
        return FunctionResponse(result="Event received")

    # 4. Validate with Model (Function Call)
    try:
        call = RetellFunctionCall(**normalized_body)
    except Exception as e:
        logger.error(f"Invalid webhook payload structure: {e}")
        raise HTTPException(status_code=400, detail=f"Schema validation failed: {str(e)}")
    
    return await _process_function_call(agent_id, call.function_name, call.arguments)


@router.post("/webhook/{agent_id}/{function_name}", response_model=FunctionResponse)
async def handle_specific_tool(agent_id: str, function_name: str, request: Request):
    """Specific endpoint for a named function."""
    body = _parse_json(await read_verified_body(request))
    logger.info(f"Specific tool call '{function_name}' for agent {agent_id}")

    # Normalize arguments from nested structure if needed
    arguments = body
    if "tool_call" in body and isinstance(body["tool_call"], dict):
         tool_call = body["tool_call"]
         arguments = _ensure_dict(tool_call.get("arguments", tool_call.get("args", {})))
    elif "args" in body:
        arguments = _ensure_dict(body["args"])
    elif "arguments" in body:
        arguments = _ensure_dict(body["arguments"])
    
    return await _process_function_call(agent_id, function_name, arguments)


async def _process_function_call(agent_id: str, function_name: str, arguments: dict):
    """Common logic for executing a function."""
    logger.info(f"Processing function: {function_name} for agent {agent_id}")
    logger.debug(f"Arguments for {function_name}: {arguments}")

    # Get Agent Config
    agent = await get_agent_config(agent_id)
    if not agent:
        logger.error(f"Agent {agent_id} not found in registry")
        return FunctionResponse(
            result="I'm having trouble accessing our systems right now. Please call back in a few minutes."
        )
    
    if not agent.active:
        logger.warning(f"Agent {agent_id} is inactive")
        return FunctionResponse(result="Our system is currently being updated. Please call back shortly.")
    
    # Find Function Config
    func_config = agent.functions.get(function_name)
    if not func_config:
        logger.error(f"Function {function_name} not registered for agent {agent_id}")
        return FunctionResponse(
            result="I'm not able to do that right now. Can I help you with something else?"
        )
    
    # Execute
    result = await execute_function(
        function_name=function_name,
        arguments=arguments,
        function_config=func_config,
    )
    
    return FunctionResponse(result=result)


@router.post("/admin/refresh-cache", dependencies=[Depends(require_admin)])
async def admin_refresh_cache():
    await refresh_cache()
    return {"status": "cache_cleared"}


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "nexqa-webhooks"}
