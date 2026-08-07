"""Deterministic tests for SHACL-informed in-loop revision (Priority 3).

These tests do not require a running Ollama server: `generate_risk_report`
is monkeypatched at the bounded_agent module boundary with a scripted
sequence of return dicts, exactly like the existing SequencePlanner-based
tests in tests/test_planner_contract.py in the main repo. This isolates the
new wiring (clinical_case_id/clinical_facts_path threading, revision
feedback construction, revision_changed_output bookkeeping) from any need
for a real model or vector store.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bounded_agent
from agent_trace_schema import ActionProposal, AgentAction
from bounded_agent import build_revision_feedback_block, run_bounded_agent


class SequencePlanner:
    def __init__(self, actions):
        self.actions = iter(actions)

    def next_action(self, state, **kwargs):
        action = next(self.actions)
        return ActionProposal(action=action, rationale="fixture", query="specific technical query")


class BuildRevisionFeedbackBlockTests(unittest.TestCase):
    def test_empty_inputs_produce_empty_block(self):
        self.assertEqual(build_revision_feedback_block([], [], []), "")

    def test_shacl_violation_is_serialized_with_shape_and_message(self):
        text = build_revision_feedback_block(
            policy_actions=[],
            missing_evidence=[],
            shacl_violations=[{"shape": "concept_severity_undercall", "message": "Severity below SNOMED-derived floor."}],
        )
        self.assertIn("concept_severity_undercall", text)
        self.assertIn("Severity below SNOMED-derived floor.", text)

    def test_opa_and_shacl_findings_are_both_present(self):
        text = build_revision_feedback_block(
            policy_actions=["high_severity_cannot_remain_no_action_or_monitor"],
            missing_evidence=["Clinical SHACL nonconformance requires human review."],
            shacl_violations=[{"shape": "concept_severity_undercall", "message": "floor breach"}],
        )
        self.assertIn("high_severity_cannot_remain_no_action_or_monitor", text)
        self.assertIn("Clinical SHACL nonconformance requires human review.", text)
        self.assertIn("floor breach", text)


class InLoopRevisionWiringTests(unittest.TestCase):
    """Exercises run_bounded_agent's revise path with a scripted generate_risk_report."""

    def _first_pass_result(self):
        # Simulates a report that is OPA-clean (no policy_actions) but SHACL
        # nonconformant: the model under-called severity relative to the
        # curated SNOMED-derived floor, which only the clinical guard sees.
        return {
            "risk_report": {"severity": 1, "recommendation": "NO_ACTION"},
            "verified_risk_report": {
                "severity": 1,
                "recommendation": "NO_ACTION",
                "missing_evidence": ["Clinical SHACL nonconformance requires human review."],
            },
            "verification": {"policy_actions": [], "policy_engine": "opa"},
            "clinical_validation": {
                "conforms": False,
                "clinical_inconsistency_class": "concept_severity_undercall",
                "violations": [{"shape": "concept_severity_undercall", "message": "Severity below SNOMED-derived floor for confirmed life-threatening event."}],
            },
            "generation_source": "ollama_real",
        }

    def _second_pass_result(self):
        # The revised report: severity corrected upward, now SHACL-conformant.
        return {
            "risk_report": {"severity": 4, "recommendation": "ESCALATE_TO_HUMAN_IMMEDIATE"},
            "verified_risk_report": {
                "severity": 4,
                "recommendation": "ESCALATE_TO_HUMAN_IMMEDIATE",
                "missing_evidence": [],
            },
            "verification": {"policy_actions": [], "policy_engine": "opa"},
            "clinical_validation": {"conforms": True, "clinical_inconsistency_class": "none", "violations": []},
            "generation_source": "ollama_real",
        }

    def test_clinical_case_id_and_facts_path_are_threaded_to_generate_risk_report(self):
        calls = []

        def fake_generate(*args, **kwargs):
            calls.append(kwargs)
            return self._first_pass_result()

        with patch.object(bounded_agent, "generate_risk_report", side_effect=fake_generate):
            run_bounded_agent(
                "case-1", "technical fixture",
                planner=SequencePlanner([AgentAction.INSPECT, AgentAction.RETRIEVE, AgentAction.SYNTHESIZE, AgentAction.ESCALATE]),
                context={"regulatory": [], "artifacts": [{"id": "TECH-1", "text": "fixture", "metadata": {"artifact_type": "test_log"}}]},
                clinical_case_id="SYN-IND-0031", clinical_facts_path="ontology/clinical_concepts_independent_40.json",
            )
        self.assertEqual(calls[0]["clinical_case_id"], "SYN-IND-0031")
        self.assertEqual(calls[0]["clinical_facts_path"], "ontology/clinical_concepts_independent_40.json")

    def test_shacl_nonconformance_alone_triggers_a_revise_proposal_opportunity(self):
        # missing_evidence populated by the (simulated) SHACL guard is exactly
        # what the rule-based/model planner reads to decide whether to revise;
        # confirm it reaches the planner-visible `missing` state correctly.
        with patch.object(bounded_agent, "generate_risk_report", return_value=self._first_pass_result()):
            run = run_bounded_agent(
                "case-2", "technical fixture",
                planner=SequencePlanner([AgentAction.INSPECT, AgentAction.RETRIEVE, AgentAction.SYNTHESIZE, AgentAction.ESCALATE]),
                context={"regulatory": [], "artifacts": [{"id": "TECH-1", "text": "fixture", "metadata": {"artifact_type": "test_log"}}]},
                clinical_case_id="SYN-IND-0031", clinical_facts_path="ontology/clinical_concepts_independent_40.json",
            )
        self.assertIn("Clinical SHACL nonconformance requires human review.", run.records[-1]["evidence_gaps"])

    def test_revise_receives_shacl_feedback_and_records_changed_output(self):
        results = iter([self._first_pass_result(), self._second_pass_result()])
        received_feedback = []

        def fake_generate(*args, **kwargs):
            received_feedback.append(kwargs.get("revision_feedback", ""))
            return next(results)

        with patch.object(bounded_agent, "generate_risk_report", side_effect=fake_generate):
            run = run_bounded_agent(
                "case-3", "technical fixture",
                planner=SequencePlanner([AgentAction.INSPECT, AgentAction.RETRIEVE, AgentAction.SYNTHESIZE, AgentAction.REVISE, AgentAction.ESCALATE]),
                context={"regulatory": [], "artifacts": [{"id": "TECH-1", "text": "fixture", "metadata": {"artifact_type": "test_log"}}]},
                clinical_case_id="SYN-IND-0031", clinical_facts_path="ontology/clinical_concepts_independent_40.json",
            )
        # First call (synthesize): no feedback yet.
        self.assertEqual(received_feedback[0], "")
        # Second call (revise): feedback must reference the SHACL violation
        # from the first pass, not just OPA's (empty here) policy_actions.
        self.assertIn("Severity below SNOMED-derived floor", received_feedback[1])
        # The revise record must show the output actually changed.
        revise_record = run.records[3]
        self.assertEqual(revise_record["accepted_action"], "revise")
        self.assertTrue(revise_record["revision_changed_output"])


if __name__ == "__main__":
    unittest.main()
