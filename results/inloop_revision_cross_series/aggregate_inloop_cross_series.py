"""Aggregate SHACL-Informed In-Loop Revision results across three model configurations
(qwen2.5:3b frozen baseline, qwen3.5:9b, gemma3:12b) directly from raw campaign outputs.

Every number in this script's output is computed from run_manifest.jsonl / traces/*.jsonl /
summary.json under the three campaign directories below. Nothing is hand-entered.

Usage: venv/bin/python aggregate_inloop_cross_series.py
Output: cross_series_metrics.json, cross_series_table.csv, cross_series_table.tex (this dir)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CAMPAIGNS = {
    "qwen2.5:3b": Path("/root/Desktop/BioDevOps/results/inloop_revision_campaign_rerun_20260805"),
    "qwen3.5:9b": Path("/root/Desktop/BioDevOps/results/inloop_revision_cross_series_20260806/qwen3.5_9b"),
    "gemma3:12b": Path("/root/Desktop/BioDevOps/results/inloop_revision_cross_series_20260806/gemma3_12b"),
}

OUT_DIR = Path("/root/Desktop/BioDevOps/results/inloop_revision_cross_series_20260806")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows(campaign_dir: Path) -> list[dict]:
    summary = json.loads((campaign_dir / "summary.json").read_text())
    return summary["rows"]


def load_all_events(campaign_dir: Path) -> list[dict]:
    events = []
    for trace_file in sorted((campaign_dir / "traces").glob("*.jsonl")):
        for line in trace_file.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("record_type") == "event":
                events.append(rec)
    return events


def metrics_for(model: str, campaign_dir: Path) -> dict:
    rows = load_rows(campaign_dir)
    events = load_all_events(campaign_dir)
    n = len(rows)

    completions = sum(1 for r in rows if r["success"])
    real_generation = sum(1 for e in events if e.get("generation_source") == "ollama_real")
    fallback_events = sum(1 for e in events if e.get("is_fallback"))
    mock_events = sum(1 for e in events if e.get("is_mock"))

    revise_attempted = sum(1 for r in rows if r["revise_attempted"])
    revise_shacl = sum(1 for r in rows if r["revise_triggered_by_shacl"])
    revise_opa_only = sum(1 for r in rows if r["revise_attempted"] and not r["revise_triggered_by_shacl"])

    changed_shacl = sum(1 for r in rows if r["revise_triggered_by_shacl"] and r["revision_changed_output"])
    changed_opa_only = sum(
        1 for r in rows if r["revise_attempted"] and not r["revise_triggered_by_shacl"] and r["revision_changed_output"]
    )
    changed_any = sum(1 for r in rows if r["revision_changed_output"])

    # residual SHACL violations: shacl_findings present on the LAST event of a scenario
    residual_shacl = 0
    by_scenario: dict[str, list[dict]] = {}
    for e in events:
        by_scenario.setdefault(e["scenario_id"], []).append(e)
    for sid, evs in by_scenario.items():
        evs_sorted = sorted(evs, key=lambda e: e["step_index"])
        last_with_findings_field = [e for e in evs_sorted if "shacl_findings" in e]
        if last_with_findings_field and last_with_findings_field[-1].get("shacl_findings"):
            residual_shacl += 1

    # evidence_gaps_before/after on a "revise" event describe gaps found in the draft
    # that step is producing/verifying, not a before/after-revision delta, so they
    # cannot be diffed for "evidence added by the revision." Instead we count
    # claim_support (evidence-citation) entries in the final report for scenarios
    # whose revision was SHACL-triggered, as a direct measurement from raw output.
    evidence_links_final_report = []
    for sid, r in {row["scenario_id"]: row for row in rows}.items():
        if not r["revise_triggered_by_shacl"]:
            continue
        report_path = campaign_dir / "reports" / f"{sid}.json"
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text())
        rr = report.get("verified_risk_report") or report.get("risk_report") or {}
        evidence_links_final_report.append(len(rr.get("claim_support") or []))
    mean_evidence_links_shacl_triggered = (
        round(sum(evidence_links_final_report) / len(evidence_links_final_report), 2)
        if evidence_links_final_report else None
    )

    schema_parse_failures = sum(1 for e in events if e.get("planner_parse_status") not in ("parsed", None))
    illegal_transitions = sum(1 for e in events if e.get("rejection_reason") == "illegal_state_transition")
    second_revision_blocked = sum(1 for e in events if e.get("rejection_reason") == "revision_limit_exhausted")

    opa_before = sum(len(e.get("opa_actions") or []) for e in events if e.get("accepted_action") == "synthesize")
    opa_after = sum(len(e.get("opa_actions") or []) for e in events if e.get("accepted_action") == "revise")

    return {
        "model": model,
        "n": n,
        "completions": completions,
        "real_generation_events": real_generation,
        "fallback_events": fallback_events,
        "mock_events": mock_events,
        "revise_attempted": revise_attempted,
        "revise_shacl_triggered": revise_shacl,
        "revise_opa_only": revise_opa_only,
        "revise_both_shacl_and_opa": None,  # not separately distinguishable from current row schema; see note
        "changed_output_shacl_triggered": changed_shacl,
        "changed_output_opa_only": changed_opa_only,
        "changed_output_any": changed_any,
        "changed_rate_shacl_triggered": round(changed_shacl / revise_shacl, 4) if revise_shacl else None,
        "changed_rate_opa_only": round(changed_opa_only / revise_opa_only, 4) if revise_opa_only else None,
        "residual_shacl_violations_final_event": residual_shacl,
        "mean_evidence_links_final_report_shacl_triggered": mean_evidence_links_shacl_triggered,
        "schema_or_parse_failures": schema_parse_failures,
        "illegal_state_transitions_blocked": illegal_transitions,
        "second_revision_attempts_blocked": second_revision_blocked,
        "opa_actions_count_on_synthesize_events": opa_before,
        "opa_actions_count_on_revise_events": opa_after,
        "campaign_dir": str(campaign_dir),
        "campaign_dir_sha256_manifest": sha(campaign_dir / "run_manifest.jsonl"),
        "campaign_dir_sha256_summary": sha(campaign_dir / "summary.json"),
    }


def main() -> None:
    all_metrics = [metrics_for(model, path) for model, path in CAMPAIGNS.items()]

    (OUT_DIR / "cross_series_metrics.json").write_text(json.dumps(all_metrics, indent=2))

    csv_cols = [
        "model", "n", "completions", "real_generation_events", "fallback_events", "mock_events",
        "revise_attempted", "revise_shacl_triggered", "revise_opa_only",
        "changed_output_shacl_triggered", "changed_output_opa_only", "changed_output_any",
        "changed_rate_shacl_triggered", "changed_rate_opa_only",
        "residual_shacl_violations_final_event", "mean_evidence_links_final_report_shacl_triggered",
        "schema_or_parse_failures", "illegal_state_transitions_blocked", "second_revision_attempts_blocked",
        "opa_actions_count_on_synthesize_events", "opa_actions_count_on_revise_events",
    ]
    lines = [",".join(csv_cols)]
    for m in all_metrics:
        lines.append(",".join(str(m[c]) for c in csv_cols))
    (OUT_DIR / "cross_series_table.csv").write_text("\n".join(lines) + "\n")

    tex_lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\hline",
        r"\textbf{Model} & \textbf{Revise att.} & \textbf{SHACL-trig.} & \textbf{OPA-only} & "
        r"\textbf{Changed|SHACL} & \textbf{Changed|OPA-only} \\",
        r"\hline",
    ]
    for m in all_metrics:
        cs = f"{m['changed_output_shacl_triggered']}/{m['revise_shacl_triggered']}" if m["revise_shacl_triggered"] else "0/0"
        co = f"{m['changed_output_opa_only']}/{m['revise_opa_only']}" if m["revise_opa_only"] else "0/0"
        tex_lines.append(
            f"{m['model']} & {m['revise_attempted']}/{m['n']} & {m['revise_shacl_triggered']}/{m['n']} & "
            f"{m['revise_opa_only']}/{m['n']} & {cs} & {co} \\\\"
        )
    tex_lines += [r"\hline", r"\end{tabular}"]
    (OUT_DIR / "cross_series_table.tex").write_text("\n".join(tex_lines) + "\n")

    # Manual audit: up to 3 SHACL-triggered revisions per model that changed the
    # output, with the pre-revision SHACL finding and the post-revision resolution.
    audit = []
    for model, campaign_dir in CAMPAIGNS.items():
        rows = load_rows(campaign_dir)
        cases = [
            r for r in rows
            if r["revise_triggered_by_shacl"] and r["revision_changed_output"]
        ][:3]
        for r in cases:
            sid = r["scenario_id"]
            trace_path = campaign_dir / "traces" / f"{sid}.jsonl"
            events = [
                json.loads(l) for l in trace_path.read_text().splitlines()
                if l.strip() and json.loads(l).get("record_type") == "event"
            ]
            revise_event = next(e for e in events if e.get("accepted_action") == "revise")
            events_sorted = sorted(events, key=lambda e: e["step_index"])
            last_event = events_sorted[-1]
            audit.append({
                "model": model,
                "scenario_id": sid,
                "shacl_finding_before_revision": revise_event.get("shacl_findings"),
                "shacl_findings_after_final_event": last_event.get("shacl_findings"),
                "termination_reason": r["termination_reason"],
            })
    (OUT_DIR / "manual_audit_shacl_revisions.json").write_text(json.dumps(audit, indent=2))

    print(json.dumps(all_metrics, indent=2))
    print("\n--- manual audit (SHACL-triggered, output changed) ---")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
