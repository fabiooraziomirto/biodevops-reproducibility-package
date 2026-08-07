#!/usr/bin/env python3
"""Freeze and execute the OPA-only Class 9 technical-evidence supplement."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]
REPO = SUITE.parent
sys.path.insert(0, str(REPO / "scripts"))

from risk_report_schema import ClaimSupport, ClaimSupportStatus, EvidenceLink, RecommendationEnum, RiskReport
from symbolic_verifier import verify_risk_report

CASES = SUITE / "cases" / "class9_technical_evidence_v1.jsonl"
LABELS = SUITE / "labels" / "class9_technical_evidence_labels_v1.jsonl"
MANIFEST = SUITE / "labels" / "CLASS9_SUPPLEMENT_v1.json"
RESULTS = SUITE / "results" / "class9_v1"
V1_CASES = SUITE / "cases" / "arrhythmia_factorial_v1.jsonl"
V1_FREEZE = SUITE / "labels" / "LABEL_FREEZE_v1.json"
V2_POLICY = SUITE / "labels" / "POLICY_CHANGE_v2.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_context() -> dict:
    # All rows retain retrieved technical context. Only the report linkage varies.
    return {
        "regulatory": [{"id": "REG-ONLY", "text": "Regulatory extract.", "metadata": {}}],
        "artifacts": [{"id": "ARTIFACT-TECH-001", "text": "Technical test log evidence.", "metadata": {"artifact_type": "test_log"}}],
    }


def build() -> list[dict]:
    rows = []
    for severity in (2, 3):
        for evidence_state in ("linked_technical", "no_report_link", "linked_nontechnical_regulatory"):
            positive = evidence_state != "linked_technical"
            if evidence_state == "linked_technical":
                links = [EvidenceLink(artifact_id="ARTIFACT-TECH-001", artifact_type="test_log", relevance_note="Retrieved technical test log.")]
                claims = [ClaimSupport(claim="Technical incident assessed.", cited_artifact_id="ARTIFACT-TECH-001", support_status=ClaimSupportStatus.SUPPORTED, support_note="Directly supported by test log.")]
            elif evidence_state == "linked_nontechnical_regulatory":
                links = [EvidenceLink(artifact_id="REG-ONLY", artifact_type="regulatory_extract", relevance_note="Valid regulatory source, not technical evidence.")]
                claims = [ClaimSupport(claim="Technical incident assessed.", cited_artifact_id="REG-ONLY", support_status=ClaimSupportStatus.SUPPORTED, support_note="Source resolves but is not a technical artifact.")]
            else:
                links, claims = [], []
            ordinal = len(rows) + 1
            case_id = f"FC-09-{ordinal:02d}"
            report = RiskReport(severity=severity, confidence=0.8, evidence_links=links, claim_support=claims,
                                recommendation=RecommendationEnum.CAPA_INVESTIGATE,
                                rationale="Technical incident assessment without a field safety corrective action request.").model_dump(mode="json")
            label = {
                "id": case_id, "class": 9,
                "opa": {
                    "eligibility": "eligible", "violation_present": positive,
                    "expected_verdict": "issue" if positive else "no_issue",
                    "expected_opa_issue": positive,
                    "expected_opa_requires_human_review": True,
                    "review_routing_scoring": "excluded_structural_default",
                    "expected_family": "technical_incident_missing_technical_evidence" if positive else "technical_evidence_present",
                    "rationale": "Severity >=2 requires a report-linked technical artifact; review routing is not the scored OPA issue.",
                },
                "shacl": {
                    "eligibility": "not_applicable", "violation_present": None,
                    "expected_verdict": "not_applicable", "expected_family": "not_applicable",
                    "rationale": "Technical evidence linkage is not a SHACL-side input predicate.",
                },
            }
            rows.append({
                "id": case_id, "class": 9,
                "axis_values": {"severity": severity, "report_evidence_state": evidence_state},
                "report": report, "narrative": "Technical incident assessment.", "retrieval_context": fixture_context(),
                "fixture_provenance": "class9_technical_evidence_v1; LLM-free OPA-only supplement",
                "target_rule": "technical_incident_missing_technical_evidence",
                "label": label,
            })
    return rows


def freeze() -> None:
    rows = build()
    CASES.write_text("".join(json.dumps({k: v for k, v in row.items() if k != "label"}, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    LABELS.write_text("".join(json.dumps(row["label"], sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    current_policy = json.loads(V2_POLICY.read_text(encoding="utf-8"))
    manifest = {
        "version": "class9_supplement_v1", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_v1_case_bank": str(V1_CASES.relative_to(REPO)), "parent_v1_case_bank_sha256": digest(V1_CASES),
        "parent_v1_freeze_sha256": digest(V1_FREEZE), "parent_v2_policy_manifest_sha256": digest(V2_POLICY),
        "current_v2_policy_sha256": current_policy["policy_sha256"],
        "supplement_case_bank_sha256": digest(CASES), "supplement_labels_sha256": digest(LABELS),
        "scope": "Separate six-row Class 9 OPA-only supplement; original 48-row v1 case bank and labels are immutable and unchanged.",
        "opa_scoring": "opa_issue is deny/action/override; opa_requires_human_review is separately recorded and excluded as the structural default.",
        "shacl_eligibility": "not_applicable for every Class 9 row.",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run() -> None:
    if not MANIFEST.exists():
        raise SystemExit("Freeze the Class 9 supplement before execution.")
    labels = {json.loads(line)["id"]: json.loads(line) for line in LABELS.read_text(encoding="utf-8").splitlines() if line}
    observed = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        row = json.loads(line); verification = verify_risk_report(RiskReport.model_validate(row["report"]), row["retrieval_context"], row["narrative"], domain="arrhythmia")
        actions = verification.policy_actions
        observed.append({
            "id": row["id"], "class": 9, "axis_values": row["axis_values"], "frozen_label": labels[row["id"]],
            "observed": {
                "opa_issue": bool(actions), "opa_requires_human_review": verification.verified_report.requires_human_review,
                "opa_policy_actions": actions, "opa_engine": verification.policy_engine,
                "opa_recommendation": verification.verified_report.recommendation.value,
                "shacl_verdict": "not_run_not_applicable",
            },
        })
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "raw_observations.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in observed), encoding="utf-8")
    print(f"Executed {len(observed)} isolated Class 9 rows to {RESULTS}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--freeze", action="store_true"); parser.add_argument("--run", action="store_true"); args = parser.parse_args()
    if args.freeze: freeze()
    if args.run: run()
    if not args.freeze and not args.run: parser.error("choose --freeze and/or --run")
