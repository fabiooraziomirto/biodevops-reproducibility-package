"""
BioDevOps -- Human Accountability: bounded Python enumeration.

The structural claim is that every approval record is created by an authorized
human actor. The Alloy model is the primary relational artifact; this script is
a small explicit enumeration over a finite scope used as an independent
cross-check and negative-control harness.
"""

from itertools import product
from typing import Optional, Tuple


AGENTS = ("agent_1",)
HUMANS = ("human_dev", "human_clin", "human_observer")
AUTHORIZED_HUMANS = frozenset({"human_dev", "human_clin"})
ACTORS = AGENTS + HUMANS
APPROVAL_SLOTS = ("approval_1", "approval_2")

Creator = Optional[str]
ApprovalState = Tuple[Creator, ...]


def records(state: ApprovalState) -> list[tuple[str, str]]:
    return [
        (slot, creator)
        for slot, creator in zip(APPROVAL_SLOTS, state)
        if creator is not None
    ]


def strict_valid(state: ApprovalState) -> bool:
    return all(creator in AUTHORIZED_HUMANS for _, creator in records(state))


def broken_valid(state: ApprovalState) -> bool:
    return all(creator in ACTORS for _, creator in records(state))


def has_violation(state: ApprovalState) -> bool:
    return any(creator not in AUTHORIZED_HUMANS for _, creator in records(state))


def enumerate_states() -> list[ApprovalState]:
    choices: tuple[Creator, ...] = (None,) + ACTORS
    return list(product(choices, repeat=len(APPROVAL_SLOTS)))


def main() -> int:
    print("=" * 78)
    print("BioDevOps -- Human Accountability bounded enumeration")
    print("=" * 78)
    print(f"Actors: {list(ACTORS)}")
    print(f"Authorized humans: {sorted(AUTHORIZED_HUMANS)}")
    print(f"Approval slots: {list(APPROVAL_SLOTS)}")
    print()

    states = enumerate_states()
    strict_states = [state for state in states if strict_valid(state)]
    strict_violations = [state for state in strict_states if has_violation(state)]
    sanity_states = [state for state in strict_states if records(state)]

    print("Strict model")
    print(f"  Enumerated states: {len(states)}")
    print(f"  Strict-valid states: {len(strict_states)}")
    print(f"  Non-empty strict-valid states: {len(sanity_states)}")
    print(f"  Accountability violations: {len(strict_violations)}")
    if strict_violations:
        print(f"  Example violation: {strict_violations[0]}")
        return 1
    if not sanity_states:
        print("  ERROR: strict model is vacuous; no approval records can exist")
        return 1

    broken_states = [state for state in states if broken_valid(state)]
    broken_violations = [state for state in broken_states if has_violation(state)]

    print()
    print("Negative control")
    print(f"  Broken-valid states: {len(broken_states)}")
    print(f"  Accountability violations admitted: {len(broken_violations)}")
    if not broken_violations:
        print("  ERROR: broken model did not admit a non-human or unauthorized creator")
        return 1
    print(f"  Example violation: {broken_violations[0]}")
    print()
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
