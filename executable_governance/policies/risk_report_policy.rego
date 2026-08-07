package biodevops.risk_report

import rego.v1

default allow := true
default recommendation_override := ""
# Structural invariant: every risk report is subject to human review by
# default. The specific conditions below are retained for policy_action
# correlation/audit trail, not as the sole source of the requirement.
default requires_human_review := true

deny contains msg if {
  input.has_hallucinated_citations
  msg := "risk_report_contains_unresolved_or_trap_citation"
}

deny contains msg if {
  input.report.severity >= 2
  not input.has_technical_evidence
  msg := "technical_incident_missing_technical_evidence"
}

policy_action contains "severity4_or_death_forced_immediate_human_escalation" if {
  input.report.severity == 4
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

policy_action contains "severity4_or_death_forced_immediate_human_escalation" if {
  input.narrative_flags.death_or_died
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

policy_action contains "high_severity_cannot_remain_no_action_or_monitor" if {
  input.report.severity >= 3
  input.report.recommendation == "NO_ACTION"
}

policy_action contains "high_severity_cannot_remain_no_action_or_monitor" if {
  input.report.severity >= 3
  input.report.recommendation == "MONITOR"
}

policy_action contains "fsca_without_confirmatory_evidence_downgraded" if {
  input.report.recommendation == "FIELD_SAFETY_CORRECTIVE_ACTION"
  not input.has_confirmed_fsca_basis
}

policy_action contains "technical_incident_missing_technical_evidence" if {
  input.report.severity >= 2
  not input.has_technical_evidence
}

recommendation_override := "ESCALATE_TO_HUMAN_IMMEDIATE" if {
  input.report.severity == 4
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

recommendation_override := "ESCALATE_TO_HUMAN_IMMEDIATE" if {
  input.narrative_flags.death_or_died
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

recommendation_override := "CAPA_INVESTIGATE" if {
  not input.narrative_flags.death_or_died
  input.report.severity >= 3
  input.report.severity < 4
  input.report.recommendation == "NO_ACTION"
}

recommendation_override := "CAPA_INVESTIGATE" if {
  not input.narrative_flags.death_or_died
  input.report.severity >= 3
  input.report.severity < 4
  input.report.recommendation == "MONITOR"
}

recommendation_override := "CAPA_INVESTIGATE" if {
  not input.narrative_flags.death_or_died
  input.report.severity < 4
  input.report.recommendation == "FIELD_SAFETY_CORRECTIVE_ACTION"
  not input.has_confirmed_fsca_basis
}

requires_human_review if {
  input.report.severity >= 3
}

requires_human_review if {
  input.report.confidence < 0.65
}

requires_human_review if {
  input.has_hallucinated_citations
}

requires_human_review if {
  count(input.weakly_supported_claims) > 0
}

requires_human_review if {
  count(input.unsupported_claims) > 0
}

requires_human_review if {
  count(policy_action) > 0
}

missing_evidence_addition contains "At least one retrieved technical artifact supporting the incident judgment." if {
  input.report.severity >= 2
  not input.has_technical_evidence
}

missing_evidence_addition contains "Evidence of recurrence or confirmed deployed-population impact." if {
  input.report.recommendation == "FIELD_SAFETY_CORRECTIVE_ACTION"
  not input.has_confirmed_fsca_basis
}

missing_evidence_addition contains "Causal link between the artifact/change and the observed event." if {
  input.report.recommendation == "FIELD_SAFETY_CORRECTIVE_ACTION"
  not input.has_confirmed_fsca_basis
}

decision := {
  "allow": allow,
  "deny": sort([msg | deny[msg]]),
  "policy_actions": sort([action | policy_action[action]]),
  "recommendation_override": recommendation_override,
  "requires_human_review": requires_human_review,
  "missing_evidence_additions": sort([item | missing_evidence_addition[item]]),
}
