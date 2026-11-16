"""
NEXQA v1.0 — Prompt History (Versioned)

Manages prompt versions with JSON file persistence, semantic versioning,
and rollback support. Each agent gets its own JSON history file.

Usage:
    from nexqa.storage.prompt_history import prompt_history

    pv = prompt_history.save_version(
        agent_id="agent_abc",
        prompt_text="You are Sarah...",
        gene_set=my_gene_set,
        change_type="gene_rewrite",
    )
    latest = prompt_history.get_latest("agent_abc")
    prompt_history.rollback("agent_abc", "1.0.0")
"""

import json
import time
from pathlib import Path

from nexqa.storage.config import Config
from typing import Dict, List, Optional

from pydantic import BaseModel

from nexqa.storage.logger import logger


# ─── Models ──────────────────────────────────────────────────────────

class PromptVersion(BaseModel):
    """A single versioned snapshot of an agent's prompt."""

    agent_id: str
    version: str                     # semver: "MAJOR.MINOR.PATCH"
    prompt_text: str
    genes_json: str                  # JSON-serialized gene list
    score: Optional[float] = None
    created_at: int                  # unix timestamp
    deployed: bool = False
    change_type: str = "patch"       # identity_change | gene_rewrite | wording_tweak
    change_description: str = ""
    parent_version: Optional[str] = None
    rollback_of: Optional[str] = None


# ─── Version bump mapping ────────────────────────────────────────────

CHANGE_TYPE_MAP: Dict[str, str] = {
    "identity_change": "major",
    "gene_rewrite": "minor",
    "wording_tweak": "patch",
    # Aliases
    "major": "major",
    "minor": "minor",
    "patch": "patch",
}


# ─── Prompt History Manager ─────────────────────────────────────────

class PromptHistory:
    """Manages prompt versions with JSON file persistence."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._storage_dir = storage_dir or Config.PROMPT_VERSIONS_DIR
        self._cache: Dict[str, List[PromptVersion]] = {}

    def _ensure_dir(self) -> None:
        """Create storage directory if it doesn't exist."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _history_path(self, agent_id: str) -> Path:
        """Return the JSON file path for an agent's history."""
        return self._storage_dir / f"{agent_id}.json"

    def _load_history(self, agent_id: str) -> List[PromptVersion]:
        """Load history from disk (with in-memory cache)."""
        if agent_id in self._cache:
            return self._cache[agent_id]

        path = self._history_path(agent_id)
        if not path.exists():
            self._cache[agent_id] = []
            return self._cache[agent_id]

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            versions = [PromptVersion(**item) for item in raw]
            self._cache[agent_id] = versions
            return versions
        except Exception as e:
            logger.error(f"Failed to load prompt history for {agent_id}: {e}")
            self._cache[agent_id] = []
            return self._cache[agent_id]

    def _persist(self, agent_id: str) -> None:
        """Write in-memory history to disk."""
        self._ensure_dir()
        path = self._history_path(agent_id)
        versions = self._cache.get(agent_id, [])
        data = [v.model_dump() for v in versions]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ─── Version Bumping ─────────────────────────────────────────────

    @staticmethod
    def _bump_version(version: str, change_type: str) -> str:
        """Increment semver based on change type."""
        bump_level = CHANGE_TYPE_MAP.get(change_type, "patch")
        major, minor, patch = map(int, version.split("."))

        if bump_level == "major":
            return f"{major + 1}.0.0"
        elif bump_level == "minor":
            return f"{major}.{minor + 1}.0"
        else:
            return f"{major}.{minor}.{patch + 1}"

    # ─── Public API ──────────────────────────────────────────────────

    def save_version(
        self,
        agent_id: str,
        prompt_text: str,
        gene_set,  # GeneSet — kept untyped to avoid circular imports
        change_type: str = "patch",
        description: str = "",
        score: Optional[float] = None,
        deployed: bool = False,
        rollback_of: Optional[str] = None,
    ) -> PromptVersion:
        """Create and persist a new prompt version."""
        history = self._load_history(agent_id)

        if history:
            latest = history[-1]
            next_ver = self._bump_version(latest.version, change_type)
            parent = latest.version
        else:
            next_ver = "1.0.0"
            parent = None

        # Serialize genes
        try:
            genes_json = json.dumps([g.model_dump() for g in gene_set.genes])
        except Exception:
            genes_json = json.dumps([g.dict() for g in gene_set.genes])

        pv = PromptVersion(
            agent_id=agent_id,
            version=next_ver,
            prompt_text=prompt_text,
            genes_json=genes_json,
            created_at=int(time.time()),
            parent_version=parent,
            change_type=change_type,
            change_description=description,
            score=score,
            deployed=deployed,
            rollback_of=rollback_of,
        )

        history.append(pv)
        self._persist(agent_id)
        logger.info(
            f"Prompt version {next_ver} saved for {agent_id} "
            f"(type={change_type}, score={score})"
        )
        return pv

    def get_latest(self, agent_id: str) -> Optional[PromptVersion]:
        """Get the most recent version for an agent."""
        history = self._load_history(agent_id)
        return history[-1] if history else None

    def get_history(self, agent_id: str) -> List[PromptVersion]:
        """Get full version history for an agent."""
        return self._load_history(agent_id)

    def get_prompt_at_version(
        self, agent_id: str, version: str
    ) -> Optional[str]:
        """Get the prompt text at a specific version."""
        for pv in self._load_history(agent_id):
            if pv.version == version:
                return pv.prompt_text
        return None

    def rollback(
        self, agent_id: str, target_version: str
    ) -> Optional[PromptVersion]:
        """Create a new version that rolls back to a previous version.

        Does NOT delete intermediate versions — creates a new version
        whose content matches the target, with rollback_of set.
        """
        target_prompt = self.get_prompt_at_version(agent_id, target_version)
        if target_prompt is None:
            logger.error(
                f"Cannot rollback: version {target_version} not found "
                f"for agent {agent_id}"
            )
            return None

        # Find the target version's genes
        target_pv = None
        for pv in self._load_history(agent_id):
            if pv.version == target_version:
                target_pv = pv
                break

        if not target_pv:
            return None

        # Create a stub gene_set-like object for save_version
        class _StubGeneSet:
            def __init__(self, genes_json_str: str):
                import json as _json
                self.genes = []

                class _StubGene:
                    def __init__(self, d):
                        self._d = d
                    def model_dump(self):
                        return self._d
                    def dict(self):
                        return self._d

                try:
                    for g in _json.loads(genes_json_str):
                        self.genes.append(_StubGene(g))
                except Exception:
                    pass

        stub = _StubGeneSet(target_pv.genes_json)

        return self.save_version(
            agent_id=agent_id,
            prompt_text=target_prompt,
            gene_set=stub,
            change_type="patch",
            description=f"Rollback to version {target_version}",
            score=target_pv.score,
            rollback_of=target_version,
        )


# Module-level singleton
prompt_history = PromptHistory()
