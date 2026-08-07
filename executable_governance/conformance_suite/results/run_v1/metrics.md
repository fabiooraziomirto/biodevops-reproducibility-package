# Factorial Conformance Metrics

Primary intervals are class-level and conservative; row-level intervals are descriptive because rows within a class are correlated.

| Guard | TP | FN | TN | FP | Sensitivity (95% Wilson) | Specificity (95% Wilson) |
|---|---:|---:|---:|---:|---|---|
| OPA | 7 | 1 | 16 | 0 | 0.875 ([0.5291, 0.9776]) | 1.0 ([0.8064, 1.0]) |
| SHACL | 14 | 2 | 20 | 0 | 0.875 ([0.6398, 0.965]) | 1.0 ([0.8389, 1.0]) |

## Primary class-level analysis

- OPA: sensitivity 0.5 (95% Wilson [0.0945, 0.9055]; 1/2 class units); specificity 1.0 (95% Wilson [0.5101, 1.0]; 4/4 class units).
- SHACL: sensitivity 0.75 (95% Wilson [0.3006, 0.9544]; 3/4 class units); specificity 1.0 (95% Wilson [0.6097, 1.0]; 6/6 class units).
