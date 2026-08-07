#!/usr/bin/env python3
"""Execute the frozen 48-row v1 bank plus frozen Class-9 supplement."""
from __future__ import annotations
import hashlib
import json
import sys
import argparse
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]
REPO = SUITE.parent
sys.path.insert(0, str(REPO / "scripts"))
from ontology_validate import CaseFacts, validate_case
from risk_report_schema import RiskReport
from symbolic_verifier import verify_risk_report

V1_CASES = SUITE / "cases" / "arrhythmia_factorial_v1.jsonl"
V1_LABELS = SUITE / "labels" / "labels_v1.jsonl"
C9_CASES = SUITE / "cases" / "class9_technical_evidence_v1.jsonl"
C9_LABELS = SUITE / "labels" / "class9_technical_evidence_labels_v1.jsonl"
V1_FREEZE = SUITE / "labels" / "LABEL_FREEZE_v1.json"
C9_FREEZE = SUITE / "labels" / "CLASS9_SUPPLEMENT_v1.json"

def digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def read_jsonl(path: Path) -> list[dict]: return [json.loads(x) for x in path.read_text().splitlines() if x]

def assert_frozen() -> None:
    v1, c9 = json.loads(V1_FREEZE.read_text()), json.loads(C9_FREEZE.read_text())
    assert digest(V1_CASES) == v1["sha256"]["conformance_suite/cases/arrhythmia_factorial_v1.jsonl"]
    assert digest(V1_LABELS) == v1["sha256"]["conformance_suite/labels/labels_v1.jsonl"]
    assert digest(C9_CASES) == c9["supplement_case_bank_sha256"]
    assert digest(C9_LABELS) == c9["supplement_labels_sha256"]

def main(run_id: str) -> None:
    assert_frozen()
    labels = {item["id"]: item for item in read_jsonl(V1_LABELS) + read_jsonl(C9_LABELS)}
    output = []
    for item in read_jsonl(V1_CASES) + read_jsonl(C9_CASES):
        report = RiskReport.model_validate(item["report"])
        verification = verify_risk_report(report, item["retrieval_context"], item["narrative"], domain="arrhythmia")
        actions = verification.policy_actions
        observed = {
            "opa_issue": bool(actions), "opa_requires_human_review": verification.verified_report.requires_human_review,
            "opa_policy_actions": actions, "opa_engine": verification.policy_engine,
            "opa_recommendation": verification.verified_report.recommendation.value,
        }
        if item["class"] != 9:
            f = item["clinical_facts"]
            facts = CaseFacts(item["id"], f["snomed_code"], f["lethality_class"], f["clinical_event_occurred"], f["patient_exposed"], f["harm_outcome"], f["note"], f["fhir_fragment"])
            row = {"report_id": item["id"], "base_scenario_id": item["id"], "predicted_severity": report.severity, "predicted_recommendation": report.recommendation.value, "retrieved_artifacts": [x["id"] for x in item["retrieval_context"]["artifacts"]], "expected_artifacts": [x["id"] for x in item["retrieval_context"]["artifacts"]], "policy_actions": actions}
            shacl = validate_case(row, {item["id"]: facts})
            observed.update({"shacl_issue": not shacl["ontology_conforms"], "shacl_conforms": shacl["ontology_conforms"], "shacl_violations": shacl["violations"]})
        else:
            observed.update({"shacl_issue": False, "shacl_conforms": None, "shacl_violations": [], "shacl_verdict": "not_run_not_applicable"})
        output.append({"id": item["id"], "class": item["class"], "axis_values": item["axis_values"], "frozen_label": labels[item["id"]], "observed": observed})
    out = SUITE / "results" / f"run_{run_id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "raw_observations.jsonl").write_text("".join(json.dumps(x, sort_keys=True)+"\n" for x in output), encoding="utf-8")
    print(f"Executed {len(output)} frozen combined rows to {out}")
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="v3_final")
    main(parser.parse_args().run_id)
