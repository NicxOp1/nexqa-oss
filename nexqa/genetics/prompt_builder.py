"""
NEXQA v1.0 — Prompt Builder (Genetic)

Compiles agent specification YAML into a gene-tagged prompt ready for
Retell AI. Produces a GeneSet with IDENTITY, FLOW, OBJECTIONS,
GUARDRAILS, PERSONALITY, and RULES genes.

Usage:
    from nexqa.genetics.prompt_builder import prompt_builder

    gene_set = prompt_builder.build(spec_path=Path("spec.yaml"))
    prompt   = prompt_builder.build_prompt_text(gene_set)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from nexqa.models.gene_models import Gene, GeneSet, GenePriority, GeneType
from nexqa.storage.logger import logger


class PromptBuilder:
    """Compiles YAML specs into gene-tagged voice agent prompts."""

    def build(self, spec_path: Path) -> GeneSet:
        """Build a GeneSet from a YAML spec file.

        Args:
            spec_path: Path to the agent specification YAML.

        Returns:
            GeneSet containing structured prompt genes.
        """
        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        logger.info(f"Building prompt from spec: {spec_path.name}")
        return self._build_from_dict(raw)

    def build_from_dict(self, spec: Dict[str, Any]) -> GeneSet:
        """Build a GeneSet from a spec dictionary."""
        return self._build_from_dict(spec)

    def build_prompt_text(self, gene_set: GeneSet) -> str:
        """Serialize a GeneSet into markdown prompt text.

        Produces the format expected by Retell LLM's general_prompt field.
        """
        sections: List[str] = []

        for gene in gene_set.genes:
            header = self._gene_header(gene.type)
            sections.append(f"## {header}\n{gene.content.strip()}")

        return "\n\n".join(sections)

    # ─── Private ─────────────────────────────────────────────────────

    def _build_from_dict(self, spec: Dict[str, Any]) -> GeneSet:
        """Build genes from parsed YAML dict."""
        genes: List[Gene] = []

        # IDENTITY gene — immutable
        identity = self._build_identity(spec)
        if identity:
            genes.append(identity)

        # PERSONALITY gene
        personality = self._build_personality(spec)
        if personality:
            genes.append(personality)

        # FLOW gene
        flow = self._build_flow(spec)
        if flow:
            genes.append(flow)

        # OBJECTIONS gene
        objections = self._build_objections(spec)
        if objections:
            genes.append(objections)

        # GUARDRAILS gene
        guardrails = self._build_guardrails(spec)
        if guardrails:
            genes.append(guardrails)

        # RULES gene
        rules = self._build_rules(spec)
        if rules:
            genes.append(rules)

        # TOOLS gene (reference info, not the actual tool config)
        tools_gene = self._build_tools_reference(spec)
        if tools_gene:
            genes.append(tools_gene)

        logger.info(
            f"Built {len(genes)} genes from spec "
            f"(agent={spec.get('agent_name', 'unnamed')})"
        )

        return GeneSet(
            genes=genes,
            version="1.0.0",
            agent_id=spec.get("agent_name", ""),
        )

    def _build_identity(self, spec: Dict[str, Any]) -> Optional[Gene]:
        """Build the IDENTITY gene — who the agent is."""
        name = spec.get("agent_name", "")
        company = spec.get("company_name", "")
        goal = spec.get("primary_goal", "")
        agent_type = spec.get("agent_type", "")

        if not name and not company:
            return None

        lines = [f"You are {name}", ""]

        if company:
            lines[0] += f", a voice agent for {company}"
        lines[0] += "."

        if agent_type:
            lines.append(f"Role: {agent_type}")
        if goal:
            lines.append(f"\n{goal.strip()}")

        return Gene(
            type=GeneType.IDENTITY,
            content="\n".join(lines),
            immutable=True,
            max_mutations=0,
            priority=GenePriority.CRITICAL,
        )

    def _build_personality(self, spec: Dict[str, Any]) -> Optional[Gene]:
        """Build the PERSONALITY gene — tone and style."""
        personality = spec.get("personality", {})
        if not personality:
            return None

        lines: List[str] = []

        # Handle plain string (e.g. "warm") or dict (e.g. {tone: ..., speaking_style: ...})
        if isinstance(personality, str):
            lines.append(f"Tone: {personality}")
        else:
            tone = personality.get("tone", "")
            if tone:
                lines.append(f"Tone: {tone}")

            style = personality.get("speaking_style", "")
            if style:
                lines.append(f"Speaking style: {style}")

        # Style guardrails — voice AI best practices
        lines.extend([
            "",
            "Be concise: Keep responses under 2 sentences.",
            "Be conversational: Use natural language and contractions.",
            "Never use markdown, bullets, or numbered lists in responses.",
            "Always format numbers, dates, and currencies in spoken form.",
        ])

        return Gene(
            type=GeneType.PERSONALITY,
            content="\n".join(lines),
            immutable=False,
            max_mutations=3,
            priority=GenePriority.HIGH,
        )

    def _build_flow(self, spec: Dict[str, Any]) -> Optional[Gene]:
        """Build the FLOW gene — conversation steps."""
        goal = spec.get("primary_goal", "")
        criteria = spec.get("qualification_criteria", [])
        begin = spec.get("begin_message", "")
        locations = spec.get("locations", [])
        hours = spec.get("hours", "")
        dentists = spec.get("dentists", [])
        insurance = spec.get("insurance_accepted", [])

        lines: List[str] = []

        if begin:
            lines.append(f"Begin the conversation with: \"{begin.strip()}\"")
            lines.append("")

        if goal:
            lines.append(f"Primary objective: {goal.strip()}")
            lines.append("")

        if criteria:
            lines.append("Required information to collect (one at a time):")
            for i, c in enumerate(criteria, 1):
                lines.append(f"  {i}. {c}")
            lines.append("")

        if locations:
            lines.append("Available locations:")
            for loc in locations:
                if isinstance(loc, str):
                    lines.append(f"  - {loc}")
                else:
                    name = loc.get("name", "")
                    addr = loc.get("address", "")
                    loc_hours = loc.get("hours", "")
                    lines.append(f"  - {name}: {addr} ({loc_hours})")
            lines.append("")

        if hours:
            h = hours.strip() if isinstance(hours, str) else str(hours)
            lines.append(f"Office hours: {h}")
            lines.append("")

        if dentists:
            lines.append("Available dentists:")
            for d in dentists:
                if isinstance(d, str):
                    lines.append(f"  - {d}")
                else:
                    lines.append(f"  - {d.get('name', '')} — {d.get('specialty', '')}")
            lines.append("")

        if insurance:
            lines.append("Accepted insurance providers:")
            for provider in insurance:
                lines.append(f"  - {provider}")
            lines.append("")

        lines.append("After collecting all required information, confirm details before proceeding.")
        lines.append("Ask one question at a time, then wait for the response.")

        return Gene(
            type=GeneType.FLOW,
            content="\n".join(lines),
            immutable=False,
            max_mutations=5,
            priority=GenePriority.HIGH,
        )

    def _build_objections(self, spec: Dict[str, Any]) -> Optional[Gene]:
        """Build the OBJECTIONS gene — handling specific situations."""
        objections = spec.get("objections", [])
        if not objections:
            return None

        lines: List[str] = []
        for obj in objections:
            trigger = obj.get("trigger", "")
            response = obj.get("response", "")
            lines.append(f"If {trigger}:")
            lines.append(f"  → {response.strip()}")
            lines.append("")

        return Gene(
            type=GeneType.OBJECTIONS,
            content="\n".join(lines),
            immutable=False,
            max_mutations=5,
            priority=GenePriority.MEDIUM,
        )

    def _build_guardrails(self, spec: Dict[str, Any]) -> Optional[Gene]:
        """Build the GUARDRAILS gene — hard safety constraints."""
        guardrails = spec.get("guardrails", [])
        if not guardrails:
            return None

        lines: List[str] = []
        for rule in guardrails:
            lines.append(f"- {rule}")

        # Add universal voice AI guardrails
        lines.extend([
            "",
            "- Never expose internal tool names or function calls to the caller.",
            "- Never announce call transfers or endings — trigger them silently.",
            "- If unsure about any information, say so rather than guessing.",
        ])

        return Gene(
            type=GeneType.GUARDRAILS,
            content="\n".join(lines),
            immutable=False,
            max_mutations=2,
            priority=GenePriority.CRITICAL,
        )

    def _build_rules(self, spec: Dict[str, Any]) -> Optional[Gene]:
        """Build the RULES gene — custom instructions."""
        custom = spec.get("custom_instructions", "")
        if not custom:
            return None

        return Gene(
            type=GeneType.RULES,
            content=custom.strip(),
            immutable=False,
            max_mutations=3,
            priority=GenePriority.MEDIUM,
        )

    def _build_tools_reference(self, spec: Dict[str, Any]) -> Optional[Gene]:
        """Build a tools reference gene with trigger conditions.

        NOTE: This does NOT create the actual Retell tool configs —
        that's tool_builder.py's job. This gene tells the LLM
        WHEN to use each tool.
        """
        tools = spec.get("tools", [])
        if not tools:
            return None

        lines: List[str] = []
        for tool in tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            lines.append(f"Use the `{name}` function {desc.lower()}")

        return Gene(
            type=GeneType.TOOLS,
            content="Tool usage instructions:\n" + "\n".join(lines),
            immutable=False,
            max_mutations=2,
            priority=GenePriority.LOW,
        )

    @staticmethod
    def _gene_header(gene_type: GeneType) -> str:
        """Map GeneType to Retell-recommended section header."""
        return {
            GeneType.IDENTITY: "Identity",
            GeneType.FLOW: "Task Instructions",
            GeneType.OBJECTIONS: "Objection Handling",
            GeneType.PERSONALITY: "Style Guardrails",
            GeneType.GUARDRAILS: "Guardrails",
            GeneType.RULES: "Response Guidelines",
        }.get(gene_type, gene_type.value.title())


# Module-level singleton
prompt_builder = PromptBuilder()
