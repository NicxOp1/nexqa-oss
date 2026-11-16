"""
NEXQA v1.0 — Gene Crossover

Implements genetic crossover between two GeneSet "parents" to produce
an offspring that inherits the best-performing genes from each.

Strategy:
  - Immutable genes (IDENTITY) always come from parent_a.
  - For each mutable gene, pick the version from the parent
    that scored higher on the relevant evaluation dimension.
  - If scores are tied, prefer the shorter version (less bloat).

Usage:
    from nexqa.genetics.gene_crossover import gene_crossover

    offspring = gene_crossover.crossover(parent_a, parent_b, scores_a, scores_b)
"""

from typing import Dict, List, Optional

from nexqa.models.gene_models import Gene, GeneSet, GeneType
from nexqa.storage.logger import logger


class GeneCrossover:
    """Performs genetic crossover between two GeneSets."""

    # Gene type → evaluation dimension mapping
    GENE_SCORE_MAP: Dict[str, str] = {
        "FLOW": "flow_adherence",
        "OBJECTIONS": "objection_handling",
        "PERSONALITY": "tone_accuracy",
        "GUARDRAILS": "safety_compliance",
        "RULES": "rule_adherence",
    }

    def crossover(
        self,
        parent_a: GeneSet,
        parent_b: GeneSet,
        scores_a: Dict[str, float],
        scores_b: Dict[str, float],
    ) -> GeneSet:
        """Produce an offspring GeneSet from two parents.

        Args:
            parent_a: First parent GeneSet.
            parent_b: Second parent GeneSet.
            scores_a: Per-dimension scores for parent A.
            scores_b: Per-dimension scores for parent B.

        Returns:
            New GeneSet combining best genes from each parent.
        """
        offspring_genes: List[Gene] = []

        # Index parent genes by type
        genes_a: Dict[str, Gene] = {g.type.value: g for g in parent_a.genes}
        genes_b: Dict[str, Gene] = {g.type.value: g for g in parent_b.genes}

        # All gene types present in either parent
        all_types = set(genes_a.keys()) | set(genes_b.keys())

        for gene_type in sorted(all_types):
            gene_a = genes_a.get(gene_type)
            gene_b = genes_b.get(gene_type)

            # Only one parent has this gene
            if gene_a and not gene_b:
                offspring_genes.append(gene_a.model_copy())
                continue
            if gene_b and not gene_a:
                offspring_genes.append(gene_b.model_copy())
                continue

            # Both parents have this gene
            assert gene_a is not None and gene_b is not None

            # Immutable genes always come from parent A
            if gene_a.immutable:
                offspring_genes.append(gene_a.model_copy())
                logger.debug(f"Crossover {gene_type}: immutable → parent_a")
                continue

            # Score-based selection
            selected = self._select_gene(
                gene_type, gene_a, gene_b, scores_a, scores_b
            )
            offspring_genes.append(selected.model_copy())

        # Combine version info
        offspring = GeneSet(
            genes=offspring_genes,
            version=f"{parent_a.version}x{parent_b.version}",
            agent_id=parent_a.agent_id or parent_b.agent_id,
        )

        logger.info(
            f"Crossover produced {len(offspring_genes)} genes "
            f"from {len(genes_a)} + {len(genes_b)} parents"
        )
        return offspring

    def _select_gene(
        self,
        gene_type: str,
        gene_a: Gene,
        gene_b: Gene,
        scores_a: Dict[str, float],
        scores_b: Dict[str, float],
    ) -> Gene:
        """Select the better gene based on relevant score dimension."""
        dimension = self.GENE_SCORE_MAP.get(gene_type)

        if dimension:
            score_a = scores_a.get(dimension, 0.0)
            score_b = scores_b.get(dimension, 0.0)
        else:
            # No specific dimension — use overall score
            score_a = scores_a.get("overall", 0.0)
            score_b = scores_b.get("overall", 0.0)

        if score_a > score_b:
            logger.debug(
                f"Crossover {gene_type}: parent_a wins "
                f"({score_a:.2f} > {score_b:.2f})"
            )
            return gene_a

        if score_b > score_a:
            logger.debug(
                f"Crossover {gene_type}: parent_b wins "
                f"({score_b:.2f} > {score_a:.2f})"
            )
            return gene_b

        # Tie: prefer shorter content (less bloat)
        if len(gene_a.content) <= len(gene_b.content):
            logger.debug(f"Crossover {gene_type}: tie → parent_a (shorter)")
            return gene_a
        else:
            logger.debug(f"Crossover {gene_type}: tie → parent_b (shorter)")
            return gene_b


# Module-level singleton
gene_crossover = GeneCrossover()
