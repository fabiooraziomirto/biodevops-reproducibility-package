# Provenance classes

| Class | Meaning | Examples |
|---|---|---|
| Frozen | Fixed before evaluation | prompt blocks, policies, ontology, split manifests |
| Generated | Reconstructable derived artifact | traces, metrics, SHA-256 manifest |
| Non-redistributable | Identifier/digest reference only | MAUDE narratives (`data_availability/`), standards, model weights |

Formal models check finite abstractions. Policy and shape tests are predicate-level operational evidence, not refinement proofs or authenticated production authorization.

**Exception:** `evaluation_protocol/maude_ecg_annotations/` includes full FDA
MAUDE narrative text (public domain, U.S. government work) alongside the
per-rater/merged/adjudicated labels, so the kappa computation reported in the
manuscript can be audited against the source text. This is deliberate and
narrower in scope than the general index-only policy above, which still
applies to `data_availability/maude_record_index.json`.
