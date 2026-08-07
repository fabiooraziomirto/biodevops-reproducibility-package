# Directional/ordinal asymmetry audit (Phase A, point 4)

Every OPA rule and SHACL shape in `risk_report_policy.rego`, `biodevops_clinical.ttl`,
`cgm_policy.rego`, and `biodevops_cgm.ttl` that operates over an ordinal or directional quantity
(severity, escalation level, recommendation "strength"), checked for whether it is symmetric
(catches both directions of error) or one-sided.

| Check | Direction it catches | Direction it is blind to | Verdict |
|---|---|---|---|
| SHACL `concept_severity_undercall` | predicted severity **below** derived floor | predicted severity **above** floor (over-call) | **One-sided by construction.** `FILTER (?pred < ?floor)` — mathematically cannot fire on an over-call. This is the asymmetry already identified in the earlier qwen3.5:27b/gemma3:27b analysis; 9 of qwen3.5:27b's 10 in-scope severity misses in the new sweep are over-calls this shape structurally cannot see. |
| OPA/SHACL `severity4_or_death_forced_immediate_human_escalation` / `severity4_opa_overlap` | severity==4 **not** paired with `ESCALATE_TO_HUMAN_IMMEDIATE` (under-escalation at the ceiling) | severity<4 paired with `ESCALATE_TO_HUMAN_IMMEDIATE` (over-escalation) is never flagged anywhere | One-sided. Consistent with a safety-first design: an unescalated severity-4 case is dangerous; an over-escalated low-severity case is merely inefficient. |
| OPA `high_severity_cannot_remain_no_action_or_monitor` / SHACL `recommendation_vs_documented_outcome` | severity≥3 (or documented harm/life-threatening outcome) paired with `NO_ACTION`/`MONITOR` (under-triage) | mild case paired with `ESCALATE_TO_HUMAN_IMMEDIATE`/`CAPA_INVESTIGATE` (over-triage) is never flagged | One-sided, same safety-first rationale. |
| OPA/CGM `severe_hypoglycemia_forced_immediate_human_escalation`, `loss_of_consciousness_forced_immediate_human_escalation`, SHACL `documented_severe_hypoglycemia_cannot_produce_no_action` | confirmed severe hypoglycemia / LOC not escalated | over-escalation of a mild glucose event never flagged | Same pattern, CGM domain. |
| OPA `fsca_without_confirmatory_evidence_downgraded` / CGM `unsupported_field_safety_action` | recommendation **is** `FIELD_SAFETY_CORRECTIVE_ACTION` **without** confirmed population/recurrence evidence (over-claiming the single most disruptive/costly action) | an under-claimed FSCA (i.e. a case that plausibly warranted FSCA but got a lesser recommendation) is not separately flagged by this rule — though it would still trip the severity/recommendation under-triage rules above if severity≥3 | **Opposite-direction one-sidedness, and it looks intentional, not an oversight.** Every other ordinal check in the system is under-triage-only (biased toward flagging insufficient escalation); this is the one check biased toward flagging *excessive* escalation. It targets specifically the one recommendation whose false-positive cost (an unwarranted field corrective action / recall) is asymmetric in the other direction from a missed escalation. |
| SHACL `hasEvidenceId`, `reportConcept`, `fhirSystem`, `fhirCode` | presence/absence and categorical membership, not ordinal | n/a | Not applicable to directional analysis. |

## Conclusion

The system encodes exactly one class of ordinal check in each direction:
- **Under-triage / under-escalation checks are the norm** (concept_severity_undercall, both
  severity4 rules, both high-severity/documented-outcome rules, both CGM confirmed-event rules) —
  consistent, deliberate, and matches the stated safety rationale (missed escalation is the
  dangerous failure mode).
- **Exactly one check (FSCA-without-evidence, in both domains) runs the other direction**,
  guarding against over-claiming the costliest, most disruptive recommendation.

No undisclosed or accidental one-sided check was found beyond the already-known
`concept_severity_undercall` case; the pattern generalizes cleanly to a "guard direction follows
the cost asymmetry of the specific recommendation" design, not an inconsistency. This should be
stated explicitly in the paper (Table tab:guards note) rather than left implicit, since a reader
auditing only `concept_severity_undercall` in isolation could otherwise mistake the one-sidedness
for an oversight rather than a general, principled pattern.
