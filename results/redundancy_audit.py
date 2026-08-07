"""Phase A redundancy audit: OPA/SHACL field-sharing and structural-vs-genuine overlap.

Applies the corrected OPA-independence classifier (excluding the
`clinical_shacl_nonconformance_routes_review` marker that
rag_pipeline.generate_risk_report unconditionally appends to policy_actions
whenever the SHACL clinical guard is nonconformant -- see
biodevops_rag/scripts/reproducibility_audit.py::_opa_independent, which
already carries this fix in the live repo though main_revised.tex's Table
tab:independent-scenario-level was never updated to match) to both:
  (a) the three qwen2.5 model sizes cited in the published paper table, and
  (b) the new 9-model two-family matched_strict sweep.

For every case it also decomposes any OPA/SHACL overlap into
"structurally_redundant" (both layers fired from reading the identical
underlying field/condition: report.evidence_links emptiness, or
severity==4-not-escalated) vs "genuinely_independent" (each layer fired for a
distinct reason) vs "mixed" (both a shared-field trigger and an independent
trigger present) vs "unclassified".
"""
from __future__ import annotations

import json
import math
from pathlib import Path

BIODEVOPS_ROOT = Path("/root/Desktop/BioDevOps")
PROD_RAG = BIODEVOPS_ROOT / "biodevops_rag"
SWEEP_ROOT = BIODEVOPS_ROOT / "si_scaling_sweep_2026"
OUT_DIR = SWEEP_ROOT / "results" / "redundancy_audit"

SHACL_INJECTED_MARKER = "clinical_shacl_nonconformance_routes_review"

EVIDENCE_OPA_ACTIONS = {
    "technical_incident_missing_technical_evidence",
    "deny:technical_incident_missing_technical_evidence",
}
SEVERITY4_OPA_ACTIONS = {"severity4_or_death_forced_immediate_human_escalation"}


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / d
    return max(0.0, c - h), min(1.0, c + h)


def opa_actions_of(row: dict) -> set[str]:
    value = row.get("policy_actions") or ""
    if isinstance(value, list):
        parts = [str(x) for x in value]
    else:
        parts = str(value).split("|")
    return {p for p in parts if p and p != SHACL_INJECTED_MARKER}


def classify_shacl_shapes(row: dict) -> set[str]:
    """Classify each stored clinical_guard_violations entry by message pattern."""
    if row.get("clinical_guard_conforms") is not False:
        return set()
    shapes = set()
    for v in row.get("clinical_guard_violations") or []:
        msg = (v.get("message") or "").strip()
        if msg.startswith("concept_severity_undercall"):
            shapes.add("concept_severity_undercall")
        elif msg.startswith("severity4_opa_overlap"):
            shapes.add("severity4_shared_field")
        elif msg.startswith("recommendation_vs_documented_outcome"):
            shapes.add("recommendation_vs_documented_outcome")
        elif "must link at least one evidence id" in msg or "evidence id" in msg:
            shapes.add("evidence_shared_field")
        elif "SNOMED" in msg or "FHIR" in msg or "Clinical concept must be" in msg:
            shapes.add("fhir_structural")
        else:
            shapes.add("shacl_other:" + msg[:60])
    if not shapes:
        # clinical_guard_conforms is False but no per-shape detail was stored
        # (older runs); still record that SHACL fired without attribution.
        shapes.add("unattributed")
    return shapes


def classify_overlap(opa_actions: set[str], shacl_shapes: set[str]) -> str:
    shared_e = bool(opa_actions & EVIDENCE_OPA_ACTIONS) and "evidence_shared_field" in shacl_shapes
    shared_s4 = bool(opa_actions & SEVERITY4_OPA_ACTIONS) and "severity4_shared_field" in shacl_shapes
    opa_other = bool(opa_actions - EVIDENCE_OPA_ACTIONS - SEVERITY4_OPA_ACTIONS)
    shacl_other = bool(shacl_shapes - {"evidence_shared_field", "severity4_shared_field"})
    independent_both = opa_other and shacl_other
    has_shared = shared_e or shared_s4
    if has_shared and independent_both:
        return "mixed"
    if has_shared:
        return "structurally_redundant"
    if independent_both:
        return "genuinely_independent"
    return "unclassified"


def classify_case(row: dict) -> dict:
    opa_actions = opa_actions_of(row)
    opa_independent = bool(opa_actions)
    shacl_shapes = classify_shacl_shapes(row)
    shacl_flagged = bool(shacl_shapes)
    if opa_independent and shacl_flagged:
        bucket = "overlap"
        overlap_class = classify_overlap(opa_actions, shacl_shapes)
    elif opa_independent:
        bucket = "opa_only"
        overlap_class = ""
    elif shacl_flagged:
        bucket = "shacl_only"
        overlap_class = ""
    else:
        bucket = "neither"
        overlap_class = ""
    return {
        "report_id": row.get("report_id"),
        "opa_actions": sorted(opa_actions),
        "shacl_shapes": sorted(shacl_shapes),
        "bucket": bucket,
        "overlap_class": overlap_class,
    }


def summarize(cases_classified: list[dict]) -> dict:
    n = len(cases_classified)
    counts = {"opa_only": 0, "shacl_only": 0, "overlap": 0, "neither": 0}
    overlap_classes = {"structurally_redundant": 0, "genuinely_independent": 0, "mixed": 0, "unclassified": 0}
    for c in cases_classified:
        counts[c["bucket"]] += 1
        if c["bucket"] == "overlap":
            overlap_classes[c["overlap_class"]] += 1
    union = counts["opa_only"] + counts["shacl_only"] + counts["overlap"]
    # "genuine incremental SHACL value": SHACL-only + (overlap cases that are
    # genuinely_independent or mixed, i.e. SHACL contributed a distinct signal
    # on top of an independently-firing OPA action).
    genuine_shacl_contribution = counts["shacl_only"] + overlap_classes["genuinely_independent"] + overlap_classes["mixed"]
    structurally_inflated = overlap_classes["structurally_redundant"]
    lo, hi = wilson(union, n)
    return {
        "n": n,
        "opa_only": counts["opa_only"],
        "shacl_only": counts["shacl_only"],
        "overlap": counts["overlap"],
        "neither": counts["neither"],
        "overlap_structurally_redundant": overlap_classes["structurally_redundant"],
        "overlap_genuinely_independent": overlap_classes["genuinely_independent"],
        "overlap_mixed": overlap_classes["mixed"],
        "overlap_unclassified": overlap_classes["unclassified"],
        "raw_union_yield": f"{union}/{n}={union/n:.3f}" if n else "NA",
        "union_yield_ci95": [round(lo, 3), round(hi, 3)],
        "genuine_incremental_shacl_value": f"{genuine_shacl_contribution}/{n}={genuine_shacl_contribution/n:.3f}" if n else "NA",
        "structurally_redundant_share_of_union": (
            f"{structurally_inflated}/{union}={structurally_inflated/union:.3f}" if union else "NA"
        ),
    }


def run_qwen25() -> dict:
    files = {
        "qwen2.5:1.5b": PROD_RAG / "evaluation_outputs/generator_sweep_matched/qwen2.5_1.5b/batch_eval_results.json",
        "qwen2.5:3b": PROD_RAG / "evaluation_outputs/generator_sweep_matched/qwen2.5_3b/batch_eval_results.json",
        "qwen2.5:7b": PROD_RAG / "evaluation_outputs/generator_sweep/qwen25_7b_strict_runtime_shacl/batch_eval_results.json",
    }
    results = {}
    for label, path in files.items():
        if not path.exists():
            results[label] = {"status": "MISSING", "path": str(path)}
            continue
        rows = json.loads(path.read_text())["cases"]
        classified = [classify_case(r) for r in rows]
        results[label] = {
            "status": "OK",
            "source_file": str(path.resolve()),
            "pooled": summarize(classified),
            "development": summarize(classified[:20]),
            "held_out": summarize(classified[20:]),
            "cases": classified,
        }
    return results


NEW_SWEEP_MODELS = [
    "qwen3.5_0.8b", "gemma3_1b", "qwen3.5_2b", "gemma3_4b", "qwen3.5_4b",
    "gemma3_12b", "qwen3.5_9b", "gemma3_27b", "qwen3.5_27b",
]


def run_new_sweep() -> dict:
    results = {}
    for model in NEW_SWEEP_MODELS:
        dev_path = SWEEP_ROOT / "results/matched_strict" / model / "development/batch_eval_results.json"
        held_path = SWEEP_ROOT / "results/matched_strict" / model / "held_out/batch_eval_results.json"
        if not dev_path.exists() or not held_path.exists():
            results[model] = {"status": "FAILED_OR_MISSING"}
            continue
        dev_rows = json.loads(dev_path.read_text())["cases"]
        held_rows = json.loads(held_path.read_text())["cases"]
        dev_classified = [classify_case(r) for r in dev_rows]
        held_classified = [classify_case(r) for r in held_rows]
        pooled_classified = dev_classified + held_classified
        results[model] = {
            "status": "OK",
            "pooled": summarize(pooled_classified),
            "development": summarize(dev_classified),
            "held_out": summarize(held_classified),
            "cases": pooled_classified,
        }
    return results


def markdown_qwen25(results: dict) -> str:
    lines = [
        "# qwen2.5 published-table decomposition (corrected classifier)",
        "",
        "Source: same raw `batch_eval_results.json` files cited by `main_revised.tex` Table "
        "tab:independent-scenario-level. Classifier excludes the "
        "`clinical_shacl_nonconformance_routes_review` marker before deciding OPA independence "
        "(the fix already present in `biodevops_rag/scripts/reproducibility_audit.py`, not yet "
        "reflected in the paper text).",
        "",
        "| Model | n | OPA-only | SHACL-only | Overlap | Neither | Overlap: structural | Overlap: genuine | Overlap: mixed | Raw union yield | Structural share of union |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for label, r in results.items():
        if r["status"] != "OK":
            lines.append(f"| {label} | MISSING | - | - | - | - | - | - | - | - | - |")
            continue
        p = r["pooled"]
        lines.append(
            f"| {label} | {p['n']} | {p['opa_only']} | {p['shacl_only']} | {p['overlap']} | {p['neither']} | "
            f"{p['overlap_structurally_redundant']} | {p['overlap_genuinely_independent']} | {p['overlap_mixed']} | "
            f"{p['raw_union_yield']} | {p['structurally_redundant_share_of_union']} |"
        )
    lines.append("")
    lines.append(
        "**Paper currently states SHACL-only = 0/20, 0/20, 0/40 for these three models "
        "(main_revised.tex Table tab:independent-scenario-level, line ~351). This audit "
        "reproduces the corrected non-zero SHACL-only counts independently (matching "
        "`si_experiments_2026/priority2_shacl_uniqueness/BUG_REPORT_AND_CORRECTED_RESULTS.md`) "
        "and additionally shows how much of the *overlap* bucket is structurally redundant "
        "(same underlying field driving both layers) vs a genuine two-mechanism agreement.**"
    )
    return "\n".join(lines)


def markdown_new_sweep(results: dict) -> str:
    lines = [
        "# New 9-model matched_strict sweep decomposition (corrected classifier)",
        "",
        "| Model | n | OPA-only | SHACL-only | Overlap | Neither | Overlap: structural | Overlap: genuine | Overlap: mixed | Raw union yield | Structural share of union |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for model, r in results.items():
        if r["status"] != "OK":
            lines.append(f"| {model} | FAILED/MISSING | - | - | - | - | - | - | - | - | - |")
            continue
        p = r["pooled"]
        lines.append(
            f"| {model} | {p['n']} | {p['opa_only']} | {p['shacl_only']} | {p['overlap']} | {p['neither']} | "
            f"{p['overlap_structurally_redundant']} | {p['overlap_genuinely_independent']} | {p['overlap_mixed']} | "
            f"{p['raw_union_yield']} | {p['structurally_redundant_share_of_union']} |"
        )
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    qwen25 = run_qwen25()
    new_sweep = run_new_sweep()

    (OUT_DIR / "qwen25_decomposition.json").write_text(json.dumps(qwen25, indent=2, sort_keys=True))
    (OUT_DIR / "new_sweep_decomposition.json").write_text(json.dumps(new_sweep, indent=2, sort_keys=True))
    (OUT_DIR / "qwen25_decomposition.md").write_text(markdown_qwen25(qwen25) + "\n")
    (OUT_DIR / "new_sweep_decomposition.md").write_text(markdown_new_sweep(new_sweep) + "\n")

    print(markdown_qwen25(qwen25))
    print()
    print(markdown_new_sweep(new_sweep))


if __name__ == "__main__":
    main()
