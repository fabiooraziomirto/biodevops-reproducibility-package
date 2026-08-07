# Bounded evidence-assembly agent specification

The agent is advisory, not an execution or authorization agent. The model may propose `inspect`, `retrieve`, `request`, `synthesize`, `revise`, or `escalate`. The runtime accepts only legal transitions, permits at most six steps and one revision, records every proposal/outcome, and terminates through human escalation on invalid transitions or unresolved evidence.

Allowed tools are `inspect_case`, `retrieve_context`, `request_evidence`, `synthesize_report`, and `verify_report`. There is no deploy, execute, approval, or release tool, and `RiskReport` rejects extra authority-bearing fields.

The model-selected portion is the advisory action proposal and, for retrieval, the proposed query/evidence request. State transitions, tool execution, budget, OPA/SHACL checks, and termination are deterministic runtime controls. Trace files contain hashes, source IDs, governance actions, missing evidence and generation source. A mock source is valid only for plumbing tests, never metrics.
