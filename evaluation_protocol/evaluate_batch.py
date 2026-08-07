"""
Batch evaluation for the BioDevOps RAG agent.

Runs the synthetic MAUDE-style arrhythmia cases and writes machine-readable
metrics for the paper's Agent Evaluation table.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rag_pipeline import (
    PROMPT_CONDITIONS,
    generate_risk_report,
    generate_risk_report_no_rag,
    get_embedder,
    get_ollama_client,
    retrieve_context,
)
from risk_report_schema import RecommendationEnum, RiskReport
from symbolic_verifier import HALLUCINATION_TRAP_IDS, normalize_cited_id, valid_context_ids, verify_risk_report

CORPUS_DIR = Path(__file__).parent.parent / "corpus"
OUTPUT_DIR = Path(__file__).parent.parent / "evaluation_outputs"
DATASET_ALIASES = {
    "arrhythmia": CORPUS_DIR / "synthetic_maude_arrhythmia.json",
    "cgm": CORPUS_DIR / "synthetic_cgm_validation.json",
}


@dataclass
class EvaluationRow:
    report_id: str
    base_scenario_id: str
    ground_truth_severity: int
    predicted_severity: int
    verified_severity: int
    severity_correct: int
    verified_severity_correct: int
    ground_truth_recommendation: str
    predicted_recommendation: str
    verified_recommendation: str
    recommendation_correct: int
    verified_recommendation_correct: int
    confidence: float
    requires_human_review: bool
    artifact_recall_at_4: float
    retrieved_artifacts: str
    expected_artifacts: str
    citation_validity: float
    claim_grounding_rate: float
    citation_hallucination: int
    unsupported_claim_present: int
    hallucination_escape: int
    hallucination_escape_combined: int
    claim_grounding_omission: int
    policy_engine: str
    generation_source: str
    policy_actions: str
    rationale: str
    evidence_links: list[dict] = field(default_factory=list)
    evidence_link_artifact_ids_raw: list[str] = field(default_factory=list)
    evidence_link_artifact_ids_normalized: list[str] = field(default_factory=list)
    hallucinated_citation_ids: list[str] = field(default_factory=list)
    hallucinated_citation_ids_normalized: list[str] = field(default_factory=list)
    citation_id_audit: list[dict] = field(default_factory=list)
    risk_report_pre_opa: dict = field(default_factory=dict)
    verified_risk_report_post_opa: dict = field(default_factory=dict)
    clinical_guard_conforms: bool | None = None
    clinical_guard_violations: list[dict] = field(default_factory=list)
    clinical_facts_bundle: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def load_maude_data(dataset_path: Path) -> dict:
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_dataset_path(dataset: str) -> Path:
    return DATASET_ALIASES.get(dataset, Path(dataset))


def resolve_domain(dataset: str) -> str:
    return "cgm" if "cgm" in str(resolve_dataset_path(dataset)).lower() else "arrhythmia"


def keyword_baseline(narrative: str) -> RiskReport:
    text = narrative.lower()
    if "death" in text or "died" in text:
        severity = 4
        recommendation = RecommendationEnum.ESCALATE_TO_HUMAN_IMMEDIATE
    elif "failed to flag" in text or "vtach" in text or "sustained" in text:
        severity = 3
        recommendation = RecommendationEnum.CAPA_INVESTIGATE
    elif "pre-release" in text or "blocked" in text or "not yet deployed" in text:
        severity = 1
        recommendation = RecommendationEnum.NO_ACTION
    elif "false-positive" in text or "false positive" in text:
        severity = 2
        recommendation = RecommendationEnum.MONITOR
    else:
        severity = 2
        recommendation = RecommendationEnum.CAPA_INVESTIGATE

    return RiskReport(
        severity=severity,
        confidence=0.55,
        evidence_links=[],
        missing_evidence=["No retrieval context used by keyword baseline."],
        claim_support=[],
        requires_human_review=severity >= 3,
        recommendation=recommendation,
        rationale="Keyword baseline used for comparison only; no RAG grounding.",
    )


def expected_calibration_error(rows: list[dict], bins: int = 5) -> float:
    if not rows:
        return 0.0
    total = len(rows)
    ece = 0.0
    for bin_index in range(bins):
        low = bin_index / bins
        high = (bin_index + 1) / bins
        if bin_index == bins - 1:
            bucket = [row for row in rows if low <= row["confidence"] <= high]
        else:
            bucket = [row for row in rows if low <= row["confidence"] < high]
        if not bucket:
            continue
        accuracy = sum(row["severity_correct"] for row in bucket) / len(bucket)
        confidence = sum(row["confidence"] for row in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(accuracy - confidence)
    return round(ece, 4)


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return round(statistics.stdev(values), 4)


def mode_agreement(values: list) -> dict:
    if not values:
        return {"mode": None, "mode_count": 0, "agreement_rate": 0.0}
    counts = Counter(values)
    mode, count = counts.most_common(1)[0]
    return {
        "mode": mode,
        "mode_count": count,
        "agreement_rate": round(count / len(values), 4),
    }


def artifact_recall_at_k(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    expected = set(expected_ids) - HALLUCINATION_TRAP_IDS
    if not expected:
        return 1.0
    retrieved = set(retrieved_ids) - HALLUCINATION_TRAP_IDS
    return round(len(expected & retrieved) / len(expected), 4)


def group_by_base_scenario(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.get("base_scenario_id", row["report_id"])].append(row)
    return dict(sorted(grouped.items()))


def per_scenario_breakdown(rows: list[dict]) -> list[dict]:
    breakdown = []
    metric_fields = [
        "severity_correct",
        "recommendation_correct",
        "citation_hallucination",
        "claim_grounding_rate",
    ]
    for scenario_id, scenario_rows in group_by_base_scenario(rows).items():
        row = {
            "base_scenario_id": scenario_id,
            "n_cases": len(scenario_rows),
            "ground_truth_severity": scenario_rows[0]["ground_truth_severity"],
            "ground_truth_recommendation": scenario_rows[0]["ground_truth_recommendation"],
        }
        for field in metric_fields:
            values = [float(case_row.get(field, 0)) for case_row in scenario_rows]
            row[f"{field}_mean"] = mean(values)
            row[f"{field}_std"] = stdev(values)

        severity_agreement = mode_agreement([case_row["predicted_severity"] for case_row in scenario_rows])
        recommendation_agreement = mode_agreement(
            [case_row["predicted_recommendation"] for case_row in scenario_rows]
        )
        row.update(
            {
                "severity_mode": severity_agreement["mode"],
                "severity_mode_count": severity_agreement["mode_count"],
                "severity_agreement_rate": severity_agreement["agreement_rate"],
                "recommendation_mode": recommendation_agreement["mode"],
                "recommendation_mode_count": recommendation_agreement["mode_count"],
                "recommendation_agreement_rate": recommendation_agreement["agreement_rate"],
            }
        )
        breakdown.append(row)
    return breakdown


def dataset_scenario_consistency(maude_data: dict) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for case in maude_data["synthetic_incident_reports"]:
        grouped[case.get("base_scenario_id", case["report_id"])].append(case)

    report = []
    for scenario_id, cases in sorted(grouped.items()):
        ground_truths = {
            (case["ground_truth_severity"], case["ground_truth_recommendation"])
            for case in cases
        }
        artifact_sets = {tuple(sorted(case["linked_artifacts"])) for case in cases}
        report.append(
            {
                "base_scenario_id": scenario_id,
                "n_variants": len(cases),
                "same_ground_truth": len(ground_truths) == 1,
                "same_linked_artifacts": len(artifact_sets) == 1,
                "ground_truth_values": [
                    {"severity": severity, "recommendation": recommendation}
                    for severity, recommendation in sorted(ground_truths)
                ],
                "linked_artifact_sets": [list(artifact_set) for artifact_set in sorted(artifact_sets)],
            }
        )
    return report


def print_dataset_consistency_report(consistency_report: list[dict]) -> None:
    print("Dataset base-scenario consistency report:")
    for row in consistency_report:
        gt_status = "same" if row["same_ground_truth"] else "DIFFERS"
        artifact_status = "same" if row["same_linked_artifacts"] else "DIFFERS"
        print(
            f"  {row['base_scenario_id']}: n={row['n_variants']}, "
            f"ground_truth={gt_status}, linked_artifacts={artifact_status}"
        )


def evaluate_case(
    report: RiskReport,
    verified: RiskReport,
    verification: dict,
    case: dict,
    context: dict,
    generation_source: str,
    clinical_validation: dict | None = None,
) -> dict:
    expected_artifacts = case["linked_artifacts"]
    retrieved_artifacts = [hit["id"] for hit in context["artifacts"]]
    evidence_links = [
        link.model_dump(mode="json")
        for link in report.evidence_links
    ]
    raw_citation_ids = [link["artifact_id"] for link in evidence_links]
    normalized_citation_ids = [normalize_cited_id(raw_id) for raw_id in raw_citation_ids]
    valid_ids = valid_context_ids(context)
    citation_id_audit = [
        {
            "raw_artifact_id": raw_id,
            "normalized_artifact_id": normalized_id,
            "is_valid_retrieved_context_id": normalized_id in valid_ids,
            "is_hallucinated": normalized_id not in valid_ids,
        }
        for raw_id, normalized_id in zip(raw_citation_ids, normalized_citation_ids)
    ]
    hallucinated_ids = [
        item["raw_artifact_id"]
        for item in citation_id_audit
        if item["is_hallucinated"]
    ]
    hallucinated_ids_normalized = [
        item["normalized_artifact_id"]
        for item in citation_id_audit
        if item["is_hallucinated"]
    ]
    row = EvaluationRow(
        report_id=case["report_id"],
        base_scenario_id=case.get("base_scenario_id", case["report_id"]),
        ground_truth_severity=case["ground_truth_severity"],
        predicted_severity=report.severity,
        verified_severity=verified.severity,
        severity_correct=int(report.severity == case["ground_truth_severity"]),
        verified_severity_correct=int(verified.severity == case["ground_truth_severity"]),
        ground_truth_recommendation=case["ground_truth_recommendation"],
        predicted_recommendation=report.recommendation.value,
        verified_recommendation=verified.recommendation.value,
        recommendation_correct=int(report.recommendation.value == case["ground_truth_recommendation"]),
        verified_recommendation_correct=int(verified.recommendation.value == case["ground_truth_recommendation"]),
        confidence=report.confidence,
        requires_human_review=verified.requires_human_review,
        artifact_recall_at_4=artifact_recall_at_k(retrieved_artifacts, expected_artifacts),
        retrieved_artifacts="|".join(retrieved_artifacts),
        expected_artifacts="|".join(expected_artifacts),
        citation_validity=verification["citation_validity"],
        claim_grounding_rate=verification["claim_grounding_rate"],
        citation_hallucination=verification.get("citation_hallucination", 0),
        unsupported_claim_present=verification.get("unsupported_claim_present", 0),
        hallucination_escape=verification.get(
            "hallucination_escape_combined",
            verification.get("hallucination_escape", 0),
        ),
        hallucination_escape_combined=verification.get(
            "hallucination_escape_combined",
            verification.get("hallucination_escape", 0),
        ),
        claim_grounding_omission=verification.get("claim_grounding_omission", 0),
        policy_engine=verification.get("policy_engine", "unknown"),
        generation_source=generation_source,
        policy_actions="|".join(verification["policy_actions"]),
        rationale=report.rationale,
        evidence_links=evidence_links,
        evidence_link_artifact_ids_raw=raw_citation_ids,
        evidence_link_artifact_ids_normalized=normalized_citation_ids,
        hallucinated_citation_ids=hallucinated_ids,
        hallucinated_citation_ids_normalized=hallucinated_ids_normalized,
        citation_id_audit=citation_id_audit,
        risk_report_pre_opa=report.model_dump(mode="json"),
        verified_risk_report_post_opa=verified.model_dump(mode="json"),
        clinical_guard_conforms=(
            clinical_validation["conforms"] if clinical_validation is not None else None
        ),
        clinical_guard_violations=(
            clinical_validation["violations"] if clinical_validation is not None else []
        ),
        clinical_facts_bundle=(
            clinical_validation["bundle_path"] if clinical_validation is not None else ""
        ),
    )
    return row.to_dict()


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {}
    n = len(rows)
    high_risk_rows = [r for r in rows if r["ground_truth_severity"] >= 3]
    if high_risk_rows:
        escalation_safety = sum(
            r["verified_recommendation"] not in {"NO_ACTION", "MONITOR"}
            for r in high_risk_rows
        ) / len(high_risk_rows)
    else:
        escalation_safety = 1.0
    return {
        "n_cases": n,
        "n_base_scenarios": len({r.get("base_scenario_id", r["report_id"]) for r in rows}),
        "severity_accuracy": round(sum(r["severity_correct"] for r in rows) / n, 4),
        "verified_severity_accuracy": round(sum(r["verified_severity_correct"] for r in rows) / n, 4),
        "recommendation_accuracy": round(sum(r["recommendation_correct"] for r in rows) / n, 4),
        "verified_recommendation_accuracy": round(sum(r["verified_recommendation_correct"] for r in rows) / n, 4),
        "mean_artifact_recall_at_4": round(sum(r["artifact_recall_at_4"] for r in rows) / n, 4),
        "mean_citation_validity": round(sum(r["citation_validity"] for r in rows) / n, 4),
        "mean_claim_grounding_rate": round(sum(r["claim_grounding_rate"] for r in rows) / n, 4),
        "citation_hallucination_rate": round(sum(r.get("citation_hallucination", 0) for r in rows) / n, 4),
        "unsupported_claim_rate": round(sum(r.get("unsupported_claim_present", 0) for r in rows) / n, 4),
        "hallucination_escape_rate": round(sum(r["hallucination_escape"] for r in rows) / n, 4),
        "claim_grounding_omission_rate": round(sum(r.get("claim_grounding_omission", 0) for r in rows) / n, 4),
        "escalation_safety": round(escalation_safety, 4),
        "human_review_rate": round(sum(int(r["requires_human_review"]) for r in rows) / n, 4),
        "severity_ece": expected_calibration_error(rows),
        "mock_fallback_cases": sum(r["generation_source"] == "mock_fallback" for r in rows),
        "opa_policy_cases": sum(r["policy_engine"] == "opa" for r in rows),
        "per_scenario_breakdown": per_scenario_breakdown(rows),
}


def audit_paper_grade(rows: list[dict]) -> dict:
    mock_fallback_cases = [
        row["report_id"]
        for row in rows
        if row.get("generation_source") != "ollama_real"
    ]
    non_opa_cases = [
        row["report_id"]
        for row in rows
        if row.get("policy_engine") != "opa"
    ]
    return {
        "paper_grade_pass": not mock_fallback_cases and not non_opa_cases,
        "n_cases": len(rows),
        "mock_fallback_cases": len(mock_fallback_cases),
        "non_opa_cases": len(non_opa_cases),
        "mock_fallback_report_ids": mock_fallback_cases,
        "non_opa_report_ids": non_opa_cases,
    }


def validate_paper_grade(rows: list[dict]) -> None:
    audit = audit_paper_grade(rows)
    if not audit["paper_grade_pass"]:
        raise RuntimeError(
            "Paper-grade run failed: "
            f"non-real generation cases={audit['mock_fallback_report_ids']}; "
            f"non-OPA policy cases={audit['non_opa_report_ids']}"
        )


def write_outputs(
    rows: list[dict],
    summary: dict,
    output_dir: Path,
    dataset_consistency: list[dict] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "cases": rows}
    if dataset_consistency is not None:
        payload["dataset_consistency"] = dataset_consistency
    with open(output_dir / "batch_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    with open(output_dir / "batch_eval_results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([csv_safe_row(row) for row in rows])


def csv_safe_row(row: dict) -> dict:
    csv_row = {}
    for key, value in row.items():
        if isinstance(value, (list, dict)):
            csv_row[key] = json.dumps(value, ensure_ascii=False)
        else:
            csv_row[key] = value
    return csv_row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["keyword-baseline", "no-rag-llm", "rag"],
        default="rag",
        help=(
            "Evaluation mode. 'rag' uses retrieval plus the local Ollama/mock pipeline; "
            "'no-rag-llm' uses the same structured LLM path with empty retrieved context."
        ),
    )
    parser.add_argument(
        "--dataset",
        default=str(CORPUS_DIR / "synthetic_maude_arrhythmia.json"),
        help=(
            "Synthetic benchmark JSON to evaluate; may be 'arrhythmia', 'cgm', "
            "or an explicit JSON path. The default arrhythmia path is unchanged."
        ),
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate only the first N cases; useful for quick Ollama smoke tests.",
    )
    parser.add_argument(
        "--split",
        choices=["development", "held_out", "pooled"],
        default="pooled",
        help=(
            "Filter cases to a development/held_out partition defined by --split-file "
            "(report_id membership). 'pooled' (default) evaluates every case, unchanged "
            "from prior behavior."
        ),
    )
    parser.add_argument(
        "--split-file",
        default=str(CORPUS_DIR / "independent_40_split.json"),
        help="JSON file with {'development': [...report_ids], 'held_out': [...report_ids]}.",
    )
    parser.add_argument(
        "--ollama-model",
        default=None,
        help="Override the default Ollama model used by rag mode.",
    )
    parser.add_argument(
        "--prompt-condition",
        choices=sorted(PROMPT_CONDITIONS),
        default="all_combined",
        help="System prompt ablation condition for rag mode.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-case progress messages.",
    )
    parser.add_argument(
        "--paper-grade",
        action="store_true",
        help="Fail if any case uses mock fallback generation or non-OPA policy.",
    )
    parser.add_argument(
        "--clinical-facts-bundle",
        default=None,
        help=(
            "Optional versioned clinical-facts JSON bundle. When supplied, run the "
            "SHACL clinical guard inside the report pipeline using each case's "
            "base_scenario_id and record its structured verdict."
        ),
    )
    args = parser.parse_args()

    maude_data = load_maude_data(resolve_dataset_path(args.dataset))
    domain = resolve_domain(args.dataset)
    consistency_report = dataset_scenario_consistency(maude_data)
    if not args.quiet:
        print_dataset_consistency_report(consistency_report)
    cases = maude_data["synthetic_incident_reports"]
    if args.split != "pooled":
        with open(args.split_file, "r", encoding="utf-8") as f:
            split_ids = set(json.load(f)[args.split])
        cases = [case for case in cases if case["report_id"] in split_ids]
        if not args.quiet:
            print(f"Filtered to split={args.split!r}: {len(cases)} cases from {args.split_file}")
    if args.limit is not None:
        cases = cases[:args.limit]
    embedder = get_embedder() if args.mode != "no-rag-llm" else None
    ollama_client = get_ollama_client() if args.mode in {"rag", "no-rag-llm"} else None
    rows = []

    for index, case in enumerate(cases, start=1):
        if not args.quiet:
            print(f"[{index}/{len(cases)}] Evaluating {case['report_id']} ({args.mode}) ...", flush=True)
        narrative = case["narrative"]
        context = (
            {"regulatory": [], "artifacts": []}
            if args.mode == "no-rag-llm"
            else retrieve_context(narrative, embedder)
        )
        if args.mode == "keyword-baseline":
            report = keyword_baseline(narrative)
            verification_result = verify_risk_report(report, context, narrative, domain=domain)
            verified = verification_result.verified_report
            verification = verification_result.model_dump()
            generation_source = "keyword_baseline"
            clinical_validation = None
        elif args.mode == "no-rag-llm":
            result = generate_risk_report_no_rag(
                narrative,
                ollama_model=args.ollama_model or None,
                ollama_client=ollama_client,
                domain=domain,
            )
            if "error" in result:
                raise RuntimeError(f"{case['report_id']} failed: {result['error']}")
            report = RiskReport.model_validate(result["risk_report"])
            verified = RiskReport.model_validate(result["verified_risk_report"])
            verification = result["verification"]
            generation_source = result.get("generation_source", "unknown")
            clinical_validation = result.get("clinical_validation")
        else:
            result = generate_risk_report(
                narrative,
                ollama_model=args.ollama_model or None,
                embedder=embedder,
                ollama_client=ollama_client,
                context=context,
                prompt_condition=args.prompt_condition,
                domain=domain,
                clinical_case_id=case.get("base_scenario_id", case["report_id"])
                if args.clinical_facts_bundle else None,
                clinical_facts_path=args.clinical_facts_bundle,
            )
            if "error" in result:
                raise RuntimeError(f"{case['report_id']} failed: {result['error']}")
            report = RiskReport.model_validate(result["risk_report"])
            verified = RiskReport.model_validate(result["verified_risk_report"])
            verification = result["verification"]
            generation_source = result.get("generation_source", "unknown")
            clinical_validation = result.get("clinical_validation")
        rows.append(
            evaluate_case(
                report, verified, verification, case, context, generation_source,
                clinical_validation=clinical_validation,
            )
        )

    summary = summarize(rows)
    if args.paper_grade:
        validate_paper_grade(rows)
    write_outputs(rows, summary, Path(args.output_dir), consistency_report)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
