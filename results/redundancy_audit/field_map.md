# OPA/SHACL rule-to-field map (Phase A, si_scaling_sweep_2026)

Source files inspected (live code paths, not just stored booleans):
`biodevops_rag/policies/risk_report_policy.rego`, `biodevops_rag/policies/cgm_policy.rego`,
`biodevops_rag/ontology/biodevops_clinical.ttl`, `biodevops_rag/ontology/biodevops_cgm.ttl`,
`biodevops_rag/scripts/opa_policy.py`, `biodevops_rag/scripts/rag_pipeline.py`
(`run_clinical_guard`, the function actually invoked in-generation for every sweep row —
not the standalone `ontology_validate.py --all` CLI path, which reads different, weaker
source fields; see "Divergent post-hoc validator" note below).

## RiskReport domain (arrhythmia, the domain of the paper's Table tab:independent-scenario-level
and the new 9-model matched_strict sweep)

| Check (engine) | Underlying field(s) read | Shares a field with |
|---|---|---|
| `deny: technical_incident_missing_technical_evidence` (OPA) | `report.severity>=2`, `has_technical_evidence` (derived from `report.evidence_links`, filtered by `TECHNICAL_ARTIFACT_TYPES`) | SHACL `hasEvidenceId` shape (both ultimately gate on `report.evidence_links` emptiness in the live pipeline — see below) |
| `policy_action: technical_incident_missing_technical_evidence` (OPA) | identical condition to the `deny` rule above | Same as above. **Also duplicates the `deny` rule internally** — both fire on the same condition and both land in the stored `policy_actions` string (`deny:technical_incident_missing_technical_evidence` and `technical_incident_missing_technical_evidence`), i.e. OPA double-counts its own signal before SHACL is even considered. |
| SHACL `hasEvidenceId` (minCount 1) | In the live in-generation guard (`rag_pipeline.run_clinical_guard`), the graph's evidence facts are built from `[link.artifact_id for link in report.evidence_links]` — i.e. **the model's own citations, the same field OPA reads.** (The standalone `ontology_validate.py --all` CLI instead reads `retrieved_artifacts`/`expected_artifacts` columns — RAG retrieval + ground truth — a different, near-always-populated field; see divergence note.) | **Confirmed structural overlap** with both `technical_incident_missing_technical_evidence` OPA rules. Note the trigger conditions differ even though the field is shared: OPA gates on `severity>=2`, SHACL's minCount check is severity-blind (fires regardless of severity). So the field is shared but the two checks are not perfectly redundant in coverage — SHACL alone catches severity<2 cases with empty evidence_links that OPA's rule structurally cannot. |
| `policy_action`/`recommendation_override: severity4_or_death_forced_immediate_human_escalation` (OPA) | `report.severity==4`, `report.recommendation` | SHACL `severity4_opa_overlap` sparql shape |
| SHACL `severity4_opa_overlap` (sparql) | `bdv:predictedSeverity==4`, `bdv:recommendation` | **Confirmed structural overlap.** The shape's own `sh:message` text already names this ("this overlaps OPA policy behavior") — it was already self-documented in the ontology, just never surfaced in the paper's overlap accounting. |
| `deny: high_severity_cannot_remain_no_action_or_monitor` / `policy_action` (OPA) | `report.severity>=3`, `report.recommendation in {NO_ACTION, MONITOR}` | Partially overlaps SHACL `recommendation_vs_documented_outcome` (see below) |
| SHACL `recommendation_vs_documented_outcome` (sparql) | `bdv:recommendation`, `bdv:harmOutcome` (ground-truth fact, not model output), `bdv:clinicalEventOccurred` (ground truth), `bdv:reportConcept`→`lethalityClass` (ground truth) | **Genuine, not structural**: this shape fires off documented ground-truth harm outcome, independent of what severity the model predicted. A model can have `severity<3` (so OPA's rule above never fires) while the ground-truth harm outcome shape still fires, and vice versa. Different source of truth (ground truth vs model's own severity claim), so co-occurrence here is a real second signal, not the same field re-read. |
| SHACL `concept_severity_undercall` (sparql) | `bdv:predictedSeverity`, `bdv:derivedSeverityFloor` (ground-truth-derived) | **No OPA equivalent at all.** OPA has no rule that reads any ground-truth/derived-floor field — it only ever compares the report to itself (citations, its own severity, its own recommendation). This is SHACL's only true independent-of-OPA detection surface in the RiskReport domain, and it is one-sided (see asymmetry note below). |
| SHACL `reportConcept` / `fhirSystem` / `fhirCode` structural shapes | `bdv:reportConcept`, `bdv:fhirSystem`, `bdv:fhirCode` | No OPA equivalent — OPA never inspects FHIR coding fields. Independent. |
| `requires_human_review` (OPA) | severity, confidence, hallucinated citations, weak/unsupported claims, `count(policy_action)>0` | Not a "catch" bucketed against SHACL in the union-yield metric; it's the always-on review gate, separate from the yield accounting. |

## CGM domain (`cgm_policy.rego` / `biodevops_cgm.ttl` — additive, demonstration-only extension;
not used in the arrhythmia scaling sweep, but in scope for "every active rule/shape" and directly
relevant to the Phase B CGM stress test)

| Check (engine) | Field(s) | Shares with |
|---|---|---|
| OPA `deny: sensor_failure_cannot_be_no_action` | `cgm_flags.sensor_failure`, `recommendation==NO_ACTION` | SHACL `sensor_failure_cannot_be_clinically_normal` — **identical condition encoded twice** (both read `hasSensorFailure`/`cgm_flags.sensor_failure`, same narrative-regex-derived flag, same NO_ACTION gate). This is a literal duplicate rule, not just a shared field. |
| OPA `deny: missing_glucose_evidence_for_no_action` | `cgm_flags.has_glucose_evidence`, `recommendation==NO_ACTION` | SHACL `missing_glucose_evidence_triggers_review` — same structural duplicate as above. |
| OPA `policy_action: conflicting_observations_force_review` | `cgm_flags.conflicting_observations` | SHACL `conflicting_observations_require_review` — shares the source flag, but SHACL additionally gates on `recommendation in {NO_ACTION, MONITOR}` where OPA's policy_action does not gate on recommendation at all, so coverage is not identical (SHACL narrower, OPA broader). Partial structural overlap. |
| OPA `severe_hypoglycemia_forced_immediate_human_escalation` / `loss_of_consciousness_forced_immediate_human_escalation` | `cgm_flags.severe_hypoglycemia_confirmed` / `..._confirmed` (regex-trigger assertion-status classifier over narrative + rationale text, in `opa_policy.py::_cgm_flags`) | SHACL `documented_severe_hypoglycemia_cannot_produce_no_action` reads `reportConcept` (SevereHypoglycemia/LossOfConsciousness), which in the only implemented CGM post-hoc validator (`domain_transferability.py::cgm_concept`) is derived from the **ground-truth case JSON + rationale text**, not the live narrative-regex flags OPA uses. These are two different derivations of a conceptually similar signal — **likely structural in spirit (same clinical fact) but not literally the same field/function**, so classify as "related but not proven identical field" rather than confirmed structural. Flagged for the Phase B CGM run to check empirically. |
| SHACL `hasEvidenceId` (CGM) | In `domain_transferability.py::validate_cgm_case`, sourced from the row's `retrieved_artifacts` column (RAG retrieval), **not** the model's own evidence_links | No confirmed OPA equivalent in the CGM domain (CGM policy has no direct evidence-citation deny rule mirroring the RiskReport one) — likely independent, but see divergent-validator note: this is the same weaker/near-vacuous "retrieved_artifacts" pattern as the standalone arrhythmia CLI validator, not the live-pipeline evidence_links pattern. |

## Divergent post-hoc validator (methodological finding, not a paper contradiction — nothing in
main_revised.tex currently cites these numbers)

There are **two non-equivalent implementations** of "does this report have linked evidence" in
the repo:

1. **Live in-generation guard** (`rag_pipeline.run_clinical_guard`, used for every row in both
   the qwen2.5 published sweep and the new 9-model sweep): evidence facts = the model's own
   `report.evidence_links`. This is the one that actually produced every `clinical_guard_conforms`
   value used in the paper and in this audit.
2. **Standalone CLI re-validator** (`ontology_validate.py --all`, and its CGM analogue in
   `domain_transferability.py`): evidence facts = `retrieved_artifacts`/`expected_artifacts`
   columns, i.e. RAG retrieval hits and ground truth — fields that are populated by the
   retrieval pipeline regardless of what the model actually cited, so the evidence shape is
   close to vacuous under this path. Spot-checked
   `evaluation_outputs/ontology_validation/per_file/..._qwen2.5_3b.json`: it reports
   `ontology_nonconformant=40/40`, `opa_only=0`, `ontology_only_catch=0` for a file where the
   in-generation guard (used for the actual paper numbers) shows a very different picture —
   consistent with this CLI path over-flagging almost every row for reasons unrelated to the
   model's real citation behavior.

**Recommendation**: do not cite `ontology_validate.py --all`'s aggregate `summary.json` for any
paper claim; nothing currently does. If it is ever used for a headline number, it must first be
patched to source evidence facts from `report.evidence_links` (or the stored
`evidence_link_artifact_ids_raw`/`_normalized` columns), matching the live guard.
