"""
NEXQA API — Run Orchestration

Trigger QA runs, optimization loops, and human testing sessions.
Runs are persisted to MongoDB (collection: nexqa_runs).
Engine runs as asyncio.create_task() to avoid blocking the endpoint.
"""

import asyncio
import json
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nexqa.core.engine import engine, RunResult
from nexqa.storage.config import Config
from nexqa.storage.database import get_db, with_mongo_retry, MONGO_TRANSIENT_ERRORS
from nexqa.storage.logger import logger
from pathlib import Path


router = APIRouter()

# MongoDB collection name
COLLECTION = "nexqa_runs"


class RunRequest(BaseModel):
    agent_id: str
    spec_path: Optional[str] = None
    spec_json: Optional[Dict[str, Any]] = None
    workspace_id: Optional[str] = None


def _run_to_doc(run_id: str, result: RunResult, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Convert RunResult to a MongoDB document."""
    return {
        "run_id": run_id,
        "workspace_id": workspace_id or "",
        "agent_id": result.agent_id,
        "status": result.action,
        "success": result.success,
        "final_score": result.final_score,
        "total_iterations": result.total_iterations,
        "iterations": [
            {
                "iteration": it.iteration,
                "avg_score": it.avg_score,
                "error_count": it.error_count,
                "action": it.action,
            }
            for it in result.iterations
        ],
        "scores": result.cost_metrics,
        "error": result.error,
        "created_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
    }


@router.post("/")
async def start_qa_run(req: RunRequest):
    """Start a full QA run as an async background task.

    Accepts either spec_path (filesystem path for CLI) or spec_json
    (inline JSON object from Hermes). If both are provided, spec_json
    takes priority.
    """
    if not req.spec_path and not req.spec_json:
        raise HTTPException(
            status_code=400,
            detail="Either spec_path or spec_json is required",
        )

    run_id = f"run_{req.agent_id}_{int(time.time())}"
    db = get_db()

    # Insert initial pending record. Retry transient Atlas failovers instead of
    # bubbling a raw 500 — if the primary is genuinely unreachable after the
    # retries, return 503 so the calling app shows "temporarily unavailable"
    # rather than a hard error.
    pending_doc = {
        "run_id": run_id,
        "workspace_id": req.workspace_id or "",
        "agent_id": req.agent_id,
        "status": "running",
        "success": False,
        "final_score": 0.0,
        "total_iterations": 0,
        "iterations": [],
        "scores": {},
        "error": None,
        "created_at": datetime.now(timezone.utc),
        "completed_at": None,
    }
    try:
        await with_mongo_retry(lambda: db[COLLECTION].insert_one(pending_doc))
    except MONGO_TRANSIENT_ERRORS as exc:
        logger.error(f"Could not persist run {run_id} (DB failover): {exc}")
        raise HTTPException(
            status_code=503,
            detail="Database is failing over — please retry the validation in a moment.",
        )

    # Fire-and-forget async task (non-blocking)
    asyncio.create_task(
        _execute_run(run_id, req.agent_id, req.spec_path, req.workspace_id, req.spec_json)
    )

    return {"run_id": run_id, "status": "running"}


@router.get("/{run_id}")
async def get_run_status(run_id: str):
    """Check status of a QA run from MongoDB."""
    db = get_db()
    doc = await db[COLLECTION].find_one(
        {"run_id": run_id},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Run not found")
    return doc


@router.get("/")
async def list_runs(workspace_id: Optional[str] = None, limit: int = 20):
    """List recent runs, optionally filtered by workspace."""
    try:
        db = get_db()
        query: Dict[str, Any] = {}
        if workspace_id:
            query["workspace_id"] = workspace_id

        cursor = db[COLLECTION].find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        return [doc async for doc in cursor]
    except Exception as e:
        logger.error(f"list_runs error: {e}")
        raise


async def _execute_run(
    run_id: str,
    agent_id: str,
    spec_path: Optional[str] = None,
    workspace_id: Optional[str] = None,
    spec_json: Optional[Dict[str, Any]] = None,
) -> None:
    """Async wrapper that runs engine.run_async() and persists result to MongoDB.

    Supports two modes:
    - spec_json: inline JSON spec from Hermes (written to temp file for engine)
    - spec_path: filesystem path for CLI usage
    """
    db = get_db()
    logger.info(f"Starting run {run_id} via API")

    try:
        if spec_json:
            # Write inline spec to a temp file so the engine can ingest it
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            json.dump(spec_json, tmp)
            tmp.close()
            path = Path(tmp.name)
            logger.info(f"Spec JSON written to temp file: {path}")
        elif spec_path:
            path = Path(spec_path)
            if not path.exists():
                raise FileNotFoundError(f"Spec not found: {spec_path}")
        else:
            raise ValueError("No spec provided (need spec_json or spec_path)")

        result = await engine.run_async(agent_id, path)

        doc = _run_to_doc(run_id, result, workspace_id)
        await with_mongo_retry(
            lambda: db[COLLECTION].replace_one({"run_id": run_id}, doc, upsert=True)
        )
        logger.info(f"Run {run_id} completed: {result.success}")

    except Exception as e:
        logger.error(f"Run {run_id} crashed: {e}")
        # Best-effort failure write — also retried so a failover during the run
        # doesn't leave the record stuck in "running" forever.
        try:
            await with_mongo_retry(
                lambda: db[COLLECTION].update_one(
                    {"run_id": run_id},
                    {"$set": {
                        "status": "failed",
                        "error": str(e),
                        "completed_at": datetime.now(timezone.utc),
                    }},
                )
            )
        except Exception as persist_err:
            logger.error(f"Run {run_id} failure-status write also failed: {persist_err}")
