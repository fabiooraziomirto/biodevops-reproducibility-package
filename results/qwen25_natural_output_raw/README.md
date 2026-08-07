# Raw qwen2.5 natural-output inputs

These three frozen 40-row `batch_eval_results.json` files support the
qwen2.5:1.5b/3b/7b natural-output statement in manuscript line 277.  Run
`recompute_opa_shacl_breakdown.py` against them to reproduce the corrected
OPA-only, SHACL-only, overlap, and neither counts.  The classifier excludes
the SHACL-injected `clinical_shacl_nonconformance_routes_review` routing marker
when deciding whether OPA independently acted.

The scaling-sweep structural-overlap claim (line 288) is reproducible from the
per-case raw files already retained in `../matched_strict/`, together with
`../redundancy_audit/new_sweep_decomposition.json` and its README.

The raw qwen2.5:3b eight-paraphrase run underlying manuscript line 408 is not
present in this workspace and is therefore not represented here.  It must be
restored from its original archive or rerun under the frozen paraphrase
protocol before an unqualified claim of complete raw-result availability is
made.
