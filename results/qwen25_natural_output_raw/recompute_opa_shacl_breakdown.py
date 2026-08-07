#!/usr/bin/env python3
"""Corrected OPA-only/SHACL-only/overlap/neither breakdown for a batch_eval_results.json.

Fixes the classification bug documented in BUG_REPORT_AND_CORRECTED_RESULTS.md:
biodevops_rag/scripts/reproducibility_audit.py::model_breakdown checks
`bool(r.get("policy_actions"))` on the pipe-joined policy_actions string without
excluding the "clinical_shacl_nonconformance_routes_review" marker that
rag_pipeline.generate_risk_report always appends whenever the SHACL clinical
guard is nonconformant. Since that marker is itself non-empty text, every
SHACL-nonconformant row is unconditionally counted as "overlap", making a
nonzero SHACL-only count structurally impossible regardless of the underlying
data. This script splits policy_actions on "|" and excludes that marker before
deciding whether OPA acted independently.

Usage: python3 recompute_opa_shacl_breakdown.py <batch_eval_results.json> [...]
"""
import json
import sys

SHACL_MARKER = "clinical_shacl_nonconformance_routes_review"


def action_list(row: dict) -> list[str]:
    value = row.get("policy_actions") or ""
    if isinstance(value, str):
        return [a for a in value.split("|") if a]
    return list(value)


def opa_independent(row: dict) -> bool:
    return bool([a for a in action_list(row) if a != SHACL_MARKER])


def shacl_flagged(row: dict) -> bool:
    return row.get("clinical_guard_conforms") is False


def breakdown(rows: list[dict]) -> dict:
    n = len(rows)
    opa_only = sum(1 for r in rows if opa_independent(r) and not shacl_flagged(r))
    shacl_only = sum(1 for r in rows if not opa_independent(r) and shacl_flagged(r))
    overlap = sum(1 for r in rows if opa_independent(r) and shacl_flagged(r))
    neither = n - opa_only - shacl_only - overlap
    return {"n": n, "opa_only": opa_only, "shacl_only": shacl_only, "overlap": overlap, "neither": neither}


def main(argv: list[str]) -> None:
    for path in argv:
        data = json.load(open(path))
        rows = data["cases"] if isinstance(data, dict) else data
        result = breakdown(rows)
        print(path)
        print(f"  OPA-only={result['opa_only']}/{result['n']}  SHACL-only={result['shacl_only']}/{result['n']}  "
              f"overlap={result['overlap']}/{result['n']}  neither={result['neither']}/{result['n']}")


if __name__ == "__main__":
    main(sys.argv[1:])
