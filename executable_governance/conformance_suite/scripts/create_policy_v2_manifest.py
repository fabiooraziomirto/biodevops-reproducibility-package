#!/usr/bin/env python3
"""Write a v2 policy-change provenance record without modifying the v1 freeze."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]
REPO = SUITE.parent
V1 = SUITE / "labels" / "LABEL_FREEZE_v1.json"
V2 = SUITE / "labels" / "POLICY_CHANGE_v2.json"

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

payload = {
    "version": "v2",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "parent_label_freeze": str(V1.relative_to(REPO)),
    "parent_label_freeze_sha256": digest(V1),
    "case_bank_sha256": digest(SUITE / "cases" / "arrhythmia_factorial_v1.jsonl"),
    "labels_sha256": digest(SUITE / "labels" / "labels_v1.jsonl"),
    "policy_sha256": digest(REPO / "policies" / "risk_report_policy.rego"),
    "adapter_sha256": digest(REPO / "scripts" / "opa_policy.py"),
    "change_rationale": "Targeted FC-04-04 fix: FSCA downgrade now requires an exact confirmed-basis allowlist phrase. This narrows matching to exact phrases and is not a general paraphrase-robustness improvement.",
    "scope": "Only the arrhythmia risk-report FSCA confirmed-basis predicate; frozen cases and labels are unchanged.",
}
V2.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(V2)
