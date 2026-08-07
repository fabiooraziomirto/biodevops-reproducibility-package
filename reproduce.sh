#!/usr/bin/env bash
# Regenerates every table/number in the manuscript's Evaluation section from
# the stored raw outputs in this package. Does NOT rerun any frozen campaign,
# OPA/SHACL/Ollama inference, or formal-verification search -- see
# environment/TOOL_VERSIONS.md and README.md ("Folder naming vs. internal
# provenance records") for why those are one-shot, hash-authorized runs.
#
# Usage: ./reproduce.sh
# Requires: Python 3.10+ with environment/requirements.txt installed.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== Table I (tab:rq2-governance): completion + governance-exact agreement ==="
python3 results/rq2_multimodel_cluster_ci.py
python3 results/inloop_revision_cross_series/verify_rq2_table.py

echo
echo "=== Table II (tab:independent-scenario-level) / SHACL-only 4/6/12 ==="
python3 results/recompute_opa_shacl_breakdown.py \
  results/qwen25_natural_output_raw/qwen2.5_1.5b_baseline_batch_eval_results.json \
  results/qwen25_natural_output_raw/qwen2.5_3b_baseline_batch_eval_results.json \
  results/qwen25_natural_output_raw/qwen2.5_7b_baseline_batch_eval_results.json

echo
echo "=== Field-sharing decomposition (87.5-92.5% of union findings) ==="
python3 results/redundancy_audit.py

echo
echo "=== Table V (tab:scaling-sweep): two-series scaling sweep ==="
python3 results/build_scaling_summary_table.py

echo
echo "=== Table III (tab:inloop-cross-series) aggregation ==="
python3 results/inloop_revision_cross_series/aggregate_inloop_cross_series.py

echo
echo "=== Table IV (tab:maude-governance) inter-rater Cohen's kappa ==="
python3 evaluation_protocol/maude_ecg_annotations/compute_kappa.py \
  evaluation_protocol/maude_ecg_annotations/development/maude_ecg_40_development_annotations_merged.csv
python3 evaluation_protocol/maude_ecg_annotations/compute_kappa.py \
  evaluation_protocol/maude_ecg_annotations/held_out/maude_ecg_40_held_out_annotations_merged.csv

echo
echo "=== Paraphrase robustness: OPA-or-SHACL union yield 19/40 (3/6/10) ==="
echo "Requires pyshacl/rdflib (environment/requirements.txt)."
python3 executable_governance/ontology_validate.py \
  --input results/paraphrase_robustness/batch_eval_results.json \
  --concepts executable_governance/ontology/clinical_concepts.json \
  --out /tmp/reproduce_paraphrase_ontology \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['files'][0]['summary'], indent=2))"

echo
echo "=== Done. Cross-check printed values against manuscript/main.tex. ==="
echo "Formal verification (514->12,292 / 13->275 / 25->625 states) and the"
echo "72-hour drift probe are pre-computed, machine-verifiable logs, not"
echo "regenerated here -- see formal_models/extended_scope/results/*.log and"
echo "results/matched_strict_drift_probe/, respectively."
