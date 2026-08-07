# This extension introduces a second clinical domain solely to demonstrate architectural transferability. It does not modify or replace the published arrhythmia benchmark, and no new scientific performance claims are introduced.

package biodevops.cgm_risk_report

import rego.v1

default allow := true
default recommendation_override := ""
# Structural invariant: every risk report is subject to human review by
# default. The specific conditions below are retained for policy_action
# correlation/audit trail, not as the sole source of the requirement.
default requires_human_review := true

deny contains msg if {
  input.has_hallucinated_citations
  msg := "cgm_risk_report_contains_unresolved_or_trap_citation"
}

deny contains msg if {
  input.report.recommendation == "FIELD_SAFETY_CORRECTIVE_ACTION"
  not input.has_population_or_recurrence_evidence
  msg := "unsupported_field_safety_action"
}

deny contains msg if {
  input.report.recommendation == "NO_ACTION"
  input.cgm_flags.sensor_failure
  msg := "sensor_failure_cannot_be_no_action"
}

deny contains msg if {
  input.report.recommendation == "NO_ACTION"
  not input.cgm_flags.has_glucose_evidence
  msg := "missing_glucose_evidence_for_no_action"
}

policy_action contains "severe_hypoglycemia_forced_immediate_human_escalation" if {
  input.cgm_flags.severe_hypoglycemia_confirmed
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

policy_action contains "loss_of_consciousness_forced_immediate_human_escalation" if {
  input.cgm_flags.loss_of_consciousness_confirmed
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

policy_action contains "high_risk_event_requires_escalation_or_capa" if {
  input.report.severity >= 3
  input.report.recommendation == "NO_ACTION"
}

policy_action contains "high_risk_event_requires_escalation_or_capa" if {
  input.report.severity >= 3
  input.report.recommendation == "MONITOR"
}

policy_action contains "missing_glucose_evidence_forces_review" if {
  not input.cgm_flags.has_glucose_evidence
}

policy_action contains "conflicting_observations_force_review" if {
  input.cgm_flags.conflicting_observations
}

policy_action contains "human_approval_required_for_retraining_release" if {
  input.cgm_flags.post_market_retraining
  not input.has_human_approval
}

recommendation_override := "ESCALATE_TO_HUMAN_IMMEDIATE" if {
  input.cgm_flags.severe_hypoglycemia_confirmed
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

recommendation_override := "ESCALATE_TO_HUMAN_IMMEDIATE" if {
  input.cgm_flags.loss_of_consciousness_confirmed
  input.report.recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE"
}

recommendation_override := "CAPA_INVESTIGATE" if {
  not input.cgm_flags.severe_hypoglycemia_confirmed
  not input.cgm_flags.loss_of_consciousness_confirmed
  input.report.severity >= 3
  input.report.recommendation == "NO_ACTION"
}

recommendation_override := "CAPA_INVESTIGATE" if {
  not input.cgm_flags.severe_hypoglycemia_confirmed
  not input.cgm_flags.loss_of_consciousness_confirmed
  input.report.severity >= 3
  input.report.recommendation == "MONITOR"
}

requires_human_review if {
  input.report.severity >= 3
}

requires_human_review if {
  input.report.confidence < 0.65
}

requires_human_review if {
  input.cgm_flags.severe_hypoglycemia
}

requires_human_review if {
  input.cgm_flags.loss_of_consciousness
}

requires_human_review if {
  input.cgm_flags.sensor_failure
}

requires_human_review if {
  input.cgm_flags.conflicting_observations
}

requires_human_review if {
  not input.cgm_flags.has_glucose_evidence
}

requires_human_review if {
  input.has_hallucinated_citations
}

requires_human_review if {
  count(input.unsupported_claims) > 0
}

requires_human_review if {
  count(input.weakly_supported_claims) > 0
}

requires_human_review if {
  count(policy_action) > 0
}

missing_evidence_addition contains "Documented glucose evidence from CGM, laboratory, or confirmatory meter record." if {
  not input.cgm_flags.has_glucose_evidence
}

missing_evidence_addition contains "Resolution of conflicting glucose observations before clinical normalization." if {
  input.cgm_flags.conflicting_observations
}

missing_evidence_addition contains "Authorized human approval for post-market retraining release." if {
  input.cgm_flags.post_market_retraining
  not input.has_human_approval
}

missing_evidence_addition contains "Evidence of recurrence, deployed-population impact, or causality before field safety corrective action." if {
  input.report.recommendation == "FIELD_SAFETY_CORRECTIVE_ACTION"
  not input.has_population_or_recurrence_evidence
}

decision := {
  "allow": allow,
  "deny": sort([msg | deny[msg]]),
  "policy_actions": sort([action | policy_action[action]]),
  "recommendation_override": recommendation_override,
  "requires_human_review": requires_human_review,
  "missing_evidence_additions": sort([item | missing_evidence_addition[item]]),
}
