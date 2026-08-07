"""Build the 2-family x N-size scaling table from matched_strict sweep outputs.

OPA-or-SHACL union yield here follows the same definition used elsewhere in
the repo (e.g. experiments/extension/scripts/cluster_adjust_wilson.py): a
case is "caught" if OPA recorded any policy_actions OR the SHACL clinical
guard found the case non-conformant (clinical_guard_conforms is False).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "matched_strict"

MODELS = [
    "qwen3.5_0.8b", "gemma3_1b", "qwen3.5_2b", "gemma3_4b", "qwen3.5_4b",
    "gemma3_12b", "qwen3.5_9b", "gemma3_27b", "qwen3.5_27b",
]


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / d
    return max(0.0, c - h), min(1.0, c + h)


def union_caught(case: dict) -> int:
    opa_flag = bool(case.get("policy_actions"))
    shacl_flag = case.get("clinical_guard_conforms") is False
    return int(opa_flag or shacl_flag)


def load_pooled_cases(model: str) -> list[dict] | None:
    cases = []
    for split in ("development", "held_out"):
        f = RESULTS / model / split / "batch_eval_results.json"
        if not f.exists():
            return None
        cases.extend(json.loads(f.read_text())["cases"])
    return cases


def main() -> None:
    rows = []
    for model in MODELS:
        cases = load_pooled_cases(model)
        if cases is None:
            rows.append({"model": model, "status": "FAILED_OR_MISSING"})
            continue
        n = len(cases)
        severity_exact = sum(c["severity_correct"] for c in cases)
        severity_within1 = sum(1 for c in cases if abs(c["ground_truth_severity"] - c["verified_severity"]) <= 1)
        union = sum(union_caught(c) for c in cases)
        halluc = sum(c["citation_hallucination"] for c in cases)
        sev_lo, sev_hi = wilson(severity_exact, n)
        sw_lo, sw_hi = wilson(severity_within1, n)
        un_lo, un_hi = wilson(union, n)
        rows.append({
            "model": model, "status": "OK", "n": n,
            "severity_exact": f"{severity_exact}/{n}={severity_exact/n:.3f}",
            "severity_exact_ci95": [round(sev_lo, 3), round(sev_hi, 3)],
            "severity_within1": f"{severity_within1}/{n}={severity_within1/n:.3f}",
            "severity_within1_ci95": [round(sw_lo, 3), round(sw_hi, 3)],
            "opa_or_shacl_union_yield": f"{union}/{n}={union/n:.3f}",
            "union_yield_ci95": [round(un_lo, 3), round(un_hi, 3)],
            "citation_hallucination_rate": f"{halluc}/{n}={halluc/n:.3f}",
        })

    out = ROOT / "scaling_summary_table.json"
    out.write_text(json.dumps(rows, indent=2))

    lines = [
        "| Model | Status | n | Severity exact | Severity within-1 | OPA-or-SHACL union yield | Citation hallucination |",
        "|---|---|---:|---|---|---|---|",
    ]
    for r in rows:
        if r["status"] != "OK":
            lines.append(f"| {r['model']} | {r['status']} | - | - | - | - | - |")
            continue
        lines.append(
            f"| {r['model']} | OK | {r['n']} | {r['severity_exact']} {r['severity_exact_ci95']} | "
            f"{r['severity_within1']} {r['severity_within1_ci95']} | "
            f"{r['opa_or_shacl_union_yield']} {r['union_yield_ci95']} | {r['citation_hallucination_rate']} |"
        )
    (ROOT / "scaling_summary_table.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
