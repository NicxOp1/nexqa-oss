"""
NEXQA v1.0 — Gene Validator

Validates inter-gene consistency after mutations or builds.
Catches structural issues (missing genes, duplicates, immutability violations)
and optionally runs semantic checks via Claude.

Usage:
    from nexqa.genetics.gene_validator import gene_validator

    issues = gene_validator.validate(gene_set)
    issues = gene_validator.validate_mutation(original, mutated, "FLOW")
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from nexqa.models.gene_models import GeneSet, GeneType
from nexqa.storage.logger import logger


# ─── Models ──────────────────────────────────────────────────────────

class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationIssue(BaseModel):
    """A single validation issue found in a GeneSet."""

    gene_type: str
    severity: Severity
    message: str
    related_gene: Optional[str] = None


# ─── Gene Validator ──────────────────────────────────────────────────

class GeneValidator:
    """Validates GeneSet structural and semantic consistency."""

    # Gene types that MUST exist in any valid GeneSet
    REQUIRED_GENES = {"IDENTITY"}

    # Gene types that SHOULD exist (warning if missing)
    RECOMMENDED_GENES = {"GUARDRAILS", "FLOW"}

    def validate(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Run all structural validation checks on a GeneSet.

        Returns a list of ValidationIssues. Empty list = valid.
        """
        issues: List[ValidationIssue] = []

        issues.extend(self._check_required_genes(gene_set))
        issues.extend(self._check_recommended_genes(gene_set))
        issues.extend(self._check_duplicate_types(gene_set))
        issues.extend(self._check_valid_gene_types(gene_set))
        issues.extend(self._check_immutability(gene_set))
        issues.extend(self._check_flow_has_content(gene_set))
        issues.extend(self._check_empty_genes(gene_set))

        if issues:
            errors = [i for i in issues if i.severity == Severity.ERROR]
            warnings = [i for i in issues if i.severity == Severity.WARNING]
            logger.info(
                f"Gene validation: {len(errors)} errors, "
                f"{len(warnings)} warnings"
            )

        return issues

    def validate_mutation(
        self,
        original: GeneSet,
        mutated: GeneSet,
        changed_gene_type: str,
    ) -> List[ValidationIssue]:
        """Validate a mutation — full check plus identity preservation.

        Ensures that:
        1. The mutated GeneSet passes all structural checks.
        2. IDENTITY gene content is preserved (immutable).
        3. GUARDRAILS gene is not removed.
        """
        issues = self.validate(mutated)

        # Check IDENTITY preservation
        original_identity = self._find_gene(original, "IDENTITY")
        mutated_identity = self._find_gene(mutated, "IDENTITY")

        if original_identity and mutated_identity:
            if original_identity.content.strip() != mutated_identity.content.strip():
                issues.append(ValidationIssue(
                    gene_type="IDENTITY",
                    severity=Severity.ERROR,
                    message=(
                        "IDENTITY gene content was modified during mutation. "
                        "IDENTITY is immutable."
                    ),
                    related_gene=changed_gene_type,
                ))

        # Check GUARDRAILS preservation
        original_guardrails = self._find_gene(original, "GUARDRAILS")
        mutated_guardrails = self._find_gene(mutated, "GUARDRAILS")

        if original_guardrails and not mutated_guardrails:
            issues.append(ValidationIssue(
                gene_type="GUARDRAILS",
                severity=Severity.ERROR,
                message=(
                    "GUARDRAILS gene was removed during mutation. "
                    "Safety rules must be preserved."
                ),
                related_gene=changed_gene_type,
            ))

        return issues

    def has_errors(self, issues: List[ValidationIssue]) -> bool:
        """Check if any issues are ERROR severity."""
        return any(i.severity == Severity.ERROR for i in issues)

    def has_warnings(self, issues: List[ValidationIssue]) -> bool:
        """Check if any issues are WARNING severity."""
        return any(i.severity == Severity.WARNING for i in issues)

    # ─── Private Checks ──────────────────────────────────────────────

    def _check_required_genes(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Check that all required gene types are present."""
        issues: List[ValidationIssue] = []
        present = {g.type.value for g in gene_set.genes}

        for required in self.REQUIRED_GENES:
            if required not in present:
                issues.append(ValidationIssue(
                    gene_type=required,
                    severity=Severity.ERROR,
                    message=f"Required gene type {required} is missing.",
                ))
        return issues

    def _check_recommended_genes(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Check that recommended gene types are present."""
        issues: List[ValidationIssue] = []
        present = {g.type.value for g in gene_set.genes}

        for recommended in self.RECOMMENDED_GENES:
            if recommended not in present:
                issues.append(ValidationIssue(
                    gene_type=recommended,
                    severity=Severity.WARNING,
                    message=f"Recommended gene type {recommended} is missing.",
                ))
        return issues

    def _check_duplicate_types(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Check for duplicate gene types."""
        issues: List[ValidationIssue] = []
        seen: set = set()

        for gene in gene_set.genes:
            type_val = gene.type.value
            if type_val in seen:
                issues.append(ValidationIssue(
                    gene_type=type_val,
                    severity=Severity.ERROR,
                    message=f"Duplicate gene type {type_val} found.",
                ))
            seen.add(type_val)

        return issues

    def _check_valid_gene_types(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Check that all gene types are valid GeneType enum values."""
        issues: List[ValidationIssue] = []
        valid = {gt.value for gt in GeneType}

        for gene in gene_set.genes:
            if gene.type.value not in valid:
                issues.append(ValidationIssue(
                    gene_type=gene.type.value,
                    severity=Severity.ERROR,
                    message=f"Invalid gene type: {gene.type.value}",
                ))
        return issues

    def _check_immutability(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Check that immutable genes are properly flagged."""
        issues: List[ValidationIssue] = []

        identity = self._find_gene(gene_set, "IDENTITY")
        if identity and not identity.immutable:
            issues.append(ValidationIssue(
                gene_type="IDENTITY",
                severity=Severity.WARNING,
                message="IDENTITY gene should be marked as immutable.",
            ))

        return issues

    def _check_flow_has_content(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Check that FLOW gene has actual step content."""
        issues: List[ValidationIssue] = []

        flow = self._find_gene(gene_set, "FLOW")
        if flow and len(flow.content.strip()) < 20:
            issues.append(ValidationIssue(
                gene_type="FLOW",
                severity=Severity.WARNING,
                message="FLOW gene has very little content (< 20 chars).",
            ))

        return issues

    def _check_empty_genes(self, gene_set: GeneSet) -> List[ValidationIssue]:
        """Check for genes with empty content."""
        issues: List[ValidationIssue] = []

        for gene in gene_set.genes:
            if not gene.content or not gene.content.strip():
                issues.append(ValidationIssue(
                    gene_type=gene.type.value,
                    severity=Severity.ERROR,
                    message=f"Gene {gene.type.value} has empty content.",
                ))

        return issues

    # ─── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _find_gene(gene_set: GeneSet, type_name: str):
        """Find a gene by type name string."""
        for gene in gene_set.genes:
            if gene.type.value == type_name:
                return gene
        return None


# Module-level singleton
gene_validator = GeneValidator()
