"""Full-scale validation of SHACL-informed in-loop revision on the independent-40 benchmark.

This is a new, separately versioned runner for the newly added revision
mechanism (clinical_case_id/clinical_facts_path threading and revision
feedback in bounded_agent.run_bounded_agent). It does not modify or reuse
run_bounded_arm.py, which is coupled to the frozen matched-agentic-campaign
protocol; this script validates new functionality across all 40 scenarios,
independent of the frozen development/held-out split.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from bounded_agent import OllamaBoundedPlanner, run_bounded_agent
from rag_pipeline import get_ollama_client


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--clinical-facts-bundle", required=True, type=Path)
    p.add_argument("--campaign-dir", required=True, type=Path)
    p.add_argument("--campaign-id", default="inloop_revision_validation")
    p.add_argument("--model", default="qwen2.5:3b")
    p.add_argument("--model-digest", default="357c53fb659c")
    p.add_argument("--seed", type=int, default=20260803)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    data = json.loads(args.dataset.read_text())
    cases = data["synthetic_incident_reports"]
    if args.limit:
        cases = cases[: args.limit]
    traces = args.campaign_dir / "traces"
    reports = args.campaign_dir / "reports"
    traces.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    manifest = args.campaign_dir / "run_manifest.jsonl"
    client = get_ollama_client()
    provenance = {
        "dataset_sha256": sha(args.dataset),
        "policy_sha256": sha(Path(__file__).parent.parent / "policies/risk_report_policy.rego"),
        "ontology_sha256": sha(Path(__file__).parent.parent / "ontology/biodevops_clinical.ttl"),
        "clinical_facts_sha256": sha(args.clinical_facts_bundle),
    }
    rows = []
    for i, case in enumerate(cases, 1):
        run_id = f"inloop_{case['report_id']}_{uuid4().hex[:8]}"
        trace_path = traces / f"{case['report_id']}.jsonl"
        run = run_bounded_agent(
            case["report_id"], case["narrative"], planner=OllamaBoundedPlanner(client, args.model),
            ollama_client=client, model=args.model, trace_path=trace_path, model_digest=args.model_digest,
            seed=args.seed, campaign_id=args.campaign_id, run_id=run_id, dataset_name=args.dataset.name,
            split="pooled", run_phase="validation", provenance=provenance,
            clinical_case_id=case["report_id"], clinical_facts_path=str(args.clinical_facts_bundle),
        )
        result = run.final_result or {}
        report_path = reports / f"{case['report_id']}.json"
        report_path.write_text(json.dumps(result, indent=2, sort_keys=True))
        eligible = result.get("generation_source") == "ollama_real"
        events = [r for r in run.records if r.get("record_type") == "event"]
        revise_events = [r for r in events if r.get("accepted_action") == "revise"]
        revise_attempted = bool(revise_events)
        # The event immediately before each revise is the synthesize (or prior
        # revise) whose gaps made revise eligible; a non-empty shacl_findings
        # there means SHACL contributed to triggering this specific revision.
        revise_triggered_by_shacl = False
        for idx, event in enumerate(events):
            if event.get("accepted_action") == "revise" and idx > 0:
                if events[idx - 1].get("shacl_findings"):
                    revise_triggered_by_shacl = True
        revision_changed_output = any(r.get("revision_changed_output") for r in revise_events)
        row = {
            "campaign_id": args.campaign_id, "run_id": run_id, "scenario_id": case["report_id"],
            "trace_id": run.metadata["trace_id"], "success": eligible,
            "termination_reason": run.termination_reason,
            "revise_attempted": revise_attempted,
            "revise_triggered_by_shacl": revise_triggered_by_shacl,
            "revision_changed_output": revision_changed_output,
        }
        with manifest.open("a") as h:
            h.write(json.dumps(row, sort_keys=True) + "\n")
        rows.append(row)
        print(f"[{i}/{len(cases)}] {case['report_id']} eligible={eligible} "
              f"revise_attempted={revise_attempted} changed_output={revision_changed_output}", flush=True)
    n = len(rows)
    summary = {
        "n": n,
        "eligible": sum(r["success"] for r in rows),
        "revise_attempted": sum(r["revise_attempted"] for r in rows),
        "revise_triggered_by_shacl": sum(r["revise_triggered_by_shacl"] for r in rows),
        "revision_changed_output": sum(r["revision_changed_output"] for r in rows),
        "rows": rows,
    }
    (args.campaign_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    if not all(r["success"] for r in rows):
        raise SystemExit("At least one run was ineligible (non-real generation); see run_manifest.jsonl")


if __name__ == "__main__":
    main()
