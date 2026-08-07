"""Bounded, traceable advisory evidence-assembly orchestration.

The model proposes an action and (for retrieval) a query.  The runtime alone
validates transitions, executes allow-listed tools, and writes audit records.
There is no approval, validation-execution, deployment, or release tool.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from agent_trace_schema import ActionProposal, AgentAction, TRACE_SCHEMA_VERSION, TraceEvent
from rag_pipeline import MockOllamaClient, build_revision_feedback_block, generate_risk_report, get_embedder, retrieve_context

MAX_STEPS = 6
MAX_REVISIONS = 1
ALLOWED_TOOLS = {"inspect_case", "retrieve_context", "request_evidence", "synthesize_report", "verify_report"}
LEGAL_TRANSITIONS = {
    "new": {AgentAction.INSPECT},
    "inspected": {AgentAction.RETRIEVE},
    "retrieved": {AgentAction.REQUEST, AgentAction.SYNTHESIZE},
    "requested": {AgentAction.SYNTHESIZE},
    "verified": {AgentAction.REVISE, AgentAction.ESCALATE},
}


def validate_transition(state: str, proposed: AgentAction, *, parse_failed: bool = False) -> tuple[AgentAction, str | None, str]:
    """Return the runtime action and an auditable rejection outcome.

    This is deliberately pure so every state/action combination can be tested
    independently of model inference or retrieval infrastructure.
    """
    if proposed in LEGAL_TRANSITIONS.get(state, set()):
        return proposed, None, ""
    return AgentAction.ESCALATE, proposed.value, "planner_parse_error" if parse_failed else "illegal_state_transition"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_retrieval_query(query: str) -> str:
    """v2: NFKC, case-fold, trim, collapse whitespace, exact comparison."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", query).casefold().strip())


class Planner(Protocol):
    def next_action(self, state: str, *, missing: list[str], revisions: int) -> ActionProposal: ...


class RuleBoundedPlanner:
    """Deterministic test planner. Never eligible as a real model planner."""
    def next_action(self, state: str, *, missing: list[str], revisions: int) -> ActionProposal:
        if state == "new":
            return ActionProposal(action="inspect", rationale="Inspect the supplied signal.")
        if state == "inspected":
            return ActionProposal(action="retrieve", rationale="Retrieve allow-listed evidence.", query="incident evidence and applicable governance requirements")
        if state == "retrieved" and missing:
            return ActionProposal(action="request", rationale="Record unavailable evidence.", requested_evidence=missing)
        if state in {"retrieved", "requested"}:
            return ActionProposal(action="synthesize", rationale="Produce an advisory report.")
        if state == "verified" and missing and revisions < MAX_REVISIONS:
            return ActionProposal(action="revise", rationale="Revise once after governance feedback.")
        return ActionProposal(action="escalate", rationale="Terminate safely with human review.")


class OllamaBoundedPlanner:
    """Structured LLM planner; failures are exposed, never silently replaced."""
    def __init__(self, client, model: str, seed: int | None = None):
        self.client, self.model, self.seed = client, model, seed
        self.last_raw_output = ""
        self.last_parse_status = "not_called"
        self.last_error = ""

    @staticmethod
    def _response_schema(state: str) -> dict:
        """Return the smallest state-specific JSON contract for the planner."""
        legal = {
            "new": ["inspect"], "inspected": ["retrieve"],
            "retrieved": ["request", "synthesize"], "requested": ["synthesize"],
            "verified": ["revise", "escalate"],
        }.get(state, [])
        properties = {
            "action": {"type": "string", "enum": legal},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 500},
            "query": {"type": "string", "maxLength": 1000},
            "requested_evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        }
        required = ["action", "rationale"]
        if state == "inspected":
            properties["query"]["minLength"] = 1
            required.append("query")
        if state == "retrieved":
            # It is permitted to synthesize directly after sufficient retrieval;
            # a request proposal must nevertheless name its technical gap.
            properties["requested_evidence"]["description"] = "Required and non-empty when action is request."
        return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}

    def next_action(self, state: str, *, missing: list[str], revisions: int) -> ActionProposal:
        # Repeat the runtime contract in the planner prompt.  The runtime remains
        # authoritative: this text only makes the sole legal next action(s)
        # unambiguous to the model and does not widen the transition table.
        legal_by_state = {
            "new": ["inspect"],
            "inspected": ["retrieve"],
            "retrieved": ["request", "synthesize"],
            "requested": ["synthesize"],
            "verified": ["revise", "escalate"],
        }
        legal = legal_by_state.get(state, [])
        prompt = (
            "You are a bounded advisory evidence-assembly planner. Return exactly one JSON object conforming "
            "to the supplied schema, with no prose or markdown. The deterministic runtime will reject every "
            "action outside the state contract. Global action vocabulary: inspect, retrieve, request, synthesize, "
            "revise, escalate. Never propose approval, release, deployment, execution, or any tool name. "
            f"Current state: {state}. Legal next action(s), and only these: {', '.join(legal) or 'none'}. "
            "State contract: new->inspect; inspected->retrieve; retrieved->request or synthesize; "
            "requested->synthesize; verified->revise or escalate. "
            "For retrieve, `query` MUST be specific and non-empty. For request, `requested_evidence` MUST list "
            "the missing technical evidence. Do not synthesize before retrieval. Do not revise when revisions "
            "are exhausted. State=" + state + "; missing evidence=" + json.dumps(missing) + "; revisions=" + str(revisions)
        )
        try:
            chat_kwargs = dict(model=self.model, messages=[{"role": "user", "content": prompt}],
                                format=self._response_schema(state),
                                options={"temperature": 0.0, "num_predict": 4096, **({"seed": self.seed} if self.seed is not None else {})})
            if not isinstance(self.client, MockOllamaClient):
                # Reasoning-capable model families (e.g. qwen3.5) default to
                # emitting a "thinking" pass before any structured output; without
                # think=False the entire num_predict budget can be consumed by
                # thinking, leaving message.content empty (observed directly:
                # qwen3.5:27b, done_reason="length", content="", 17k+ chars of
                # unused thinking). generate_risk_report already guards this the
                # same way; the planner call needs the identical guard.
                chat_kwargs["think"] = False
            response = self.client.chat(**chat_kwargs)
            self.last_raw_output = response.message.content
            proposal = ActionProposal.model_validate_json(self.last_raw_output)
            if proposal.action.value not in legal:
                # Defense-in-depth: see si_experiments_2026/priority1_agentic_trajectory
                # for the historical failure this guards against (a model re-proposing
                # an out-of-state action despite a schema enum restricted to the legal set).
                self.last_parse_status = "error"
                self.last_error = f"planner_schema_violation: action={proposal.action.value!r} not in legal={legal!r} for state={state!r}"
                return ActionProposal(action="escalate", rationale="Planner proposed an out-of-contract action; safe escalation.")
            self.last_parse_status, self.last_error = "parsed", ""
            return proposal
        except Exception as exc:
            self.last_parse_status, self.last_error = "error", f"{type(exc).__name__}: {exc}"
            # An explicit invalid proposal leads to a runtime-recorded escalation.
            return ActionProposal(action="escalate", rationale="Planner output unavailable; safe escalation.")


@dataclass
class AgentRun:
    case_id: str
    trace: list[TraceEvent]
    final_result: dict | None
    termination_reason: str
    metadata: dict = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)


def run_bounded_agent(case_id: str, narrative: str, *, planner: Planner | None = None,
                      context: dict | None = None, ollama_client=None, model: str | None = None,
                      trace_path: Path | None = None, max_steps: int = MAX_STEPS,
                      model_digest: str = "unrecorded", seed: int | None = None,
                      temperature: float = 0.0,
                      campaign_id: str = "unscoped", run_id: str = "unscoped",
                      dataset_name: str = "unscoped", split: str = "unscoped", run_phase: str = "development",
                      provenance: dict | None = None,
                      clinical_case_id: str | None = None,
                      clinical_facts_path: str | None = None) -> AgentRun:
    """Execute one bounded advisory trace and emit complete JSONL when requested."""
    provenance = provenance or {}
    planner = planner or RuleBoundedPlanner()
    supplied_context = context is not None
    trace_id, report_id = str(uuid4()), case_id
    state, revisions, events, records, result, missing = "new", 0, [], [], None, []
    retrievals = evidence_requests = invalid_proposals = 0
    executed_queries: dict[str, int] = {}
    terminal_reason = "step_budget_exhausted"
    for step in range(1, max_steps + 1):
        started = perf_counter()
        proposal = planner.next_action(state, missing=missing, revisions=revisions)
        raw = getattr(planner, "last_raw_output", "")
        parse_status = getattr(planner, "last_parse_status", "not_model_planner")
        planner_error = getattr(planner, "last_error", "")
        proposed_action = proposal.action
        normalized_query = normalize_retrieval_query(proposal.query) if proposed_action == AgentAction.RETRIEVE else ""
        action, rejected_action_value, rejection_reason = validate_transition(
            state, proposed_action, parse_failed=parse_status == "error"
        )
        rejected_action = AgentAction(rejected_action_value) if rejected_action_value else None
        if action == AgentAction.REVISE and revisions >= MAX_REVISIONS:
            rejected_action, action, rejection_reason = AgentAction.REVISE, AgentAction.ESCALATE, "revision_limit_exhausted"
        duplicate_of_step = executed_queries.get(normalized_query)
        if proposed_action == AgentAction.RETRIEVE and normalized_query and duplicate_of_step is not None:
            rejected_action, action, rejection_reason = AgentAction.RETRIEVE, AgentAction.ESCALATE, "repeated_query"
        if rejected_action:
            invalid_proposals += 1
        before, runtime_reason, output, tool, query_executed, query_reason = state, "accepted bounded action", {}, None, "", ""
        error_type = error_message = ""
        revision_changed_output = None
        if action == AgentAction.INSPECT:
            tool, state, output = "inspect_case", "inspected", {"case_id": case_id, "narrative_sha256": _digest(narrative)}
        elif action == AgentAction.RETRIEVE:
            tool, retrievals = "retrieve_context", retrievals + 1
            # Critical plumbing: a non-empty planner query is precisely the retrieval query.
            query_executed = proposal.query.strip()
            if not query_executed:
                action, state, runtime_reason = AgentAction.ESCALATE, "terminal", "retrieve proposal missing query"
                rejected_action, rejection_reason = AgentAction.RETRIEVE, "empty_retrieval_query"
                invalid_proposals += 1
            else:
                try:
                    # Injected contexts exist only for deterministic unit tests; campaign
                    # runs leave this unset and perform actual query-controlled retrieval.
                    if supplied_context:
                        query_reason, output = "test_context_injected_not_empirical", context
                    else:
                        context = retrieve_context(query_executed, get_embedder())
                        query_reason, output = "planner_query_used_verbatim", context
                    state = "retrieved"
                    executed_queries[normalized_query] = step
                except Exception as exc:
                    state, error_type, error_message = "terminal", type(exc).__name__, str(exc)
                    runtime_reason = "retrieval_tool_error"
        elif action == AgentAction.REQUEST:
            tool, evidence_requests = "request_evidence", evidence_requests + 1
            missing = proposal.requested_evidence or ["Evidence requested by bounded agent."]
            state, output = "requested", {"missing_evidence": missing}
        elif action in {AgentAction.SYNTHESIZE, AgentAction.REVISE}:
            tool = "synthesize_report" if action == AgentAction.SYNTHESIZE else "verify_report"
            previous_result = result if action == AgentAction.REVISE else None
            if action == AgentAction.REVISE:
                revisions += 1
            if action == AgentAction.SYNTHESIZE and not (context or {}).get("artifacts"):
                state, runtime_reason = "terminal", "insufficient_evidence_for_synthesis"
                error_type = "EvidenceMinimumError"
                error_message = "No retrieved artifact is available for report synthesis."
                output = {"missing_evidence": ["At least one retrieved technical artifact is required before synthesis."]}
            else:
                revision_feedback_text = ""
                if previous_result is not None:
                    # Serialize OPA + SHACL findings from the prior attempt so the
                    # revise call is governance-conditioned, not a bare re-generation.
                    revision_feedback_text = build_revision_feedback_block(
                        policy_actions=(previous_result or {}).get("verification", {}).get("policy_actions", []),
                        missing_evidence=(previous_result or {}).get("verified_risk_report", {}).get("missing_evidence", []),
                        shacl_violations=((previous_result or {}).get("clinical_validation") or {}).get("violations", []),
                    )
                try:
                    result = generate_risk_report(narrative, ollama_model=model, ollama_client=ollama_client, context=context,
                                                  temperature=temperature,
                                                  clinical_case_id=clinical_case_id, clinical_facts_path=clinical_facts_path,
                                                  revision_feedback=revision_feedback_text)
                    if result.get("error"):
                        # generate_risk_report returns {"error": ..., "raw_content": ...} on a
                        # schema-validation failure instead of raising; without this check the
                        # missing-evidence lookup below silently defaults to [] on the error
                        # dict (which has no "verified_risk_report" key), so a genuinely failed
                        # generation was previously misclassified as a complete, evidence-full
                        # report ("advisory_complete") instead of the report_tool_error it is.
                        raise RuntimeError(result["error"])
                    missing = result.get("verified_risk_report", {}).get("missing_evidence", [])
                    state, output = "verified", result
                    if previous_result is not None:
                        prev_report = previous_result.get("verified_risk_report", {})
                        new_report = result.get("verified_risk_report", {})
                        revision_changed_output = (
                            prev_report.get("severity") != new_report.get("severity")
                            or prev_report.get("recommendation") != new_report.get("recommendation")
                        )
                except Exception as exc:
                    state, error_type, error_message = "terminal", type(exc).__name__, str(exc)
                    runtime_reason = "report_tool_error"
        else:
            state, runtime_reason, output = "terminal", "human escalation or invalid transition", {"missing_evidence": missing}
        event = TraceEvent(step=step, proposed=proposal, accepted_action=action, runtime_reason=runtime_reason,
            state_before=before, state_after=state, input_sha256=_digest({"state": before, "missing": missing}),
            output_sha256=_digest(output), retrieved_ids=[x["id"] for x in (context or {}).get("artifacts", [])],
            missing_or_contradictory_evidence=missing,
            policy_actions=(result or {}).get("verification", {}).get("policy_actions", []))
        events.append(event)
        record = {
            "record_type": "event", "schema_version": TRACE_SCHEMA_VERSION, "campaign_id": campaign_id,
            "run_id": run_id, "trace_id": trace_id, "event_id": f"{trace_id}:{step}",
            "parent_event_id": f"{trace_id}:{step - 1}" if step > 1 else None, "scenario_id": case_id,
            "report_id": report_id, "dataset_name": dataset_name, "split": split, "run_phase": run_phase,
            "timestamp_utc": _utcnow(), "step_index": step, "state_before": before, "state_after": state,
            "proposed_action": proposed_action.value, "accepted_action": action.value,
            "rejected_action": rejected_action.value if rejected_action else None, "rejection_reason": rejection_reason,
            "action_status": "rejected" if rejected_action else "accepted",
            "rejection": ({"code": rejection_reason, "message": runtime_reason, "duplicate_of_step": duplicate_of_step} if rejected_action else None),
            "state_changed": before != state, "query_normalized": normalized_query, "duplicate_of_step": duplicate_of_step,
            "planner_raw_output": raw, "planner_parse_status": parse_status, "query_proposed": proposal.query,
            "query_executed": query_executed, "query_normalization": query_reason,
            "requested_tool": tool, "executed_tool": tool if not error_type else None,
            "tool_arguments_hash": _digest({"query": query_executed, "narrative": narrative if tool == "synthesize_report" else ""}),
            "tool_result_hash": _digest(output), "retrieved_artifact_ids": event.retrieved_ids,
            "retrieval_scores": [x.get("score") for x in (context or {}).get("artifacts", [])],
            "evidence_gaps_before": [], "evidence_gaps_after": missing, "contradictions_before": [], "contradictions_after": [],
            "draft_report_sha256": _digest(result.get("risk_report", {})) if result else None,
            "opa_input_sha256": _digest((result or {}).get("verification", {})), "opa_actions": event.policy_actions,
            "opa_verdict": (result or {}).get("verification", {}).get("policy_engine"), "shacl_findings": ((result or {}).get("clinical_validation") or {}).get("violations", []),
            "revision_index": revisions, "revision_reason": proposal.rationale if action == AgentAction.REVISE else "",
            "revision_changed_output": revision_changed_output, "termination_reason": None, "final_report_sha256": None,
            "model_name": model or "default", "model_digest": model_digest, "temperature": temperature, "seed": seed,
            "prompt_sha256": provenance.get("prompt_sha256"), "policy_sha256": provenance.get("policy_sha256"),
            "ontology_sha256": provenance.get("ontology_sha256"), "retrieval_snapshot_sha256": provenance.get("retrieval_snapshot_sha256"),
            "dataset_sha256": provenance.get("dataset_sha256"), "code_commit": provenance.get("code_commit"),
            "generation_source": (result or {}).get("generation_source", "none"), "is_mock": (result or {}).get("generation_source") == "mock_fallback",
            "is_fallback": bool(planner_error) or (result or {}).get("generation_source") == "mock_fallback",
            "error_type": error_type, "error_message": error_message, "latency_ms": round((perf_counter() - started) * 1000, 3),
            "input_sha256": event.input_sha256, "output_sha256": event.output_sha256,
        }
        records.append(record)
        if state == "terminal":
            terminal_reason = runtime_reason
            break
        if state == "verified" and not missing:
            state, terminal_reason = "terminal", "advisory_complete"
            break
    final_report = (result or {}).get("verified_risk_report", {})
    terminal = {
        "record_type": "terminal", "schema_version": TRACE_SCHEMA_VERSION, "campaign_id": campaign_id, "run_id": run_id,
        "trace_id": trace_id, "scenario_id": case_id, "report_id": report_id, "timestamp_utc": _utcnow(),
        "state_terminal": state, "termination_reason": terminal_reason, "total_steps": len(events), "revisions": revisions,
        "retrievals": retrievals, "evidence_requests": evidence_requests, "invalid_proposals": invalid_proposals,
        "escalated": terminal_reason != "advisory_complete", "final_report": final_report,
        "final_report_sha256": _digest(final_report) if final_report else None,
        "opa_actions": (result or {}).get("verification", {}).get("policy_actions", []),
        "shacl_findings": ((result or {}).get("clinical_validation") or {}).get("violations", []),
        "severity": final_report.get("severity"), "recommendation": final_report.get("recommendation"),
        "citations": final_report.get("evidence_links", []), "evidence_gaps": missing, "contradiction_status": [],
        "generation_source": (result or {}).get("generation_source", "none"), "is_mock": (result or {}).get("generation_source") == "mock_fallback",
        "is_fallback": bool(getattr(planner, "last_error", "")) or (result or {}).get("generation_source") == "mock_fallback",
    }
    records.append(terminal)
    metadata = {"case_id": case_id, "trace_id": trace_id, "model": model or "default", "model_digest": model_digest,
        "seed": seed, "max_steps": max_steps, "max_revisions": MAX_REVISIONS, "allowed_tools": sorted(ALLOWED_TOOLS),
        "generation_source": (result or {}).get("generation_source", "none"),
        # Campaign consumers need the exact retrieval payload to apply an
        # offline policy or SHACL check to the raw report without issuing a
        # second retrieval.  This is provenance, not a planner capability.
        "retrieval_context": context or {"regulatory": [], "artifacts": []}}
    run = AgentRun(case_id, events, result, terminal_reason, metadata, records)
    if trace_path:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return run
