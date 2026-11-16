"""
NEXQA v1.0 — Gene Parser

Decomposes XML-tagged prompts into GeneSet objects and reassembles them.

XML format:
  <prompt version="1.0.0" agent="agent-name">
    <gene type="IDENTITY" immutable="true">...</gene>
    <gene type="FLOW" priority="medium" max_mutations="5">
      <step id="1" name="Greeting">...</step>
    </gene>
    <gene type="OBJECTIONS">
      <scenario trigger="taxes">...</scenario>
    </gene>
  </prompt>

Parsing strategy: xml.etree.ElementTree with fallback for malformed XML.
Content that contains raw <, >, & is pre-escaped before parsing.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from nexqa.models.gene_models import (
    Gene,
    GenePriority,
    GeneScenario,
    GeneSet,
    GeneStep,
    GeneType,
)
from nexqa.storage.logger import logger


# ─── XML Helpers ─────────────────────────────────────────────────

# Valid gene types for content escaping boundary detection
_VALID_GENE_TYPES = {"IDENTITY", "PERSONALITY", "FLOW", "OBJECTIONS", "RULES", "TOOLS", "GUARDRAILS", "CLOSING"}

# Regex to find text content BETWEEN known tags (for escaping & in natural language)
_AMP_IN_TEXT = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;|#)')


def _sanitize_xml(raw: str) -> str:
    """Escape bare ampersands in text content so ElementTree can parse it.

    We only escape & that are NOT already part of XML entities.
    Angle brackets inside gene content are tricky — we rely on the XML
    structure being well-formed at the tag level. Content between tags
    may contain natural language with & which must be escaped.
    """
    return _AMP_IN_TEXT.sub('&amp;', raw)


def _unescape_content(text: str) -> str:
    """Reverse XML entity escaping for content strings."""
    return (
        text
        .replace('&amp;', '&')
        .replace('&lt;', '<')
        .replace('&gt;', '>')
        .replace('&quot;', '"')
        .replace('&apos;', "'")
    )


def _get_text(elem: ET.Element) -> str:
    """Get the full inner text of an element (text + tail of children),
    preserving original content."""
    # For elements with no children, just return text
    if len(elem) == 0:
        return _unescape_content(elem.text or "")

    # For elements with children (like <gene> with <step> children),
    # return only the direct text (not child content)
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tail:
            parts.append(child.tail)
    return _unescape_content("".join(parts))


# ─── Gene Parser ────────────────────────────────────────────────────

class GeneParser:
    """Parses XML-tagged prompts into GeneSet objects and back."""

    def parse(self, prompt_text: str) -> GeneSet:
        """Parse an XML-tagged prompt into a GeneSet.

        Falls back to wrapping the entire text as a single IDENTITY gene
        if no <gene> tags are found or XML is malformed.
        """
        # Quick check: if there are no gene tags at all, wrap as IDENTITY
        if "<gene" not in prompt_text.lower():
            logger.warning(
                "No <gene> tags found in prompt — wrapping entire content as IDENTITY gene"
            )
            return GeneSet(
                genes=[
                    Gene(
                        type=GeneType.IDENTITY,
                        content=prompt_text.strip(),
                        immutable=True,
                    )
                ],
                version="1.0.0",
                agent_name="",
            )

        # Sanitize & parse
        sanitized = _sanitize_xml(prompt_text)
        try:
            root = ET.fromstring(sanitized)
        except ET.ParseError as e:
            logger.error(
                f"Malformed XML in prompt (line {e.position[0] if e.position else '?'}, "
                f"col {e.position[1] if e.position else '?'}): {e}. "
                "Falling back to IDENTITY gene wrapper."
            )
            return GeneSet(
                genes=[
                    Gene(
                        type=GeneType.IDENTITY,
                        content=prompt_text.strip(),
                        immutable=True,
                    )
                ],
                version="1.0.0",
                agent_name="",
            )

        # Extract prompt-level attributes
        version = root.attrib.get("version", "1.0.0")
        agent_name = root.attrib.get("agent", "")

        # Find all <gene> elements (direct children or nested)
        gene_elems = root.findall(".//gene") if root.tag != "gene" else [root]
        if root.tag == "prompt":
            gene_elems = root.findall("gene")

        if not gene_elems:
            logger.warning(
                "XML parsed but no <gene> elements found — wrapping as IDENTITY"
            )
            return GeneSet(
                genes=[
                    Gene(
                        type=GeneType.IDENTITY,
                        content=prompt_text.strip(),
                        immutable=True,
                    )
                ],
                version=version,
                agent_name=agent_name,
            )

        genes: List[Gene] = []
        for elem in gene_elems:
            try:
                gene = self._parse_gene_element(elem)
                genes.append(gene)
            except Exception as e:
                gene_type = elem.attrib.get("type", "UNKNOWN")
                logger.error(
                    f"Failed to parse <gene type=\"{gene_type}\">: {e}. Skipping."
                )

        if not genes:
            logger.error("All gene elements failed to parse — wrapping as IDENTITY")
            return GeneSet(
                genes=[
                    Gene(
                        type=GeneType.IDENTITY,
                        content=prompt_text.strip(),
                        immutable=True,
                    )
                ],
                version=version,
                agent_name=agent_name,
            )

        return GeneSet(genes=genes, version=version, agent_name=agent_name)

    def _parse_gene_element(self, elem: ET.Element) -> Gene:
        """Parse a single <gene> XML element into a Gene model."""
        attrs = dict(elem.attrib)

        # Required: type
        gene_type_str = attrs.pop("type", "IDENTITY").upper()
        try:
            gene_type = GeneType(gene_type_str)
        except ValueError:
            logger.warning(f"Unknown gene type '{gene_type_str}', defaulting to RULES")
            gene_type = GeneType.RULES

        # Optional known attributes
        immutable = attrs.pop("immutable", "false").lower() == "true"
        priority_str = attrs.pop("priority", "medium").lower()
        try:
            priority = GenePriority(priority_str)
        except ValueError:
            priority = GenePriority.MEDIUM
        max_mutations = int(attrs.pop("max_mutations", "5"))

        # Parse nested elements
        steps: List[GeneStep] = []
        scenarios: List[GeneScenario] = []

        if gene_type == GeneType.FLOW:
            steps = self._parse_step_elements(elem)
        elif gene_type == GeneType.OBJECTIONS:
            scenarios = self._parse_scenario_elements(elem)

        # Content is the direct text (excluding child elements' text)
        content = _get_text(elem)

        return Gene(
            type=gene_type,
            content=content.strip(),
            immutable=immutable,
            priority=priority,
            max_mutations=max_mutations,
            attributes=attrs,
            steps=steps,
            scenarios=scenarios,
        )

    def _parse_step_elements(self, gene_elem: ET.Element) -> List[GeneStep]:
        """Extract <step> elements from a FLOW gene."""
        steps: List[GeneStep] = []
        for step_elem in gene_elem.findall("step"):
            step = GeneStep(
                id=step_elem.attrib.get("id", str(len(steps) + 1)),
                name=step_elem.attrib.get("name", f"Step {len(steps) + 1}"),
                content=_unescape_content((step_elem.text or "").strip()),
            )
            steps.append(step)
        return steps

    def _parse_scenario_elements(self, gene_elem: ET.Element) -> List[GeneScenario]:
        """Extract <scenario> elements from an OBJECTIONS gene."""
        scenarios: List[GeneScenario] = []
        for sc_elem in gene_elem.findall("scenario"):
            scenario = GeneScenario(
                trigger=sc_elem.attrib.get("trigger", "unknown"),
                content=_unescape_content((sc_elem.text or "").strip()),
            )
            scenarios.append(scenario)
        return scenarios

    def serialize(self, gene_set: GeneSet) -> str:
        """Reassemble a GeneSet into an XML prompt string."""
        return gene_set.serialize()

    def extract_gene(
        self, gene_set: GeneSet, gene_type: GeneType
    ) -> Optional[Gene]:
        """Extract a specific gene by type from a GeneSet."""
        return gene_set.get_gene(gene_type)

    def replace_gene(
        self,
        gene_set: GeneSet,
        gene_type: GeneType,
        new_content: str,
    ) -> GeneSet:
        """Replace a gene's content in a GeneSet.

        Returns a new GeneSet (immutable pattern).
        Raises ValueError if gene is immutable.
        """
        return gene_set.replace_gene(gene_type, new_content)

    def auto_tag(self, untagged_prompt: str) -> str:
        """Use Claude to convert a markdown-section prompt to XML gene tags."""
        from nexqa.integrations.claude_client import claude_client

        system_prompt = """You are a Prompt Gene Tagger for Voice AI agents.

Your job is to take an untagged voice agent prompt and wrap each section
in XML <gene> tags with appropriate attributes.

Available gene types and their purposes:
- IDENTITY (immutable="true"): Who the agent is, their role, company
- PERSONALITY (priority="high"): Tone, phrasing style, conversational manner
- GUARDRAILS (priority="critical" max_mutations="0"): Safety rules, forbidden actions
- RULES (priority="high"): Operational rules, objectives, tasks
- FLOW (priority="medium"): Call script steps — use <step id="N" name="..."> for each step
- OBJECTIONS (priority="medium"): Objection handling — use <scenario trigger="..."> for each
- TOOLS: Tool/function usage instructions
- CLOSING (priority="medium"): Wrap-up and closing script

Output format:
<prompt version="1.0.0" agent="agent-name">
  <gene type="IDENTITY" immutable="true">...</gene>
  <gene type="FLOW" priority="medium" max_mutations="5">
    <step id="1" name="Step Name">...</step>
  </gene>
  ...
</prompt>

Rules:
1. Preserve ALL original content — do not summarize or rewrite
2. Extract guardrails from wherever they appear (often scattered)
3. FLOW steps should maintain their original order
4. Output ONLY the tagged XML — no explanations
"""

        logger.info("Auto-tagging prompt with Claude...")
        result = claude_client.complete(
            system_prompt,
            f"Tag this prompt:\n\n{untagged_prompt}",
        )
        return result.strip()


# Module-level singleton
gene_parser = GeneParser()
