# CGM Formal Boundary Note

This extension introduces a second clinical domain solely to demonstrate architectural transferability. It does not modify or replace the published arrhythmia benchmark, and no new scientific performance claims are introduced.

The Alloy and TLA artifacts are intentionally unchanged. They model the governance boundary: machine-generated evidence and RiskReports cannot substitute for required human accountability, and autonomous transitions remain constrained by evidence and approval state.

The CGM extension changes the clinical ontology and the domain policy, not the formal governance boundary. Severe hypoglycemia, sensor failure, missing glucose evidence, and conflicting observations are domain-specific facts. They are mapped into the same architectural roles already represented by the formal models: evidence, risk classification, policy gating, and human approval.

For this reason, the existing formal artifacts remain reusable:

- The governance boundary is domain-independent.
- The clinical ontology is domain-specific.
- OPA policies are domain-specific.
- Human approval remains mandatory for high-risk governance actions.

No Alloy or TLA specification is changed, regenerated, or revalidated by this extension.
