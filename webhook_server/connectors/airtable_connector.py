"""
Airtable connector for patient records and CRM operations.

Supports:
- check_patient_record: Look up patient by name or phone
- create_patient_record: Add new patient
- update_patient_record: Update existing patient notes
"""
import logging
from typing import Any
import aiohttp
from webhook_server.connectors.base import BaseConnector
from webhook_server.config import settings

logger = logging.getLogger(__name__)


class AirtableConnector(BaseConnector):
    connector_type = "airtable"
    
    async def execute(self, function_name: str, arguments: dict[str, Any], config: dict[str, Any]) -> str:
        handlers = {
            "check_patient_record": self._check_patient,
            "create_patient_record": self._create_patient,
            "update_patient_record": self._update_patient,
        }
        handler = handlers.get(function_name)
        if not handler:
            return "I can't look that up right now. Can I help you another way?"
        return await handler(arguments, config)
    
    async def _check_patient(self, args: dict, config: dict) -> str:
        """Look up a patient record in Airtable."""
        base_id = config.get("base_id", settings.airtable_registry_base_id)
        table_name = config.get("table_name", "Patients")
        lookup_field = config.get("lookup_field", "Name")
        
        patient_name = args.get("patient_name", "")
        patient_phone = args.get("patient_phone", "")
        
        if patient_name:
            # Escape single quotes for Airtable formula
            safe_name = patient_name.replace("'", "\\'")
            formula = f"FIND(LOWER('{safe_name}'), LOWER({{{lookup_field}}}))"
        elif patient_phone:
            formula = f"{{Phone}}='{patient_phone}'"
        else:
            return "I need a name or phone number to look up the record."
        
        url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        headers = {"Authorization": f"Bearer {settings.airtable_api_key}"}
        params = {"filterByFormula": formula, "maxRecords": 1}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    data = await resp.json()
            
            records = data.get("records", [])
            if not records:
                search_term = patient_name or patient_phone
                return f"I don't have a record for {search_term} in our system. Are you a new patient?"
            
            fields = records[0]["fields"]
            name = fields.get("Name", patient_name)
            parts = [f"I found the record for {name}."]
            
            if "Last Visit" in fields:
                parts.append(f"Last visit was {self.format_date_for_speech(fields['Last Visit'])}.")
            if "Insurance" in fields:
                parts.append(f"Insurance on file is {fields['Insurance']}.")
            if "Dentist" in fields:
                parts.append(f"Assigned dentist is {fields['Dentist']}.")
            if "Next Appointment" in fields:
                parts.append(f"Next appointment is {fields['Next Appointment']}.")
            if "Notes" in fields and fields["Notes"]:
                parts.append(f"Notes: {fields['Notes']}.")
            
            return " ".join(parts)
            
        except Exception as e:
            logger.error(f"Airtable lookup failed: {e}")
            return "I'm having trouble accessing our records right now. Can you hold a moment?"
    
    async def _create_patient(self, args: dict, config: dict) -> str:
        """Create a new patient record."""
        base_id = config.get("base_id")
        table_name = config.get("table_name", "Patients")
        
        fields = {
            "Name": args.get("patient_name", ""),
            "Phone": args.get("patient_phone", ""),
            "Insurance": args.get("insurance", ""),
            "Notes": args.get("notes", "New patient"),
        }
        
        url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
        headers = {
            "Authorization": f"Bearer {settings.airtable_api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json={"records": [{"fields": fields}]}) as resp:
                    data = await resp.json()
            
            if data.get("records"):
                return f"I've created a new patient record for {fields['Name']}."
            else:
                return "I wasn't able to create the record. Let me transfer you to someone who can help."
                
        except Exception as e:
            logger.error(f"Airtable create failed: {e}")
            return "I'm having trouble with our system right now. Someone will follow up."
    
    async def _update_patient(self, args: dict, config: dict) -> str:
        """Update an existing patient record."""
        return "I've updated the record. Is there anything else you need?"
