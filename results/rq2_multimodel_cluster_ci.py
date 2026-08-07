"""Cluster-adjusted Wilson intervals for every cell of the 9(+1)-model RQ2
scaling sweep, reusing the identical method already applied to the single-model
qwen2.5:7b RQ2 campaign (rq2_cluster_adjustment.py): scenario_id is the exact
cluster unit (5 replicate traces of the same scenario are not independent
observations), one-way ANOVA ICC, design effect DE=1+(N/K-1)*ICC, Wilson CI
computed at both nominal n and effective n=N/DE.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path("/root/Desktop/BioDevOps")
OUT_ROOT = ROOT / "si_scaling_sweep_2026/results/rq2_multimodel_bounded_agent"
MODELS = [
    "qwen3.5_0.8b", "gemma3_1b", "qwen3.5_2b", "gemma3_4b", "qwen3.5_4b",
    "qwen3.5_9b", "gemma3_12b", "gemma3_27b", "qwen3.5_27b", "qwen2.5_7b",
]
ARMS = ("direct", "rag", "agent_raw", "agent_opa")


def wilson(p: float, n: float) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    z = 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / d
    return max(0.0, c - h), min(1.0, c + h)


def icc_de(values_by_scenario: dict[str, list[int]]) -> tuple[float, float, float]:
    groups = [g for g in values_by_scenario.values() if g]
    n = sum(len(g) for g in groups)
    k = len(groups)
    if k < 2 or n <= k:
        return 0.0, 1.0, float(n)
    mean = sum(sum(g) for g in groups) / n
    msb = sum(len(g) * (sum(g) / len(g) - mean) ** 2 for g in groups) / (k - 1)
    msw_num = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in groups)
    msw = msw_num / (n - k) if n > k else 0.0
    m0 = (n - sum(len(g) ** 2 for g in groups) / n) / (k - 1)
    denom = msb + (m0 - 1) * msw
    rho = max(0.0, (msb - msw) / denom) if denom else 0.0
    de = 1 + (n / k - 1) * rho
    return rho, de, n / de


def cell_row(model: str, split: str, arm: str, values_by_scenario: dict[str, list[int]]) -> dict:
    flat = [v for vs in values_by_scenario.values() for v in vs]
    n = len(flat)
    successes = sum(flat)
    p = successes / n if n else 0.0
    lo, hi = wilson(p, n)
    rho, de, neff = icc_de(values_by_scenario)
    alo, ahi = wilson(p, neff)
    return {
        "model": model, "split": split, "arm": arm,
        "successes": successes, "n": n, "estimate": round(p, 4),
        "nominal_ci_lo": round(lo, 4), "nominal_ci_hi": round(hi, 4),
        "icc": round(rho, 4), "design_effect": round(de, 4), "effective_n": round(neff, 3),
        "adj_ci_lo": round(alo, 4), "adj_ci_hi": round(ahi, 4),
    }


def main() -> None:
    rows = []
    for model in MODELS:
        for split in ("development", "held_out"):
            path = OUT_ROOT / model / split / "paired_results.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text())["rows"]
            for arm in ARMS:
                by_scenario: dict[str, list[int]] = defaultdict(list)
                for r in data:
                    if r["arm"] != arm:
                        continue
                    by_scenario[r["scenario_id"]].append(int(bool(r["governance_exact_agreement"])))
                if not by_scenario:
                    continue
                rows.append(cell_row(model, split, arm, by_scenario))

    out_dir = ROOT / "results/rq2_full_sweep_cluster_ci"
    out_dir.mkdir(parents=True, exist_ok=True)
    import csv
    with (out_dir / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (out_dir / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")

    # Flag overlapping CI pairs the paper would want to describe as "different":
    # (a) raw vs agent_opa within the same model/split
    # (b) each model's held-out cell vs the 0/100 baseline (any other model's
    #     held-out same-arm cell that is exactly 0), to check if 5-13/100 cells
    #     are actually distinguishable from zero under cluster adjustment.
    notes = []
    by_key = {(r["model"], r["split"], r["arm"]): r for r in rows}
    for model in MODELS:
        for split in ("development", "held_out"):
            raw = by_key.get((model, split, "agent_raw"))
            opa = by_key.get((model, split, "agent_opa"))
            if not raw or not opa:
                continue
            overlap = not (raw["adj_ci_hi"] < opa["adj_ci_lo"] or opa["adj_ci_hi"] < raw["adj_ci_lo"])
            if overlap and raw["successes"] != opa["successes"]:
                notes.append(
                    f"{model}/{split}: raw={raw['successes']}/100 [{raw['adj_ci_lo']},{raw['adj_ci_hi']}] "
                    f"vs opa={opa['successes']}/100 [{opa['adj_ci_lo']},{opa['adj_ci_hi']}] -- "
                    f"cluster-adjusted CIs OVERLAP despite different point estimates"
                )
    # zero-baseline check: held-out cells with successes in [1,15] vs a true 0/100 cell
    zero_cell_adj_hi = None
    for r in rows:
        if r["split"] == "held_out" and r["successes"] == 0:
            zero_cell_adj_hi = max(zero_cell_adj_hi or 0, r["adj_ci_hi"])
    for r in rows:
        if r["split"] == "held_out" and 0 < r["successes"] <= 15:
            distinguishable = r["adj_ci_lo"] > (zero_cell_adj_hi or 0)
            notes.append(
                f"{r['model']}/{r['arm']} held_out={r['successes']}/100 adj_ci=[{r['adj_ci_lo']},{r['adj_ci_hi']}] "
                f"vs zero-baseline adj_ci_hi={zero_cell_adj_hi} -- "
                f"{'DISTINGUISHABLE from 0' if distinguishable else 'NOT reliably distinguishable from 0 under cluster adjustment'}"
            )

    (out_dir / "non_distinguishable_pairs.md").write_text(
        "# Cells whose cluster-adjusted CIs overlap despite different point estimates\n\n"
        + "\n".join(f"- {n}" for n in notes) + "\n"
    )
    print(f"{len(rows)} cells written. {len(notes)} flagged notes.")


if __name__ == "__main__":
    main()
