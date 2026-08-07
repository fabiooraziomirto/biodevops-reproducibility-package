"""Non-clinical planner-protocol fixtures and failure-recovery tests."""
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from agent_trace_schema import ActionProposal, AgentAction
from bounded_agent import MAX_REVISIONS, OllamaBoundedPlanner, run_bounded_agent
from rag_pipeline import MockOllamaClient


class ResponseClient:
    def __init__(self, response): self.response = response
    def chat(self, **kwargs):
        class Message: pass
        class Result: pass
        response = Result(); response.message = Message(); response.message.content = self.response
        return response


class SequencePlanner:
    def __init__(self, actions): self.actions = iter(actions)
    def next_action(self, state, **kwargs):
        action = next(self.actions)
        return ActionProposal(action=action, rationale="technical fixture", query="specific technical query",
                              requested_evidence=["fixture evidence"])


class PlannerContractTests(unittest.TestCase):
    def test_invalid_json_is_explicitly_recorded_and_safely_terminated(self):
        planner = OllamaBoundedPlanner(ResponseClient("not json"), "fixture-model")
        run = run_bounded_agent("bad-json", "technical fixture", planner=planner,
                                context={"regulatory": [], "artifacts": []})
        self.assertEqual(run.records[0]["planner_parse_status"], "error")
        self.assertEqual(run.records[0]["rejection_reason"], "planner_parse_error")
        self.assertTrue(run.records[-1]["termination_reason"])

    def test_unknown_and_privileged_actions_fail_schema_recovery(self):
        for action in ("unknown_action", "approve", "deploy"):
            with self.subTest(action=action):
                planner = OllamaBoundedPlanner(ResponseClient(json.dumps({"action": action, "rationale": "fixture"})), "fixture-model")
                run = run_bounded_agent("forbidden", "technical fixture", planner=planner,
                                        context={"regulatory": [], "artifacts": []})
                self.assertEqual(run.records[0]["planner_parse_status"], "error")
                self.assertEqual(run.records[-1]["termination_reason"], "human escalation or invalid transition")

    def test_synthesis_without_an_artifact_terminates_without_report(self):
        planner = SequencePlanner([AgentAction.INSPECT, AgentAction.RETRIEVE, AgentAction.SYNTHESIZE])
        run = run_bounded_agent("no-evidence", "technical fixture", planner=planner,
                                context={"regulatory": [], "artifacts": []})
        self.assertEqual(run.termination_reason, "insufficient_evidence_for_synthesis")
        self.assertIsNone(run.final_result)

    def test_revision_limit_is_runtime_enforced(self):
        actions = [AgentAction.INSPECT, AgentAction.RETRIEVE, AgentAction.SYNTHESIZE,
                   AgentAction.REVISE, AgentAction.REVISE]
        run = run_bounded_agent("revision-limit", "technical fixture", planner=SequencePlanner(actions),
                                context={"regulatory": [], "artifacts": [{"id": "TECH-1", "text": "fixture", "metadata": {"artifact_type": "test_log"}}]},
                                ollama_client=MockOllamaClient())
        self.assertLessEqual(run.records[-1]["revisions"], MAX_REVISIONS)
        self.assertEqual(run.records[-2]["rejection_reason"], "revision_limit_exhausted")

    def test_termination_stops_any_later_retrieval(self):
        run = run_bounded_agent("terminated", "technical fixture", planner=SequencePlanner([AgentAction.ESCALATE, AgentAction.RETRIEVE]),
                                context={"regulatory": [], "artifacts": []})
        self.assertEqual(len(run.trace), 1)
        self.assertEqual(run.records[-1]["termination_reason"], "human escalation or invalid transition")

    def test_globally_legal_but_state_illegal_action_is_rejected_by_the_planner_layer(self):
        # Reproduces the historical qwen2.5:7b failure mode: a model that keeps
        # proposing "inspect" (globally a legal AgentAction) even after the
        # runtime has moved past the "new" state, where only "retrieve" is
        # legal. Before the fix, ActionProposal.model_validate_json only
        # checked "inspect" against the global vocabulary and returned it
        # unchanged; only the downstream runtime transition table caught the
        # mismatch. This test locks in the planner-side re-check added to
        # OllamaBoundedPlanner.next_action.
        client = ResponseClient(json.dumps({"action": "inspect", "rationale": "keep inspecting"}))
        planner = OllamaBoundedPlanner(client, "fixture-model")
        run = run_bounded_agent("repeat-inspect", "technical fixture", planner=planner,
                                context={"regulatory": [], "artifacts": []})
        # Step 1: state="new", legal=["inspect"] -> accepted, state becomes "inspected".
        self.assertEqual(run.records[0]["accepted_action"], "inspect")
        self.assertEqual(run.records[0]["state_after"], "inspected")
        # Step 2: state="inspected", legal=["retrieve"], but the planner proposes
        # "inspect" again. The planner layer itself must now flag this as a
        # schema violation (not merely rely on the runtime transition table).
        self.assertEqual(run.records[1]["planner_parse_status"], "error")
        self.assertIn("planner_schema_violation", planner.last_error)
        self.assertEqual(run.records[1]["rejection_reason"], "planner_parse_error")
        self.assertTrue(run.records[-1]["termination_reason"])
