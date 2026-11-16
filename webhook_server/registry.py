import json
import logging
import asyncio
from typing import Optional, Dict
from datetime import datetime
from webhook_server.models import AgentRegistry, FunctionConfig, ConnectorType
from webhook_server.config import settings

logger = logging.getLogger(__name__)

_agent_cache: Dict[str, AgentRegistry] = {}
_cache_lock: asyncio.Lock = asyncio.Lock()


async def get_agent_config(agent_id: str) -> Optional[AgentRegistry]:
    """
    Retrieve agent configuration from cache or Airtable.
    Thread-safe via asyncio.Lock on cache reads/writes.
    """
    async with _cache_lock:
        if agent_id in _agent_cache:
            return _agent_cache[agent_id]

    try:
        import aiohttp

        base_id = settings.airtable_registry_base_id
        table = settings.airtable_registry_table
        api_key = settings.airtable_api_key

        url = f"https://api.airtable.com/v0/{base_id}/{table}"
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {"filterByFormula": f"{{agent_id}}='{agent_id}'"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Airtable registry error {resp.status}: {await resp.text()}")
                    return None
                data = await resp.json()

        records = data.get("records", [])
        if not records:
            logger.warning(f"Agent {agent_id} not found in registry (Base: {base_id})")
            return None

        fields = records[0]["fields"]

        functions_raw = json.loads(fields.get("functions_json", "{}"))
        functions = {
            name: FunctionConfig(
                connector=ConnectorType(cfg["connector"]),
                config=cfg.get("config", {}),
            )
            for name, cfg in functions_raw.items()
        }

        agent = AgentRegistry(
            agent_id=agent_id,
            agent_name=fields.get("agent_name", ""),
            company_name=fields.get("company_name", ""),
            phone_number=fields.get("phone_number", ""),
            functions=functions,
            credentials=json.loads(fields.get("credentials_json", "{}")),
            active=fields.get("active", True),
        )

        async with _cache_lock:
            _agent_cache[agent_id] = agent
        logger.info(f"Loaded config for agent {agent_id} ({agent.agent_name})")
        return agent

    except Exception as e:
        logger.error(f"Failed to load agent {agent_id} from registry: {e}")
        return None


async def refresh_cache():
    """Clear the cache to force re-fetch from Airtable."""
    async with _cache_lock:
        _agent_cache.clear()
    logger.info("Agent registry cache cleared")


async def register_agent(agent: AgentRegistry) -> bool:
    """
    Register a new agent in Airtable.
    Called by NEXQA's `nexqa create --deploy` command.
    """
    try:
        import aiohttp

        url = f"https://api.airtable.com/v0/{settings.airtable_registry_base_id}/{settings.airtable_registry_table}"
        headers = {
            "Authorization": f"Bearer {settings.airtable_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "records": [{
                "fields": {
                    "agent_id": agent.agent_id,
                    "agent_name": agent.agent_name,
                    "company_name": agent.company_name,
                    "phone_number": agent.phone_number,
                    "functions_json": json.dumps({
                        name: {"connector": cfg.connector.value, "config": cfg.config}
                        for name, cfg in agent.functions.items()
                    }),
                    "credentials_json": json.dumps(agent.credentials),
                    "active": agent.active,
                    "webhook_url": f"{settings.public_base_url.rstrip('/')}/webhook/{agent.agent_id}",
                    "created_at": agent.created_at.strftime("%Y-%m-%d"),
                }
            }]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    logger.info(f"Registered agent {agent.agent_id} in registry")
                    async with _cache_lock:
                        _agent_cache[agent.agent_id] = agent
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Failed to register agent: {error}")
                    return False

    except Exception as e:
        logger.error(f"Failed to register agent {agent.agent_id}: {e}")
        return False
