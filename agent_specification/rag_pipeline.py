"""
BioDevOps RAG Agent — RAG + LLM RiskReport Pipeline (Ollama backend)
======================================================================

Given an input artifact (a code diff, test log, static analysis output, or
incident narrative), this pipeline:
  1. Retrieves relevant regulatory extracts (FDA QMSR / EU MDR) and any
     related synthetic artifacts from the Chroma vector store built by
     ingest_corpus.py.
  2. Builds a grounded prompt containing ONLY the retrieved context (no
     reliance on the LLM's parametric/training-time knowledge of medical
     device regulation, by design — this is the point of the RAG
     architecture for an evidence-mediated governance claim).
  3. Calls a local Ollama model with `format=<RiskReport JSON schema>` to
     force schema-conformant structured output.
  4. Validates the response with Pydantic and runs an automatic
     hallucination check: any cited evidence_links.artifact_id that does
     NOT appear in the retrieved context set is flagged as a hallucinated
     citation.

BACKEND: Ollama only, by design (see project decision log). No external
API calls. Requires a running local Ollama server (`ollama serve`) with a
structured-output-capable model pulled, e.g.:
    ollama pull llama3.1
    ollama pull qwen2.5

*** SANDBOX NOTE ***
This sandbox cannot reach the Ollama installer or run a local Ollama
server (no GPU/model runtime, restricted egress). OllamaClientWrapper
below talks to the real `ollama` Python client and a real local server
when one is available (host machine), and transparently falls back to
MockOllamaClient — a deterministic stand-in that returns a
schema-valid-but-not-semantically-grounded RiskReport — when no server is
reachable, purely so this script's plumbing (retrieval -> prompt ->
parse -> hallucination check) can be exercised end-to-end here. Set
FORCE_MOCK = False and run with a real `ollama serve` + pulled model on
your machine to get real generations; no other code changes needed.
"""

import json
import os
from pathlib import Path
from functools import lru_cache

import chromadb
import ollama
from pydantic import ValidationError

from risk_report_schema import RiskReport, get_ollama_json_schema
from symbolic_verifier import (
    normalize_cited_id,
    valid_context_ids,
    verify_risk_report,
)
from ontology_validate import load_clinical_mapping, validate_case

DB_DIR = Path(os.getenv("BIODEVOPS_CHROMA_DB", Path(__file__).parent.parent / "chroma_db"))
OLLAMA_MODEL = "llama3.2:3b"  # change to any locally-pulled structured-output-capable model
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("BIODEVOPS_OLLAMA_TIMEOUT_SECONDS", "20"))
# Default False for local/your-machine use (requires `ollama serve` running
# with a pulled model — see README.md). Set to True only to smoke-test the
# pipeline's plumbing without a real Ollama server reachable.
FORCE_MOCK = os.getenv("BIODEVOPS_FORCE_MOCK", "0") in {"1", "true", "True"}
NO_MOCK_FALLBACK = os.getenv("BIODEVOPS_NO_MOCK_FALLBACK", "0") in {"1", "true", "True"}


# ---------------------------------------------------------------------------
# Embedder: reuse the same placeholder-or-real switch as ingest_corpus.py.
# Retrieval and generation must use embeddings consistent with what was used
# to build the index, so we keep this logic identical and import-light
# rather than re-implementing it.
# ---------------------------------------------------------------------------
import importlib.util

_ingest_spec = importlib.util.spec_from_file_location(
    "ingest_corpus", Path(__file__).parent / "ingest_corpus.py"
)
_ingest_module = importlib.util.module_from_spec(_ingest_spec)
_ingest_spec.loader.exec_module(_ingest_module)

PlaceholderHashEmbedder = _ingest_module.PlaceholderHashEmbedder
USE_REAL_EMBEDDINGS = _ingest_module.USE_REAL_EMBEDDINGS


def get_embedder():
    if USE_REAL_EMBEDDINGS:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(_ingest_module.EMBEDDING_MODEL_NAME)
    return PlaceholderHashEmbedder()


# ---------------------------------------------------------------------------
# Ollama client wrapper with mock fallback
# ---------------------------------------------------------------------------
class MockOllamaClient:
    """
    Deterministic stand-in for a real Ollama server, used only when no
    server is reachable (e.g. this sandbox). Returns a schema-valid
    RiskReport built directly from whatever context was retrieved, so the
    surrounding pipeline logic (parsing, hallucination check, scoring) can
    be exercised honestly even though the "judgment" itself is a fixed
    placeholder rather than a real LLM inference.
    """

    def chat(self, model: str, messages: list[dict], format: dict, options: dict | None = None):
        context_text = messages[-1]["content"]
        # Naively pull any artifact/extract IDs visible in the prompt context
        # and echo back the FIRST one as a fabricated demonstration of
        # correct grounding behavior. This is intentionally simplistic.
        mock_body = {
            "severity": 3,
            "confidence": 0.55,
            "evidence_links": [],
            "missing_evidence": [
                "A real LLM judgment was not available in this environment."
            ],
            "claim_support": [],
            "requires_human_review": True,
            "recommendation": "CAPA_INVESTIGATE",
            "rationale": "[MOCK OLLAMA RESPONSE — no real LLM reachable in this "
                          "sandbox. This placeholder demonstrates schema-valid "
                          "output shape only; it is not a real risk judgment. "
                          "Run with a live `ollama serve` + pulled model for "
                          "actual generations.]",
        }

        class _Message:
            def __init__(self, content):
                self.content = content

        class _Response:
            def __init__(self, content):
                self.message = _Message(content)

        return _Response(json.dumps(mock_body))


class OllamaUnavailableError(RuntimeError):
    """Raised when a strict run requires real Ollama generation."""


def get_ollama_client():
    if FORCE_MOCK:
        print("  [FORCE_MOCK=True] Using MockOllamaClient — see module docstring.")
        return MockOllamaClient()
    try:
        client = ollama.Client(timeout=OLLAMA_TIMEOUT_SECONDS)
        client.list()  # cheap call to confirm a server is actually reachable
        return client
    except Exception as e:
        if NO_MOCK_FALLBACK:
            raise OllamaUnavailableError(
                f"Could not reach a local Ollama server and mock fallback is disabled: {e}"
            ) from e
        print(f"  Could not reach a local Ollama server ({e}); falling back to MockOllamaClient.")
        return MockOllamaClient()


@lru_cache(maxsize=4)
def _clinical_mapping(path: str):
    """Load a versioned clinical-facts bundle once per process."""
    return load_clinical_mapping(Path(path))


def run_clinical_guard(report: RiskReport, case_id: str, facts_path: str | Path) -> dict:
    """Validate a governed report against an explicit, versioned facts bundle.

    This guard is opt-in: production callers must supply both the case identifier
    and the facts bundle. It never infers clinical facts from the generated prose.
    A nonconformant result routes the report to review and is returned as a
    structured audit record.
    """
    facts_path = Path(facts_path).resolve()
    row = {
        "report_id": case_id,
        "base_scenario_id": case_id,
        "predicted_severity": report.severity,
        "predicted_recommendation": report.recommendation.value,
        "policy_actions": "",
        "retrieved_artifacts": [link.artifact_id for link in report.evidence_links],
    }
    result = validate_case(row, _clinical_mapping(str(facts_path)))
    return {
        "bundle_path": str(facts_path),
        "case_id": case_id,
        "conforms": result["ontology_conforms"],
        "clinical_inconsistency_class": result["clinical_inconsistency_class"],
        "violations": result["violations"],
    }


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def retrieve_context(
    query_text: str,
    embedder,
    n_regulatory: int = 4,
    n_artifacts: int = 4,
) -> dict:
    """Retrieve top-k regulatory extracts and top-k synthetic artifacts for a query."""
    client = chromadb.PersistentClient(path=str(DB_DIR))
    reg_collection = client.get_collection("regulatory_corpus")
    art_collection = client.get_collection("synthetic_artifacts")

    query_embedding = embedder.encode([query_text]).tolist()

    reg_results = reg_collection.query(query_embeddings=query_embedding, n_results=n_regulatory)
    art_results = art_collection.query(query_embeddings=query_embedding, n_results=n_artifacts)

    regulatory_hits = [
        {"id": doc_id, "text": doc, "metadata": meta}
        for doc_id, doc, meta in zip(
            reg_results["ids"][0], reg_results["documents"][0], reg_results["metadatas"][0]
        )
    ]
    artifact_hits = [
        {"id": doc_id, "text": doc, "metadata": meta}
        for doc_id, doc, meta in zip(
            art_results["ids"][0], art_results["documents"][0], art_results["metadatas"][0]
        )
    ]
    return {"regulatory": regulatory_hits, "artifacts": artifact_hits}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
PROMPT_CONDITIONS = {
    "baseline": {
        "include_rubric": False,
        "include_fewshot": False,
        "include_id_typo_warning": False,
    },
    "rubric_only": {
        "include_rubric": True,
        "include_fewshot": False,
        "include_id_typo_warning": False,
    },
    "fewshot_only": {
        "include_rubric": False,
        "include_fewshot": True,
        "include_id_typo_warning": False,
    },
    "id_typo_only": {
        "include_rubric": False,
        "include_fewshot": False,
        "include_id_typo_warning": True,
    },
    "all_combined": {
        "include_rubric": True,
        "include_fewshot": True,
        "include_id_typo_warning": True,
    },
}

BASE_SYSTEM_PROMPT_PREFIX = """You are a regulatory risk-assessment assistant for a medical device \
DevOps pipeline (BioDevOps). You are given an incident narrative or development artifact, \
plus retrieved regulatory context (FDA QMSR / EU MDR extracts) and retrieved supporting \
artifacts (code diffs, test logs, static analysis output, deployment logs).

Each retrieved item below is shown as:
    ID: <exact_id>
    (other metadata)
    <content>

When you cite an item in evidence_links, set artifact_id to EXACTLY the value that follows \
"ID:" — copy it verbatim, as a bare string with no brackets, no prefix such as "ARTIFACT:" \
or "REGULATORY:", and no surrounding punctuation. For example, if you see "ID: ARTIFACT-TESTLOG-0050", \
the correct artifact_id value is ARTIFACT-TESTLOG-0050, not [ARTIFACT:ARTIFACT-TESTLOG-0050] \
and not "ARTIFACT-TESTLOG-0050" with quotes.
"""

ID_TYPO_WARNING_BLOCK = """Pay close attention to exact spelling when copying IDs. Do not introduce typos such as \
changing ARTIFACT to ARTIFECT; a misspelled ID is an unresolved citation even if it \
looks similar to a retrieved ID.
"""

BASE_SYSTEM_PROMPT_MIDDLE = """Ground EVERY claim in the provided context. Do NOT use any artifact_id in evidence_links \
that does not appear after an "ID:" label below — fabricating a citation is a severe failure \
mode. If nothing retrieved is relevant, return an empty evidence_links list rather than \
inventing a plausible-sounding one.

For technical incidents or development artifacts, cite at least one technical artifact \
(code_diff, test_log, static_analysis_output, deployment_log, or incident_report) when \
one was retrieved and relevant. Regulatory extracts alone are not enough to ground a \
technical causality or validation judgment.

Do NOT say "violation of regulation X" unless the retrieved text explicitly supports \
that legal conclusion. Prefer "may trigger obligations under X" or "requires review \
under X" when the evidence is incomplete.

Distinguish CAPA investigation from field safety corrective action. Use \
FIELD_SAFETY_CORRECTIVE_ACTION only when the retrieved evidence supports confirmed \
recurrence, deployed-population impact, serious risk, recall/withdrawal, or an explicit \
FSCA obligation. Otherwise use CAPA_INVESTIGATE or ESCALATE_TO_HUMAN_IMMEDIATE and list \
the missing evidence.
"""

SEVERITY_RUBRIC_BLOCK = """Severity rubric:
- Severity 1: no patient exposure or patient-safety impact; the issue was blocked or \
  contained by an automatic control before clinical deployment or use.
- Severity 2: low or moderate patient-safety concern, nuisance alerting, recoverable \
  degradation, or technical issue needing monitoring/investigation, without clear \
  potential for serious harm.
- Severity 3: serious potential patient-safety risk, including failure or missed \
  detection in a safety-critical function that might have led to serious harm, even if \
  no harm actually occurred in the reported event.
- Severity 4: realized serious harm, death, broad deployed-population exposure to a \
  serious risk, recurrence with serious impact, or evidence supporting immediate field \
  safety action or human escalation.

When assigning severity, consider three dimensions separately: (a) harm actually \
realized, (b) potential harm if the event had evolved differently, and (c) containment \
status, including whether the event reached a patient or was blocked by an automatic \
control before exposure. An event can be high severity because of serious potential harm \
in a safety-critical function even when no injury occurred. Conversely, a technical \
regression successfully blocked before any patient exposure should be severity 1, even \
if the underlying engineering issue is real and may be handled separately by CI quality \
controls.
"""

CGM_SEVERITY_RUBRIC_BLOCK = """Severity rubric (clinical-harm scale for continuous glucose monitoring / \
insulin-dosing safety events):
- Severity 1: no harm and routine monitoring only — a normal or expected glucose pattern, \
  or an issue caught and fully resolved with no documented patient-facing exposure and no \
  gap in glucose visibility or alerting.
- Severity 2: minor harm or process exposure risk — a real technical or process issue \
  (e.g. a defect caught pre-release, a brief and fully corroborated sensor discrepancy) \
  that carried no meaningful gap in glucose visibility, alerting, or clinical decision-making, \
  and no plausible path to a missed hypo/hyperglycemic event.
- Severity 3: serious harm or a clinically serious event — any device/process problem that \
  created a real gap in glucose visibility, alerting, or clinical decision-making during \
  which a clinically significant glucose excursion could have gone undetected or \
  unconfirmed, EVEN IF the narrative does not explicitly state that harm occurred. This \
  includes: sensor dropout or failure during which no confirmatory glucose evidence was \
  available, conflicting or discordant glucose observations left unresolved, missing \
  evidence needed to rule out a hypo/hyperglycemic event, citation/traceability failures \
  in a safety-relevant judgment, and post-market drift indicating a systematic prediction \
  problem. Do not downgrade these to severity 2 merely because the narrative does not use \
  the word "harm" — a documented gap in glucose safety monitoring is itself the serious event.
- Severity 4: death or a life-threatening event — severe hypoglycemia (e.g. glucose at or \
  below the low-50s mg/dL or lower), loss of consciousness, a hypoglycemic event requiring \
  caregiver-administered glucagon or emergency treatment, or broad deployed-population \
  exposure to a serious risk. If the narrative documents a confirmed severe hypoglycemia or \
  loss-of-consciousness event, the severity is 4 regardless of how the incident was \
  ultimately contained or resolved afterward.

When assigning severity, weigh whether patient-facing glucose safety monitoring or alerting \
was actually compromised during the event window, not only whether harm was explicitly \
narrated. A sensor failure, conflicting reading, or missing-evidence gap during which a \
dangerous glucose excursion could have been missed is a serious event (severity 3) even \
when the narrative does not state that harm occurred, because CGM/insulin-dosing safety \
depends on continuous, reliable glucose visibility.
"""

CGM_CONTROL_GATE_FEWSHOT_BLOCK = """Few-shot control example for a genuinely low-risk CGM event:

Input example: A routine glucose trace shows values within the normal range for the full \
monitoring window, with no missed alerts, no sensor gaps, and no conflicting observations.

Correct output pattern: severity=1, recommendation=NO_ACTION, requires_human_review=true \
(structural human-review requirement applies regardless of severity). Rationale: the \
glucose trace and alerting behavior were normal for the full window; there was no gap in \
glucose visibility and no plausible missed safety event.

Few-shot example for a device/process gap that should NOT be downgraded to severity 2:

Input example: The sensor experienced a signal dropout lasting several minutes, and no \
confirmatory glucose evidence (meter, lab, or otherwise) was available for that window. The \
narrative does not state that the patient was harmed.

Correct output pattern: severity=3. Rationale: even though no harm is explicitly narrated, \
the dropout created a real gap in glucose visibility during which a hypoglycemic or \
hyperglycemic event could have gone undetected — that gap itself is the serious event, not \
a minor monitoring nuisance.
"""

BASE_SYSTEM_PROMPT_SUFFIX = """Populate claim_support with one entry for each safety, technical, or regulatory claim \
in the rationale. Mark an ID as weakly_supported when it is real but only indirectly \
supports the claim.

Be conservative with confidence: lower confidence when evidence is sparse, contradictory, \
or when you are relying on general reasoning rather than a specific retrieved item.
"""

CONTROL_GATE_FEWSHOT_BLOCK = """Few-shot control example for pre-deployment containment:

Input example: A synthetic telemetry classifier change reduced sensitivity in an internal \
validation test. The CI/CD quality gate detected the regression, blocked the release, \
and the candidate build was never deployed to any clinical environment. No patient was \
exposed and no clinical alert was missed in use.

Correct output pattern: severity=1, recommendation=NO_ACTION, requires_human_review=false. \
Rationale: the safety control worked as intended; the regression is a real technical \
quality finding, but it was contained before clinical deployment and caused no patient \
exposure. Do not escalate severity merely because the blocked regression involved a \
safety-related classifier.
"""


def build_system_prompt(
    domain: str = "arrhythmia",
    include_rubric: bool = True,
    include_fewshot: bool = True,
    include_id_typo_warning: bool = True,
) -> str:
    blocks = [BASE_SYSTEM_PROMPT_PREFIX]
    if include_id_typo_warning:
        blocks.append(ID_TYPO_WARNING_BLOCK)
    blocks.append(BASE_SYSTEM_PROMPT_MIDDLE)
    if include_rubric:
        blocks.append(CGM_SEVERITY_RUBRIC_BLOCK if domain == "cgm" else SEVERITY_RUBRIC_BLOCK)
    blocks.append(BASE_SYSTEM_PROMPT_SUFFIX)
    if include_fewshot:
        blocks.append(CGM_CONTROL_GATE_FEWSHOT_BLOCK if domain == "cgm" else CONTROL_GATE_FEWSHOT_BLOCK)
    return "\n".join(blocks)


def build_system_prompt_for_condition(prompt_condition: str, domain: str = "arrhythmia") -> str:
    if prompt_condition not in PROMPT_CONDITIONS:
        valid = ", ".join(sorted(PROMPT_CONDITIONS))
        raise ValueError(f"Unknown prompt condition {prompt_condition!r}; expected one of: {valid}")
    return build_system_prompt(domain=domain, **PROMPT_CONDITIONS[prompt_condition])


SYSTEM_PROMPT = build_system_prompt_for_condition("all_combined")

_LEGACY_COMBINED_SYSTEM_PROMPT = """You are a regulatory risk-assessment assistant for a medical device \
DevOps pipeline (BioDevOps). You are given an incident narrative or development artifact, \
plus retrieved regulatory context (FDA QMSR / EU MDR extracts) and retrieved supporting \
artifacts (code diffs, test logs, static analysis output, deployment logs).

Each retrieved item below is shown as:
    ID: <exact_id>
    (other metadata)
    <content>

When you cite an item in evidence_links, set artifact_id to EXACTLY the value that follows \
"ID:" — copy it verbatim, as a bare string with no brackets, no prefix such as "ARTIFACT:" \
or "REGULATORY:", and no surrounding punctuation. For example, if you see "ID: ARTIFACT-TESTLOG-0050", \
the correct artifact_id value is ARTIFACT-TESTLOG-0050, not [ARTIFACT:ARTIFACT-TESTLOG-0050] \
and not "ARTIFACT-TESTLOG-0050" with quotes.

Pay close attention to exact spelling when copying IDs. Do not introduce typos such as \
changing ARTIFACT to ARTIFECT; a misspelled ID is an unresolved citation even if it \
looks similar to a retrieved ID.

Ground EVERY claim in the provided context. Do NOT use any artifact_id in evidence_links \
that does not appear after an "ID:" label below — fabricating a citation is a severe failure \
mode. If nothing retrieved is relevant, return an empty evidence_links list rather than \
inventing a plausible-sounding one.

For technical incidents or development artifacts, cite at least one technical artifact \
(code_diff, test_log, static_analysis_output, deployment_log, or incident_report) when \
one was retrieved and relevant. Regulatory extracts alone are not enough to ground a \
technical causality or validation judgment.

Do NOT say "violation of regulation X" unless the retrieved text explicitly supports \
that legal conclusion. Prefer "may trigger obligations under X" or "requires review \
under X" when the evidence is incomplete.

Distinguish CAPA investigation from field safety corrective action. Use \
FIELD_SAFETY_CORRECTIVE_ACTION only when the retrieved evidence supports confirmed \
recurrence, deployed-population impact, serious risk, recall/withdrawal, or an explicit \
FSCA obligation. Otherwise use CAPA_INVESTIGATE or ESCALATE_TO_HUMAN_IMMEDIATE and list \
the missing evidence.

Severity rubric:
- Severity 1: no patient exposure or patient-safety impact; the issue was blocked or \
  contained by an automatic control before clinical deployment or use.
- Severity 2: low or moderate patient-safety concern, nuisance alerting, recoverable \
  degradation, or technical issue needing monitoring/investigation, without clear \
  potential for serious harm.
- Severity 3: serious potential patient-safety risk, including failure or missed \
  detection in a safety-critical function that might have led to serious harm, even if \
  no harm actually occurred in the reported event.
- Severity 4: realized serious harm, death, broad deployed-population exposure to a \
  serious risk, recurrence with serious impact, or evidence supporting immediate field \
  safety action or human escalation.

When assigning severity, consider three dimensions separately: (a) harm actually \
realized, (b) potential harm if the event had evolved differently, and (c) containment \
status, including whether the event reached a patient or was blocked by an automatic \
control before exposure. An event can be high severity because of serious potential harm \
in a safety-critical function even when no injury occurred. Conversely, a technical \
regression successfully blocked before any patient exposure should be severity 1, even \
if the underlying engineering issue is real and may be handled separately by CI quality \
controls.

Populate claim_support with one entry for each safety, technical, or regulatory claim \
in the rationale. Mark an ID as weakly_supported when it is real but only indirectly \
supports the claim.

Be conservative with confidence: lower confidence when evidence is sparse, contradictory, \
or when you are relying on general reasoning rather than a specific retrieved item.

Few-shot control example for pre-deployment containment:

Input example: A synthetic telemetry classifier change reduced sensitivity in an internal \
validation test. The CI/CD quality gate detected the regression, blocked the release, \
and the candidate build was never deployed to any clinical environment. No patient was \
exposed and no clinical alert was missed in use.

Correct output pattern: severity=1, recommendation=NO_ACTION, requires_human_review=false. \
Rationale: the safety control worked as intended; the regression is a real technical \
quality finding, but it was contained before clinical deployment and caused no patient \
exposure. Do not escalate severity merely because the blocked regression involved a \
safety-related classifier.
"""

assert SYSTEM_PROMPT == _LEGACY_COMBINED_SYSTEM_PROMPT


def build_revision_feedback_block(policy_actions: list[str], missing_evidence: list[str],
                                   shacl_violations: list[dict]) -> str:
    """Serialize OPA and SHACL findings from a prior attempt into a compact,
    planner/model-readable feedback block used only on a `revise` transition.

    This is new: the historical pipeline re-generated an identical prompt on
    revise, carrying no information about *why* the governance layer asked
    for a revision, so "revise" could not distinguish an OPA-triggered
    request from a SHACL-triggered one, or change the output accordingly.
    """
    lines = []
    if policy_actions:
        lines.append("OPA policy actions from the previous attempt: " + "; ".join(policy_actions))
    if missing_evidence:
        lines.append("Missing or contradictory evidence flagged: " + "; ".join(missing_evidence))
    if shacl_violations:
        shacl_lines = [f"- ({v.get('shape', 'shacl')}) {v.get('message', '')}".strip() for v in shacl_violations]
        lines.append("Clinical SHACL/ontology violations against curated facts:\n" + "\n".join(shacl_lines))
    return "\n".join(lines)


def build_prompt(input_narrative: str, context: dict, revision_feedback: str = "") -> str:
    reg_block = "\n\n".join(
        f"ID: {hit['id']}\n(regulatory citation: {hit['metadata']['citation']})\n{hit['text']}"
        for hit in context["regulatory"]
    )
    art_block = "\n\n".join(
        f"ID: {hit['id']}\n(artifact type: {hit['metadata']['artifact_type']})\n{hit['text']}"
        for hit in context["artifacts"]
    )
    feedback_block = ""
    if revision_feedback:
        feedback_block = f"""

GOVERNANCE FEEDBACK FROM THE PREVIOUS ATTEMPT (this is a revision; the prior draft was not \
accepted as-is):
{revision_feedback}

Revise the report to resolve every item above. Do not repeat the same severity or \
recommendation unless it remains correct after considering this feedback.
"""
    return f"""INPUT ARTIFACT / INCIDENT NARRATIVE:
{input_narrative}

RETRIEVED REGULATORY CONTEXT:
{reg_block}

RETRIEVED ARTIFACTS:
{art_block}

Produce a RiskReport for the input artifact above, grounded strictly in the retrieved \
context. Every evidence_links entry must reference an artifact_id that is an EXACT, bare \
copy of a value that appears after "ID:" above — no brackets, no prefix, no quotes. \
Set requires_human_review=true for severity >= 3, confidence < 0.65, unsupported or \
weakly supported safety claims, or any recommendation stronger than CAPA_INVESTIGATE.{feedback_block}
"""


# ---------------------------------------------------------------------------
# Hallucination check
# ---------------------------------------------------------------------------
def _normalize_cited_id(raw_id: str) -> str:
    """
    Strip common formatting noise a model may add around a copied ID
    (brackets, a "REGULATORY:"/"ARTIFACT:" prefix it picked up from
    earlier prompt formats or from imitating other text, surrounding
    quotes/whitespace) before comparing against the known-valid ID set.

    This is a defense-in-depth normalization, not a substitute for fixing
    the prompt (see build_prompt's explicit "ID:" labeling and bare-copy
    instruction) — it exists so that pure formatting noise from the model
    does not inflate the measured hallucination rate with false positives
    that are not genuine fabricated citations. Any reported hallucination
    rate in the paper should state explicitly that this normalization is
    applied, since it changes what counts as a hallucination.
    """
    return normalize_cited_id(raw_id)


def check_hallucinated_citations(report: RiskReport, context: dict) -> list[str]:
    """
    Return the list of cited artifact_ids that were NOT actually retrieved,
    after normalizing common formatting noise (see _normalize_cited_id).
    Returned strings are the ORIGINAL (un-normalized) cited values, so the
    caller can see exactly what the model produced.
    """
    valid_ids = valid_context_ids(context)
    hallucinated = []
    for link in report.evidence_links:
        normalized = _normalize_cited_id(link.artifact_id)
        if normalized not in valid_ids:
            hallucinated.append(link.artifact_id)
    return hallucinated


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------
def generate_risk_report(
    input_narrative: str,
    ollama_model: str | None = OLLAMA_MODEL,
    embedder=None,
    ollama_client=None,
    context: dict | None = None,
    system_prompt: str | None = None,
    prompt_condition: str = "all_combined",
    domain: str = "arrhythmia",
    clinical_case_id: str | None = None,
    clinical_facts_path: str | Path | None = None,
    temperature: float = 0.1,
    seed: int | None = None,
    revision_feedback: str = "",
    think: bool | str | None = False,
) -> dict:
    if context is None:
        if embedder is None:
            embedder = get_embedder()
        context = retrieve_context(input_narrative, embedder)
    prompt = build_prompt(input_narrative, context, revision_feedback=revision_feedback)
    ollama_model = ollama_model or OLLAMA_MODEL
    if system_prompt is None:
        system_prompt = build_system_prompt_for_condition(prompt_condition, domain=domain)

    client = ollama_client or get_ollama_client()
    generation_source = "mock_fallback" if isinstance(client, MockOllamaClient) else "ollama_real"
    chat_kwargs = dict(
        model=ollama_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        format=get_ollama_json_schema(),
        options={"temperature": temperature, "num_predict": 4096, **({"seed": seed} if seed is not None else {})},
    )
    if think is not None and not isinstance(client, MockOllamaClient):
        chat_kwargs["think"] = think
    try:
        response = client.chat(**chat_kwargs)
    except Exception as e:
        if NO_MOCK_FALLBACK:
            raise OllamaUnavailableError(
                f"Ollama generation failed and mock fallback is disabled: {e}"
            ) from e
        print(f"  Ollama chat failed or timed out ({e}); falling back to MockOllamaClient.")
        generation_source = "mock_fallback"
        response = MockOllamaClient().chat(
            model=ollama_model,
            messages=chat_kwargs["messages"],
            format=get_ollama_json_schema(),
            options=chat_kwargs["options"],
        )

    raw_content = response.message.content
    try:
        report = RiskReport.model_validate_json(raw_content)
    except ValidationError as e:
        return {"error": f"Schema validation failed: {e}", "raw_content": raw_content}

    hallucinated = check_hallucinated_citations(report, context)
    verification = verify_risk_report(report, context, input_narrative, domain=domain)
    clinical_validation = None
    if (clinical_case_id is None) != (clinical_facts_path is None):
        raise ValueError("clinical_case_id and clinical_facts_path must be provided together")
    if clinical_case_id and clinical_facts_path:
        clinical_validation = run_clinical_guard(
            verification.verified_report, clinical_case_id, clinical_facts_path
        )
        if not clinical_validation["conforms"]:
            verification.verified_report.requires_human_review = True
            verification.policy_actions.append("clinical_shacl_nonconformance_routes_review")
            missing = "Clinical SHACL nonconformance requires human review."
            if missing not in verification.verified_report.missing_evidence:
                verification.verified_report.missing_evidence.append(missing)

    return {
        "input_narrative": input_narrative,
        "raw_content": raw_content,
        "model_token_counts": {"prompt": getattr(response, "prompt_eval_count", None), "completion": getattr(response, "eval_count", None)},
        "retrieved_regulatory_ids": [h["id"] for h in context["regulatory"]],
        "retrieved_artifact_ids": [h["id"] for h in context["artifacts"]],
        "risk_report": report.model_dump(),
        "verified_risk_report": verification.verified_report.model_dump(),
        "hallucinated_citations": hallucinated,
        "verification": verification.model_dump(),
        "clinical_validation": clinical_validation,
        "generation_source": generation_source,
        "revision_feedback": revision_feedback,
    }


def generate_risk_report_no_rag(
    input_narrative: str,
    ollama_model: str | None = OLLAMA_MODEL,
    ollama_client=None,
    domain: str = "arrhythmia",
    temperature: float = 0.1,
    prompt_condition: str = "baseline",
    seed: int | None = None,
    think: bool | str | None = False,
) -> dict:
    """Generate a structured RiskReport with the LLM but no retrieved context."""
    empty_context = {"regulatory": [], "artifacts": []}
    return generate_risk_report(
        input_narrative,
        ollama_model=ollama_model,
        ollama_client=ollama_client,
        context=empty_context,
        prompt_condition=prompt_condition,
        domain=domain,
        temperature=temperature,
        seed=seed,
        think=think,
    )


if __name__ == "__main__":
    sample_narrative = (
        "User facility reported that the device failed to flag a sustained VTach "
        "episode lasting approximately 4 minutes during overnight telemetry. "
        "Device log shows the VTach classifier confidence score for the relevant "
        "window was 0.61, below the 0.75 escalation threshold."
    )
    print("Running end-to-end pipeline on sample narrative...\n")
    result = generate_risk_report(sample_narrative)
    print(json.dumps(result, indent=2))
