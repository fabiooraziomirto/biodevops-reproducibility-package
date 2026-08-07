"""Recompute the RQ2/RQ4 matched-campaign table (Table tab:rq2-governance in the paper)
directly from raw paired_results.json files, independent of any hand-edited paper table.

Source: si_scaling_sweep_2026/results/rq2_multimodel_bounded_agent/<model>/<split>/paired_results.json
Each row has arm in {direct, rag, agent_raw, agent_opa}, completion (bool),
governance_exact_agreement (bool), scenario_id.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "rq2_multimodel_bounded_agent"
MODELS = ["qwen2.5_7b", "qwen3.5_0.8b", "gemma3_1b", "qwen3.5_2b", "gemma3_4b",
          "qwen3.5_4b", "qwen3.5_9b", "gemma3_12b", "gemma3_27b", "qwen3.5_27b"]
SPLITS = ["development", "held_out"]
ARMS = ["direct", "rag", "agent_raw", "agent_opa"]


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def load_rows(model: str, split: str) -> list[dict]:
    path = ROOT / model / split / "paired_results.json"
    return json.loads(path.read_text())["rows"]


def summarize(rows: list[dict]) -> dict:
    out = {}
    for arm in ARMS:
        arm_rows = [r for r in rows if r["arm"] == arm]
        n_total = len(arm_rows)
        n_complete = sum(1 for r in arm_rows if r["completion"])
        n_agree = sum(1 for r in arm_rows if r["completion"] and r["governance_exact_agreement"])
        out[arm] = {"n_total": n_total, "n_complete": n_complete, "n_agree": n_agree}
    return out


def main() -> None:
    all_results = {}
    for model in MODELS:
        all_results[model] = {}
        for split in SPLITS:
            rows = load_rows(model, split)
            all_results[model][split] = summarize(rows)

    # Table reconstruction matching the paper's structure: Complete D/H, Best base
    # (max of direct, rag agreement over n_total=100), Raw (agent_raw agreement /
    # agent_raw completions), +OPA (agent_opa agreement / agent_opa completions).
    print(f"{'model':14s} {'compl.D':>9s} {'compl.H':>9s} "
          f"{'bestD':>10s} {'rawD':>10s} {'opaD':>10s} "
          f"{'bestH':>10s} {'rawH':>10s} {'opaH':>10s}")
    table_rows = []
    for model in MODELS:
        r = all_results[model]
        dev, held = r["development"], r["held_out"]
        compl_d = f"{dev['agent_raw']['n_complete']}/{dev['agent_raw']['n_total']}"
        compl_h = f"{held['agent_raw']['n_complete']}/{held['agent_raw']['n_total']}"
        best_d = max(dev["direct"]["n_agree"], dev["rag"]["n_agree"])
        best_h = max(held["direct"]["n_agree"], held["rag"]["n_agree"])
        raw_d, raw_d_n = dev["agent_raw"]["n_agree"], dev["agent_raw"]["n_complete"]
        opa_d, opa_d_n = dev["agent_opa"]["n_agree"], dev["agent_opa"]["n_complete"]
        raw_h, raw_h_n = held["agent_raw"]["n_agree"], held["agent_raw"]["n_complete"]
        opa_h, opa_h_n = held["agent_opa"]["n_agree"], held["agent_opa"]["n_complete"]
        print(f"{model:14s} {compl_d:>9s} {compl_h:>9s} "
              f"{best_d:>3d}/100   {raw_d:>2d}/{raw_d_n:<3d}   {opa_d:>2d}/{opa_d_n:<3d}   "
              f"{best_h:>3d}/100   {raw_h:>2d}/{raw_h_n:<3d}   {opa_h:>2d}/{opa_h_n:<3d}")
        table_rows.append({
            "model": model, "compl_d": compl_d, "compl_h": compl_h,
            "best_d": best_d, "raw_d": raw_d, "raw_d_n": raw_d_n, "opa_d": opa_d, "opa_d_n": opa_d_n,
            "best_h": best_h, "raw_h": raw_h, "raw_h_n": raw_h_n, "opa_h": opa_h, "opa_h_n": opa_h_n,
            "wilson_agent_opa_dev": wilson_ci(opa_d, opa_d_n),
            "wilson_agent_opa_held": wilson_ci(opa_h, opa_h_n),
        })

    total_attempted = sum(all_results[m][s]["agent_raw"]["n_total"] for m in MODELS for s in SPLITS)
    total_complete = sum(all_results[m][s]["agent_raw"]["n_complete"] for m in MODELS for s in SPLITS)
    print(f"\nTotal attempted agent_raw runs: {total_attempted}")
    print(f"Total completed agent_raw runs: {total_complete}")

    n_models_full = sum(
        1 for m in MODELS
        if all_results[m]["development"]["agent_raw"]["n_complete"] == 100
        and all_results[m]["held_out"]["agent_raw"]["n_complete"] == 100
    )
    print(f"Models with 100/100 on both splits: {n_models_full}")

    out_path = Path(__file__).resolve().parent / "rq2_table_verified.json"
    out_path.write_text(json.dumps(table_rows, indent=2))
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
