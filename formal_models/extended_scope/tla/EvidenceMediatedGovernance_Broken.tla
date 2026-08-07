---------------------------- MODULE EvidenceMediatedGovernance_Broken ----------------------------
(***************************************************************************)
(* NEGATIVE CONTROL for EvidenceMediatedGovernance.tla                    *)
(*                                                                          *)
(* Identical to EvidenceMediatedGovernance.tla EXCEPT that                *)
(* GrantAuthorization's guard (no pending unreviewed risk signal) is       *)
(* removed. If TLC, run against THIS spec checking EvidenceMediationSafety *)
(* as an invariant, finds NO violation, something is wrong with the        *)
(* property statement or the model (the safety property would be trivially*)
(* true regardless of the guard, which would mean it isn't actually        *)
(* testing what we think it's testing).                                    *)
(*                                                                          *)
(* Expected outcome when checked: TLC FINDS a violation (a state where     *)
(* some risk signal is pending and unreviewed, yet authorized = TRUE),     *)
(* with a concrete error trace. This is the TLA+ analogue of the Alloy     *)
(* negativeControlCanViolate run.                                          *)
(***************************************************************************)

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    RiskSignals,
    MaxSteps

VARIABLES
    pendingRisk,
    reviewed,
    authorized

vars == <<pendingRisk, reviewed, authorized>>

Init ==
    /\ pendingRisk = {}
    /\ reviewed = [r \in RiskSignals |-> FALSE]
    /\ authorized = FALSE

RiskArrives(r) ==
    /\ r \notin pendingRisk
    /\ reviewed[r] = FALSE
    /\ pendingRisk' = pendingRisk \cup {r}
    /\ reviewed' = reviewed
    /\ authorized' = FALSE   \* same fix as in the main spec -- kept
                              \* identical here so the ONLY difference
                              \* from the correct model is
                              \* GrantAuthorization's missing guard

ReviewRisk(r) ==
    /\ r \in pendingRisk
    /\ reviewed[r] = FALSE
    /\ pendingRisk' = pendingRisk \ {r}
    /\ reviewed' = [reviewed EXCEPT ![r] = TRUE]
    /\ authorized' = authorized

\* BROKEN: the "every pending risk signal is reviewed" guard is removed.
\* Authorization can now be granted unconditionally, exactly like a system
\* that lets raw runtime alerts (or an unreviewed condition) coexist with
\* an active authorization -- the violation this whole property exists to
\* prevent.
GrantAuthorization_Broken ==
    /\ authorized' = TRUE
    /\ pendingRisk' = pendingRisk
    /\ reviewed' = reviewed

RevokeAuthorization ==
    /\ authorized' = FALSE
    /\ pendingRisk' = pendingRisk
    /\ reviewed' = reviewed

Next ==
    \/ \E r \in RiskSignals : RiskArrives(r)
    \/ \E r \in RiskSignals : ReviewRisk(r)
    \/ GrantAuthorization_Broken
    \/ RevokeAuthorization

Spec == Init /\ [][Next]_vars

EvidenceMediationSafety ==
    [] ( (\E r \in RiskSignals : r \in pendingRisk /\ ~reviewed[r]) => ~authorized )

\* Same condition WITHOUT the leading [] -- this is the per-state predicate
\* TLC's INVARIANT mechanism expects (TLC implicitly checks it holds in
\* EVERY reached state; the [] is implied by the INVARIANT keyword itself,
\* so writing it explicitly inside the formula would be redundant/invalid
\* for this usage).
EvidenceMediationSafetyAsInvariant ==
    (\E r \in RiskSignals : r \in pendingRisk /\ ~reviewed[r]) => ~authorized

=============================================================================
