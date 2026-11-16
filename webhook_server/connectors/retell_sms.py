"""
Retell native SMS connector for sending confirmation/cancellation texts.

Uses Retell's POST /create-sms-chat endpoint to send outbound SMS from 
the same Retell number used for voice calls. Patient gets call + text 
from the SAME number.

This connector is typically called BY other connectors (e.g., Cal.com
sends SMS after booking). It can also be called directly as a function.

Requires:
- Retell API key (RETELL_API_KEY env var)
- A Retell phone number with SMS capability enabled
"""
import logging
from typing import Any, Optional
import aiohttp
from webhook_server.connectors.base import BaseConnector
from webhook_server.config import settings

logger = logging.getLogger(__name__)


class RetellSMSConnector(BaseConnector):
    connector_type = "retell_sms"
    
    async def execute(self, function_name: str, arguments: dict[str, Any], config: dict[str, Any]) -> str:
        """Direct function call — send SMS from voice agent via Retell."""
        to_number = arguments.get("phone_number", arguments.get("patient_phone", ""))
        from_number = config.get("from_number", arguments.get("from_number", ""))
        
        if not to_number:
            return "I need a phone number to send the text to."
        
        dynamic_vars = {
            k: v for k, v in arguments.items() 
            if k not in ("phone_number", "patient_phone", "from_number")
        }
        
        success = await self.send_confirmation(
            from_number=from_number,
            to_number=to_number,
            dynamic_variables=dynamic_vars,
            sms_agent_id=config.get("sms_agent_id"),
        )
        
        if success:
            return "I've sent a text message confirmation."
        else:
            return "I wasn't able to send the text right now, but your appointment is still confirmed."
    
    async def send_confirmation(
        self,
        from_number: str,
        to_number: str,
        dynamic_variables: dict[str, str],
        sms_agent_id: Optional[str] = None,
    ) -> bool:
        """
        Send an outbound SMS via Retell's native endpoint.
        
        POST https://api.retellai.com/v2/create-sms-chat
        
        Args:
            from_number: Retell number with SMS capability (E.164)
            to_number: Recipient phone number (E.164)
            dynamic_variables: Variables injected into the SMS agent prompt
            sms_agent_id: Optional override for SMS chat agent
            
        Returns:
            True if SMS was queued successfully
        """
        if not from_number:
            logger.error("No from_number configured for Retell SMS")
            return False
        
        url = "https://api.retellai.com/v2/create-sms-chat"
        headers = {
            "Authorization": f"Bearer {settings.retell_api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "from_number": from_number,
            "to_number": to_number,
            "retell_llm_dynamic_variables": {
                k: str(v) for k, v in dynamic_variables.items()
            },
        }
        
        if sms_agent_id:
            payload["override_agent_id"] = sms_agent_id
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        chat_id = data.get("chat_id", "unknown")
                        logger.info(f"Retell SMS sent to {to_number}: chat_id={chat_id}")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Retell SMS failed ({resp.status}): {error}")
                        return False
                        
        except Exception as e:
            logger.error(f"Retell SMS request failed to {to_number}: {e}")
            return False
