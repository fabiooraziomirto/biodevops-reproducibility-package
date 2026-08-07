# Exact tool versions used to produce the stored results

Pinning these matters because SHACL/OWL verdicts depend on the pySHACL/rdflib/owlrl
version, OPA verdicts depend on the OPA binary version and Rego syntax version,
and the formal checks depend on the Alloy/TLC build. `requirements.txt` in this
directory pins the Python side; this file records the non-Python tools, which
are not installable via pip.

| Tool | Version | Notes |
|---|---|---|
| Python | 3.10 | Interpreter used for all scripts in this package |
| Ollama server | 0.32.5 | Recorded per-run in `results/*/model_provenance*.json`; required only to regenerate raw model outputs, not to recompute stored tables |
| Open Policy Agent (OPA) | 1.18.1 (`acc8bf9f88bbef57c500dbdd7231509e48ade525-dirty`, Go 1.26.4, Rego v1) | Evaluates `executable_governance/policies/*.rego`; obtain a matching release from https://github.com/open-policy-agent/opa/releases (this package does not bundle the ~54MB binary -- see note below) |
| Alloy | 6.2.0.202501090817 | Bundled as `formal_models/formal_artifacts/tools/org.alloytools.alloy.dist.jar` |
| TLA+ Tools (TLC) | 2.0, built 2026-05-26, commit `4ba7d88` | Bundled as `formal_models/formal_artifacts/tools/tla2tools.jar` |

## What this package lets you re-run without external tools

The table-regeneration scripts (`results/rq2_multimodel_cluster_ci.py`,
`results/build_scaling_summary_table.py`, `results/redundancy_audit.py`,
`results/recompute_opa_shacl_breakdown.py`,
`results/inloop_revision_cross_series/aggregate_inloop_cross_series.py`,
`results/inloop_revision_cross_series/verify_rq2_table.py`,
`evaluation_protocol/maude_ecg_annotations/compute_kappa.py`) only need
Python 3.10 with `requirements.txt` installed -- they recompute tables from
the already-stored raw outputs and do not call OPA, SHACL, or Ollama.

Re-running OPA/SHACL verification itself against new input, or generating new
model output via Ollama, requires the OPA binary and Ollama server versions
above; the adapter scripts that call them (`opa_policy.py`,
`ontology_validate.py`, `rag_pipeline.py` generation path) live in the full
project repository, not in this package, consistent with the "do not rerun
frozen campaigns" policy in the top-level README.
