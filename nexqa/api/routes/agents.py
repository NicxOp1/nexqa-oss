"""
NEXQA API — Agent Management

Wraps Retell Client for agent CRUD operations.
"""

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException

from nexqa.integrations.retell_client import retell_client
from nexqa.genetics.gene_parser import gene_parser
from nexqa.storage.logger import logger


router = APIRouter()


@router.get("/", response_model=List[Dict[str, Any]])
def list_agents():
    """List all available agents from Retell."""
    try:
        return retell_client.list_agents()
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}", response_model=Dict[str, Any])
def get_agent(agent_id: str):
    """Get single agent details."""
    try:
        return retell_client.get_agent(agent_id)
    except Exception as e:
        logger.error(f"Failed to get agent {agent_id}: {e}")
        raise HTTPException(status_code=404, detail="Agent not found")


@router.get("/{agent_id}/prompt")
def get_prompt_genes(agent_id: str):
    """Get current prompt parsed as Genes."""
    try:
        current_prompt = retell_client.get_current_prompt(agent_id)
        if not current_prompt:
            return {"genes": []}
        gene_set = gene_parser.parse(current_prompt)
        # Return serialized XML or JSON representation of genes
        return {"xml": current_prompt, "genes": [g.dict() for g in gene_set.genes]}
    except Exception as e:
        logger.error(f"Failed to fetch prompt for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
