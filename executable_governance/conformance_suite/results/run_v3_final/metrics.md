# Factorial Conformance Metrics

Primary intervals are class-level and conservative; row-level intervals are descriptive because rows within a class are correlated.

| Guard | TP | FN | TN | FP | Sensitivity (95% Wilson) | Specificity (95% Wilson) |
|---|---:|---:|---:|---:|---|---|
| OPA | 12 | 0 | 18 | 0 | 1.0 ([0.7575, 1.0]) | 1.0 ([0.8241, 1.0]) |
| SHACL | 16 | 0 | 20 | 0 | 1.0 ([0.8064, 1.0]) | 1.0 ([0.8389, 1.0]) |

## Primary class-level analysis

- OPA: sensitivity 1.0 (95% Wilson [0.4385, 1.0]; 3/3 class units); specificity 1.0 (95% Wilson [0.5655, 1.0]; 5/5 class units).
- SHACL: sensitivity 1.0 (95% Wilson [0.5101, 1.0]; 4/4 class units); specificity 1.0 (95% Wilson [0.6097, 1.0]; 6/6 class units).
