# Arrhythmia factorial conformance rubric v1

This 48-row, LLM-free suite tests conformance to a governance rubric, not clinical diagnostic accuracy or generator defect prevalence. OPA positives are a deny, policy action, or recommendation override; the policy's mandatory default human-review field alone is excluded. SHACL-side positives are nonconformance results excluding informational messages.

OPA labels use only the report, narrative, retrieval context, citation resolution, and claim-support view. SHACL-side labels use the report plus curated FHIR/clinical facts. Inapplicable guard/class combinations are `not_applicable`, not negative observations.

The label freeze is a single-author fallback: cases and labels are hashed before execution. This prevents outcome-driven relabeling but does not provide independent clinical adjudication or remove policy-author/case-author overlap. A two-person study should use a policy-blind second annotator and retain initial labels, disagreements, and adjudications.

Malformed and irrelevant FHIR risk-tag extensions are rubric violations even where the current validator only checks extension presence. Such accepted rows are intentionally retained as false negatives that justify a targeted 16-row expansion of that class.
