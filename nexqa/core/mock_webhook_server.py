"""
NEXQA Mock Webhook Server — For Retell Batch Testing

This FastAPI server exposes public endpoints that return IDEAL responses
for each dental agent tool. It's started locally and exposed via ngrok/localtunnel
so Retell can call it during batch simulation tests.

Usage:
    python nexqa/core/mock_webhook_server.py
    # Then in another terminal:
    # ngrok http 8765
    # Use the ngrok URL in nexqa run --mock-webhook-url https://xxxx.ngrok.io

The server reads mock responses from the spec's tool_mocks.default section.
"""
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from nexqa.storage.logger import logger

app = FastAPI(title="NEXQA Mock Webhook Server")

# ── Dental Agent Mock Responses ──────────────────────────────────────────────
# These mimic IDEAL tool responses for QA testing purposes.

MOCK_RESPONSES = {
    "check_availability": {
        "slots": [
            {"date": "Tuesday March 4th", "time": "2:00 PM", "dentist": "Dr. Thompson", "duration": 60},
            {"date": "Wednesday March 5th", "time": "10:00 AM", "dentist": "Dr. Park", "duration": 30},
            {"date": "Thursday March 6th", "time": "9:00 AM", "dentist": "Dr. Reyes", "duration": 45},
        ]
    },
    "book_appointment": {
        "success": True,
        "confirmation_number": "BK-20260304-001",
        "summary": "Appointment confirmed with Dr. Thompson on Tuesday March 4th at 2:00 PM.",
        "reminder_sent": True,
    },
    "check_patient_record": {
        "found": True,
        "name": "John Smith",
        "last_visit": "2025-09-12",
        "insurance": "Delta Dental",
        "dentist": "Dr. Thompson",
        "overdue_cleaning": True,
        "months_since_visit": 6,
        "notes": "Prefers morning appointments.",
    },
    "cancel_appointment": {
        "cancelled": True,
        "confirmation_number": "BK-20260304-001",
        "cancellation_fee": 0,
        "message": "Appointment cancelled successfully. No fee applied.",
    },
    "transfer_call": {
        "transferred": True,
        "department": "requested_department",
        "status": "connecting",
    },
}


@app.get("/health")
async def health():
    return {"status": "ok", "server": "NEXQA Mock Webhook"}


@app.post("/webhook/{agent_id}/{tool_name}")
async def mock_tool(agent_id: str, tool_name: str, request: Request):
    """Universal mock endpoint — accepts any tool call, returns ideal response."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    logger.info(f"[Mock] Tool called: {tool_name} | Agent: {agent_id} | Payload: {body}")

    response = MOCK_RESPONSES.get(tool_name)
    if response is None:
        # Generic success for unknown tools
        response = {"success": True, "tool": tool_name, "message": "Completed successfully."}

    # For transfer_call, echo back the requested department
    if tool_name == "transfer_call" and "department" in body:
        response = dict(response)
        response["department"] = body["department"]

    return JSONResponse(content=response)


@app.post("/tools/{tool_name}")
async def mock_tool_simple(tool_name: str, request: Request):
    """Alternative simple path without agent_id."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    logger.info(f"[Mock] Tool called: {tool_name} | Payload: {body}")
    response = MOCK_RESPONSES.get(tool_name, {"success": True})
    return JSONResponse(content=response)


if __name__ == "__main__":
    print("Starting NEXQA Mock Webhook Server on port 8765")
    print("Expose publicly with: ngrok http 8765")
    print("Then set --mock-webhook-url https://YOUR-NGROK-URL.ngrok.io")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
