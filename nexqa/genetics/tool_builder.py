"""
NEXQA v1.0 — Tool Builder

Converts tool descriptions from agent spec YAML into Retell's
`general_tools` format for the LLM API.

CRITICAL: In Retell's architecture, tools are configured on the LLM
(via POST /create-retell-llm), NOT on the agent. This module produces
the general_tools array that feeds into retell_client.create_retell_llm().

Retell tool types:
  - end_call: End the current call
  - transfer_call: Transfer to another number
  - book_appointment_cal: Cal.com booking
  - check_availability_cal: Cal.com availability check
  - send_sms: Send an SMS via Twilio
  - agent_transfer: Transfer to another Retell agent
  - setup_mcp: MCP server integration
  - custom: Custom webhook-based tool (most common)

Usage:
    from nexqa.genetics.tool_builder import tool_builder

    retell_tools = tool_builder.build(spec_tools)
    # → Pass to retell_client.create_retell_llm(general_tools=retell_tools)
"""

from typing import Any, Dict, List, Optional

from nexqa.storage.logger import logger


class ToolBuilder:
    """Converts spec tool definitions into Retell general_tools format."""

    # Retell built-in tool types (no webhook needed)
    BUILT_IN_TYPES = {
        "end_call",
        "transfer_call",
        "book_appointment_cal",
        "check_availability_cal",
        "send_sms",
        "agent_transfer",
        "setup_mcp",
    }

    def build(
        self,
        tools: List[Dict[str, Any]],
        webhook_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Convert spec tool definitions to Retell general_tools format.

        Args:
            tools: List of tool dicts from the agent spec YAML.
            webhook_url: Default webhook URL for custom tools.

        Returns:
            List of Retell-formatted general_tools.
        """
        retell_tools: List[Dict[str, Any]] = []

        for tool_def in tools:
            tool_type = tool_def.get("type", "custom")
            name = tool_def.get("name", "")

            if tool_type in self.BUILT_IN_TYPES:
                retell_tool = self._build_builtin(tool_def, tool_type)
            else:
                retell_tool = self._build_custom(tool_def, webhook_url)

            if retell_tool:
                retell_tools.append(retell_tool)
                logger.debug(f"Built tool: {name} (type={tool_type})")

        logger.info(f"Built {len(retell_tools)} Retell tools from spec")
        return retell_tools

    # ─── Built-in Tool Builders ──────────────────────────────────────

    def _build_builtin(
        self, tool_def: Dict[str, Any], tool_type: str
    ) -> Dict[str, Any]:
        """Build a Retell built-in tool."""
        base: Dict[str, Any] = {"type": tool_type}

        if tool_type == "end_call":
            return base

        if tool_type == "transfer_call":
            number = tool_def.get("transfer_number", "")
            result: Dict[str, Any] = {
                "type": "transfer_call",
                "name": tool_def.get("name", "transfer_call"),
                "description": tool_def.get(
                    "description", "Transfer the call"
                ),
                "number": number,
            }
            return result

        if tool_type == "send_sms":
            return {
                "type": "send_sms",
                "name": tool_def.get("name", "send_sms"),
                "description": tool_def.get(
                    "description", "Send SMS to caller"
                ),
            }

        if tool_type == "agent_transfer":
            return {
                "type": "agent_transfer",
                "name": tool_def.get("name", "agent_transfer"),
                "description": tool_def.get(
                    "description", "Transfer to another agent"
                ),
                "agent_id": tool_def.get("agent_id", ""),
            }

        if tool_type in ("book_appointment_cal", "check_availability_cal"):
            return {
                "type": tool_type,
                "name": tool_def.get("name", tool_type),
                "description": tool_def.get("description", ""),
                "cal_api_key": tool_def.get("cal_api_key", ""),
                "event_type_id": tool_def.get("event_type_id", ""),
            }

        # Generic built-in fallback
        return base

    # ─── Custom Tool Builder ─────────────────────────────────────────

    def _build_custom(
        self,
        tool_def: Dict[str, Any],
        default_webhook_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a custom Retell tool (webhook-based)."""
        name = tool_def.get("name", "")
        if not name:
            logger.warning("Skipping tool with no name")
            return None

        description = tool_def.get("description", "")
        
        # Determine URL: explicit tool URL > compiled default URL/{name}
        webhook_url = tool_def.get("url")
        if not webhook_url and default_webhook_url:
             webhook_url = f"{default_webhook_url.rstrip('/')}/{name}"

        result: Dict[str, Any] = {
            "type": "custom",
            "name": name,
            "description": description,
            "url": webhook_url,
        }

        # Build parameters in JSON Schema format
        params = tool_def.get("parameters", {})
        if params:
            properties: Dict[str, Any] = {}
            required: List[str] = []

            # Handle list-of-dicts format: [{name, type, description, required}, ...]
            if isinstance(params, list):
                for p in params:
                    p_name = p.get("name", "")
                    if not p_name:
                        continue
                    properties[p_name] = {
                        "type": p.get("type", "string"),
                        "description": p.get("description", ""),
                    }
                    if p.get("required", True):
                        required.append(p_name)
            # Handle dict-of-dicts format: {param_name: {type, description, required}, ...}
            elif isinstance(params, dict):
                for param_name, param_def in params.items():
                    if isinstance(param_def, dict):
                        prop: Dict[str, Any] = {
                            "type": param_def.get("type", "string"),
                            "description": param_def.get("description", ""),
                        }
                        properties[param_name] = prop

                        if param_def.get("required", True):
                            required.append(param_name)
                    else:
                        # Simple string definition
                        properties[param_name] = {
                            "type": "string",
                            "description": str(param_def),
                        }
                        required.append(param_name)

            result["parameters"] = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

        # Webhook URL
        if webhook_url:
            result["url"] = webhook_url

        # Speak during execution
        speak = tool_def.get("speak_during_execution", False)
        if speak:
            result["speak_during_execution"] = True
            speak_msg = tool_def.get("speak_message", "")
            if speak_msg:
                result["execution_message_description"] = speak_msg

        # Timeout
        timeout = tool_def.get("timeout_ms")
        if timeout:
            result["timeout_ms"] = timeout

        return result

    # ─── Convenience ─────────────────────────────────────────────────

    def build_from_spec(
        self,
        spec: Dict[str, Any],
        webhook_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract and build tools from a full spec dictionary.

        Args:
            spec: The full agent spec YAML dict.
            webhook_url: Default webhook URL for custom tools.

        Returns:
            List of Retell-formatted general_tools.
        """
        tools = spec.get("tools", [])
        if not tools:
            logger.info("No tools found in spec")
            return []

        return self.build(tools, webhook_url)


# Module-level singleton
tool_builder = ToolBuilder()
