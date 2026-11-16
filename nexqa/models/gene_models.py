"""
NEXQA v1.0 — Prompt Gene Models

XML-based gene structures for prompt decomposition, mutation, and optimization.
Gene format uses XML tags: <gene type="X" attr="val">content</gene>

Gene types:
  IDENTITY    — Who the agent is (immutable)
  PERSONALITY — Tone, phrasing style
  GUARDRAILS  — Safety constraints, forbidden actions (critical priority)
  RULES       — Operational rules, objectives
  FLOW        — Call script with <step> nesting
  OBJECTIONS  — Objection handling with <scenario trigger="..."> nesting
  TOOLS       — Tool usage instructions
  CLOSING     — Wrap-up and closing script
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ─── Enums ──────────────────────────────────────────────────────────

class GeneType(str, Enum):
    """Prompt gene types — each maps to a section of a voice agent prompt."""

    IDENTITY = "IDENTITY"
    PERSONALITY = "PERSONALITY"
    GUARDRAILS = "GUARDRAILS"
    RULES = "RULES"
    FLOW = "FLOW"
    OBJECTIONS = "OBJECTIONS"
    TOOLS = "TOOLS"
    CLOSING = "CLOSING"


class GenePriority(str, Enum):
    """Priority levels for gene optimization ordering."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─── Nested Elements ───────────────────────────────────────────────

class GeneStep(BaseModel):
    """A step within a FLOW gene — maps to <step id="N" name="...">."""

    id: str
    name: str
    content: str

    def to_xml(self) -> str:
        return f'  <step id="{self.id}" name="{self.name}">\n{self.content}\n  </step>'


class GeneScenario(BaseModel):
    """A scenario within an OBJECTIONS gene — maps to <scenario trigger="...">."""

    trigger: str
    content: str

    def to_xml(self) -> str:
        return f'  <scenario trigger="{self.trigger}">\n{self.content}\n  </scenario>'


# ─── Core Gene Model ───────────────────────────────────────────────

class Gene(BaseModel):
    """A single gene — the atomic unit of prompt optimization.

    Maps to: <gene type="X" immutable="true" priority="high" max_mutations="3">
    """

    type: GeneType
    content: str
    immutable: bool = False
    priority: GenePriority = GenePriority.MEDIUM
    max_mutations: int = Field(default=5, ge=0)
    attributes: Dict[str, str] = Field(
        default_factory=dict,
        description="Catch-all for extra XML attributes",
    )

    # Nested elements (only populated for FLOW / OBJECTIONS genes)
    steps: List[GeneStep] = Field(default_factory=list)
    scenarios: List[GeneScenario] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_identity_immutable(self) -> "Gene":
        """IDENTITY genes are always immutable."""
        if self.type == GeneType.IDENTITY:
            self.immutable = True
        return self

    @model_validator(mode="after")
    def enforce_guardrails_no_mutations(self) -> "Gene":
        """GUARDRAILS genes default to 0 mutations and critical priority."""
        if self.type == GeneType.GUARDRAILS:
            if self.max_mutations > 0 and "max_mutations" not in self.model_fields_set:
                self.max_mutations = 0
            if self.priority != GenePriority.CRITICAL and "priority" not in self.model_fields_set:
                self.priority = GenePriority.CRITICAL
        return self

    def to_xml(self) -> str:
        """Serialize this gene back to XML format."""
        attrs = [f'type="{self.type.value}"']

        if self.immutable:
            attrs.append('immutable="true"')
        if self.priority != GenePriority.MEDIUM:
            attrs.append(f'priority="{self.priority.value}"')
        if self.max_mutations != 5:
            attrs.append(f'max_mutations="{self.max_mutations}"')

        for key, val in self.attributes.items():
            attrs.append(f'{key}="{val}"')

        attr_str = " ".join(attrs)

        # Build inner content
        inner_parts: List[str] = []

        if self.steps:
            for step in self.steps:
                inner_parts.append(step.to_xml())
        elif self.scenarios:
            for scenario in self.scenarios:
                inner_parts.append(scenario.to_xml())
        else:
            inner_parts.append(self.content)

        inner = "\n\n".join(inner_parts)
        return f"<gene {attr_str}>\n{inner}\n</gene>"


# ─── Gene Set (Full Prompt) ────────────────────────────────────────

class GeneSet(BaseModel):
    """A collection of genes that constitutes one full prompt version.

    Maps to: <prompt version="1.0.0" agent="agent-name">
    """

    genes: List[Gene] = Field(default_factory=list)
    version: str = "1.0.0"
    agent_name: str = ""

    def serialize(self) -> str:
        """Reassemble all genes into a complete XML prompt string."""
        parts = [f'<prompt version="{self.version}" agent="{self.agent_name}">']
        for gene in self.genes:
            parts.append("")
            parts.append(gene.to_xml())
        parts.append("")
        parts.append("</prompt>")
        return "\n".join(parts)

    def get_gene(self, gene_type: GeneType) -> Optional[Gene]:
        """Extract a specific gene by type."""
        for gene in self.genes:
            if gene.type == gene_type:
                return gene
        return None

    def get_mutable_genes(self) -> List[Gene]:
        """Return only genes that can be mutated."""
        return [g for g in self.genes if not g.immutable and g.max_mutations > 0]

    def replace_gene(self, gene_type: GeneType, new_content: str) -> "GeneSet":
        """Create a new GeneSet with one gene's content replaced.

        Returns a new GeneSet (immutable pattern). Raises ValueError
        if the target gene is immutable.
        """
        new_genes: List[Gene] = []
        found = False

        for gene in self.genes:
            if gene.type == gene_type:
                if gene.immutable:
                    raise ValueError(
                        f"Cannot replace {gene_type.value} gene — it is immutable"
                    )
                updated = gene.model_copy(update={"content": new_content})
                new_genes.append(updated)
                found = True
            else:
                new_genes.append(gene.model_copy())

        if not found:
            raise ValueError(f"Gene type {gene_type.value} not found in set")

        return GeneSet(
            genes=new_genes,
            version=self.version,
            agent_name=self.agent_name,
        )


# ─── Mutation Tracking ─────────────────────────────────────────────

class GeneMutation(BaseModel):
    """Record of a single gene mutation during optimization."""

    gene_type: GeneType
    original_content: str
    mutated_content: str
    reason: str = ""
    score_delta: float = 0.0


class MutationResult(BaseModel):
    """Result of a mutation batch applied to a GeneSet."""

    success: bool
    gene_set: GeneSet
    mutations: List[GeneMutation] = Field(default_factory=list)
    lint_passed: bool = True
    error: Optional[str] = None
