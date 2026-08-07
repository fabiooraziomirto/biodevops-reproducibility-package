"""Versioned audit schemas for the bounded evidence-assembly agent.

The schemas deliberately separate an advisory model proposal from the action
accepted and executed by the deterministic runtime.  They are also used by the
campaign trace validator; do not remove fields merely because a given action
does not populate them.
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


TRACE_SCHEMA_VERSION = "2.1.0"


class AgentAction(str, Enum):
    INSPECT = "inspect"
    RETRIEVE = "retrieve"
    REQUEST = "request"
    SYNTHESIZE = "synthesize"
    REVISE = "revise"
    ESCALATE = "escalate"


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: AgentAction
    rationale: str = Field(min_length=1, max_length=500)
    query: str = Field(default="", max_length=1000)
    requested_evidence: list[str] = Field(default_factory=list, max_length=8)


class TraceEvent(BaseModel):
    """Compatibility model for an action record.

    ``record`` serializes it together with the required campaign provenance.
    The retained compact fields preserve the public test/API surface.
    """
    model_config = ConfigDict(extra="forbid")
    step: int
    proposed: ActionProposal
    accepted_action: AgentAction
    runtime_reason: str
    state_before: str
    state_after: str
    input_sha256: str
    output_sha256: str
    retrieved_ids: list[str] = Field(default_factory=list)
    missing_or_contradictory_evidence: list[str] = Field(default_factory=list)
    policy_actions: list[str] = Field(default_factory=list)
