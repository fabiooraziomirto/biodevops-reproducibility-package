# BioDevOps Zenodo package

This package supports the manuscript "BioDevOps: An Assurance Architecture for
Bounded Agentic Evidence Assembly in Medical-Device Governance" (`manuscript/main.tex`).
It is not a clinical validation package.

## Layers

- `manuscript/`: manuscript source (`main.tex`), compiled PDF, IEEE class/style
  files, and figure sources (TikZ + PDF).
- `environment/`: pinned Python dependencies (`requirements.txt`) and exact
  non-Python tool versions (`TOOL_VERSIONS.md`: OPA, Ollama, Alloy, TLC).
- `reproduce.sh`: single entry point that regenerates every number in
  Tables I-V from stored raw outputs (see Reproduction below).
- `formal_models/`: bounded Alloy/TLA+/Python models and negative controls
  (`formal_artifacts/`), plus `extended_scope/`, the larger-bound re-run
  (autonomy 514->12,292 states, evidence mediation 13->275, human
  accountability 25->625; Alloy UNSAT logs, TLC logs, Python BFS logs).
- `agent_specification/`: frozen prompts, advisory/report schemas, and the
  bounded orchestrator (`bounded_agent.py`, `rag_pipeline.py`), plus the
  matched development/held-out campaign raw traces.
- `executable_governance/`: OPA/Rego policies, SHACL/OWL shapes, clinical
  concept mappings, `ontology_validate.py` (the pySHACL/rdflib validator that
  regenerates the paraphrase OPA-or-SHACL decomposition), and the frozen
  factorial conformance suite (48-row prospective + 54-row regression
  results).
- `evaluation_protocol/`: rubrics, frozen labels, the blinded independent-40
  annotation packet, and `maude_ecg_annotations/` (see below).
- `data_availability/`: complete synthetic data; MAUDE identifiers/digests.
- `results/`: stored auditable summaries -- the ten-model RQ2/RQ4 matched
  campaign (raw per-arm traces, `paired_results.json`, `logical_output_checkpoint.jsonl`
  with per-run `latency_ms`), the two-series scaling sweep, the qwen2.5
  single-series sweep, the field-provenance/redundancy audit, the
  SHACL-informed in-loop revision campaigns (with per-call `model_token_counts`),
  `matched_strict_drift_probe/` (the 72-hour same-digest re-probe cited under
  Threats to Validity), and `paraphrase_robustness/` (the qwen2.5:3b
  paraphrase-set OPA/SHACL detection decomposition). Mock fallback runs are
  not empirical evidence.

## Manuscript claim -> source correspondence

| Manuscript item | Source in this package |
|---|---|
| Table I (`tab:rq2-governance`): completion + governance-exact agreement, 10 models | `results/rq2_multimodel_bounded_agent/`; aggregated in `results/rq2_full_sweep_cluster_ci/` |
| 2,000 attempted runs; 1,947/1,189/443/315/53 completion breakdown | `results/rq2_multimodel_bounded_agent/*/*/logical_output_checkpoint.jsonl` and sibling `analysis.json` per model/split |
| Bounded-agent generation latency (median 14.3s, range 7.4-72.8s) | `results/rq2_multimodel_bounded_agent/*/*/logical_output_checkpoint.jsonl`, field `latency_ms` |
| Scenario-cluster-adjusted CIs (e.g. qwen2.5:7b held-out agent+OPA CI [0.028,0.301]) | `results/rq2_full_sweep_cluster_ci/` |
| Formal verification: 514->12,292 / 13->275 / 25->625 states, UNSAT 6.3s | `formal_models/formal_artifacts/` (base scope), `formal_models/extended_scope/` (extended scope + logs) |
| Conformance suite: 48-row prospective (87.5%/87.5%), 54-row regression (12/12, 16/16) | `executable_governance/conformance_suite/results/run_v1/` (pre-repair), `run_v3_final/` (final); `evaluation_protocol/labels/` |
| Table II (`tab:independent-scenario-level`): qwen2.5:3b pooled 17/40, 25/40 union yield | `results/qwen25_natural_output_raw/` (raw) + `results/redundancy_audit/qwen25_decomposition.md` (decomposed) |
| SHACL-only catches 4/6/12 (qwen2.5:1.5b/3b/7b) | `results/qwen25_natural_output_raw/`; recomputed with `results/recompute_opa_shacl_breakdown.py` |
| Field-sharing 87.5-92.5% of union findings; 37/37, 35/35 overlap | `results/redundancy_audit/field_map.md` and sibling `new_sweep_decomposition.md` |
| Table III (`tab:inloop-cross-series`): revise/SHACL-trig./changed counts, 3 models | `results/inloop_revision_baseline_qwen25_3b/` (qwen2.5:3b baseline), `results/inloop_revision_cross_series/` (qwen3.5:9b, gemma3:12b) |
| Per-call token counts (median 1,989 prompt / 437 completion) | `results/inloop_revision_cross_series/*/reports/*.json` + `results/inloop_revision_baseline_qwen25_3b/reports/*.json`, field `model_token_counts` |
| Pre/post-revision ground-truth agreement 5/20->9/20, McNemar p=0.219 | `results/inloop_revision_cross_series/manual_audit_shacl_revisions.json` |
| Table IV (`tab:maude-governance`): MAUDE under-/over-routing, McNemar p=0.031/p=0.5 | `evaluation_protocol/maude_ecg_annotations/`; source labels for the McNemar computation |
| MAUDE inter-rater Cohen's kappa (0.72/1.00, 0.90/0.74, 0.78/0.88) | `evaluation_protocol/maude_ecg_annotations/compute_kappa.py` (script above) |
| Table V (`tab:scaling-sweep`): 8-config scaling sweep | `results/matched_strict/`; aggregated in `results/consolidated_tables/table_scaling_sweep.json` |
| Same-digest 72h re-probe (Threats to Validity, Model reproducibility) | `results/matched_strict_drift_probe/` |
| Cross-domain (CGM) stress test | `formal_models/formal_artifacts/CGM_BOUNDARY_NOTE.md`; CGM-arm rows are part of the frozen campaigns above (see per-model manifests) |
| Paraphrase robustness: 24/40 agreement, 19/40 OPA-or-SHACL union yield | `results/paraphrase_robustness/`; regenerable via `executable_governance/ontology_validate.py` (see `reproduce.sh`) |
| Internal-validity design effect (36 scenarios -> 19 clusters, DE 1.7-2.0) | `results/rq2_full_sweep_cluster_ci/` (cluster-adjustment method; see `README.md`/scripts in `results/`) |

This table lists where each manuscript-reported number lives; most entries
also carry additional decomposition, denominators, and per-model detail not
printed in the manuscript body, consistent with the "full details ... in the
reproducibility package" references throughout Section VI.

## MAUDE-ECG annotations (`evaluation_protocol/maude_ecg_annotations/`)

Per-rater (author_A/author_B), merged, adjudicated, and reference-label CSVs
for both the development and held-out MAUDE-ECG splits, plus
`compute_kappa.py`, which reproduces the inter-rater Cohen's kappa values
reported in the manuscript (Section VI-A) directly from the merged CSVs:

```bash
python3 evaluation_protocol/maude_ecg_annotations/compute_kappa.py \
  evaluation_protocol/maude_ecg_annotations/development/maude_ecg_40_development_annotations_merged.csv
python3 evaluation_protocol/maude_ecg_annotations/compute_kappa.py \
  evaluation_protocol/maude_ecg_annotations/held_out/maude_ecg_40_held_out_annotations_merged.csv
```

These CSVs include the full source narrative text of the underlying FDA MAUDE
reports (public domain, U.S. government work), reproduced from the public
FDA MAUDE database. This is a deliberate exception to the index-only policy
in `data_availability/` (see below): full narrative text is included here so
a reviewer can audit each rater's judgment and the kappa computation directly
against the source text, rather than only against an FDA record ID/digest.

## Reproduction

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r environment/requirements.txt
./reproduce.sh
```

`reproduce.sh` runs every table-regeneration script in sequence
(`rq2_multimodel_cluster_ci.py`, `build_scaling_summary_table.py`,
`redundancy_audit.py`, `recompute_opa_shacl_breakdown.py`,
`inloop_revision_cross_series/aggregate_inloop_cross_series.py`,
`inloop_revision_cross_series/verify_rq2_table.py`,
`evaluation_protocol/maude_ecg_annotations/compute_kappa.py`,
`executable_governance/ontology_validate.py`) against the stored raw
outputs and prints every number that appears in Tables I-V. It requires only
Python 3.10+ and `environment/requirements.txt` -- no OPA binary, no Ollama,
no Alloy/TLC (see `environment/TOOL_VERSIONS.md` for exact versions and what
does vs. does not need them).

The matched development/held-out bounded-agent campaigns, the RQ2 ten-model
campaign, the in-loop revision campaigns, and the drift probe under
`results/` are frozen, hash-authorized, one-shot runs; `reproduce.sh` never
reruns them, only the derived-table scripts above. `agent_specification/
run_bounded_arm_inloop_revision.py` is the runner that produced the in-loop
revision campaigns and can be rerun on new scenarios or models under the
same frozen protocol (requires OPA and Ollama, see
`environment/TOOL_VERSIONS.md`) -- `reproduce.sh` does not call it.

## Data availability and reuse

Synthetic scenarios are included and marked synthetic. FDA MAUDE narratives
are, as a general policy, not redistributed outside the annotation CSVs
described above: `data_availability/maude_record_index.json` provides FDA
IDs, URLs, and SHA-256 provenance for records not otherwise reproduced here.
No license is asserted for third-party standards, ontologies, model weights,
or FDA source text.

## Folder naming vs. internal provenance records

Top-level folder names avoid embedding the calendar date a run happened to
launch (e.g. `results/inloop_revision_cross_series/`, not
`..._20260806/`). The `campaign_manifest.json`, `cross_series_metrics.json`,
and script files *inside* those folders retain their original absolute
paths, `campaign-id` strings, and executed commands unchanged (e.g.
`--campaign-id inloop_revision_qwen3.5_9b_20260806`): these are frozen,
hash-referenced provenance records of what was actually run, not
presentation text, and rewriting them would misrepresent the historical
record rather than merely rename a folder. Cross-reference the table above
if a path inside a manifest no longer matches the folder it lives in.

## Checksums

`SHA256SUMS.json` is a flat `relative_path -> sha256` manifest covering
every file in this package (3,214 files). Verify with:

```bash
python3 -c "
import hashlib, json
from pathlib import Path
manifest = json.load(open('SHA256SUMS.json'))
bad = [p for p, h in manifest.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest() != h]
print('OK' if not bad else f'MISMATCH: {bad}')
"
```

Regenerate after any further change to this package's contents.
