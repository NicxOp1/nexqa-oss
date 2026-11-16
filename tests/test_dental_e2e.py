"""
NEXQA End-to-End Test — Dental Receptionist Agent ("Maria")

Validates the full pipeline:
  Phase 1 (CREATE)  — YAML spec → GeneSet → tool schemas → prompt text
  Phase 2 (SCORE)   — Score mock transcripts via Claude LLM Judge
  Phase 3 (OPTIMIZE)— Mutate failing genes via Claude
  Phase 4 (COMPARE) — Before/after delta report + regression check

Usage:
    python -m tests.test_dental_e2e              # limited (5 transcripts)
    python -m tests.test_dental_e2e --full        # all 15 transcripts
    python -m tests.test_dental_e2e --phase create  # Phase 1 only (no API)

API calls:
    Phase 1  → ZERO (pure local logic)
    Phase 2+ → Claude calls via score_engine + gene_optimizer
"""

import argparse
import json
import sys
import time
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── NEXQA imports (adapted to REAL API signatures) ─────────────────

from nexqa.genetics.prompt_builder import prompt_builder
from nexqa.genetics.tool_builder import tool_builder
from nexqa.genetics.gene_parser import gene_parser
from nexqa.genetics.gene_validator import gene_validator
from nexqa.core.score_engine import score_engine
from nexqa.optimizer.gene_optimizer import gene_optimizer
from nexqa.optimizer.linter import linter
from nexqa.storage.prompt_history import prompt_history
from nexqa.storage.logger import logger
from nexqa.models.scenario_models import EvaluationResult, ValidationResult

# ─── Test data ──────────────────────────────────────────────────────

from tests.fixtures.dental_mock_transcripts import (
    ALL_TRANSCRIPTS,
    LIMITED_TRANSCRIPTS,
)
from tests.fixtures.dental_mock_tools import MockRetellClient


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _transcript_to_string(transcript: List[Dict[str, Any]]) -> str:
    """Serialize a transcript list into the text format score_engine expects.

    Skips tool_call / tool_result turns (they're internal metadata) and
    outputs only Agent:/User: lines.
    """
    lines: List[str] = []
    for turn in transcript:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == "agent":
            lines.append(f"Agent: {content}")
        elif role == "user":
            lines.append(f"User: {content}")
        # tool_call / tool_result omitted — score_engine scores spoken turns
    return "\n".join(lines)


def _mock_deterministic(transcript: List[Dict[str, Any]]) -> ValidationResult:
    """Run quick deterministic checks against the transcript.

    This replaces the full DeterministicValidator (which needs CompiledRules).
    We check a handful of hard rules from the dental spec.
    """
    text = _transcript_to_string(transcript)
    failed: List[str] = []

    # Rule: never give medical advice
    medical_phrases = [
        "you should probably take",
        "try the ibuprofen",
        "you might need antibiotics",
        "most toothaches can wait",
    ]
    for phrase in medical_phrases:
        if phrase.lower() in text.lower():
            failed.append("NO_MEDICAL_ADVICE")
            break

    # Rule: no internal tool names in spoken text
    tool_names = [
        "check_patient_record",
        "check_availability",
        "book_appointment",
        "cancel_appointment",
        "transfer_call",
        "function_call",
        "tool_result",
    ]
    for tn in tool_names:
        if tn in text:
            failed.append("NO_INTERNAL_TOOL_NAMES")
            break

    # Rule: 2-sentence max (heuristic — check for >3 periods in a single agent turn)
    for turn in transcript:
        if turn.get("role") == "agent":
            content = turn.get("content", "")
            sentence_count = content.count(".") + content.count("!") + content.count("?")
            if sentence_count > 4 and len(content) > 200:
                failed.append("MAX_2_SENTENCES")
                break

    # Rule: ISO dates exposed (e.g. "2026-02-27" in agent text)
    import re
    for turn in transcript:
        if turn.get("role") == "agent":
            if re.search(r"\b20\d{2}-\d{2}-\d{2}\b", turn.get("content", "")):
                failed.append("NO_ISO_DATES_IN_SPEECH")
                break

    # Rule: patient IDs exposed
    for turn in transcript:
        if turn.get("role") == "agent":
            if re.search(r"PAT-\d+", turn.get("content", "")):
                failed.append("NO_PATIENT_IDS")
                break

    return ValidationResult(
        passed=len(failed) == 0,
        failed_rules=failed,
        details={r: "Failed" for r in failed},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1: CREATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def phase_create(spec_path: Path) -> Dict[str, Any]:
    """Build GeneSet and tool schemas from YAML. No API calls."""
    print("\n" + "=" * 70)
    print("  📋 PHASE 1: Creating agent from spec (dry run)")
    print("=" * 70)

    # 1. Build GeneSet via prompt_builder
    gene_set = prompt_builder.build(spec_path)
    prompt_text = gene_parser.serialize(gene_set)

    # 2. Validate
    issues = gene_validator.validate(gene_set)
    errors = [i for i in issues if i.severity.value == "ERROR"]
    warnings = [i for i in issues if i.severity.value == "WARNING"]

    gene_types = [g.type.value for g in gene_set.genes]
    print(f"  ✅ Generated {len(gene_set.genes)} genes")
    print(f"  Gene types: {gene_types}")
    print(f"  Prompt length: {len(prompt_text)} chars")
    print(f"  Validation: {len(errors)} errors, {len(warnings)} warnings")

    if errors:
        for e in errors:
            print(f"    ❌ ERROR: {e.message}")

    if warnings:
        for w in warnings:
            print(f"    ⚠️  WARN: {w.message}")

    # 3. Build tool schemas
    raw_spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    tool_schemas = tool_builder.build_from_spec(raw_spec)
    print(f"  🔧 Generated {len(tool_schemas)} tool schemas")
    for ts in tool_schemas:
        name = ts.get("name", ts.get("type", "?"))
        print(f"      → {name}")

    # 4. Save prompt v1
    v1 = prompt_history.save_version(
        agent_id="test_dental_maria",
        prompt_text=prompt_text,
        gene_set=gene_set,
        change_type="gene_rewrite",
        description="Initial prompt from dental_receptionist_spec.yaml",
    )
    print(f"  📌 Saved as version {v1.version}")

    # 5. Write prompt to fixture file
    output_path = Path("tests/fixtures/dental_maria_v1.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt_text, encoding="utf-8")
    print(f"  💾 Prompt saved to {output_path}")

    # Identity checks
    identity_gene = next((g for g in gene_set.genes if g.type.value == "IDENTITY"), None)
    if identity_gene:
        content = identity_gene.content.lower()
        checks = {
            "Maria": "maria" in content,
            "Bright Smile Dental": "bright smile" in content,
            "receptionist": "receptionist" in content,
        }
        for label, ok in checks.items():
            icon = "✅" if ok else "❌"
            print(f"  {icon} Identity check: '{label}' {'found' if ok else 'MISSING'}")

    return {
        "gene_count": len(gene_set.genes),
        "gene_types": gene_types,
        "prompt_length": len(prompt_text),
        "tool_count": len(tool_schemas),
        "validation_errors": len(errors),
        "validation_warnings": len(warnings),
        "version": v1.version,
        "gene_set": gene_set,
        "prompt_text": prompt_text,
        "tool_schemas": tool_schemas,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 2: SCORE (Before Optimization)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def phase_score(
    transcripts: List[Dict[str, Any]],
    prompt_text: str,
    label: str = "BEFORE",
) -> Dict[str, Dict[str, Any]]:
    """Score each transcript using score_engine (real Claude calls).

    Returns dict of scenario_id → score info.
    """
    print(f"\n📊 Scoring transcripts ({label})...")

    scores: Dict[str, Dict[str, Any]] = {}
    api_calls = 0
    start = time.time()

    for tx in transcripts:
        tx_id = tx["id"]
        transcript_str = _transcript_to_string(tx["transcript"])
        det_result = _mock_deterministic(tx["transcript"])

        # ── Real Claude call via score_engine ──
        try:
            result: EvaluationResult = score_engine.evaluate(
                scenario_id=tx_id,
                transcript=transcript_str,
                deterministic=det_result,
            )
            api_calls += 1

            scores[tx_id] = {
                "deterministic": result.subscores.get("deterministic", 0.0),
                "semantic": result.subscores.get("semantic", 0.0),
                "conversational": result.subscores.get("conversational", 0.0),
                "turing": result.subscores.get("turing", 0.0),
                "overall": result.overall_score,
                "expected": tx.get("expected_score"),
                "tier": (
                    "happy" if tx_id.startswith("happy")
                    else "fail" if tx_id.startswith("fail")
                    else "adversarial"
                ),
                "det_passed": det_result.passed,
                "det_failed_rules": det_result.failed_rules,
                "semantic_issues": [
                    {"gene": i.root_cause_gene, "desc": i.description, "sev": i.severity}
                    for i in result.semantic_issues
                ],
            }

            tier_icon = "✅" if tx_id.startswith("happy") else "❌" if tx_id.startswith("fail") else "⚡"
            det_tag = "✓" if det_result.passed else f"✗ {det_result.failed_rules}"
            print(
                f"  {tier_icon} {tx_id}: {result.overall_score:.2f} "
                f"(det={result.subscores.get('deterministic', 0):.2f} "
                f"sem={result.subscores.get('semantic', 0):.2f} "
                f"conv={result.subscores.get('conversational', 0):.2f} "
                f"tur={result.subscores.get('turing', 0):.2f}) "
                f"[det: {det_tag}]"
            )

        except Exception as e:
            logger.error(f"Scoring failed for {tx_id}: {e}")
            print(f"  💥 {tx_id}: SCORING FAILED — {e}")
            scores[tx_id] = {
                "overall": 0.0,
                "error": str(e),
                "tier": (
                    "happy" if tx_id.startswith("happy")
                    else "fail" if tx_id.startswith("fail")
                    else "adversarial"
                ),
            }

    elapsed = time.time() - start
    print(f"\n  ⏱️  {api_calls} Claude calls in {elapsed:.1f}s")

    # Averages per tier
    for tier in ["happy", "fail", "adversarial"]:
        tier_scores = [s["overall"] for s in scores.values() if s.get("tier") == tier]
        if tier_scores:
            avg = sum(tier_scores) / len(tier_scores)
            print(f"  📈 {tier:<12} avg: {avg:.2f} ({len(tier_scores)} calls)")

    total_avg = sum(s["overall"] for s in scores.values()) / max(len(scores), 1)
    print(f"  📈 {'OVERALL':<12} avg: {total_avg:.2f}")

    return scores


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3: OPTIMIZE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def phase_optimize(
    gene_set,
    prompt_text: str,
    before_scores: Dict[str, Dict[str, Any]],
    transcripts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Run gene_optimizer on failing evaluations.

    Returns dict with optimized gene_set, prompt, optimization log.
    """
    print("\n" + "=" * 70)
    print("  🧬 PHASE 3: Running genetic optimization")
    print("=" * 70)

    # Build EvaluationResult objects for the optimizer
    # (it needs the real objects, not our score dicts)
    evaluations: List[EvaluationResult] = []

    for tx in transcripts:
        tx_id = tx["id"]
        score_data = before_scores.get(tx_id, {})
        if "error" in score_data:
            continue

        transcript_str = _transcript_to_string(tx["transcript"])
        det_result = _mock_deterministic(tx["transcript"])

        # Reconstruct EvaluationResult from scores
        from nexqa.models.scenario_models import SemanticIssue
        semantic_issues = []
        for issue_data in score_data.get("semantic_issues", []):
            semantic_issues.append(SemanticIssue(
                section="Agent Response",
                severity=issue_data.get("sev", "MEDIUM"),
                description=issue_data.get("desc", ""),
                root_cause_gene=issue_data.get("gene"),
                recommendation=None,
            ))

        evaluations.append(EvaluationResult(
            scenario_id=tx_id,
            deterministic_result=det_result,
            semantic_score=score_data.get("semantic", 0.0),
            semantic_issues=semantic_issues,
            overall_score=score_data.get("overall", 0.0),
            subscores={
                "deterministic": score_data.get("deterministic", 0.0),
                "semantic": score_data.get("semantic", 0.0),
                "conversational": score_data.get("conversational", 0.0),
                "turing": score_data.get("turing", 0.0),
            },
            is_critical_fail=not det_result.passed,
        ))

    print(f"  📄 {len(evaluations)} evaluations fed to optimizer")

    # Run optimizer (this calls Claude internally for gene mutation)
    start = time.time()
    optimized = gene_optimizer.optimize(
        current_gene_set=gene_set,
        evaluations=evaluations,
        rule_context="Dental receptionist agent. 2-sentence max per turn. No medical advice. HIPAA compliant. Natural speech (no ISO dates). No internal tool names.",
    )
    elapsed = time.time() - start
    print(f"  ⏱️  Optimization took {elapsed:.1f}s")

    if optimized is None:
        print("  ⚠️  Optimizer returned None — no mutations applied")
        return {
            "status": "no_changes",
            "gene_set": gene_set,
            "prompt_text": prompt_text,
        }

    # Serialize and lint
    optimized_prompt = gene_parser.serialize(optimized)
    lint_passed = linter.lint(prompt_text, optimized_prompt)
    print(f"  🔍 Linter: {'PASS ✅' if lint_passed else 'FAIL ❌'}")
    print(f"  📏 Prompt: {len(prompt_text)} → {len(optimized_prompt)} chars")

    # Compare genes
    original_types = {g.type.value: g.content for g in gene_set.genes}
    mutated_types = {g.type.value: g.content for g in optimized.genes}
    changed_genes = []
    for gtype, content in mutated_types.items():
        if content != original_types.get(gtype, ""):
            changed_genes.append(gtype)
            print(f"    🔄 {gtype} mutated ({len(original_types.get(gtype, ''))} → {len(content)} chars)")

    # Save v2
    v2 = prompt_history.save_version(
        agent_id="test_dental_maria",
        prompt_text=optimized_prompt,
        gene_set=optimized,
        change_type="gene_rewrite",
        description=f"Post-optimization: mutated {', '.join(changed_genes)}",
    )
    print(f"  📌 Saved as version {v2.version}")

    return {
        "status": "optimized",
        "gene_set": optimized,
        "prompt_text": optimized_prompt,
        "genes_changed": changed_genes,
        "lint_passed": lint_passed,
        "version": v2.version,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 4: COMPARE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def phase_compare(
    before_scores: Dict[str, Dict[str, Any]],
    after_scores: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Print comparison report and check for regressions."""
    print("\n" + "=" * 70)
    print("  📊 FINAL COMPARISON REPORT")
    print("=" * 70)

    # Per-transcript deltas
    print(f"\n  {'Scenario':<40} {'Before':>8} {'After':>8} {'Delta':>8}")
    print(f"  {'-' * 64}")

    regressions = []
    for tx_id in before_scores:
        b = before_scores[tx_id].get("overall", 0.0)
        a = after_scores.get(tx_id, {}).get("overall", 0.0)
        delta = a - b
        arrow = "↑" if delta > 0.01 else "↓" if delta < -0.01 else "="
        tier = before_scores[tx_id].get("tier", "?")
        icon = "✅" if tier == "happy" else "❌" if tier == "fail" else "⚡"
        print(f"  {icon} {tx_id:<37} {b:>8.2f} {a:>8.2f} {arrow}{abs(delta):>7.2f}")

        if delta < -0.05:
            regressions.append(tx_id)

    # Averages
    print(f"\n  {'Metric':<20} {'Before':>10} {'After':>10} {'Delta':>10}")
    print(f"  {'-' * 50}")

    result = {}
    for tier in ["happy", "fail", "adversarial"]:
        b_vals = [s["overall"] for s in before_scores.values() if s.get("tier") == tier]
        a_vals = [after_scores.get(k, {}).get("overall", 0.0) for k, s in before_scores.items() if s.get("tier") == tier]
        if b_vals:
            b_avg = sum(b_vals) / len(b_vals)
            a_avg = sum(a_vals) / len(a_vals)
            print(f"  {tier + ' avg':<20} {b_avg:>10.2f} {a_avg:>10.2f} {a_avg - b_avg:>+10.2f}")
            result[tier] = {"before": b_avg, "after": a_avg, "delta": a_avg - b_avg}

    b_total = sum(s["overall"] for s in before_scores.values()) / max(len(before_scores), 1)
    a_total = sum(after_scores.get(k, {}).get("overall", 0.0) for k in before_scores) / max(len(before_scores), 1)
    print(f"  {'OVERALL':<20} {b_total:>10.2f} {a_total:>10.2f} {a_total - b_total:>+10.2f}")

    if regressions:
        print(f"\n  ⚠️  REGRESSIONS DETECTED: {regressions}")
    else:
        print(f"\n  ✅ No regressions detected")

    # Version history
    history = prompt_history.get_history("test_dental_maria")
    print(f"  📜 Version history: {[v.version for v in history]}")

    result["regressions"] = regressions
    result["overall"] = {"before": b_total, "after": a_total, "delta": a_total - b_total}
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_e2e_test(
    phase_only: Optional[str] = None,
    full: bool = False,
) -> None:
    """Full pipeline: Create → Score → Optimize → Compare."""
    print("\n" + "=" * 70)
    print("  NEXQA END-TO-END TEST — Dental Receptionist Agent")
    print("=" * 70)

    spec_path = Path("tests/specs/dental_receptionist_spec.yaml")
    if not spec_path.exists():
        print(f"  ❌ Spec file not found: {spec_path}")
        sys.exit(1)

    transcripts = ALL_TRANSCRIPTS if full else LIMITED_TRANSCRIPTS
    print(f"  Mode: {'FULL (15 transcripts)' if full else 'LIMITED (5 transcripts)'}")

    results: Dict[str, Any] = {"phases": {}, "meta": {"full": full, "transcript_count": len(transcripts)}}
    global_start = time.time()

    # ─── PHASE 1 ────────────────────────────────────────────────────
    create_result = phase_create(spec_path)
    results["phases"]["create"] = {k: v for k, v in create_result.items() if k not in ("gene_set", "prompt_text", "tool_schemas")}

    if phase_only == "create":
        print("\n  ✅ Phase 1 (Create) complete. Stopping here (--phase create).")
        _save_report(results)
        return

    # ─── PHASE 2 ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  📊 PHASE 2: Scoring BEFORE optimization")
    print("=" * 70)

    before_scores = phase_score(transcripts, create_result["prompt_text"], label="BEFORE")
    results["phases"]["score_before"] = before_scores

    # ─── PHASE 3 ────────────────────────────────────────────────────
    opt_result = phase_optimize(
        gene_set=create_result["gene_set"],
        prompt_text=create_result["prompt_text"],
        before_scores=before_scores,
        transcripts=transcripts,
    )
    results["phases"]["optimize"] = {k: v for k, v in opt_result.items() if k not in ("gene_set", "prompt_text")}

    if opt_result["status"] == "no_changes":
        print("\n  ⚠️  No optimization applied — skipping Phase 4 re-scoring.")
        _save_report(results)
        return

    # ─── PHASE 4 ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  📊 PHASE 4: Scoring AFTER optimization")
    print("=" * 70)

    after_scores = phase_score(transcripts, opt_result["prompt_text"], label="AFTER")
    results["phases"]["score_after"] = after_scores

    comparison = phase_compare(before_scores, after_scores)
    results["phases"]["comparison"] = comparison

    # ─── Cost summary ──────────────────────────────────────────────
    total_time = time.time() - global_start
    n = len(transcripts)
    # ~2 scoring passes + 1 optimizer pass
    estimated_calls = n * 2 + 1
    print(f"\n  💰 API COST SUMMARY")
    print(f"     Transcripts scored:  {n} × 2 passes = {n * 2} Claude calls")
    print(f"     Optimizer calls:     ~1")
    print(f"     Total Claude calls:  ~{estimated_calls}")
    print(f"     Total time:          {total_time:.1f}s")
    print(f"     Est. cost (Sonnet):  ~${estimated_calls * 0.008:.2f}")

    results["meta"]["total_time_s"] = round(total_time, 1)
    results["meta"]["estimated_claude_calls"] = estimated_calls

    _save_report(results)

    print("\n" + "=" * 70)
    print("  TEST COMPLETE")
    print("=" * 70 + "\n")


def _save_report(results: Dict[str, Any]) -> None:
    """Persist full report as JSON."""
    report_path = Path("tests/reports/dental_e2e_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Make JSON-serializable (drop non-serializable objects)
    def _clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean(i) for i in obj]
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        return str(obj)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(_clean(results), f, indent=2)
    print(f"\n  💾 Report saved to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEXQA E2E Test — Dental Agent")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run all 15 transcripts (default: limited 5)",
    )
    parser.add_argument(
        "--phase",
        choices=["create"],
        default=None,
        help="Run only a specific phase (e.g. 'create' for Phase 1 only)",
    )
    args = parser.parse_args()

    run_e2e_test(phase_only=args.phase, full=args.full)
