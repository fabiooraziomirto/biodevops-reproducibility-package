"""Post-hoc clinical ontology validation for stored BioDevOps RiskReport rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyshacl import validate
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD

REPO_ROOT = Path(__file__).resolve().parent
ONTOLOGY_DIR = REPO_ROOT / "ontology"
CONCEPTS_PATH = ONTOLOGY_DIR / "clinical_concepts.json"
SHAPES_PATH = ONTOLOGY_DIR / "biodevops_clinical.ttl"
EVAL_ROOT = REPO_ROOT.parent / "results"
DEFAULT_OUT = EVAL_ROOT / "ontology_validation"

BDV = Namespace("https://biodevops.local/ontology#")
SNOMED_SYSTEM = "http://snomed.info/sct"
CLINICAL_RISK_TAG_URL = "https://biodevops.local/fhir/StructureDefinition/clinical-risk-tag"
# Exact vocabulary already used by the curated arrhythmia and independent
# scenario mappings. This remains a closed allowlist, not general FHIR
# extension semantic validation.
CLINICAL_RISK_TAG_VALUES = {
    "documented_death",
    "event_documented",
    "life_threatening_event_occurred",
    "life_threatening_event_occurred_no_harm",
    "no_confirmed_event",
    "outage_patient_exposed_no_event",
    "patient_exposed_no_event",
    "predeployment_no_exposure",
}
BAD_RECOMMENDATIONS_FOR_HARM = {"NO_ACTION", "MONITOR"}
RECOMMENDATIONS = {
    "NO_ACTION",
    "MONITOR",
    "CAPA_INVESTIGATE",
    "FIELD_SAFETY_CORRECTIVE_ACTION",
    "ESCALATE_TO_HUMAN_IMMEDIATE",
}
ONTOLOGY_ONLY_CLASSES = {
    "recommendation_vs_documented_outcome",
    "concept_severity_undercall",
}
SEVERITY_CAVEAT = (
    "For the five curated scenarios the derived severity floor equals the labelled "
    "ground-truth severity; treat this as a one-sided under-call screen, not an "
    "independent correctness oracle."
)


@dataclass(frozen=True)
class CaseFacts:
    scenario_id: str
    snomed_code: str
    lethality_class: str
    clinical_event_occurred: bool
    patient_exposed: bool
    harm_outcome: str
    note: str
    fhir_fragment: dict[str, Any]


def load_clinical_mapping(path: Path = CONCEPTS_PATH) -> dict[str, CaseFacts]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    concepts = raw["concepts"]
    mapping: dict[str, CaseFacts] = {}
    for scenario_id, scenario in raw["scenarios"].items():
        code = scenario["snomed_code"]
        concept = concepts[code]
        mapping[scenario_id] = CaseFacts(
            scenario_id=scenario_id,
            snomed_code=code,
            lethality_class=concept["lethality_class"],
            clinical_event_occurred=bool(scenario["clinical_event_occurred"]),
            patient_exposed=bool(scenario["patient_exposed"]),
            harm_outcome=scenario["harm_outcome"],
            note=scenario["note"],
            fhir_fragment=scenario["fhir_fragment"],
        )
    return mapping


def derive_severity_floor(
    lethality_class: str,
    clinical_event_occurred: bool,
    patient_exposed: bool,
    harm_outcome: str,
) -> int:
    if harm_outcome == "death":
        return 4
    if (
        clinical_event_occurred
        and lethality_class == "life_threatening"
        and patient_exposed
        and harm_outcome == "harm"
    ):
        return 4
    if (
        clinical_event_occurred
        and lethality_class in {"life_threatening", "serious"}
        and patient_exposed
        and harm_outcome == "none"
    ):
        return 3
    if (not clinical_event_occurred) and patient_exposed:
        return 2
    if (not clinical_event_occurred) and (not patient_exposed):
        return 1
    return 1


def validate_fhir_fragment(fragment: dict[str, Any], expected_code: str) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    resource_type = fragment.get("resourceType")
    if resource_type not in {"Observation", "DetectedIssue"}:
        violations.append(_violation("fhir_structure", f"Unsupported resourceType: {resource_type!r}"))
    if not fragment.get("id"):
        violations.append(_violation("fhir_structure", "FHIR fragment must include id."))
    if resource_type == "Observation" and fragment.get("status") not in {"registered", "preliminary", "final", "amended"}:
        violations.append(_violation("fhir_structure", "Observation.status is missing or invalid."))
    if resource_type == "DetectedIssue" and fragment.get("status") not in {"registered", "preliminary", "final", "amended", "mitigated"}:
        violations.append(_violation("fhir_structure", "DetectedIssue.status is missing or invalid."))
    codings = fragment.get("code", {}).get("coding", [])
    if not isinstance(codings, list) or not codings:
        violations.append(_violation("fhir_structure", "FHIR code.coding must contain at least one coding."))
        return violations
    matching = [coding for coding in codings if coding.get("system") == SNOMED_SYSTEM]
    if not matching:
        violations.append(_violation("fhir_snomed_system", "FHIR code.coding.system must be http://snomed.info/sct."))
        return violations
    if not any(str(coding.get("code", "")).isdigit() for coding in matching):
        violations.append(_violation("fhir_numeric_snomed", "FHIR SNOMED code must be numeric."))
    if not any(str(coding.get("code")) == expected_code for coding in matching):
        violations.append(_violation("fhir_snomed_code", f"FHIR SNOMED code must match mapped concept {expected_code}."))
    extensions = fragment.get("extension", [])
    has_valid_risk_tag = (
        isinstance(extensions, list)
        and any(
            isinstance(extension, dict)
            and extension.get("url") == CLINICAL_RISK_TAG_URL
            and extension.get("valueCode") in CLINICAL_RISK_TAG_VALUES
            for extension in extensions
        )
    )
    if not has_valid_risk_tag:
        violations.append(_violation("fhir_clinical_risk_tag", "FHIR fragment must include a clinical-risk tag extension."))
    return violations


def discover_input_files(root: Path = EVAL_ROOT) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("batch_eval_results.json")
        if "_ABANDONED_" not in path.as_posix()
        and "ontology_validation" not in path.parts
    )


def is_headline_family(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(EVAL_ROOT).as_posix()
    except ValueError:
        return False
    parts = rel.split("/")
    top = parts[0]
    return (
        "papergrade" in rel
        or top == "repeat_runs"
        or top.startswith("repeat_runs_")
    ) and not (
        top in {"keyword_baseline", "no_rag_llm_baseline"}
        or rel.startswith("repeat_runs_ablation/")
    )


def condition_family(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(EVAL_ROOT).as_posix()
    except ValueError:
        return "other"
    if rel.startswith("keyword_baseline/"):
        return "keyword_baseline"
    if rel.startswith("no_rag_llm_baseline/"):
        return "no_rag_llm_baseline"
    if is_headline_family(path):
        return "paper_grade_opa"
    return "other"


def opa_accepts(row: dict[str, Any]) -> bool:
    actions = _policy_actions(row.get("policy_actions", ""))
    denied = any(action.startswith("deny:") or action == "deny" for action in actions)
    already_escalated = any(
        "severity4_or_death_forced_immediate_human_escalation" in action
        or "recommendation_override" in action
        or "force" in action.lower() and "escalat" in action.lower()
        for action in actions
    )
    return not denied and not already_escalated


def opa_has_issue(row: dict[str, Any]) -> bool:
    return not opa_accepts(row)


def validate_case(row: dict[str, Any], mapping: dict[str, CaseFacts]) -> dict[str, Any]:
    scenario_id = row.get("base_scenario_id") or row.get("report_id")
    if scenario_id not in mapping:
        violations = [_violation("clinical_mapping", f"No clinical mapping for scenario {scenario_id}.")]
        return _case_payload(row, scenario_id, None, None, False, violations, "none", False)

    facts = mapping[scenario_id]
    floor = derive_severity_floor(
        facts.lethality_class,
        facts.clinical_event_occurred,
        facts.patient_exposed,
        facts.harm_outcome,
    )
    fhir_violations = validate_fhir_fragment(facts.fhir_fragment, facts.snomed_code)
    graph = build_case_graph(row, facts, floor)
    shacl_violations = run_shacl(graph)
    rule_violations, inconsistency_class, overlap = classify_clinical_violations(row, facts, floor)
    merged = _dedupe_violations(fhir_violations + shacl_violations + rule_violations)
    conforms = not any(v["severity"] != "Info" for v in merged)
    return _case_payload(row, scenario_id, facts, floor, conforms, merged, inconsistency_class, overlap)


def build_case_graph(row: dict[str, Any], facts: CaseFacts, floor: int) -> Graph:
    graph = Graph()
    graph.parse(SHAPES_PATH, format="turtle")
    report = URIRef(f"https://biodevops.local/report/{_safe_id(row.get('report_id', 'unknown'))}")
    graph.add((report, RDF.type, BDV.RiskReport))
    graph.add((report, BDV.predictedSeverity, Literal(_int_or_zero(row.get("predicted_severity")), datatype=XSD.integer)))
    graph.add((report, BDV.derivedSeverityFloor, Literal(floor, datatype=XSD.integer)))
    graph.add((report, BDV.recommendation, BDV[str(row.get("predicted_recommendation", ""))]))
    graph.add((report, BDV.reportConcept, concept_uri(facts.snomed_code)))
    graph.add((report, BDV.clinicalEventOccurred, Literal(facts.clinical_event_occurred, datatype=XSD.boolean)))
    graph.add((report, BDV.patientExposed, Literal(facts.patient_exposed, datatype=XSD.boolean)))
    graph.add((report, BDV.harmOutcome, Literal(facts.harm_outcome)))
    coding = _first_snomed_coding(facts.fhir_fragment)
    graph.add((report, BDV.fhirSystem, Literal(coding.get("system", ""))))
    graph.add((report, BDV.fhirCode, Literal(str(coding.get("code", "")))))
    for evidence_id in evidence_ids(row):
        graph.add((report, BDV.hasEvidenceId, Literal(evidence_id)))
    return graph


def run_shacl(graph: Graph) -> list[dict[str, str]]:
    conforms, _results_graph, results_text = validate(
        graph,
        shacl_graph=str(SHAPES_PATH),
        inference="owlrl",
        abort_on_first=False,
        allow_infos=True,
        allow_warnings=True,
    )
    if conforms:
        return []
    return parse_pyshacl_text(results_text)


def classify_clinical_violations(row: dict[str, Any], facts: CaseFacts, floor: int) -> tuple[list[dict[str, str]], str, bool]:
    violations: list[dict[str, str]] = []
    predicted_severity = _int_or_zero(row.get("predicted_severity"))
    recommendation = str(row.get("predicted_recommendation", ""))
    overlap = False

    if predicted_severity < floor:
        violations.append(
            _violation(
                "concept_severity_undercall",
                f"Predicted severity {predicted_severity} is below derived clinical floor {floor}. {SEVERITY_CAVEAT}",
            )
        )
    if predicted_severity == 4 and recommendation != "ESCALATE_TO_HUMAN_IMMEDIATE":
        overlap = True
        violations.append(
            _violation(
                "severity4_opa_overlap",
                "Severity-4 report is not paired with ESCALATE_TO_HUMAN_IMMEDIATE; classified as OPA-overlap.",
            )
        )
    bad_outcome = facts.harm_outcome in {"harm", "death"}
    actual_life_threatening = facts.clinical_event_occurred and facts.lethality_class == "life_threatening"
    if (bad_outcome or actual_life_threatening) and recommendation in BAD_RECOMMENDATIONS_FOR_HARM:
        violations.append(
            _violation(
                "recommendation_vs_documented_outcome",
                "Documented harm/death or actual life-threatening event must not be paired with NO_ACTION or MONITOR.",
            )
        )

    ontology_classes = [v["shape"] for v in violations if v["shape"] in ONTOLOGY_ONLY_CLASSES]
    if "recommendation_vs_documented_outcome" in ontology_classes:
        inconsistency_class = "recommendation_vs_documented_outcome"
    elif "concept_severity_undercall" in ontology_classes:
        inconsistency_class = "concept_severity_undercall"
    else:
        inconsistency_class = "none"
    return violations, inconsistency_class, overlap


def validate_file(path: Path, mapping: dict[str, CaseFacts]) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases", data if isinstance(data, list) else [])
    details = [validate_case(row, mapping) for row in cases]
    return {
        "input_file": _display_path(path),
        "condition_family": condition_family(path),
        "headline_family": is_headline_family(path),
        "n_cases": len(details),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "cases": details,
        "summary": summarize_cases(details),
    }


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    ontology_nonconform = [case for case in cases if not case["ontology_conforms"]]
    ontology_only = [
        case
        for case in ontology_nonconform
        if case["opa_accepted"] and case["clinical_inconsistency_class"] in ONTOLOGY_ONLY_CLASSES
    ]
    overlap = [case for case in ontology_nonconform if not case["opa_accepted"] or case["opa_overlap"]]
    opa_only = [case for case in cases if case["opa_flagged"] and case["ontology_conforms"]]
    return {
        "n_cases": len(cases),
        "ontology_nonconformant": len(ontology_nonconform),
        "ontology_only_catch": len(ontology_only),
        "ontology_only_by_class": dict(Counter(case["clinical_inconsistency_class"] for case in ontology_only)),
        "ontology_only_report_ids": [case["report_id"] for case in ontology_only],
        "overlap": len(overlap),
        "opa_only": len(opa_only),
        "opa_only_report_ids": [case["report_id"] for case in opa_only],
    }


def aggregate_file_results(file_results: list[dict[str, Any]]) -> dict[str, Any]:
    all_cases = [case for result in file_results for case in result["cases"]]
    headline_cases = [case for result in file_results if result["headline_family"] for case in result["cases"]]
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in file_results:
        by_condition[result["condition_family"]].extend(result["cases"])
    return {
        "input_file_count": len(file_results),
        "discovered_total_row_count": len(all_cases),
        "paper_grade_subset_count": len(headline_cases),
        "headline": summarize_cases(headline_cases),
        "all_files": summarize_cases(all_cases),
        "by_condition": {condition: summarize_cases(cases) for condition, cases in sorted(by_condition.items())},
        "severity_floor_caveat": SEVERITY_CAVEAT,
        "files": [
            {
                "input_file": result["input_file"],
                "condition_family": result["condition_family"],
                "headline_family": result["headline_family"],
                "n_cases": result["n_cases"],
                "summary": result["summary"],
            }
            for result in file_results
        ],
    }


def write_outputs(file_results: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    detail_dir = out_dir / "per_file"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for result in file_results:
        safe_name = _safe_detail_name(result["input_file"])
        (detail_dir / safe_name).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    summary = aggregate_file_results(file_results)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_pyshacl_text(results_text: str) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    current_message = ""
    current_severity = "Violation"
    for line in results_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Severity:"):
            current_severity = stripped.rsplit("#", 1)[-1]
        elif stripped.startswith("Message:"):
            current_message = stripped.removeprefix("Message:").strip()
            shape = current_message.split(":", 1)[0] if ":" in current_message else "shacl"
            violations.append(_violation(shape, current_message, current_severity))
    return violations


def evidence_ids(row: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for field in ("retrieved_artifacts", "expected_artifacts"):
        value = row.get(field, [])
        if isinstance(value, str):
            parts = [part.strip() for part in value.replace("|", ",").split(",")]
            ids.extend(part for part in parts if part)
        elif isinstance(value, list):
            ids.extend(str(part) for part in value if str(part))
    return sorted(set(ids))


def _case_payload(
    row: dict[str, Any],
    scenario_id: str,
    facts: CaseFacts | None,
    floor: int | None,
    conforms: bool,
    violations: list[dict[str, str]],
    inconsistency_class: str,
    overlap: bool,
) -> dict[str, Any]:
    return {
        "report_id": row.get("report_id"),
        "base_scenario_id": scenario_id,
        "predicted_severity": row.get("predicted_severity"),
        "predicted_recommendation": row.get("predicted_recommendation"),
        "ground_truth_severity": row.get("ground_truth_severity"),
        "derived_severity_floor": floor,
        "floor_equals_ground_truth": floor == row.get("ground_truth_severity") if floor is not None else None,
        "snomed_code": facts.snomed_code if facts else None,
        "lethality_class": facts.lethality_class if facts else None,
        "harm_outcome": facts.harm_outcome if facts else None,
        "clinical_event_occurred": facts.clinical_event_occurred if facts else None,
        "patient_exposed": facts.patient_exposed if facts else None,
        "clinical_rationale": facts.note if facts else None,
        "ontology_conforms": conforms,
        "violations": sorted(violations, key=lambda item: (item["shape"], item["message"], item["severity"])),
        "clinical_inconsistency_class": inconsistency_class,
        "severity_floor_caveat": SEVERITY_CAVEAT if inconsistency_class == "concept_severity_undercall" else "",
        "opa_accepted": opa_accepts(row),
        "opa_flagged": opa_has_issue(row),
        "opa_overlap": overlap,
        "policy_actions": row.get("policy_actions", ""),
    }


def _violation(shape: str, message: str, severity: str = "Violation") -> dict[str, str]:
    return {"shape": shape, "message": message, "severity": severity}


def _dedupe_violations(violations: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for violation in violations:
        key = (violation["shape"], violation["message"], violation["severity"])
        if key not in seen:
            seen.add(key)
            deduped.append(violation)
    return deduped


def _policy_actions(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [part.strip() for part in value.replace(",", "|").split("|") if part.strip()]
    return []


def _first_snomed_coding(fragment: dict[str, Any]) -> dict[str, Any]:
    for coding in fragment.get("code", {}).get("coding", []):
        if coding.get("system") == SNOMED_SYSTEM:
            return coding
    codings = fragment.get("code", {}).get("coding", [])
    return codings[0] if codings else {}


def concept_uri(code: str) -> URIRef:
    return {
        "25569003": BDV.VentricularTachycardia,
        "71908006": BDV.VentricularFibrillation,
        "27885002": BDV.CompleteAtrioventricularBlock,
        "49436004": BDV.AtrialFibrillation,
        "698247007": BDV.CardiacArrhythmia,
    }[code]


def _safe_id(value: Any) -> str:
    return str(value).replace("/", "_").replace("#", "_")


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _safe_detail_name(input_file: str) -> str:
    path = Path(input_file)
    parts = [part for part in path.parts[:-1] if part not in {"", "/"}]
    if not parts:
        parts = ["root"]
    return "__".join(_safe_id(part) for part in parts) + ".json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="Stored batch_eval_results.json to validate.")
    group.add_argument("--all", action="store_true", help="Validate every non-abandoned stored batch_eval_results.json.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory for ontology validation artifacts.")
    parser.add_argument(
        "--concepts", type=Path, default=CONCEPTS_PATH,
        help="Clinical concepts/scenario-facts JSON to use (defaults to the 5-scenario mapping).",
    )
    args = parser.parse_args(argv)

    mapping = load_clinical_mapping(args.concepts)
    inputs = discover_input_files() if args.all else [args.input]
    file_results = [validate_file(path, mapping) for path in inputs]
    summary = write_outputs(file_results, args.out)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
