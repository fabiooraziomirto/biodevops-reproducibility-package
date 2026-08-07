# Formal Artifacts

This directory packages the formal artifacts supporting the paper's three
governance properties. The models verify an abstract transition-system
boundary, not the production implementation or the OPA/SHACL policy code.

## Contents

```text
formal_artifacts/
  alloy/
    ai_autonomy_constraint.als
    human_accountability.als
  tla/
    EvidenceMediatedGovernance.tla
    EvidenceMediatedGovernance.cfg
    EvidenceMediatedGovernance_Broken.tla
    EvidenceMediatedGovernance_Broken.cfg
  python/
    autonomy_transition_model.py
    evidence_governance_model.py
    human_accountability_model.py
  traces/
    EvidenceMediatedGovernance_Broken_TTrace_1782764831.tla
    EvidenceMediatedGovernance_Broken_TTrace_1782764831.bin
  tools/
    org.alloytools.alloy.dist.jar
    tla2tools.jar
  SHA256SUMS
```

`SHA256SUMS` records checksums for the packaged files.

## Properties

### AI Autonomy Constraint

Claim: no agent can obtain `can_execute` for a validation stage or `can_deploy`
for a component through the modeled transition system.

Artifacts:
- `alloy/ai_autonomy_constraint.als`
- `python/autonomy_transition_model.py`

Expected result:
- Alloy: no counterexample for the strict assertion within the declared scope.
- Python BFS: 514 reachable states and 0 invariant violations in the strict
  model; the negative control detects violations when the guard is removed.

Run:

```bash
python3 formal_artifacts/python/autonomy_transition_model.py
```

Open `alloy/ai_autonomy_constraint.als` in the Alloy Analyzer to run the Alloy
checks. The Alloy distribution jar is included under `tools/`.

### Human Accountability

Claim: every approval record is created by an authorized human actor.

Artifacts:
- `alloy/human_accountability.als`
- `python/human_accountability_model.py`

Expected result:
- `check noNonHumanApprovalRecord`: no non-authorized approval creator in scope.
- `run negativeControlCanViolate`: instance found.
- `run sanityApprovalRecordsCanExist`: instance found.
- Python enumeration: 25 bounded approval configurations enumerated; 9 are
  strict-valid, 8 contain non-empty approval records, and 0 violate authorized-
  human accountability. The negative control admits 16 non-human or
  unauthorized-human violating configurations.

Run:

```bash
python3 formal_artifacts/python/human_accountability_model.py
```

Open `alloy/human_accountability.als` in the Alloy Analyzer and run the named
commands for the relational check. The Python script is a small bounded
enumeration cross-check over the same abstract authorized-creator constraint.

### Evidence-Mediated Governance

Claim: an unreviewed pending risk signal cannot coexist with deployment
authorization, and pending risks eventually reach review under the fairness
assumptions in the TLA+ model.

Artifacts:
- `tla/EvidenceMediatedGovernance.tla`
- `tla/EvidenceMediatedGovernance.cfg`
- `tla/EvidenceMediatedGovernance_Broken.tla`
- `tla/EvidenceMediatedGovernance_Broken.cfg`
- `python/evidence_governance_model.py`
- `traces/EvidenceMediatedGovernance_Broken_TTrace_1782764831.*`

Expected result:
- Main TLA+ spec: `EvidenceMediationSafety` and `ReviewEventuallyHappens`
  hold within the configured finite model.
- Broken TLA+ spec: TLC finds a violation of the safety property; the saved
  trace is included in `traces/`.
- Python BFS: 13 reachable states and 0 safety violations in the strict model;
  the negative control reaches violating states when the authorization guard is
  removed.

Run:

```bash
python3 formal_artifacts/python/evidence_governance_model.py

java -jar formal_artifacts/tools/tla2tools.jar \
  -config formal_artifacts/tla/EvidenceMediatedGovernance.cfg \
  formal_artifacts/tla/EvidenceMediatedGovernance.tla

java -jar formal_artifacts/tools/tla2tools.jar \
  -config formal_artifacts/tla/EvidenceMediatedGovernance_Broken.cfg \
  formal_artifacts/tla/EvidenceMediatedGovernance_Broken.tla
```

## Scope and Limitations

These artifacts are bounded and abstract. They do not prove unbounded
correctness, clinical correctness, or implementation-level refinement of the
OPA/Rego and SHACL/OWL code. They support the paper's architectural claim that
agentic evidence synthesis is separated from release authority by formally
checked governance boundaries.

Java was not available in the current execution environment when this package
was assembled, so the TLA+/Alloy commands were not rerun here. The runnable
models and tool jars are included for reproducibility in an environment with
Java installed.
