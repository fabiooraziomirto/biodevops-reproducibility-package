# qwen2.5 published-table decomposition (corrected classifier)

Source: same raw `batch_eval_results.json` files cited by `main_revised.tex` Table tab:independent-scenario-level. Classifier excludes the `clinical_shacl_nonconformance_routes_review` marker before deciding OPA independence (the fix already present in `biodevops_rag/scripts/reproducibility_audit.py`, not yet reflected in the paper text).

| Model | n | OPA-only | SHACL-only | Overlap | Neither | Overlap: structural | Overlap: genuine | Overlap: mixed | Raw union yield | Structural share of union |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| qwen2.5:1.5b | 40 | 16 | 4 | 13 | 7 | 12 | 1 | 0 | 33/40=0.825 | 12/33=0.364 |
| qwen2.5:3b | 40 | 16 | 6 | 3 | 15 | 2 | 1 | 0 | 25/40=0.625 | 2/25=0.080 |
| qwen2.5:7b | 40 | 14 | 12 | 10 | 4 | 4 | 0 | 0 | 36/40=0.900 | 4/36=0.111 |

**Paper currently states SHACL-only = 0/20, 0/20, 0/40 for these three models (main_revised.tex Table tab:independent-scenario-level, line ~351). This audit reproduces the corrected non-zero SHACL-only counts independently (matching `si_experiments_2026/priority2_shacl_uniqueness/BUG_REPORT_AND_CORRECTED_RESULTS.md`) and additionally shows how much of the *overlap* bucket is structurally redundant (same underlying field driving both layers) vs a genuine two-mechanism agreement.**
