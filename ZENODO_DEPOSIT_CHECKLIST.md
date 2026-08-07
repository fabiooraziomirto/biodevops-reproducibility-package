# Zenodo deposit checklist (manual steps)

Everything below requires GitHub/Zenodo account actions I cannot perform.
The repository already exists at
`git@github.com:fabiooraziomirto/biodevops-reproducibility-package.git`
with a first commit on `main`.

## 1. GitHub repo cosmetics

In the repo's Settings / About panel, set:

- **Description**: "Reproducibility package for 'BioDevOps: An Assurance
  Architecture for Bounded Agentic Evidence Assembly in Medical-Device
  Governance' -- manuscript, code, formal models, and stored evaluation
  outputs for Tables I-V."
- **Topics**: `reproducibility`, `agentic-ai`, `medical-devices`,
  `healthcare-ai`, `formal-verification`, `opa`, `shacl`, `alloy`, `tla-plus`,
  `ai-governance`

## 2. Commit the work from this session

The changes made in this session (README rewrite, LICENSE, CITATION.cff,
`environment/`, `reproduce.sh`, path-portability fixes, `ontology_validate.py`,
regenerated `SHA256SUMS.json`, folder renames) are on disk but not yet
committed. Review with `git status` / `git diff`, then commit and push
when ready -- this is a real action affecting a shared/public repo, so do
it deliberately rather than as a side effect of reading this checklist.

## 3. Tag a release

```bash
git tag -a v1.0.0 -m "Reproducibility package for JBHI submission"
git push origin v1.0.0
```

Or create the release via the GitHub UI (Releases -> Draft a new release),
which tags automatically.

## 4. Connect to Zenodo and mint the DOI

1. https://zenodo.org/account/settings/github/ -> log in with the GitHub
   account that owns this repo -> toggle the repository on.
2. Push the `v1.0.0` tag (step 3) if not already done -- Zenodo archives a
   snapshot automatically when a new GitHub release/tag is created while
   the toggle is on.
3. On the resulting Zenodo record, fill in: description, keywords (mirror
   the GitHub topics above), license (CC BY 4.0 -- should auto-detect from
   `LICENSE`), and add a **related identifier** pointing to the JBHI
   manuscript once it has its own DOI (relation: "IsSupplementTo").
4. Use the **concept DOI** (the one Zenodo shows as "cite all versions"),
   not the version-specific DOI, in the manuscript -- this way a later
   `v1.0.1` fix does not invalidate the citation.

## 5. Update the manuscript before submission

Replace `[ZENODO DOI]` in `jbhi_submission/main.tex` (paragraph "Data and
code availability") with the concept DOI from step 4, **before** submitting
to JBHI -- not after. Recompile and re-sync into `manuscript/` in this
package (`cp jbhi_submission/main.tex jbhi_submission/main.pdf
zenodo_2026-08-07/manuscript/`), then re-tag/re-push so the archived
package matches what reviewers see cited in the PDF.

## 6. Update CITATION.cff and README with the minted DOI

Once minted, replace the `repository: "PENDING: ..."` line in
`CITATION.cff` and reference the DOI in `README.md`'s opening paragraph.
