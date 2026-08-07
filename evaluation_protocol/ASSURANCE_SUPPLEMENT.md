# Assurance supplement: interpretation and reporting tables

## Evidence-to-authority pattern

Required invariants are: (1) a typed advisory object cannot carry execution or
release authority; (2) recommendations expose their evidence roles and gaps;
(3) an external human-controlled authorization object remains distinct; and
(4) every transition is inspectable. OPA, SHACL, Alloy, TLA+, FHIR and SNOMED
are selected implementations, not requirements of the pattern.

| Alternative | Missing boundary property |
|---|---|
| RAG with citations | Citation presence does not make evidence role, gaps, or authority explicit |
| Runtime agent guardrail | Usually constrains calls but does not provide a cross-layer advisory contract |
| Generic HITL queue | Review alone does not preserve evidence-role traceability or a separate authority object |
| Policy-gated MLOps | Can block promotion but need not represent the generated recommendation or its evidence |

## Terminology and metric interpretation

| Term | Meaning in this study |
|---|---|
| Severity | 1--4 advisory harm/risk rubric; not a calibrated clinical probability |
| Recommendation | Closed advisory action label; never release authorization |
| Routing | Agreement with a developer-authored governance reference |
| Universal review | Structural policy boundary, not an empirical safety rate |
| OPA action | Incremental evidence/escalation action beyond the report draft |
| SHACL finding | Post-hoc inconsistency with curated facts, not clinical validity |

## Formal scope

| Property | Exact bounded scope | Operational correlate | Residual gap |
|---|---|---|---|
| Agent authority | Alloy: 6 Time, 6 states, 4 actors, 2 stages/components | Extra fields rejected in `RiskReport` | External endpoint may bypass contract |
| Human accountability | 25 bounded approval configurations | Mandatory review routing | No identity/persistence/authentication implementation |
| Evidence mediation | TLA+: 2 risk signals, 5 steps, stated fairness | Missing technical evidence denial | No proof of evidence completeness or all release paths |

Each property has a negative control. Passing tests are predicate-level
conformance, not a refinement proof.

## Transfer matrix

| Component | CGM status |
|---|---|
| Evidence DAG and advisory contract | Reused unchanged |
| OPA policy and severity rubric | Newly authored for CGM |
| Facts/SHACL mapping | Newly authored and curated |
| Assertion status | Parameterized; mention-versus-confirmed failure observed |
| Evaluation | Portability stress test, not out-of-box generalization |
