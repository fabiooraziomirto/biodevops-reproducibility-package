import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from agent_trace_schema import ActionProposal, AgentAction
from bounded_agent import MAX_REVISIONS, RuleBoundedPlanner, run_bounded_agent
from rag_pipeline import MockOllamaClient


class InvalidPlanner:
    def next_action(self, state, **kwargs):
        return ActionProposal(action=AgentAction.RETRIEVE, rationale="Invalid at start")


class BoundedAgentTests(unittest.TestCase):
    def test_invalid_transition_escalates_without_privileged_action(self):
        run = run_bounded_agent("case-1", "incident", planner=InvalidPlanner(), context={"regulatory": [], "artifacts": []})
        self.assertEqual(run.trace[0].accepted_action, AgentAction.ESCALATE)
        self.assertIsNone(run.final_result)

    def test_trace_is_jsonl_and_records_mock_source(self):
        context = {"regulatory": [], "artifacts": [{"id": "TECH-1", "text": "fixture", "metadata": {"artifact_type": "test_log"}}]}
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            run = run_bounded_agent("case-2", "incident", planner=RuleBoundedPlanner(), context=context,
                                    ollama_client=MockOllamaClient(), trace_path=trace)
            self.assertTrue(trace.exists())
            self.assertEqual(run.metadata["generation_source"], "mock_fallback")
            self.assertLessEqual(sum(e.accepted_action == AgentAction.REVISE for e in run.trace), MAX_REVISIONS)
