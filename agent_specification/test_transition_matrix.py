"""Contract tests for the deterministic bounded-agent transition boundary.

These are protocol/engineering fixtures.  They do not assert clinical facts.
"""
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from agent_trace_schema import ActionProposal, AgentAction
from bounded_agent import LEGAL_TRANSITIONS, run_bounded_agent, validate_transition
from rag_pipeline import MockOllamaClient


LEGAL = {
    "new": {"inspect"},
    "inspected": {"retrieve"},
    "retrieved": {"request", "synthesize"},
    "requested": {"synthesize"},
    "verified": {"revise", "escalate"},
}


class FixedPlanner:
    def __init__(self, action):
        self.action = action

    def next_action(self, state, **kwargs):
        return ActionProposal(action=self.action, rationale="technical contract fixture", query="fixture query")


class TransitionMatrixTests(unittest.TestCase):
    def test_every_state_action_pair_has_an_explicit_outcome(self):
        for state, legal_actions in LEGAL_TRANSITIONS.items():
            for action in AgentAction:
                with self.subTest(state=state, action=action.value):
                    accepted, rejected, reason = validate_transition(state, action)
                    if action in legal_actions:
                        self.assertEqual(accepted, action)
                        self.assertIsNone(rejected)
                        self.assertEqual(reason, "")
                    else:
                        self.assertEqual(accepted, AgentAction.ESCALATE)
                        self.assertEqual(rejected, action.value)
                        self.assertEqual(reason, "illegal_state_transition")

    def test_first_state_accepts_only_inspect_and_rejects_every_other_action(self):
        # ``new`` is a public runtime entry state; all action proposals are
        # exercised here. Later states are covered by deterministic paths below.
        for action in AgentAction:
            with self.subTest(action=action.value):
                run = run_bounded_agent("matrix", "technical fixture", planner=FixedPlanner(action),
                                        context={"regulatory": [], "artifacts": []})
                event, terminal = run.records[0], run.records[-1]
                if action.value in LEGAL["new"]:
                    self.assertEqual(event["accepted_action"], action.value)
                else:
                    self.assertEqual(event["accepted_action"], "escalate")
                    self.assertEqual(event["rejected_action"], action.value)
                    self.assertEqual(event["state_before"], "new")
                self.assertEqual(terminal["record_type"], "terminal")
                self.assertTrue(terminal["termination_reason"])

    def test_deterministic_legal_path_preserves_state_progression(self):
        class PathPlanner:
            sequence = iter([AgentAction.INSPECT, AgentAction.RETRIEVE, AgentAction.REQUEST,
                             AgentAction.SYNTHESIZE, AgentAction.ESCALATE])
            def next_action(self, state, **kwargs):
                action = next(self.sequence)
                return ActionProposal(action=action, rationale="technical path", query="fixture query",
                                      requested_evidence=["technical fixture missing"])
        run = run_bounded_agent("matrix-path", "technical fixture", planner=PathPlanner(),
                                context={"regulatory": [], "artifacts": [{"id": "TECH-1", "text": "fixture", "metadata": {"artifact_type": "test_log"}}]},
                                ollama_client=MockOllamaClient())
        events = run.records[:-1]
        for event in events:
            self.assertIn(event["accepted_action"], LEGAL.get(event["state_before"], set()))
            self.assertIsNone(event["rejected_action"])
        self.assertEqual(run.records[-1]["termination_reason"], "human escalation or invalid transition")
