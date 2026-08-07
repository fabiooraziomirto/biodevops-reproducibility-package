#!/usr/bin/env python3
"""Materialize, freeze, and execute the 48-row arrhythmia conformance suite."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]
REPO = SUITE.parent
sys.path.insert(0, str(REPO / "scripts"))

from ontology_validate import CaseFacts, validate_case
from risk_report_schema import ClaimSupport, ClaimSupportStatus, EvidenceLink, RecommendationEnum, RiskReport
from symbolic_verifier import verify_risk_report

CASES = SUITE / "cases" / "arrhythmia_factorial_v1.jsonl"
LABELS = SUITE / "labels" / "labels_v1.jsonl"
FREEZE = SUITE / "labels" / "LABEL_FREEZE_v1.json"
RESULTS = SUITE / "results" / "run_v1"
RISK_TAG = "https://biodevops.local/fhir/StructureDefinition/clinical-risk-tag"
CONCEPTS = [
    ("49436004", "atrial_fibrillation", "serious"),
    ("25569003", "ventricular_tachycardia", "life_threatening"),
    ("71908006", "ventricular_fibrillation", "life_threatening"),
    ("27885002", "complete_av_block", "life_threatening"),
]
ARTIFACT_TYPES = ["test_log", "incident_report", "code_diff", "deployment_log"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def context(kind: str = "test_log", recurrence: str = "") -> dict:
    return {
        "regulatory": [{"id": "REG-001", "text": "Risk management extract.", "metadata": {}}],
        "artifacts": [{"id": "ARTIFACT-OK-001", "text": f"Technical evidence {recurrence}".strip(), "metadata": {"artifact_type": kind}}],
    }


def fragment(code: str, tag: str = "valid", coding: str = "exact") -> dict:
    if coding == "exact":
        system, value = "http://snomed.info/sct", code
    elif coding == "mismatch":
        system, value = "http://snomed.info/sct", next(item[0] for item in CONCEPTS if item[0] != code)
    elif coding == "non_numeric":
        system, value = "http://snomed.info/sct", "not-a-snomed-code"
    else:
        system, value = "https://example.invalid/codes", code
    item = {"resourceType": "Observation", "id": "obs-conformance", "status": "final", "code": {"coding": [{"system": system, "code": value}]}}
    if tag == "valid":
        item["extension"] = [{"url": RISK_TAG, "valueCode": "life_threatening_event_occurred"}]
    elif tag == "malformed":
        item["extension"] = [{"url": RISK_TAG}]
    elif tag == "irrelevant":
        item["extension"] = [{"url": "https://example.invalid/other", "valueString": "irrelevant"}]
    return item


def report(severity: int, recommendation: str, artifact_id: str = "ARTIFACT-OK-001", artifact_type: str = "test_log", rationale: str = "Documented technical evidence supports this advisory report.") -> dict:
    links = [EvidenceLink(artifact_id=artifact_id, artifact_type=artifact_type, relevance_note="Technical evidence supports the report.")]
    claims = [ClaimSupport(claim="Technical event assessed.", cited_artifact_id=artifact_id, support_status=ClaimSupportStatus.SUPPORTED, support_note="Directly supported by the retrieved artifact.")]
    return RiskReport(severity=severity, confidence=0.8, evidence_links=links, claim_support=claims, recommendation=RecommendationEnum(recommendation), rationale=rationale).model_dump(mode="json")


def label(case_id: str, cls: int, opa: tuple[bool, bool, str], shacl: tuple[bool, bool, str], rationale: str) -> dict:
    def view(value: tuple[bool, bool, str]) -> dict:
        eligible, present, family = value
        return {"eligibility": "eligible" if eligible else "not_applicable", "violation_present": present if eligible else None, "expected_verdict": ("issue" if present else "no_issue") if eligible else "not_applicable", "expected_family": family, "rationale": rationale}
    return {"id": case_id, "class": cls, "opa": view(opa), "shacl": view(shacl)}


def case(case_id: str, cls: int, axes: dict, rep: dict, narrative: str, facts: dict, ctx: dict, lab: dict) -> dict:
    return {"id": case_id, "class": cls, "axis_values": axes, "report": rep, "narrative": narrative, "retrieval_context": ctx, "clinical_facts": facts, "fhir_fragment": facts["fhir_fragment"], "fixture_provenance": "arrhythmia_factorial_v1; LLM-free authored conformance fixture", "label": lab}


def facts(code: str, lethality: str, occurred: bool, harm: str, fhir: dict, note: str) -> dict:
    return {"snomed_code": code, "lethality_class": lethality, "clinical_event_occurred": occurred, "patient_exposed": occurred, "harm_outcome": harm, "note": note, "fhir_fragment": fhir}


def build_cases() -> list[dict]:
    out: list[dict] = []
    # Class 1: B1 correct; B2 low severity; B3 low recommendation; B4 both low.
    schedule = [(0, "correct"), (1, "low_severity"), (2, "low_recommendation"), (3, "both_low"), (0, "low_severity"), (1, "correct")]
    for n, (idx, state) in enumerate(schedule, 1):
        code, name, lethality = CONCEPTS[idx]
        sev, rec = {"correct": (3, "CAPA_INVESTIGATE"), "low_severity": (1, "CAPA_INVESTIGATE"), "low_recommendation": (3, "MONITOR"), "both_low": (1, "MONITOR")}[state]
        positive = state != "correct"
        f = facts(code, lethality, True, "none", fragment(code), "Confirmed event used only by SHACL-side validator.")
        lid = f"FC-01-{n:02d}"; l = label(lid, 1, (False, False, "not_applicable"), (True, positive, "clinical_undercall" if positive else "concordant"), "Confirmed clinical fact requires severity/recommendation concordance.")
        out.append(case(lid, 1, {"concept": name, "report_alignment": state}, report(sev, rec), "Confirmed documented arrhythmia event.", f, context(), l))

    # Classes 2/3: all-negative specificity controls covering four concepts, both phrasings, both postures.
    combos = [(0, "phrasing_a", "NO_ACTION"), (1, "phrasing_b", "MONITOR"), (2, "phrasing_a", "MONITOR"), (3, "phrasing_b", "NO_ACTION"), (0, "phrasing_a", "MONITOR"), (1, "phrasing_b", "NO_ACTION")]
    for cls, status in ((2, "mention"), (3, "negation")):
        for n, (idx, phrasing, posture) in enumerate(combos, 1):
            code, name, lethality = CONCEPTS[idx]
            narrative = (f"Clinician {('mentions ' if phrasing == 'phrasing_a' else 'lists a differential of ')}{name}; it is not confirmed." if status == "mention" else f"{name} was {('explicitly ruled out' if phrasing == 'phrasing_a' else 'not present after review')}.")
            f = facts(code, lethality, False, "none", fragment(code), f"{status}-only clinical assertion.")
            lid = f"FC-{cls:02d}-{n:02d}"; l = label(lid, cls, (True, False, "no_procedural_issue"), (True, False, "no_clinical_escalation"), f"{status.title()} assertions must not be promoted to confirmed events.")
            out.append(case(lid, cls, {"concept": name, "assertion_wording": phrasing, "report_posture": posture}, report(1, posture), narrative, f, context(), l))

    # Class 4: B1 confirmed basis; other recurrence states violate the governance rubric.
    rec_states = ["confirmed_basis", "absent_basis", "single_event_only", "suspected_unconfirmed"]
    for n, (idx, state) in enumerate([(0, rec_states[0]), (1, rec_states[1]), (2, rec_states[2]), (3, rec_states[3]), (0, rec_states[1]), (1, rec_states[0])], 1):
        artifact = ARTIFACT_TYPES[idx]
        phrases = {"confirmed_basis": "confirmed recurrence in the deployed population", "absent_basis": "isolated technical observation", "single_event_only": "one event only", "suspected_unconfirmed": "suspected recurrence, unconfirmed"}
        positive = state != "confirmed_basis"; f = facts("25569003", "life_threatening", True, "none", fragment("25569003"), "OPA-only FSCA basis probe.")
        lid = f"FC-04-{n:02d}"; l = label(lid, 4, (True, positive, "fsca_basis" if positive else "fsca_basis_present"), (False, False, "not_applicable"), "FSCA requires confirmed recurrence or deployed-population impact.")
        out.append(case(lid, 4, {"technical_artifact": artifact, "recurrence_basis": state}, report(3, "FIELD_SAFETY_CORRECTIVE_ACTION", artifact_type=artifact, rationale=phrases[state]), "Technical field-action assessment.", f, context(artifact, phrases[state]), l))

    # Class 5: valid tag vs three rubric-positive tag faults.
    tag_states = ["valid", "absent", "malformed", "irrelevant"]
    for n, (idx, state) in enumerate([(0, tag_states[0]), (1, tag_states[1]), (2, tag_states[2]), (3, tag_states[3]), (0, tag_states[1]), (1, tag_states[0])], 1):
        code, name, lethality = CONCEPTS[idx]; positive = state != "valid"
        f = facts(code, lethality, True, "none", fragment(code, state), "FHIR risk-tag structural probe.")
        lid = f"FC-05-{n:02d}"; l = label(lid, 5, (False, False, "not_applicable"), (True, positive, "fhir_risk_tag" if positive else "concordant"), "A clinical-risk-tag must be present and semantically valid.")
        out.append(case(lid, 5, {"concept": name, "risk_tag_state": state}, report(3, "CAPA_INVESTIGATE"), "Confirmed event with FHIR fragment.", f, context(), l))

    # Class 6: exact coding vs three coding violations.
    coding_states = ["exact", "mismatch", "non_numeric", "wrong_system"]
    for n, (idx, state) in enumerate([(0, coding_states[0]), (1, coding_states[1]), (2, coding_states[2]), (3, coding_states[3]), (0, coding_states[1]), (1, coding_states[0])], 1):
        code, name, lethality = CONCEPTS[idx]; positive = state != "exact"
        f = facts(code, lethality, True, "none", fragment(code, coding=state), "FHIR SNOMED coding probe.")
        lid = f"FC-06-{n:02d}"; l = label(lid, 6, (False, False, "not_applicable"), (True, positive, "fhir_snomed_coding" if positive else "concordant"), "FHIR coding must use the mapped numeric SNOMED-CT code.")
        out.append(case(lid, 6, {"concept": name, "coding_state": state}, report(3, "CAPA_INVESTIGATE"), "Confirmed event with coded FHIR fragment.", f, context(), l))

    # Class 7: valid citation vs unresolved/trap/malformed citation.
    citation_states = ["valid", "unresolved", "trap", "malformed"]
    bad_ids = {"unresolved": "ARTIFACT-UNKNOWN-404", "trap": "ARTIFACT-DIFF-9999", "malformed": "[not resolvable]"}
    for n, (idx, state) in enumerate([(0, citation_states[0]), (1, citation_states[1]), (2, citation_states[2]), (3, citation_states[3]), (0, citation_states[1]), (1, citation_states[0])], 1):
        artifact = ARTIFACT_TYPES[idx]; positive = state != "valid"; artifact_id = bad_ids.get(state, "ARTIFACT-OK-001")
        f = facts("25569003", "life_threatening", True, "none", fragment("25569003"), "Citation-only OPA probe.")
        lid = f"FC-07-{n:02d}"; l = label(lid, 7, (True, positive, "citation_unresolved" if positive else "citation_valid"), (False, False, "not_applicable"), "Citation IDs must resolve to retrieved non-trap artifacts.")
        out.append(case(lid, 7, {"technical_artifact": artifact, "citation_state": state}, report(1, "NO_ACTION", artifact_id=artifact_id, artifact_type=artifact), "Otherwise-correct advisory report.", f, context(artifact), l))

    # Class 8: adequate comparator states then low-action states, repeated with new concepts.
    states = [(0, "CAPA_INVESTIGATE"), (1, "ESCALATE_TO_HUMAN_IMMEDIATE"), (2, "NO_ACTION"), (3, "MONITOR"), (1, "NO_ACTION"), (2, "MONITOR")]
    for n, (idx, rec) in enumerate(states, 1):
        code, name, lethality = CONCEPTS[idx]; positive = rec in {"NO_ACTION", "MONITOR"}
        f = facts(code, lethality, True, "none", fragment(code), "Correct citation, outcome recommendation probe.")
        lid = f"FC-08-{n:02d}"; l = label(lid, 8, (False, False, "not_applicable"), (True, positive, "recommendation_vs_documented_outcome" if positive else "concordant"), "Actual life-threatening events must not receive NO_ACTION or MONITOR.")
        out.append(case(lid, 8, {"concept": name, "recommendation_state": rec}, report(3, rec), "Confirmed documented arrhythmia event.", f, context(), l))
    assert len(out) == 48
    return out


def materialize() -> None:
    cases = build_cases(); CASES.parent.mkdir(parents=True, exist_ok=True); LABELS.parent.mkdir(parents=True, exist_ok=True)
    CASES.write_text("".join(json.dumps({k: v for k, v in item.items() if k != "label"}, sort_keys=True) + "\n" for item in cases), encoding="utf-8")
    LABELS.write_text("".join(json.dumps(item["label"], sort_keys=True) + "\n" for item in cases), encoding="utf-8")


def freeze() -> None:
    materialize()
    tracked = [CASES, LABELS, REPO / "policies" / "risk_report_policy.rego", REPO / "ontology" / "biodevops_clinical.ttl", REPO / "scripts" / "ontology_validate.py", REPO / "scripts" / "opa_policy.py"]
    git = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    payload = {"suite": "arrhythmia_factorial_v1", "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "git_revision": git.stdout.strip() or "unavailable", "sha256": {str(path.relative_to(REPO)): sha(path) for path in tracked}, "labeling_protocol": "single-author freeze-before-execution fallback; see rubric_v1.md"}
    FREEZE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(out_dir: Path) -> None:
    if not FREEZE.exists():
        raise SystemExit("No frozen manifest. Run with --freeze before --run.")
    labels = {json.loads(line)["id"]: json.loads(line) for line in LABELS.read_text(encoding="utf-8").splitlines() if line}
    observed = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        item = json.loads(line); data = item["clinical_facts"]
        f = CaseFacts(scenario_id=item["id"], snomed_code=data["snomed_code"], lethality_class=data["lethality_class"], clinical_event_occurred=data["clinical_event_occurred"], patient_exposed=data["patient_exposed"], harm_outcome=data["harm_outcome"], note=data["note"], fhir_fragment=data["fhir_fragment"])
        rep = RiskReport.model_validate(item["report"]); verification = verify_risk_report(rep, item["retrieval_context"], item["narrative"], domain="arrhythmia")
        row = {"report_id": item["id"], "base_scenario_id": item["id"], "predicted_severity": rep.severity, "predicted_recommendation": rep.recommendation.value, "retrieved_artifacts": [x["id"] for x in item["retrieval_context"]["artifacts"]], "expected_artifacts": [x["id"] for x in item["retrieval_context"]["artifacts"]], "policy_actions": verification.policy_actions}
        shacl = validate_case(row, {item["id"]: f})
        opa_issue = bool(verification.policy_actions)
        observed.append({"id": item["id"], "class": item["class"], "axis_values": item["axis_values"], "frozen_label": labels[item["id"]], "observed": {"opa_issue": opa_issue, "opa_policy_actions": verification.policy_actions, "opa_engine": verification.policy_engine, "opa_error": verification.opa_error, "shacl_issue": not shacl["ontology_conforms"], "shacl_conforms": shacl["ontology_conforms"], "shacl_violations": shacl["violations"]}})
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw_observations.jsonl").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in observed), encoding="utf-8")
    comparisons = []
    for item in observed:
        comparisons.append({
            "id": item["id"], "class": item["class"], "opa": {
                "eligibility": item["frozen_label"]["opa"]["eligibility"],
                "expected_issue": item["frozen_label"]["opa"]["expected_verdict"],
                "observed_issue": item["observed"]["opa_issue"],
            }, "shacl": {
                "eligibility": item["frozen_label"]["shacl"]["eligibility"],
                "expected_issue": item["frozen_label"]["shacl"]["expected_verdict"],
                "observed_issue": item["observed"]["shacl_issue"],
            },
        })
    (out_dir / "per_case_comparison.jsonl").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in comparisons), encoding="utf-8")
    print(f"Executed {len(observed)} frozen conformance cases to {out_dir}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--freeze", action="store_true"); p.add_argument("--run", action="store_true"); p.add_argument("--run-id", default="v1"); args = p.parse_args()
    if args.freeze: freeze()
    if args.run: run(SUITE / "results" / f"run_{args.run_id}")
    if not args.freeze and not args.run: p.error("choose --freeze and/or --run")
