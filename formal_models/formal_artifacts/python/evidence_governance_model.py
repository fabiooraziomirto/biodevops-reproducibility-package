"""
BioDevOps -- Evidence-Mediated Governance: Python BFS cross-check.

This script mirrors the small abstract TLA+ model:

    state = (pendingRisk, reviewed, authorized)

The checked safety property is deliberately narrow: no reachable state may
contain an unreviewed pending risk signal while deployment authorization is
true. Evidence completeness, traceability, and approval sufficiency are paper
architecture claims, not variables in this abstract checker.
"""

from collections import deque
from dataclasses import dataclass
from typing import FrozenSet, Iterable, Tuple


RISK_SIGNALS: Tuple[str, ...] = ("r1", "r2")


@dataclass(frozen=True)
class State:
    pending_risk: FrozenSet[str]
    reviewed: Tuple[bool, ...]
    authorized: bool


def reviewed_map(state: State) -> dict[str, bool]:
    return dict(zip(RISK_SIGNALS, state.reviewed))


def set_reviewed(state: State, risk: str) -> Tuple[bool, ...]:
    values = list(state.reviewed)
    values[RISK_SIGNALS.index(risk)] = True
    return tuple(values)


def has_unreviewed_pending_risk(state: State) -> bool:
    reviewed = reviewed_map(state)
    return any(r in state.pending_risk and not reviewed[r] for r in RISK_SIGNALS)


def violates_safety(state: State) -> bool:
    return state.authorized and has_unreviewed_pending_risk(state)


def strict_successors(state: State) -> Iterable[tuple[str, State]]:
    reviewed = reviewed_map(state)

    for risk in RISK_SIGNALS:
        if risk not in state.pending_risk and not reviewed[risk]:
            yield (
                f"RiskArrives({risk})",
                State(
                    pending_risk=frozenset(set(state.pending_risk) | {risk}),
                    reviewed=state.reviewed,
                    authorized=False,
                ),
            )

    for risk in RISK_SIGNALS:
        if risk in state.pending_risk and not reviewed[risk]:
            yield (
                f"ReviewRisk({risk})",
                State(
                    pending_risk=frozenset(set(state.pending_risk) - {risk}),
                    reviewed=set_reviewed(state, risk),
                    authorized=state.authorized,
                ),
            )

    if not has_unreviewed_pending_risk(state):
        yield (
            "GrantAuthorization",
            State(
                pending_risk=state.pending_risk,
                reviewed=state.reviewed,
                authorized=True,
            ),
        )

    yield (
        "RevokeAuthorization",
        State(
            pending_risk=state.pending_risk,
            reviewed=state.reviewed,
            authorized=False,
        ),
    )


def broken_successors(state: State) -> Iterable[tuple[str, State]]:
    yield from strict_successors(state)
    yield (
        "BrokenGrantAuthorization",
        State(
            pending_risk=state.pending_risk,
            reviewed=state.reviewed,
            authorized=True,
        ),
    )


def explore(successor_fn) -> tuple[set[State], list[tuple[State, str, State]]]:
    initial = State(
        pending_risk=frozenset(),
        reviewed=tuple(False for _ in RISK_SIGNALS),
        authorized=False,
    )
    seen = {initial}
    queue = deque([initial])
    violations: list[tuple[State, str, State]] = []

    while queue:
        state = queue.popleft()
        for action, nxt in successor_fn(state):
            if violates_safety(nxt):
                violations.append((state, action, nxt))
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)

    return seen, violations


def main() -> int:
    print("=" * 78)
    print("BioDevOps -- Evidence-Mediated Governance BFS cross-check")
    print("=" * 78)
    print(f"Risk signals: {list(RISK_SIGNALS)}")
    print("Invariant: pending unreviewed risk => not authorized")
    print()

    strict_states, strict_violations = explore(strict_successors)
    print("Strict model")
    print(f"  Reachable states: {len(strict_states)}")
    print(f"  Safety violations: {len(strict_violations)}")
    if strict_violations:
        state, action, nxt = strict_violations[0]
        print(f"  Example violation: {state} --{action}--> {nxt}")
        return 1

    broken_states, broken_violations = explore(broken_successors)
    print()
    print("Negative control")
    print(f"  Reachable states: {len(broken_states)}")
    print(f"  Safety violations: {len(broken_violations)}")
    if not broken_violations:
        print("  ERROR: broken guard did not produce a violation")
        return 1

    state, action, nxt = broken_violations[0]
    print(f"  Example violation: {state} --{action}--> {nxt}")
    print()
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
