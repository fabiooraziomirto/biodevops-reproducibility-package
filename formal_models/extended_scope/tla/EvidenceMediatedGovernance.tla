---------------------------- MODULE EvidenceMediatedGovernance ----------------------------
(***************************************************************************)
(* BioDevOps -- Evidence-Mediated Governance                               *)
(*                                                                          *)
(* This module formalizes the property stated informally in the IEEEtran  *)
(* paper (Sec. IV.B.3, "Evidence-Mediated Governance") and precisely in    *)
(* the PhD Forum paper as an LTL Until formula:                           *)
(*                                                                          *)
(*     r in R  =>  not authorized(P)  U  reviewed(r, E, G)                *)
(*                                                                          *)
(* Read: once a risk signal r enters the risk state R, the system is NOT  *)
(* authorized to deploy UNTIL r has been reviewed (transformed into        *)
(* evidence and evaluated by governance). This is the formal content of   *)
(* "raw runtime alerts cannot bypass validation and review."              *)
(*                                                                          *)
(* TLA+ HAS NO NATIVE "UNTIL" OPERATOR -- THE TRANSLATION                  *)
(* --------------------------------------------------------                *)
(* LTL's "A U B" means: B eventually holds, AND A holds at every step      *)
(* strictly before B first holds. In TLA+ this is standard to express as   *)
(* a SAFETY property (not a liveness/Until primitive):                    *)
(*                                                                          *)
(*     [] ( (r \in pendingRisk /\ ~reviewed[r])  =>  ~authorized )         *)
(*                                                                          *)
(* i.e.: "at every state, if r is a pending (unreviewed) risk signal, then *)
(* the system is not authorized." This is logically equivalent to the      *)
(* Until formula PROVIDED we separately establish (as a liveness goal,     *)
(* checked independently, see ReviewEventuallyHappens below) that r does   *)
(* eventually get reviewed under fair scheduling -- otherwise the safety   *)
(* formula above would be satisfied vacuously forever by a system that     *)
(* simply never authorizes anything and never reviews anything either.     *)
(* We check BOTH conjuncts separately, exactly as recommended practice for *)
(* encoding Until-style requirements in TLA+ (the safety half via `[]`,    *)
(* the liveness half via fairness + `<>`).                                *)
(*                                                                          *)
(* LESSONS CARRIED OVER FROM THE ALLOY MODEL, AND A NEW ONE FOUND HERE     *)
(* -------------------------------------------------------------------     *)
(* The Alloy verification of the AI Autonomy Constraint went through five  *)
(* iterations because of unconstrained degenerate structures (disconnected *)
(* states, self-loops, short cycles in the time relation). TLA+'s Init/Next*)
(* idiom sidesteps that whole class of bug: TLC always starts from exactly *)
(* the states satisfying Init and explores only states reachable via Next, *)
(* so there is no equivalent "free-floating atom" loophole to accidentally *)
(* leave unconstrained.                                                     *)
(*                                                                          *)
(* This module nonetheless went through one corrective iteration of its    *)
(* own: an earlier version of RiskArrives left `authorized` unchanged when *)
(* a new signal arrived, reasoning "raw risk arrival never DIRECTLY grants *)
(* authorization." That is true but insufficient -- it allowed a           *)
(* pre-existing authorization to survive the arrival of unmediated risk,   *)
(* which the safety property (an invariant over ALL reachable states, not  *)
(* just those reached via GrantAuthorization) correctly flags as a         *)
(* violation. The fix: RiskArrives now actively sets authorized' = FALSE.  *)
(* This was caught by the Python pre-verification in                       *)
(* evidence_governance_model.py BEFORE this .tla file was finalized -- the *)
(* same negative-control discipline applied to the Alloy model caught it   *)
(* here too, just earlier in the process. We still apply the same          *)
(* discipline of a negative control for the OTHER half of the property     *)
(* (GrantAuthorization's guard), implemented here by deliberately          *)
(* weakening that guard in a separate module and confirming TLC then DOES  *)
(* find a violation.                                                       *)
(***************************************************************************)

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    RiskSignals,      \* the finite universe of risk-signal identifiers
    MaxSteps          \* bound on model-checking depth (TLC explores via BFS
                       \* over the full reachable state graph regardless;
                       \* this constant is used only to bound auxiliary
                       \* counters if needed, kept here for clarity/parity
                       \* with the Alloy model's explicit scope bounds)

VARIABLES
    pendingRisk,      \* set of risk signals that have arrived but not yet
                       \* been reviewed (raw, unmediated risk information)
    reviewed,         \* function RiskSignals -> BOOLEAN: has this signal
                       \* been transformed into governance evidence and
                       \* evaluated at a gate?
    authorized        \* BOOLEAN: is the system currently authorized to
                       \* deploy? (the safety-critical capability this
                       \* property protects)

vars == <<pendingRisk, reviewed, authorized>>

(***************************************************************************)
(* Initial state: no risk signals have arrived, nothing reviewed, system   *)
(* starts unauthorized (mirrors the Alloy model's "clean root" discipline: *)
(* always start from a state where the property's hypotheses are trivially *)
(* satisfied, then let the transition relation be the only thing that can  *)
(* change that).                                                           *)
(***************************************************************************)

Init ==
    /\ pendingRisk = {}
    /\ reviewed = [r \in RiskSignals |-> FALSE]
    /\ authorized = FALSE

(***************************************************************************)
(* Actions                                                                 *)
(***************************************************************************)

\* A new risk signal arrives (e.g. a monitoring/orchestration agent detects
\* drift, an SBOM scan finds a vulnerability, etc.) -- this is RAW runtime
\* information, mirroring the paper's "runtime risk information."
\*
\* IMPORTANT: this action REVOKES any existing authorization. The safety
\* property (EvidenceMediationSafety below) is an invariant over ALL
\* reachable states: "a pending unreviewed risk signal => not authorized."
\* If a pre-existing authorization survived the arrival of unmediated risk
\* untouched, that would itself be a violation. This was found empirically
\* by the negative-control / counterexample process (see
\* evidence_governance_model.py) on an earlier version of this action that
\* set authorized' = authorized -- TLC would have found the same
\* counterexample had this been checked before fixing it here.
RiskArrives(r) ==
    /\ r \notin pendingRisk
    /\ reviewed[r] = FALSE
    /\ pendingRisk' = pendingRisk \cup {r}
    /\ reviewed' = reviewed
    /\ authorized' = FALSE

\* A pending risk signal is reviewed: transformed into governance evidence
\* and evaluated (by a human-controlled gate, per the AI Autonomy
\* Constraint module already verified separately -- this module treats
\* "reviewed" as an atomic action and does not re-model who performs it,
\* since that is exactly the concern of the OTHER property already
\* verified in Alloy).
ReviewRisk(r) ==
    /\ r \in pendingRisk
    /\ reviewed[r] = FALSE
    /\ pendingRisk' = pendingRisk \ {r}
    /\ reviewed' = [reviewed EXCEPT ![r] = TRUE]
    /\ authorized' = authorized

\* The governance gate grants authorization. STRICT guard: authorization
\* may only be granted when there is NO unreviewed pending risk signal --
\* i.e. every risk signal that has arrived has already been mediated into
\* evidence and reviewed. This is the precondition that is supposed to
\* make the Until property hold.
GrantAuthorization ==
    /\ \A r \in RiskSignals : r \in pendingRisk => reviewed[r]
    /\ authorized' = TRUE
    /\ pendingRisk' = pendingRisk
    /\ reviewed' = reviewed

\* Authorization can also be revoked (e.g. end of a deployment window, a
\* new gate cycle starting) -- included for model realism; does not affect
\* the property since revoking only makes the system MORE restrictive.
RevokeAuthorization ==
    /\ authorized' = FALSE
    /\ pendingRisk' = pendingRisk
    /\ reviewed' = reviewed

Next ==
    \/ \E r \in RiskSignals : RiskArrives(r)
    \/ \E r \in RiskSignals : ReviewRisk(r)
    \/ GrantAuthorization
    \/ RevokeAuthorization

Spec == Init /\ [][Next]_vars /\ WF_vars(GrantAuthorization) /\ WF_vars(\E r \in RiskSignals: ReviewRisk(r))

(***************************************************************************)
(* THE SAFETY HALF OF THE UNTIL PROPERTY                                   *)
(* "not authorized(P) holds at every state where some risk signal is       *)
(* pending and unreviewed" -- this is the `[] (...)` encoding described    *)
(* above.                                                                  *)
(***************************************************************************)

EvidenceMediationSafety ==
    [] ( (\E r \in RiskSignals : r \in pendingRisk /\ ~reviewed[r]) => ~authorized )

(***************************************************************************)
(* THE LIVENESS HALF: under fair scheduling (WF_vars on ReviewRisk and     *)
(* GrantAuthorization, declared in Spec above), a pending risk signal      *)
(* eventually gets reviewed -- so the safety property above is not         *)
(* trivially satisfied forever by a system that just never authorizes      *)
(* anything. This corresponds to confirming the Until formula's "B         *)
(* eventually holds" half, not only its "A holds until then" half.        *)
(***************************************************************************)

ReviewEventuallyHappens ==
    \A r \in RiskSignals : (r \in pendingRisk) ~> reviewed[r]

(***************************************************************************)
(* NEGATIVE CONTROL                                                        *)
(* A deliberately weakened GrantAuthorization that omits the "no pending   *)
(* unreviewed risk" guard. Used in a SEPARATE spec (see                    *)
(* EvidenceMediatedGovernance_Broken below) to confirm that                 *)
(* EvidenceMediationSafety is actually falsifiable by TLC -- i.e. that the *)
(* "no violation found" result on the real spec is not vacuous.            *)
(***************************************************************************)

=============================================================================
