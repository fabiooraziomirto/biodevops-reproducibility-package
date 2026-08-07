# Factorial OPA/Rego + SHACL conformance suite

Run the freeze before execution:

```bash
venv/bin/python conformance_suite/scripts/run_factorial_conformance.py --freeze
venv/bin/python conformance_suite/scripts/run_factorial_conformance.py --run
venv/bin/python conformance_suite/scripts/compute_conformance_metrics.py
```

The suite is separate from, and does not alter, the naturalistic generator guard-trigger-yield sweep. Primary reporting uses class-level Wilson intervals; pooled row-level intervals are descriptive because rows are correlated within failure-mode classes. See `rubric_v1.md` for labeling and circularity controls.
