"""
Mock Retell client for end-to-end testing without API calls.

Provides hardcoded patient records, availability, and booking/cancel/transfer
methods that mirror the real retell_client interface.
"""
from typing import Any, Dict, List


class MockRetellClient:
    """Replaces retell_client during dry-run testing."""

    def __init__(self) -> None:
        self.calls_made: List[Dict[str, Any]] = []
        self.agents_created: List[Dict[str, Any]] = []
        self.llms_created: List[Dict[str, Any]] = []

    # ─── Mock availability ──────────────────────────────────────────

    MOCK_AVAILABILITY: Dict[str, List[Dict[str, str]]] = {
        "2026-02-20": [
            {"time": "08:00", "dentist": "Dr. Park", "procedure": "emergency"},
            {"time": "11:00", "dentist": "Dr. Thompson", "procedure": "consultation"},
        ],
        "2026-02-21": [
            {"time": "09:30", "dentist": "Dr. Thompson", "procedure": "cleaning"},
            {"time": "11:00", "dentist": "Dr. Reyes", "procedure": "cleaning"},
        ],
        "2026-02-23": [
            {"time": "09:00", "dentist": "Dr. Reyes", "procedure": "any"},
            {"time": "10:00", "dentist": "Dr. Thompson", "procedure": "cleaning"},
            {"time": "11:30", "dentist": "Dr. Reyes", "procedure": "any"},
            {"time": "14:00", "dentist": "Dr. Park", "procedure": "extraction"},
        ],
        "2026-02-24": [
            {"time": "09:00", "dentist": "Dr. Thompson", "procedure": "cleaning"},
            {"time": "14:00", "dentist": "Dr. Thompson", "procedure": "cleaning"},
            {"time": "15:30", "dentist": "Dr. Reyes", "procedure": "any"},
        ],
    }

    # ─── Mock patient records ───────────────────────────────────────

    MOCK_PATIENTS: Dict[str, Dict[str, Any]] = {
        "david chen": {
            "patient_name": "David Chen",
            "last_visit": "2025-08-15",
            "insurance": "Delta Dental",
            "assigned_dentist": "Dr. Reyes",
            "next_appointment": "2026-02-21 10:00",
            "notes": "Cosmetic consultation follow-up",
        },
        "lisa nguyen": {
            "patient_name": "Lisa Nguyen",
            "last_visit": "2025-12-10",
            "insurance": "Cigna",
            "next_appointment": "2026-02-20 09:00",
            "notes": "Filling — Dr. Park",
        },
        "robert kim": {
            "patient_name": "Robert Kim",
            "last_visit": "2025-05-10",
            "insurance": "Aetna",
            "next_appointment": "2026-02-26 16:00",
            "notes": "Crown fitting — Dr. Park. Last cleaning: May 2025.",
        },
        "margaret wilson": {
            "patient_name": "Margaret Wilson",
            "last_visit": "2025-11-03",
            "insurance": "MetLife",
            "next_appointment": "2026-02-24 09:00",
            "notes": (
                "Denture adjustment — Dr. Thompson. Hard of hearing. "
                "Emergency contact: daughter Karen 813-555-0662"
            ),
        },
        "mark stevens": {
            "patient_name": "Mark Stevens",
            "last_visit": "2026-02-01",
            "insurance": "United Healthcare",
            "next_appointment": "2026-02-25 10:00",
            "notes": "Filling #14 — Dr. Reyes. Patient called about filling issue.",
        },
        "tom walsh": {
            "patient_name": "Tom Walsh",
            "last_visit": "2026-01-15",
            "insurance": "Guardian",
            "next_appointment": "2026-02-27 15:30",
            "notes": "Extraction — Dr. Park",
            "patient_id": "PAT-4821",
        },
    }

    # ─── Tool methods ───────────────────────────────────────────────

    def check_availability(self, date: str, **kwargs: Any) -> List[Dict[str, str]]:
        return self.MOCK_AVAILABILITY.get(date, [])

    def check_patient_record(
        self, patient_name: str = "", patient_phone: str = ""
    ) -> Dict[str, Any]:
        key = patient_name.lower().strip()
        return self.MOCK_PATIENTS.get(key, {"error": "Patient not found"})

    def book_appointment(self, **kwargs: Any) -> Dict[str, Any]:
        name = kwargs.get("patient_name", "")
        conf = f"BSD-{kwargs.get('date', '').replace('-', '')}-{abs(hash(name)) % 10000:04d}"
        self.calls_made.append({"action": "book", **kwargs})
        return {
            "confirmation": conf,
            "summary": f"{kwargs.get('procedure_type')} with {kwargs.get('dentist')}",
        }

    def cancel_appointment(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls_made.append({"action": "cancel", **kwargs})
        return {"status": "cancelled", "fee": "none"}

    def transfer_call(self, department: str, reason: str) -> Dict[str, Any]:
        self.calls_made.append(
            {"action": "transfer", "department": department, "reason": reason}
        )
        return {"status": "transferring"}

    def create_retell_llm(self, general_prompt: str, **kwargs: Any) -> Dict[str, str]:
        llm_id = f"llm_mock_{len(self.llms_created) + 1}"
        self.llms_created.append(
            {"llm_id": llm_id, "prompt_length": len(general_prompt)}
        )
        return {"llm_id": llm_id}

    def create_agent(
        self, agent_name: str, voice_id: str, llm_config: Dict[str, Any], **kwargs: Any
    ) -> Dict[str, str]:
        agent_id = f"agent_mock_{len(self.agents_created) + 1}"
        self.agents_created.append({"agent_id": agent_id, "name": agent_name})
        return {"agent_id": agent_id, "agent_name": agent_name}
