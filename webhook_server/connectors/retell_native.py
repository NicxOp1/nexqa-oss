"""
Retell native connector for transfer_call and end_call.
Maps department names to real phone numbers from the config.
"""
import logging
from typing import Any
from webhook_server.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class RetellNativeConnector(BaseConnector):
    connector_type = "retell_native"
    
    async def execute(self, function_name: str, arguments: dict[str, Any], config: dict[str, Any]) -> str:
        if function_name == "transfer_call":
            return await self._transfer_call(arguments, config)
        elif function_name == "end_call":
            return "Thank you for calling. Goodbye!"
        else:
            return "I'm not sure how to handle that request."
    
    async def _transfer_call(self, args: dict, config: dict) -> str:
        department = args.get("department", "")
        departments = config.get("departments", {})
        
        target_number = departments.get(department)
        if not target_number:
            logger.warning(f"Unknown department: {department}")
            return f"I'm not able to transfer to {department} right now. Can I help you another way?"
        
        return f"Transferring you to {department.replace('_', ' ')} now."
