"""Compute Cohen's kappa between the two MAUDE-ECG annotators (author_A /
author_B) from the merged development/held-out CSVs in this directory.

Usage:
    python3 compute_kappa.py development/maude_ecg_40_development_annotations_merged.csv
    python3 compute_kappa.py held_out/maude_ecg_40_held_out_annotations_merged.csv

Reports, for assertion_status (unweighted), routing_action (ordinal,
quadratic-weighted), and evidence_insufficient (unweighted): n, percent
agreement, Cohen's kappa, and a 95% bootstrap CI (1000 resamples, stdlib
`random` only). This is the exact method used for the kappa values reported
in the manuscript (main.tex, Section VI-A).
"""
from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

ROUTING_ORDER = {
    "NO_ACTION": 0,
    "MONITOR": 1,
    "CAPA_INVESTIGATE": 2,
    "FIELD_SAFETY_CORRECTIVE_ACTION": 3,
    "ESCALATE_TO_HUMAN_IMMEDIATE": 4,
}
ASSERTION_LABELS = ["confirmed", "suspected", "negated", "mention-only"]


def load_pairs(path: Path, field: str) -> list[tuple[str, str]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    pairs = []
    for r in rows:
        a = (r.get(f"{field}_rater1") or "").strip()
        b = (r.get(f"{field}_rater2") or "").strip()
        if a and b:
            pairs.append((a, b))
    return pairs


def percent_agreement(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    return sum(1 for a, b in pairs if a == b) / len(pairs)


def cohen_kappa(pairs: list[tuple[str, str]], labels: list[str], weighted: bool = False) -> float:
    n = len(pairs)
    if n == 0:
        return 0.0
    if weighted:
        max_dist = len(labels) - 1
        po = 1 - sum(
            (abs(ROUTING_ORDER[a] - ROUTING_ORDER[b]) / max_dist) ** 2 for a, b in pairs
        ) / n
        a_counts = {l: sum(1 for a, _ in pairs if a == l) / n for l in labels}
        b_counts = {l: sum(1 for _, b in pairs if b == l) / n for l in labels}
        pe = sum(
            a_counts[la] * b_counts[lb] * (1 - (abs(ROUTING_ORDER[la] - ROUTING_ORDER[lb]) / max_dist) ** 2)
            for la in labels for lb in labels
        )
    else:
        po = percent_agreement(pairs)
        a_counts = {l: sum(1 for a, _ in pairs if a == l) / n for l in labels}
        b_counts = {l: sum(1 for _, b in pairs if b == l) / n for l in labels}
        pe = sum(a_counts[l] * b_counts[l] for l in labels)
    if pe == 1:
        return 1.0
    return (po - pe) / (1 - pe)


def bootstrap_ci(pairs: list[tuple[str, str]], labels: list[str], weighted: bool, resamples: int = 1000, ci: float = 0.95) -> tuple[float, float]:
    n = len(pairs)
    rng = random.Random(42)
    values = []
    for _ in range(resamples):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        values.append(cohen_kappa(sample, labels, weighted))
    values.sort()
    lo_idx = int((1 - ci) / 2 * resamples)
    hi_idx = int((1 + ci) / 2 * resamples) - 1
    return values[lo_idx], values[hi_idx]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: python3 {sys.argv[0]} <merged_annotations.csv>")
    path = Path(sys.argv[1])
    for field, labels, weighted in [
        ("assertion_status", ASSERTION_LABELS, False),
        ("routing_action", list(ROUTING_ORDER), True),
        ("evidence_insufficient", ["yes", "no"], False),
    ]:
        pairs = load_pairs(path, field)
        n = len(pairs)
        pa = percent_agreement(pairs)
        k = cohen_kappa(pairs, labels, weighted)
        lo, hi = bootstrap_ci(pairs, labels, weighted)
        print(f"{field}: n={n} percent_agreement={pa:.3f} kappa={k:.3f} CI=[{lo:.3f},{hi:.3f}]")


if __name__ == "__main__":
    main()
