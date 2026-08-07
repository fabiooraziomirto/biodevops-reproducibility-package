#!/usr/bin/env python3
"""Compute guard-specific row and conservative class-level conformance metrics."""
from __future__ import annotations
import json
import math
import argparse
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def wilson(success: int, total: int) -> list[float] | None:
    if not total: return None
    z = 1.959963984540054; p = success / total; d = 1 + z*z/total
    centre = (p + z*z/(2*total))/d; margin = z*math.sqrt((p*(1-p)+z*z/(4*total))/total)/d
    return [round(centre-margin, 4), round(centre+margin, 4)]

def matrix(rows: list[dict], guard: str) -> dict:
    c = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    for row in rows:
        label = row["frozen_label"][guard]
        if label["eligibility"] != "eligible": continue
        truth, pred = label["violation_present"], row["observed"][f"{guard}_issue"]
        c["TP" if truth and pred else "FN" if truth else "FP" if pred else "TN"] += 1
    sens_n, spec_n = c["TP"]+c["FN"], c["TN"]+c["FP"]
    return {**c, "sensitivity": None if not sens_n else round(c["TP"]/sens_n, 4), "sensitivity_wilson_95": wilson(c["TP"], sens_n), "specificity": None if not spec_n else round(c["TN"]/spec_n, 4), "specificity_wilson_95": wilson(c["TN"], spec_n), "positive_denominator": sens_n, "negative_denominator": spec_n}

def class_matrix(rows: list[dict], guard: str) -> dict:
    # One unit per class/polarity: success requires every eligible row of that polarity to be correct.
    by = defaultdict(list)
    for row in rows:
        label = row["frozen_label"][guard]
        if label["eligibility"] == "eligible": by[(row["class"], label["violation_present"])].append(row)
    output = {}
    for polarity, name in ((True, "sensitivity"), (False, "specificity")):
        units = []
        for (_cls, truth), group in by.items():
            if truth == polarity: units.append(all(item["observed"][f"{guard}_issue"] == truth for item in group))
        output[name] = {"class_units": len(units), "successful_classes": sum(units), "estimate": None if not units else round(sum(units)/len(units), 4), "wilson_95": wilson(sum(units), len(units))}
    return output

def main(run_id: str) -> None:
    out = ROOT / "results" / f"run_{run_id}"
    raw = out / "raw_observations.jsonl"
    rows = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines() if line]
    classes = sorted({row["class"] for row in rows})
    metrics = {"method": {"opa_positive": "deny, policy action, or recommendation override; default human review excluded", "shacl_positive": "ontology_conforms == false excluding informational-only messages", "primary": "class-level all-rows-correct Wilson; correlated rows within a class", "secondary": "row-level descriptive Wilson"}, "row_level": {g: matrix(rows, g) for g in ("opa", "shacl")}, "class_level_primary": {g: class_matrix(rows, g) for g in ("opa", "shacl")}, "per_class_row_level": {str(c): {g: matrix([r for r in rows if r["class"] == c], g) for g in ("opa", "shacl")} for c in classes}}
    out.mkdir(parents=True, exist_ok=True); (out / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    matrices = {"row_level": metrics["row_level"], "per_class_row_level": metrics["per_class_row_level"]}
    (out / "confusion_matrices.json").write_text(json.dumps(matrices, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    lines = ["# Factorial Conformance Metrics", "", "Primary intervals are class-level and conservative; row-level intervals are descriptive because rows within a class are correlated.", "", "| Guard | TP | FN | TN | FP | Sensitivity (95% Wilson) | Specificity (95% Wilson) |", "|---|---:|---:|---:|---:|---|---|"]
    for g in ("opa", "shacl"):
        m = metrics["row_level"][g]; lines.append(f"| {g.upper()} | {m['TP']} | {m['FN']} | {m['TN']} | {m['FP']} | {m['sensitivity']} ({m['sensitivity_wilson_95']}) | {m['specificity']} ({m['specificity_wilson_95']}) |")
    lines += ["", "## Primary class-level analysis", ""]
    for g in ("opa", "shacl"):
        x = metrics["class_level_primary"][g]
        sens, spec = x["sensitivity"], x["specificity"]
        lines.append(
            f"- {g.upper()}: sensitivity {sens['estimate']} (95% Wilson {sens['wilson_95']}; "
            f"{sens['successful_classes']}/{sens['class_units']} class units); specificity "
            f"{spec['estimate']} (95% Wilson {spec['wilson_95']}; "
            f"{spec['successful_classes']}/{spec['class_units']} class units)."
        )
    (out / "metrics.md").write_text("\n".join(lines)+"\n", encoding="utf-8")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="v1")
    main(parser.parse_args().run_id)
