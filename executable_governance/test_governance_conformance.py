import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from opa_policy import build_opa_input, evaluate_opa_policy  # noqa: E402
from pydantic import ValidationError

from risk_report_schema import RecommendationEnum, RiskReport  # noqa: E402


class GovernanceConformanceTests(unittest.TestCase):
    def test_agent_output_has_no_release_authority(self):
        report = RiskReport(severity=2, confidence=0.5, recommendation=RecommendationEnum.MONITOR, rationale="Advisory only.")
        payload = report.model_dump()
        self.assertFalse({"can_deploy", "can_execute", "release_authorized"} & set(payload))
        with self.assertRaises(ValidationError):
            RiskReport.model_validate({**payload, "release_authorized": True})

    def test_review_gate_is_structural(self):
        report = RiskReport(severity=1, confidence=1.0, recommendation=RecommendationEnum.NO_ACTION, rationale="Complete evidence.")
        result = evaluate_opa_policy(build_opa_input(report, {"regulatory": [], "artifacts": []}, "", [], set()))
        self.assertTrue(result.available, result.error)
        self.assertTrue(result.decision["requires_human_review"])

    def test_review_gate_mutation_is_detected(self):
        opa = ROOT / "bin" / "opa"
        if not opa.exists():
            self.skipTest("Local OPA binary is not installed")
        report = RiskReport(
            severity=1,
            confidence=1.0,
            recommendation=RecommendationEnum.NO_ACTION,
            rationale="Complete evidence.",
        )
        payload = build_opa_input(report, {"regulatory": [], "artifacts": []}, "", [], set())
        policy = (ROOT / "policies" / "risk_report_policy.rego").read_text(encoding="utf-8")
        mutant = policy.replace("default requires_human_review := true", "default requires_human_review := false")
        with tempfile.NamedTemporaryFile("w", suffix=".rego", encoding="utf-8") as policy_file, tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as input_file:
            policy_file.write(mutant); policy_file.flush(); json.dump(payload, input_file); input_file.flush()
            proc = subprocess.run([str(opa), "eval", "--format=json", "--data", policy_file.name, "--input", input_file.name,
                                   "data.biodevops.risk_report.decision"], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        decision = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
        self.assertFalse(decision["requires_human_review"], "review-gate mutant must be observable")

    def test_evidence_mediation_requires_technical_evidence(self):
        report = RiskReport(
            severity=2,
            confidence=0.9,
            recommendation=RecommendationEnum.MONITOR,
            rationale="A technical incident was reported.",
        )
        result = evaluate_opa_policy(build_opa_input(report, {"regulatory": [], "artifacts": []}, "", [], set()))
        self.assertTrue(result.available, result.error)
        self.assertIn("technical_incident_missing_technical_evidence", result.decision["deny"])
        self.assertTrue(result.decision["requires_human_review"])
        self.assertTrue(result.decision["missing_evidence_additions"])

    def test_evidence_mediation_mutation_is_detected(self):
        opa = ROOT / "bin" / "opa"
        if not opa.exists():
            self.skipTest("Local OPA binary is not installed")
        report = RiskReport(
            severity=2,
            confidence=0.9,
            recommendation=RecommendationEnum.MONITOR,
            rationale="A technical incident was reported.",
        )
        payload = build_opa_input(report, {"regulatory": [], "artifacts": []}, "", [], set())
        policy = (ROOT / "policies" / "risk_report_policy.rego").read_text(encoding="utf-8")
        mutant = policy.replace("input.report.severity >= 2", "input.report.severity >= 5")
        with tempfile.NamedTemporaryFile("w", suffix=".rego", encoding="utf-8") as policy_file, tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as input_file:
            policy_file.write(mutant); policy_file.flush(); json.dump(payload, input_file); input_file.flush()
            proc = subprocess.run([str(opa), "eval", "--format=json", "--data", policy_file.name, "--input", input_file.name,
                                   "data.biodevops.risk_report.decision"], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        decision = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
        self.assertNotIn("technical_incident_missing_technical_evidence", decision["deny"])
        self.assertFalse(decision["missing_evidence_additions"], "evidence-rule mutant must weaken the verdict")

    def test_confirmed_trigger_mutation_is_detected(self):
        opa = ROOT / "bin" / "opa"
        if not opa.exists():
            self.skipTest("Local OPA binary is not installed")
        policy = (ROOT / "policies" / "cgm_policy.rego").read_text(encoding="utf-8")
        mutant = policy.replace("input.cgm_flags.severe_hypoglycemia_confirmed", "input.cgm_flags.severe_hypoglycemia")
        payload = {"report": {"severity": 2, "confidence": 0.8, "recommendation": "MONITOR"},
                   "has_hallucinated_citations": False, "has_population_or_recurrence_evidence": False,
                   "has_human_approval": False, "weakly_supported_claims": [], "unsupported_claims": [],
                   "cgm_flags": {"severe_hypoglycemia": True, "severe_hypoglycemia_confirmed": False,
                                 "loss_of_consciousness": False, "loss_of_consciousness_confirmed": False,
                                 "sensor_failure": False, "has_glucose_evidence": True,
                                 "conflicting_observations": False, "post_market_retraining": False}}
        with tempfile.NamedTemporaryFile("w", suffix=".rego", encoding="utf-8") as policy_file, tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as input_file:
            policy_file.write(mutant); policy_file.flush(); json.dump(payload, input_file); input_file.flush()
            proc = subprocess.run([str(opa), "eval", "--format=json", "--data", policy_file.name, "--input", input_file.name,
                                   "data.biodevops.cgm_risk_report.decision"], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        decision = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
        self.assertEqual(decision["recommendation_override"], "ESCALATE_TO_HUMAN_IMMEDIATE")


if __name__ == "__main__":
    unittest.main()
