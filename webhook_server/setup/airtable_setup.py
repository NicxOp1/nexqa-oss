import asyncio
import aiohttp
import json
import os
from pathlib import Path
from webhook_server.config import settings
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AirtableSetup")

BASE_ID = settings.airtable_registry_base_id
API_KEY = settings.airtable_api_key

async def create_table(session, table_name, fields):
    url = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "name": table_name,
        "fields": fields,
        "description": f"NEXQA {table_name} Table"
    }
    
    try:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                logger.info(f"✅ Created table '{table_name}'")
                return True
            elif resp.status == 409:
                logger.info(f"ℹ️ Table '{table_name}' likely already exists (409 Conflict)")
                return True
            else:
                text = await resp.text()
                logger.warning(f"⚠️ Failed to create table '{table_name}' ({resp.status}): {text}")
                return False
    except Exception as e:
        logger.error(f"Error creating {table_name}: {e}")
        return False

async def seed_data(session):
    # Seed Patients
    patients_url = f"https://api.airtable.com/v0/{BASE_ID}/Patients"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 6 Test Patients
    patients = [
        {"fields": {"Name": "John Doe", "Phone": "+15550100", "Email": "john@example.com", "Insurance": "Delta Dental", "Last Visit": "2023-11-15", "Dentist": "Dr. Smith"}},
        {"fields": {"Name": "Jane Smith", "Phone": "+15550101", "Email": "jane@example.com", "Insurance": "Aetna", "Last Visit": "2024-01-20", "Dentist": "Dr. Lee"}},
        {"fields": {"Name": "Michael Johnson", "Phone": "+15550102", "Email": "mike@example.com", "Insurance": "None", "Last Visit": "2023-05-10", "Dentist": "Dr. Smith"}},
        {"fields": {"Name": "Emily Davis", "Phone": "+15550103", "Email": "emily@example.com", "Insurance": "Cigna", "Last Visit": "2024-02-01", "Notes": "Anxious patient"}},
        {"fields": {"Name": "Chris Wilson", "Phone": "+15550104", "Email": "chris@example.com", "Insurance": "MetLife", "Last Visit": "2023-12-05"}},
        {"fields": {"Name": "Sarah Brown", "Phone": "+15550105", "Email": "sarah@example.com", "Insurance": "Delta Dental", "Last Visit": "2023-10-30", "Dentist": "Dr. Lee"}}
    ]
    
    # Check if we should seed (simple check)
    async with session.get(patients_url, headers=headers, params={"maxRecords": 1}) as resp:
        if resp.status == 200:
            data = await resp.json()
            if len(data.get("records", [])) > 0:
                logger.info("ℹ️ Patients table already has data. Skipping seed.")
                return

    # Batch create
    for i in range(0, len(patients), 10):
        batch = patients[i:i+10]
        async with session.post(patients_url, headers=headers, json={"records": batch}) as resp:
            if resp.status == 200:
                logger.info(f"✅ Seeded {len(batch)} patients")
            else:
                logger.error(f"Failed to seed patients: {await resp.text()}")

async def main():
    if not API_KEY or not BASE_ID:
        logger.error("❌ Missing AIRTABLE_API_KEY or AIRTABLE_REGISTRY_BASE_ID in env")
        return

    logger.info(f"🔧 Setting up Airtable Base: {BASE_ID}")
    
    async with aiohttp.ClientSession() as session:
        # 1. AgentRegistry Table
        registry_fields = [
            {"name": "agent_id", "type": "singleLineText"},
            {"name": "agent_name", "type": "singleLineText"}, 
            {"name": "company_name", "type": "singleLineText"},
            {"name": "phone_number", "type": "singleLineText"},
            {"name": "functions_json", "type": "multilineText"},
            {"name": "credentials_json", "type": "multilineText"},
            {"name": "active", "type": "checkbox", "options": {"color": "greenBright", "icon": "check"}},
            {"name": "webhook_url", "type": "url"},
            {"name": "created_at", "type": "date", "options": {"dateFormat": {"name": "local"}}},
        ]
        await create_table(session, settings.airtable_registry_table, registry_fields)
        
        # 2. Patients Table
        patients_fields = [
            {"name": "Name", "type": "singleLineText"},
            {"name": "Phone", "type": "phoneNumber"},
            {"name": "Email", "type": "email"},
            {"name": "Insurance", "type": "singleLineText"},
            {"name": "Last Visit", "type": "date", "options": {"dateFormat": {"name": "local"}}},
            {"name": "Next Appointment", "type": "dateTime", "options": {"dateFormat": {"name": "local"}, "timeFormat": {"name": "12hour"}, "timeZone": "America/New_York"}},   
            {"name": "Dentist", "type": "singleLineText"},
            {"name": "Notes", "type": "multilineText"},
        ]
        await create_table(session, "Patients", patients_fields)
        
        # 3. Seed Data
        await seed_data(session)
        
    logger.info("✨ Airtable Setup Complete!")

if __name__ == "__main__":
    asyncio.run(main())
