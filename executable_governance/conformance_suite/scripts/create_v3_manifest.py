#!/usr/bin/env python3
"""Write immutable provenance for the combined post-FSCA/post-FHIR run."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
SUITE=Path(__file__).resolve().parents[1]; REPO=SUITE.parent
def d(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
paths={
 "v1_freeze": SUITE/'labels/LABEL_FREEZE_v1.json', "v2_policy_change": SUITE/'labels/POLICY_CHANGE_v2.json',
 "class9_supplement": SUITE/'labels/CLASS9_SUPPLEMENT_v1.json', "v1_case_bank": SUITE/'cases/arrhythmia_factorial_v1.jsonl',
 "v1_labels": SUITE/'labels/labels_v1.jsonl', "class9_case_bank": SUITE/'cases/class9_technical_evidence_v1.jsonl',
 "class9_labels": SUITE/'labels/class9_technical_evidence_labels_v1.jsonl', "rego_policy": REPO/'policies/risk_report_policy.rego',
 "opa_adapter": REPO/'scripts/opa_policy.py', "shacl_adapter": REPO/'scripts/ontology_validate.py', "shacl_shape": REPO/'ontology/biodevops_clinical.ttl',
}
payload={"version":"v3_final","created_at_utc":datetime.now(timezone.utc).isoformat(),"sha256":{k:d(v) for k,v in paths.items()},"change_rationale":"Adds an exact clinical-risk-tag URL plus curated valueCode allowlist check to repair FC-05-03 and FC-05-04 while preserving existing curated FHIR fragments. This is not a general FHIR-extension semantic validator or a robustness claim for paraphrased/alternative extension encodings.","scope":"Combined 54-row execution using frozen v1 cases/labels, frozen Class-9 supplement, v2 OPA policy, and the targeted SHACL-side FHIR extension fix.","supersedes":"POLICY_CHANGE_v3.json (pre-final single-value allowlist candidate retained for provenance; not used for final results)."}
(SUITE/'labels/POLICY_CHANGE_v3_final.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
