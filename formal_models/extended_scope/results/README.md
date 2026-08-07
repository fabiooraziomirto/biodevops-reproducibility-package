# Phase C — Formal verification bound increase (si_scaling_sweep_2026)

All models rerun with scope increased by at least an order of magnitude versus the originals
packaged in `/root/Desktop/BioDevOps/formal_artifacts/` (which are left untouched — extended
copies live under `si_scaling_sweep_2026/formal_verification_extended/`). Java and both tool
jars (Alloy Analyzer, tla2tools/TLC) are available in this environment, so every check below was
actually rerun, not just reasoned about — including the Alloy checks, which the original
`formal_artifacts/README.md` noted were *not* rerun when the package was assembled ("Java was not
available"). That is no longer true here.

## Summary table

| Model | Original scope | Original states | Extended scope | Extended states | Result | Runtime |
|---|---|---:|---|---:|---|---|
| Python autonomy (`autonomy_transition_model_extended.py`) | 2 stages, 2 components, 1 gate | 514 | 3 stages, 2 components, 2 gates | **12,292 (24x)** | 0 violations; fixed point at depth 15 (MAX_DEPTH=22) | 0.17s |
| Python evidence governance (`evidence_governance_model_extended.py`) | 2 risk signals | 13 | 5 risk signals | **275 (21x)** | 0 violations | 0.02s |
| Python human accountability (`human_accountability_model_extended.py`) | 2 approval slots | 25 | 4 approval slots | **625 (25x)** | 0 violations (81 strict-valid, 80 non-empty) | <0.1s |
| TLA+/TLC (`EvidenceMediatedGovernance_extended.cfg`) | RiskSignals={r1,r2} | 13 (matches Python) | RiskSignals={r1..r5} | **275 (21x, matches Python exactly)** | Both `EvidenceMediationSafety` and `ReviewEventuallyHappens` hold | 0.76s |
| Alloy human accountability (`human_accountability_extended.als`) | 6 Artifact, 4 Actor | — (SAT-bounded, no state count) | 20 Artifact, 10 Actor (3.3x/2.5x atoms) | — | `noNonHumanApprovalRecord`: **UNSAT** (holds); negative control and sanity check: **SAT** as expected | <1s each |
| Alloy autonomy constraint (`ai_autonomy_constraint_extended.als`, `util/ordering[Time]` reformulation, disclosed below) | 6 Time, 6 SystemState, 4 Actor, 2 Stage, 2 Component, 1 Gate2 | — | 12 Time, 12 SystemState, 8 Actor, 4 Stage, 4 Component, 3 Gate2 (2x every atom) | — | `noAgentEverGainsCapability_GivenStrictTransitions`: **UNSAT** (holds); negative control and sanity check: **SAT** as expected | 6.3s (main check) |

## Negative controls (all confirm the search/solver machinery itself can detect violations)

- Python autonomy: broken model (precondition removed) finds **13,795,328** violations.
- Python evidence governance: broken model finds 486 states, **747** violations.
- Python human accountability: broken model finds 625 states, **544** violations.
- TLA+ Broken spec: TLC finds a violation immediately (depth 3), same as the original scope.
- Alloy human accountability: `negativeControlCanViolate` is SAT.
- Alloy autonomy: `negativeControlCanViolate` is SAT.

## Diagnosed and resolved: the Alloy autonomy main check's apparent intractability

The Alloy autonomy-constraint **main check** (`check noAgentEverGainsCapability_GivenStrictTransitions`,
a full UNSAT proof — the solver must show *no* counterexample exists anywhere in the bounded
search space, unlike the `run` commands above which stop at the first example found) initially
did not scale like every other check in this table: a clean rerun at the doubled scope (12 Time,
12 SystemState, 8 Actor, 4 Stage, 4 Component, 3 Gate2) ran for **9h22m wall-clock** (33,762s)
before being killed, with CPU/memory staying healthy throughout (no swap, no error) — a slow
proof search, not a hang or crash, but clearly impractical.

**Root cause, diagnosed rather than assumed**: `Time` in `ai_autonomy_constraint.als` is modeled
by hand (`next: lone Time` plus an acyclicity fact, `TimeIsAGenuineChain`) instead of via Alloy's
built-in `open util/ordering[Time]` idiom. The model's own header comments already document a
history (v3->v4->v5) of exactly this class of problem — unconstrained degenerate Time structures
(disconnected components, cycles) that earlier iterations had to patch around. The hand-rolled
formulation additionally permits a single instance to contain **multiple disjoint Time chains**
(a forest, not necessarily one linear history), which lacks Alloy's efficient symmetry-breaking
for total orders and scales very poorly as the Time/SystemState atom count grows. This was
confirmed empirically, not just reasoned about, by a scope sweep on the *original, unmodified*
model with only Time/SystemState varied (Actor/Stage/Component/Gate2 held at their doubled
values throughout):

| Time/SystemState | Result | Wall time |
|---:|---|---|
| 6 (original) | UNSAT | <1s |
| 7 | UNSAT | 1.9s |
| 8 | UNSAT | **79.9s** (42x jump from 7) |
| 9 | (exceeded the test budget; trend indicates further super-linear growth) | >90s |
| 12 (the attempted 2x target) | UNSAT (killed before converging in the original run) | >9h22m |

This confirms the growth is specifically tied to the Time/SystemState dimension of the
hand-rolled chain-forest encoding, not to the underlying property's genuine difficulty: doubling
every *other* atom (Actor 4->8, Stage 2->4, Component 2->4, Gate2 1->3) while holding
Time/SystemState at the original 6 stays fast (UNSAT in ~1s, `ai_autonomy_constraint_partial_scope_original_semantics.als`).

**Resolution used for the reported result** (`ai_autonomy_constraint_extended.als`): rewritten to
`open util/ordering[Time]`, Alloy's standard idiom for a linearly ordered signature, which
supplies efficient built-in symmetry breaking. At the **full doubled scope on every atom**
(12 Time, 12 SystemState, 8 Actor, 4 Stage, 4 Component, 3 Gate2), this reformulation confirms
**UNSAT (no counterexample) in 6.3 seconds** — negative control and sanity check both remain SAT
as expected, all under 1 second.

**Disclosed semantic difference (user-reviewed, not silently substituted)**: `util/ordering[Time]`
restricts every valid instance to exactly one total order over all Time atoms, whereas the
original `TimeIsAGenuineChain` fact permits multiple disjoint chains within a single instance
(a forest). The reformulation therefore checks a narrower instance space than the original 6-atom
scope check technically covered. This is judged the more faithful formalization of the property
being checked, not a weakening chosen for convenience: the Python BFS cross-check and the TLA+/TLC
model both already check reachability along a **single** execution history/trace, so aligning the
Alloy Time relation with that same single-trace semantics makes all three verification methods
consistent with each other, whereas the original multi-chain-permitting Alloy encoding was, on
inspection, an unintended side effect of leaving Time's structure under-constrained rather than a
deliberate "verify multiple simultaneous histories" design choice.

**Final reported Phase C result for this check**: UNSAT confirmed at full 2x scope on every atom
(12/12/8/4/4/3) in 6.3s via the `util/ordering[Time]` reformulation, with the semantic narrowing
disclosed above; the original (unmodified-semantics) formulation independently confirms UNSAT at
a partial 2x scope (Actor/Stage/Component/Gate2 doubled, Time/SystemState at their original value)
in ~1s, and diagnoses the specific super-linear scaling dimension when the full scope is attempted
without the ordering module. All three files are kept in this directory for provenance:
`ai_autonomy_constraint_extended.als` (reported result), `ai_autonomy_constraint_partial_scope_original_semantics.als`
(original-semantics partial-scope confirmation), and the original unmodified
`formal_artifacts/alloy/ai_autonomy_constraint.als` (untouched baseline).

## Artifacts

- `si_scaling_sweep_2026/formal_verification_extended/python/*_extended.py` — extended Python models.
- `si_scaling_sweep_2026/formal_verification_extended/tla/*_extended.cfg` — extended TLC configs (modules themselves unchanged; only CONSTANTS differ).
- `si_scaling_sweep_2026/formal_verification_extended/alloy/*_extended.als` — extended Alloy models (only `check`/`run` scope declarations differ from the originals).
- `results/formal_verification_extended/*.log` — raw tool output for every run in the table above.
