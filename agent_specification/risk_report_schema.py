"""
RiskReport schema — the structured output contract for the BioDevOps RAG agent.

This schema is the single source of truth for:
  1. The JSON Schema passed to Ollama's `format` parameter (forces
     schema-conformant structured output natively, no manual JSON parsing
     of free text).
  2. The Pydantic model used to validate/parse the parsed response and to
     run downstream checks (e.g. hallucination detection against the
     synthetic artifact store).

Design rationale (for paper Section IV.D / RAG agent architecture):
- Severity and Confidence are kept as SEPARATE fields. Conflating them
  (e.g. a single "risk score") would hide exactly the failure mode the
  evaluation cares about: a confidently-wrong high-severity call is a
  different failure than a correctly-uncertain one. Keeping them
  orthogonal lets the evaluation report exploratory routing calibration
  (confidence vs. correctness) independently of severity accuracy.
- EvidenceLinks is a list of typed references, not free text, specifically
  so that hallucination rate can be computed mechanically: a generated
  EvidenceLink whose `artifact_id` is not in the known artifact store is
  unambiguously a hallucination, no judgment call required.
- Recommendation is a closed enum (not free text) matching the
  ground_truth_recommendation vocabulary already used in
  synthetic_maude_arrhythmia.json, so generated reports can be scored
  against ground truth without fuzzy string matching.
- rationale is intentionally short free text — kept for human review /
  qualitative error analysis, but explicitly NOT used as a scored field,
  to avoid rewarding verbose plausible-sounding text over correct
  structured judgments.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RecommendationEnum(str, Enum):
    NO_ACTION = "NO_ACTION"
    MONITOR = "MONITOR"
    CAPA_INVESTIGATE = "CAPA_INVESTIGATE"
    FIELD_SAFETY_CORRECTIVE_ACTION = "FIELD_SAFETY_CORRECTIVE_ACTION"
    ESCALATE_TO_HUMAN_IMMEDIATE = "ESCALATE_TO_HUMAN_IMMEDIATE"


class ClaimSupportStatus(str, Enum):
    SUPPORTED = "supported"
    WEAKLY_SUPPORTED = "weakly_supported"
    UNSUPPORTED = "unsupported"


class EvidenceLink(BaseModel):
    artifact_id: str = Field(
        description="Exact ID of a retrieved artifact or regulatory extract "
                     "this claim is grounded in. Must match an ID actually "
                     "returned by retrieval — never invent an ID."
    )
    artifact_type: str = Field(
        description="One of: code_diff, test_log, static_analysis_output, "
                     "deployment_log, regulatory_extract, incident_report"
    )
    relevance_note: str = Field(
        description="One short sentence on why this artifact supports the "
                     "RiskReport's severity/recommendation judgment."
    )


class ClaimSupport(BaseModel):
    claim: str = Field(
        description="One safety, technical, or regulatory claim made in the "
                    "RiskReport rationale."
    )
    cited_artifact_id: str = Field(
        description="The retrieved ID that supports this claim, copied exactly "
                    "from evidence_links. Use an empty string only when no "
                    "retrieved evidence supports the claim."
    )
    support_status: ClaimSupportStatus = Field(
        description="Whether the cited artifact directly supports, weakly "
                    "supports, or does not support the claim."
    )
    support_note: str = Field(
        description="Short explanation of the support judgment, used by the "
                    "symbolic verifier and human reviewer."
    )


class RiskReport(BaseModel):
    # This is an advisory-only contract.  Reject, rather than silently ignore,
    # a future field that could smuggle execution or release authority into an
    # agent-produced report.
    model_config = ConfigDict(extra="forbid")

    severity: int = Field(
        ge=1, le=4,
        description="1=no harm/nuisance, 2=minor harm, 3=serious harm "
                     "(meets EU MDR Article 87 'serious incident' threshold), "
                     "4=death or life-threatening."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Exploratory routing confidence (0-1) in the severity and "
                     "recommendation judgments, NOT a validated clinical "
                     "probability or surface-fluency score. Should be lower "
                     "when evidence is sparse, contradictory, or distractor "
                     "artifacts were excluded."
    )
    evidence_links: list[EvidenceLink] = Field(
        default_factory=list,
        description="All retrieved artifacts actually used to ground this "
                     "report. Empty list is valid and preferred over "
                     "fabricated links if nothing relevant was retrieved."
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence still needed before a high-impact escalation "
                    "such as field safety corrective action can be justified "
                    "(e.g. recurrence, deployed population impact, causality)."
    )
    claim_support: list[ClaimSupport] = Field(
        default_factory=list,
        description="Per-claim grounding assessment. Citation validity only "
                    "checks whether an ID exists; claim_support captures "
                    "whether the cited item actually supports the claim."
    )
    requires_human_review: bool = Field(
        default=False,
        description="Whether the report must be routed to authorized human "
                    "review before any governance action is accepted."
    )
    recommendation: RecommendationEnum
    rationale: str = Field(
        description="1-3 sentence plain-language justification, for human "
                     "reviewer context only — not used as a scored field "
                     "in the quantitative evaluation."
    )


def get_ollama_json_schema() -> dict:
    """
    Returns the JSON Schema dict to pass as `format=` to ollama.chat(),
    forcing the model to emit schema-conformant JSON natively (supported
    by Ollama >= 0.5 for tool/structured-output-capable models such as
    llama3.1, qwen2.5, mistral-nemo).
    """
    return RiskReport.model_json_schema()
