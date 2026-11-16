"""
Webhook Validator — Direct HTTP testing for agent tools.

Pings each tool endpoint on the running webhook server with realistic payloads
to verify they return 200 OK and valid JSON structure.
Critical for debugging "loop" errors in Retell batch tests (often caused by silent 500s).

Usage:
    from nexqa.core.webhook_validator import WebhookValidator
    validator = WebhookValidator()
    results = await validator.validate_all("agent_xxx", tools_map)
"""
import time
import requests
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from nexqa.storage.config import Config

logger = logging.getLogger(__name__)

class WebhookTestResult(BaseModel):
    tool: str
    status: int
    passed: bool
    response_time_ms: float
    error: Optional[str] = None
    response_body: Optional[Dict[str, Any]] = None

class WebhookValidator:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or Config.WEBHOOK_BASE_URL).rstrip("/")

    def validate_all(self, agent_id: str, tools: List[str]) -> List[WebhookTestResult]:
        """Validate a list of tools for a given agent."""
        results = []
        logger.info(f"Validating webhooks for agent {agent_id} on {self.base_url}")
        
        for tool_name in tools:
            # Skip built-in Retell tools that don't hit our webhook
            if tool_name in ["end_call", "transfer_call_native"]: 
                continue

            # Generate payload based on tool name
            payload = self._generate_payload(tool_name)
            
            url = f"{self.base_url}/webhook/{agent_id}/{tool_name}"
            start = time.time()
            try:
                # 10s timeout to catch slow cold starts but fail if hung
                resp = requests.post(url, json=payload, timeout=10)
                duration = (time.time() - start) * 1000
                
                passed = resp.status_code == 200 and "result" in resp.json()
                error = None
                if not passed:
                    error = f"Status {resp.status_code}"
                    if resp.status_code == 200:
                         error += " (missing 'result' field)"
                    else:
                         try:
                             error += f": {resp.text[:200]}"
                         except:
                             pass

                results.append(WebhookTestResult(
                    tool=tool_name,
                    status=resp.status_code,
                    passed=passed,
                    response_time_ms=duration,
                    response_body=resp.json() if passed else None,
                    error=error
                ))
                logger.info(f"  {tool_name}: {'PASS' if passed else 'FAIL'} ({int(duration)}ms)")
                
            except Exception as e:
                duration = (time.time() - start) * 1000
                logger.error(f"  {tool_name}: ERROR {e}")
                results.append(WebhookTestResult(
                    tool=tool_name,
                    status=0,
                    passed=False,
                    response_time_ms=duration,
                    error=str(e)
                ))

        return results

    def _generate_payload(self, tool_name: str) -> Dict[str, Any]:
        """Generate realistic test payloads for dental agent tools."""
        today = "2026-03-04" 
        
        if tool_name == "get_current_time":
            return {}
            
        if tool_name == "check_availability":
            return {
                "date": today,
                "dentist": "Dr. Thompson",
                "procedure_type": "checkup"
            }
            
        if tool_name == "book_appointment":
            return {
                "date": today,
                "time": "14:00",
                "patient_name": "Test Patient",
                "patient_phone": "+15550000000",
                "email": "test@example.com",
                "procedure_type": "cleaning",
                "dentist": "Dr. Thompson"
            }
            
        if tool_name == "check_patient_record":
            return {
                "patient_name": "John Doe",
                "patient_phone": "+15551234567"
            }
            
        if tool_name == "cancel_appointment":
            return {
                "confirmation_number": "BK-TEST-123",
                "patient_name": "Test Patient",
                "reason": "Test cancellation"
            }
            
        if tool_name == "transfer_call":
             return {
                 "department": "billing",
                 "reason": "Test transfer"
             }

        # Default fallback
        return {}
