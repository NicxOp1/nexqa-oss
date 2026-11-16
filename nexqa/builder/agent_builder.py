"""
NEXQA v1.0 — Agent Builder

Programmatically deploys Retell agents and custom tools from a YAML specification.
Reads `agents/*.yaml`, registers Supabase/n8n/transfer tools in Retell, and 
binds them to a new/existing LLM.
"""

import os
import yaml
import requests
from typing import Dict, Any, List, Optional
from nexqa.integrations.retell_client import RetellClient
from nexqa.storage.logger import logger

class AgentBuilder:
    def __init__(self):
        self.retell = RetellClient()

    def build_from_spec(self, yaml_path: str) -> Optional[Dict[str, Any]]:
        """Parses a YAML spec and builds the custom tools and LLM in Retell."""
        if not os.path.exists(yaml_path):
            logger.error(f"Spec file not found: {yaml_path}")
            return None

        with open(yaml_path, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)

        agent_name = spec.get("agent_name", "NEXQA Agent")
        llm_model = spec.get("llm_model", "gpt-4o")
        prompt = spec.get("prompt", "")
        tools_definition = spec.get("tools", [])

        # 1. Provision the LLM and bind the tools directly in the payload
        try:
            logger.info(f"Creating LLM: {agent_name} with {len(tools_definition)} inline tools attached.")
            resp = self.retell.create_retell_llm(
                model=llm_model,
                general_prompt=prompt,
                general_tools=tools_definition,
                starting_state="default",
                states=[
                    {
                        "name": "default",
                        "state_prompt": "You are connected to the user."
                    }
                ]
            )
            llm_id = resp.get("llm_id")
            logger.info(f"Successfully created LLM: {llm_id}")
            return resp
        except Exception as e:
            logger.error(f"Failed to create LLM: {e}")
            print(f"FAILED TO CREATE LLM: {e}")
            return None

builder = AgentBuilder()
