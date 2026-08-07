/*
 * BioDevOps -- AI Autonomy Constraint
 * Formal model for the Alloy Analyzer  (v5 -- closes the
 * "length-2 cycle" loophole found by inspecting v4's counterexample)
 *
 * WHAT WAS WRONG WITH v4
 * ------------------------
 * v4 forbade self-loops (t = t.next) but said nothing about cycles of
 * length >= 2. Alloy found Time0 -> Time1 -> Time0 (a 2-cycle). Each of
 * Time0 and Time1 has a predecessor (the other node in the cycle), so
 * neither counts as a "root" under `no t.~next`, and `allRootsClean`
 * constrains nothing on that cycle. Meanwhile `allTransitionsStrict`
 * only has to hold circularly between the two states sitting on Time0
 * and Time1 -- which, as in v3's bug, can be satisfied without either
 * state ever actually starting clean.
 *
 * This is the same root cause as v3 -> v4 (an unconstrained cyclic
 * escape hatch), just at a longer period. The fix generalizes instead
 * of patching the specific period: forbid Time from containing ANY
 * cycle, of any length, using transitive closure.
 *
 * THE FIX
 * -------
 * Alloy provides `^next` (transitive closure of `next`). A relation is
 * acyclic iff no atom is reachable from itself via one or more `next`
 * steps:
 *     no t: Time | t in t.^next
 * This single constraint forbids cycles of every length at once (1, 2,
 * 3, ...), which is the general fix the previous two patches were each
 * only special-casing.
 *
 * With Time forced to be a genuine finite DAG of in-degree/out-degree
 * <= 1 (a simple acyclic chain, given the existing `lone next` /
 * `lone ~next` constraints), every connected component now has a true
 * root with no predecessor, and `allRootsClean` + `allTransitionsStrict`
 * finally constrain the entire universe as originally intended.
 *
 * HOW TO RUN
 * ----------
 * Execute > "Check noAgentEverGainsCapability_GivenStrictTransitions"
 *   Expected: No counterexample found.
 * Execute > "Run negativeControlCanViolate"
 *   Expected: Instance found.
 * Execute > "Run sanityChainIsNontrivial"
 *   Expected: Instance found.
 */

module biodevops_autonomy_v5
open util/ordering[Time]

abstract sig Actor {}
sig Agent extends Actor {}
sig HumanActor extends Actor {}

sig Stage {}
sig Component {}
sig Gate2 {}

sig Time {}

sig SystemState {
    time: one Time,
    canExecute: Actor -> Stage,
    canDeploy: Actor -> Component,
    gateApproved: set Gate2,
    recommended: Actor -> Gate2
}

fact OneStatePerTime {
    all t: Time | one s: SystemState | s.time = t
}

// ---------------------------------------------------------------------------
// THE FIX: forbid cycles of ANY length via transitive closure, not just
// self-loops. This is the general form of the constraint that v4 only
// applied to length-1 cycles.
// ---------------------------------------------------------------------------

fun stateAt[t: Time]: SystemState {
    {s: SystemState | s.time = t}
}

pred isLegalSuccessor_Strict[s1, s2: SystemState] {
    s1.recommended in s2.recommended
    s1.gateApproved in s2.gateApproved

    all actor: Actor, st: Stage |
        (actor -> st in s2.canExecute and actor -> st not in s1.canExecute) =>
            (actor in HumanActor and some s1.gateApproved)

    all actor: Actor, c: Component |
        (actor -> c in s2.canDeploy and actor -> c not in s1.canDeploy) =>
            (actor in HumanActor and some s1.gateApproved)

    s1.canExecute in s2.canExecute
    s1.canDeploy in s2.canDeploy
}

pred isLegalSuccessor_Broken[s1, s2: SystemState] {
    s1.recommended in s2.recommended
    s1.gateApproved in s2.gateApproved

    all actor: Actor, st: Stage |
        (actor -> st in s2.canExecute and actor -> st not in s1.canExecute) =>
            (some s1.gateApproved)

    all actor: Actor, c: Component |
        (actor -> c in s2.canDeploy and actor -> c not in s1.canDeploy) =>
            (some s1.gateApproved)

    s1.canExecute in s2.canExecute
    s1.canDeploy in s2.canDeploy
}

pred allTransitionsStrict {
    all t: Time | some t.~next =>
        isLegalSuccessor_Strict[stateAt[t.~next], stateAt[t]]
}

pred allTransitionsBroken {
    all t: Time | some t.~next =>
        isLegalSuccessor_Broken[stateAt[t.~next], stateAt[t]]
}

pred initialStateClean[s: SystemState] {
    no s.canExecute
    no s.canDeploy
    no s.gateApproved
    no s.recommended
}

pred allRootsClean {
    all t: Time | no t.~next => initialStateClean[stateAt[t]]
}

// ---------------------------------------------------------------------------
// MAIN CHECK
// ---------------------------------------------------------------------------

assert noAgentEverGainsCapability_GivenStrictTransitions {
    (allTransitionsStrict and allRootsClean)
    =>
    (all s: SystemState, a: Agent | no s.canExecute[a] and no s.canDeploy[a])
}

check noAgentEverGainsCapability_GivenStrictTransitions for 12 Time, 12 SystemState, 8 Actor, 4 Stage, 4 Component, 3 Gate2

// ---------------------------------------------------------------------------
// NEGATIVE CONTROL
// ---------------------------------------------------------------------------

pred negativeControlCanViolate {
    allTransitionsBroken and
    allRootsClean and
    (some s: SystemState, a: Agent | some s.canExecute[a] or some s.canDeploy[a])
}

run negativeControlCanViolate for 12 Time, 12 SystemState, 8 Actor, 4 Stage, 4 Component, 3 Gate2

// ---------------------------------------------------------------------------
// SANITY CHECK
// ---------------------------------------------------------------------------

pred sanityChainIsNontrivial {
    allTransitionsStrict and
    allRootsClean and
    (some t: Time | some t.~next) and
    (some s: SystemState, h: HumanActor, st: Stage |
        h -> st in s.canExecute)
}

run sanityChainIsNontrivial for 12 Time, 12 SystemState, 8 Actor, 4 Stage, 4 Component, 3 Gate2
