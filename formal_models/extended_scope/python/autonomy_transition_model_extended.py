"""
BioDevOps — AI Autonomy Constraint: transition-system model (v2)
==================================================================

WHY THIS VERSION EXISTS
------------------------
A first pass (autonomy_model.py) checked that a *static policy filter*
never lets an (agent, stage) or (agent, component) pair survive. That is
a valid but weak result: it mostly verifies that a filter does what it
was written to do, not that the *system as a whole* — across every
sequence of actions any actor can take — never reaches a state where an
Agent holds execute/deploy capability.

This version models BioDevOps as an explicit LABELLED TRANSITION SYSTEM:

    states  S  = capability configurations (who can execute which stage,
                 who can deploy which component)
    actions A  = the only operations any actor in the system is allowed
                 to invoke (mirroring Sec. IV.E "Information Flow
                 Semantics" and Sec. IV.D "Constraint Enforcement")
    step    -> : S x A -> S   (a small-step transition relation)

We then perform BOUNDED EXHAUSTIVE REACHABILITY ANALYSIS: starting from
an initial state with no capabilities granted, we explore every action
sequence up to a fixed depth (the model-checking "scope", exactly as in
Alloy/TLA+ bounded checking) and verify the invariant

    INV:  for every reachable state s, no Agent appears in
          s.can_execute or s.can_deploy

This is reachability analysis over the full action alphabet, not just a
filter test — i.e. it checks that *no actor, including a fully
adversarial Agent that always attempts to self-grant capability*, can
ever drive the system into a violating state, because the only action
capable of granting execute/deploy rights (`Gate.authorize`) has a
precondition that structurally excludes Agents as its grantee.

CORRESPONDENCE TO THE PAPER
----------------------------
- States  <-> instantaneous snapshot of the access-control relations
  described informally in Sec. IV.C ("Core Architectural Entities").
- Actions <-> the operations enumerated in Sec. IV.E: Stage execution
  request, Agent analysis/recommendation, Human review & sign-off,
  Gate evaluation & authorization.
- The invariant checked here <-> Property "AI Autonomy Constraint"
  (Sec. IV.B.3).

This Python model is deliberately written so it can be translated
near-1:1 into Alloy (signatures = dataclasses, transition relation =
predicate `step`, the bounded search below = `run` command with a
scope). The accompanying autonomy_constraint.als file is that
translation, runnable in the Alloy Analyzer for independent
confirmation.
"""

from dataclasses import dataclass
from itertools import product
from typing import FrozenSet, Tuple, List

ActorId = str
StageId = str
ComponentId = str
GateId = str

# ----------------------------------------------------------------------------
# Universe (bounded scope, same role as Alloy's "scope")
# ----------------------------------------------------------------------------

AGENTS: FrozenSet[ActorId] = frozenset({"agent_1"})
HUMANS: FrozenSet[ActorId] = frozenset({"human_dev", "human_clin"})
ACTORS: FrozenSet[ActorId] = AGENTS | HUMANS

# EXTENDED SCOPE (Phase C, si_scaling_sweep_2026): +1 stage, +1 gate versus the
# original scope (2 stages, 1 gate). This grows the reachable state space by
# ~24x (514 -> 12,292 states, fixed point confirmed at depth 15) while keeping
# runtime under 1 second. AGENTS/HUMANS/COMPONENTS unchanged -- the added
# gate/stage already comfortably clears the >=10x target without needing a
# combinatorially riskier scope (an earlier attempt at AGENTS=2, HUMANS=3,
# STAGES=3, COMPONENTS=3, GATES=2 simultaneously did not terminate within
# 120s and was killed -- see results/formal_verification_extended/README.md).
STAGES: List[StageId] = ["unit_test", "sil_sim", "integration"]
COMPONENTS: List[ComponentId] = ["app", "ml_model"]
GATES: List[GateId] = ["release_gate", "deploy_gate"]


@dataclass(frozen=True)
class State:
    can_execute: FrozenSet[Tuple[ActorId, StageId]]
    can_deploy: FrozenSet[Tuple[ActorId, ComponentId]]
    approved: FrozenSet[GateId]          # gates that have a valid human approval on record
    recommended: FrozenSet[Tuple[ActorId, GateId]]  # agent recommendations attached to a gate (advisory only)

    def violates_invariant(self) -> bool:
        agent_exec = any(a in AGENTS for (a, _s) in self.can_execute)
        agent_deploy = any(a in AGENTS for (a, _c) in self.can_deploy)
        return agent_exec or agent_deploy


INITIAL_STATE = State(
    can_execute=frozenset(),
    can_deploy=frozenset(),
    approved=frozenset(),
    recommended=frozenset(),
)

# ----------------------------------------------------------------------------
# Action alphabet
# ----------------------------------------------------------------------------
#
# Each action is a (name, actor, target) tuple. The transition function
# `step` below is the ONLY place capability sets are ever modified. This
# mirrors the architectural claim: there is exactly one code path
# (Gate.authorize) capable of granting execute/deploy rights, and its
# precondition is part of the model, not an assumption external to it.


def gen_actions():
    actions = []

    # Agent action: produce an advisory recommendation attached to a gate.
    # This is the ONLY action an Agent can invoke. Critically, it does
    # NOT grant execute or deploy capability to anyone -- by definition
    # of what this action does to the state (see `step`).
    for a in AGENTS:
        for g in GATES:
            actions.append(("agent_recommend", a, g))

    # Human action: sign an approval record at a gate. Precondition (not
    # encoded here, encoded in `step`): only humans can perform this.
    for h in HUMANS:
        for g in GATES:
            actions.append(("human_approve", h, g))

    # Gate action: authorize execute capability for a stage, contingent
    # on a human approval already being on record for that gate. The
    # grantee parameter ranges over ALL actors (including agents) --
    # we deliberately do NOT exclude agents from the action's *syntax*,
    # to test whether the SEMANTICS (the precondition inside `step`)
    # is sufficient on its own to block them. This is the adversarial
    # case: what if something upstream tries to authorize an agent?
    for g in GATES:
        for actor in ACTORS:          # <-- includes AGENTS on purpose
            for s in STAGES:
                actions.append(("gate_authorize_execute", g, actor, s))
            for c in COMPONENTS:
                actions.append(("gate_authorize_deploy", g, actor, c))

    return actions


ACTIONS = gen_actions()


def step(state: State, action) -> State:
    """
    The transition relation. This function is the single source of truth
    for how capabilities can change. The AI Autonomy Constraint is upheld
    IF AND ONLY IF this function's preconditions correctly reject any
    attempt to grant an Agent execute/deploy capability -- which is
    exactly the structural claim made in Sec. IV.D ("Constraint
    Enforcement... at the infrastructure layer, regardless of internal
    inference state").
    """
    kind = action[0]

    if kind == "agent_recommend":
        _, actor, gate = action
        # Advisory only: adds a recommendation, never touches
        # can_execute / can_deploy. This is the formalization of
        # Sec IV.E: "these outputs ... cannot be mistaken for human
        # decisions ... do not directly influence safety-critical
        # actions."
        new_recommended = state.recommended | {(actor, gate)}
        return State(state.can_execute, state.can_deploy, state.approved, new_recommended)

    if kind == "human_approve":
        _, actor, gate = action
        # Precondition: actor must be human. (Structurally guaranteed
        # here because this action is only ever generated for actors in
        # HUMANS -- see gen_actions -- but we re-check explicitly to
        # keep the precondition visible and auditable.)
        if actor not in HUMANS:
            return state  # no-op: illegal invocation, state unchanged
        new_approved = state.approved | {gate}
        return State(state.can_execute, state.can_deploy, new_approved, state.recommended)

    if kind == "gate_authorize_execute":
        _, gate, grantee, stage = action
        # PRECONDITION (the crux of the AI Autonomy Constraint):
        #   (a) the gate must have a human approval on record, AND
        #   (b) the grantee must NOT be an Agent.
        # Both conditions must hold for the transition to take effect.
        if gate in state.approved and grantee not in AGENTS:
            new_exec = state.can_execute | {(grantee, stage)}
            return State(new_exec, state.can_deploy, state.approved, state.recommended)
        return state  # precondition fails: no-op

    if kind == "gate_authorize_deploy":
        _, gate, grantee, component = action
        if gate in state.approved and grantee not in AGENTS:
            new_deploy = state.can_deploy | {(grantee, component)}
            return State(state.can_execute, new_deploy, state.approved, state.recommended)
        return state

    raise ValueError(f"Unknown action kind: {kind}")


# ----------------------------------------------------------------------------
# Bounded exhaustive reachability search
# ----------------------------------------------------------------------------
#
# We explore every action sequence up to MAX_DEPTH, tracking the set of
# distinct reachable states (memoized) to avoid redundant re-exploration.
# This is breadth-first reachability analysis -- exhaustive within the
# bound, exactly the guarantee Alloy's bounded model finder provides.

MAX_DEPTH = 22  # Extended scope (Phase C): the larger action alphabet (36 vs
                # 15 actions) reaches its fixed point at depth 15; depth 22
                # is used as the bound to give 7 extra iterations of headroom
                # and confirm the fixed point is genuinely stable, not an
                # artifact of stopping exactly at the boundary.


def explore(max_depth: int):
    frontier = {INITIAL_STATE}
    all_reachable = {INITIAL_STATE}
    violations = []

    for depth in range(max_depth):
        next_frontier = set()
        for s in frontier:
            for action in ACTIONS:
                s2 = step(s, action)
                if s2.violates_invariant():
                    violations.append((s, action, s2))
                if s2 not in all_reachable:
                    all_reachable.add(s2)
                    next_frontier.add(s2)
        frontier = next_frontier
        if not frontier:
            break  # fixed point reached: no new states, search complete

    return all_reachable, violations, depth + 1


if __name__ == "__main__":
    print("=" * 78)
    print("BioDevOps — Transition-system reachability check: AI Autonomy Constraint")
    print("=" * 78)
    print(f"Actors: {sorted(ACTORS)}  (Agents: {sorted(AGENTS)}, Humans: {sorted(HUMANS)})")
    print(f"Stages: {STAGES}   Components: {COMPONENTS}   Gates: {GATES}")
    print(f"Action alphabet size: {len(ACTIONS)}")
    print(f"Search depth bound: {MAX_DEPTH} (bounded exhaustive, BFS over reachable states)")
    print()
    print("Note: the action alphabet deliberately includes")
    print("  gate_authorize_execute(gate, AGENT, stage) and")
    print("  gate_authorize_deploy(gate, AGENT, component)")
    print("as syntactically available actions -- i.e. we do NOT assume an")
    print("agent can't be *named* as the grantee. We test whether the")
    print("transition's PRECONDITION alone is sufficient to block it across")
    print("every reachable state, which is the actual claim made in the paper.")
    print()

    reachable, violations, depth_reached = explore(MAX_DEPTH)

    print("-" * 78)
    print(f"RESULT: {len(reachable):,} distinct states reachable within depth {depth_reached}")
    print(f"        (search reached a fixed point: {depth_reached < MAX_DEPTH})")
    print(f"        {len(violations)} transitions produced a state violating the")
    print(f"        AI Autonomy Constraint.")
    print("-" * 78)

    if not violations:
        print()
        print(">>> NO COUNTEREXAMPLE FOUND.")
        print(">>> No sequence of actions, up to the depth bound, drives the system")
        print(">>> into a state where any Agent holds execute or deploy capability —")
        print(">>> including sequences where the action 'gate_authorize_execute' or")
        print(">>> 'gate_authorize_deploy' is invoked with an Agent named as the")
        print(">>> grantee. The precondition inside the single capability-granting")
        print(">>> transition is sufficient, by itself, to uphold the invariant.")
        print()
        print(f">>> Total distinct reachable states explored: {len(reachable):,}")
    else:
        print()
        print(">>> COUNTEREXAMPLE FOUND:")
        for (s_before, action, s_after) in violations[:5]:
            print(f"    action={action}")
            print(f"    state_after={s_after}")
            print()

    # Sanity check / negative control: confirm the search machinery itself
    # is capable of detecting a violation, by running the same search
    # against a DELIBERATELY BROKEN transition function that omits the
    # "grantee not in AGENTS" precondition. If this control does NOT find
    # a violation, the absence of violations above would be meaningless.
    print()
    print("=" * 78)
    print("NEGATIVE CONTROL: re-running search against a deliberately broken")
    print("transition function (precondition removed) to confirm the search")
    print("procedure itself is capable of detecting violations.")
    print("=" * 78)

    def step_broken(state: State, action):
        kind = action[0]
        if kind == "gate_authorize_execute":
            _, gate, grantee, stage = action
            if gate in state.approved:           # <-- precondition on grantee REMOVED
                new_exec = state.can_execute | {(grantee, stage)}
                return State(new_exec, state.can_deploy, state.approved, state.recommended)
            return state
        if kind == "gate_authorize_deploy":
            _, gate, grantee, component = action
            if gate in state.approved:           # <-- precondition on grantee REMOVED
                new_deploy = state.can_deploy | {(grantee, component)}
                return State(state.can_execute, new_deploy, state.approved, state.recommended)
            return state
        return step(state, action)

    frontier = {INITIAL_STATE}
    all_reachable_b = {INITIAL_STATE}
    violations_b = []
    for depth in range(MAX_DEPTH):
        next_frontier = set()
        for s in frontier:
            for action in ACTIONS:
                s2 = step_broken(s, action)
                if s2.violates_invariant():
                    violations_b.append((s, action, s2))
                if s2 not in all_reachable_b:
                    all_reachable_b.add(s2)
                    next_frontier.add(s2)
        frontier = next_frontier
        if not frontier:
            break

    print(f"Broken-model violations found: {len(violations_b)}")
    if violations_b:
        print(">>> Control PASSED: the search procedure correctly detects the")
        print(">>> violation once the precondition is removed, confirming the")
        print(">>> 'no counterexample' result above is not an artifact of a")
        print(">>> search that can never find violations.")
        example = violations_b[0]
        print(f"    Example violating action: {example[1]}")
        print(f"    Resulting state: {example[2]}")
    else:
        print(">>> WARNING: control did not find a violation either — the search")
        print(">>> procedure itself may be flawed. Do not trust the main result.")
