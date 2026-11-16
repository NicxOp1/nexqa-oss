"""
NEXQA v1.0 — Gene Optimizer

Core intelligence module that mutates prompt genes to fix evaluation failures.
Uses a targeted approach: identifies the specific gene causing an issue and
rewrites only that component, preserving the rest of the prompt structure.
"""

from typing import Dict, List, Optional

from nexqa.genetics.gene_validator import gene_validator
from nexqa.integrations.claude_client import claude_client
from nexqa.models.gene_models import Gene, GeneSet, GeneType
from nexqa.models.scenario_models import EvaluationResult, SemanticIssue
from nexqa.optimizer.voice_corpus import voice_corpus
from nexqa.storage.logger import logger


class GeneOptimizer:
    """Optimizes individual prompt genes based on evaluation feedback."""

    def optimize(
        self,
        current_gene_set: GeneSet,
        evaluations: List[EvaluationResult],
        rule_context: str = "",
    ) -> Optional[GeneSet]:
        """Run one optimization pass on the gene set.

        Returns a new GeneSet if changes were made, or None if no optimization possible.
        """
        issues = self._collect_issues(evaluations)
        if not issues:
            logger.info("No issues found to optimize.")
            return None

        # Group issues by gene type
        gene_issues: Dict[GeneType, List[SemanticIssue]] = {}
        
        # Helper to map common hallucinations to valid GeneTypes
        GENE_MAPPING = {
            "SEMANTIC": "RULES",
            "UNDERSTANDING": "RULES",
            "BEHAVIOR": "PERSONALITY",
            "DETERMINISTIC": "RULES",
            "CONVERSATIONAL": "FLOW",
            "TURN-TAKING": "FLOW",
            "TURING": "PERSONALITY"
        }

        for issue in issues:
            gene_type_str = (issue.root_cause_gene or "RULES").upper()
            
            # Apply mapping if needed
            if gene_type_str in GENE_MAPPING:
                gene_type_str = GENE_MAPPING[gene_type_str]

            try:
                g_type = GeneType(gene_type_str)
                if g_type not in gene_issues:
                    gene_issues[g_type] = []
                gene_issues[g_type].append(issue)
            except ValueError:
                logger.warning(f"Still unknown root_cause_gene after mapping: {gene_type_str}")
                continue

        # Optimize genes (prioritize high-impact ones first?)
        # For now, optimize all mutable genes that have issues
        new_gene_set = current_gene_set
        mutations_count = 0

        for gene_type, specific_issues in gene_issues.items():
            gene = new_gene_set.get_gene(gene_type)
            if not gene:
                continue

            if gene.immutable:
                logger.warning(f"Skipping immutable gene {gene_type.value} despite issues")
                continue

            if gene.max_mutations <= 0:
                logger.warning(
                    f"Skipping gene {gene_type.value} (max_mutations=0)"
                )
                continue

            # Optimize this specific gene
            logger.info(f"Optimizing gene: {gene_type.value} ({len(specific_issues)} issues)")
            try:
                mutated_content = self._mutate_gene(
                    gene, specific_issues, rule_context
                )
                if mutated_content != gene.content:
                    new_gene_set = new_gene_set.replace_gene(
                        gene_type, mutated_content
                    )
                    mutations_count += 1
            except Exception as e:
                logger.error(f"Failed to optimize {gene_type.value}: {e}")

        if mutations_count == 0:
            return None

        # Post-mutation validation
        issues = gene_validator.validate_mutation(
            current_gene_set, new_gene_set,
            changed_gene_type=list(gene_issues.keys())[0].value if gene_issues else "RULES",
        )
        if gene_validator.has_errors(issues):
            error_msgs = [i.message for i in issues if i.severity.value == "ERROR"]
            logger.error(
                f"Post-mutation validation failed: {'; '.join(error_msgs)}"
            )
            return None

        return new_gene_set

    def _collect_issues(self, evaluations: List[EvaluationResult]) -> List[SemanticIssue]:
        """Aggregate semantic issues from all evaluations."""
        all_issues = []
        for ev in evaluations:
            # Add semantic issues
            all_issues.extend(ev.semantic_issues)
            # Add deterministic failures as pseudo-issues?
            # For now, rely on semantic issues which capture holistic problems
        return all_issues

    def _mutate_gene(
        self,
        gene: Gene,
        issues: List[SemanticIssue],
        rule_context: str,
    ) -> str:
        """Call Claude to rewrite a single gene's content."""
        # Get targeted corpus context for this gene type
        best_practices = voice_corpus.get_optimization_context([gene.type.value])
        issues_text = "\n".join(
            [f"- {i.severity}: {i.description} (Rec: {i.recommendation})" for i in issues]
        )

        system_prompt = f"""You are an Expert Voice AI Optimizer specializing in the '{gene.type.value}' component.

Your goal is to rewrite the GENE CONTENT below to fix specific issues identified in testing.

CONTEXT:
{rule_context}

VOICE AI BEST PRACTICES:
{best_practices}

INSTRUCTIONS:
1. Fix the identified issues while preserving the original intent.
2. Maintain the exact XML/Text structure (e.g., if FLOW gene, keep <step> tags; if OBJECTIONS, keep <scenario> tags).
3. Do NOT add <gene> wrapper tags — output ONLY the inner content.
4. Do NOT change ID attributes if they exist.
5. Be concise and conversational.
"""

        user_prompt = f"""
CURRENT GENE CONTENT ({gene.type.value}):
{gene.content}

IDENTIFIED ISSUES:
{issues_text}

Rewrite the gene content to resolve these issues.
"""

        response = claude_client.complete(
            system_prompt, user_prompt
        )
        
        # Strip any accidental wrapping provided by LLM (markdown blocks etc)
        cleaned = response.strip()
        if cleaned.startswith("```xml"):
            cleaned = cleaned.split("```xml")[1]
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
        
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]

        return cleaned.strip()


# Singleton
gene_optimizer = GeneOptimizer()
