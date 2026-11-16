"""
NEXQA v1.0 — Airtable Reporter

Syncs test results and optimization history to Airtable for visibility.
"""

from typing import Any, Dict, List
import datetime

import requests

from nexqa.models.scenario_models import EvaluationResult
from nexqa.storage.config import Config
from nexqa.storage.logger import logger


class AirtableReporter:
    """Uploads QA run data to Airtable."""

    def __init__(self) -> None:
        self.api_key = Config.AIRTABLE_API_KEY
        self.base_id = Config.AIRTABLE_BASE_ID
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def sync_run(self, run_result: Dict[str, Any]) -> None:
        """Push a RunResult to the 'QA Runs' table."""
        if not self.api_key or not self.base_id:
            logger.warning("Airtable not configured. Skipping sync.")
            return

        table_name = "QA Runs"
        url = f"https://api.airtable.com/v0/{self.base_id}/{table_name}"
        
        # Flatten metrics for Airtable
        fields = {
            "Run ID": run_result.get("run_id", "unknown"),
            "Agent ID": run_result.get("agent_id"),
            "Status": run_result.get("action"),
            "Score": run_result.get("final_score"),
            "Iterations": run_result.get("total_iterations"),
            "Cost": run_result.get("cost_metrics", {}).get("total_cost_usd", 0.0),
            "Timestamp": datetime.datetime.now().isoformat(),
        }

        try:
            resp = requests.post(url, headers=self.headers, json={"fields": fields})
            resp.raise_for_status()
            logger.info("Synced run to Airtable")
        except Exception as e:
            logger.error(f"Airtable sync failed: {e}")


# Singleton
airtable_reporter = AirtableReporter()
