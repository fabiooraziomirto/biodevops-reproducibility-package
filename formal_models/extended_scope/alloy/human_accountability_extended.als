/*
 * BioDevOps -- Human Accountability
 * Formal model for the Alloy Analyzer
 *
 * PROPERTY (Sec. IV.B.3 of the IEEEtran paper):
 *   "Every approval record traces to an authorized human actor."
 *   Formally:  forall a in Artifact :
 *                a.kind = ApprovalRecord => a.provenance.creator in AuthorizedHuman
 *
 * This is a STRUCTURAL property about a single artifact's provenance at
 * creation time -- unlike the AI Autonomy Constraint (which is about
 * capability acquired through a sequence of actions) or
 * Evidence-Mediated Governance (which is genuinely temporal, an Until
 * formula), this property does not require modeling Time/sequences at
 * all. It only requires modeling: (a) what kinds of artifacts exist,
 * (b) what provenance an artifact carries, and (c) the constraint that
 * the ONLY way to create an artifact whose kind is ApprovalRecord is
 * through an action whose actor parameter is an AuthorizedHuman.
 *
 * We nonetheless apply the SAME discipline as the previous two
 * properties: a negative control (weaken the creation guard, confirm
 * Alloy then finds a violation) and a non-triviality check (confirm the
 * model still admits legitimate ApprovalRecord creation by humans, so
 * the main check isn't vacuously true because no ApprovalRecord can
 * exist at all).
 *
 * HOW TO RUN
 * ----------
 * Execute > "Check noNonHumanApprovalRecord"
 *   Expected: No counterexample found.
 * Execute > "Run negativeControlCanViolate"
 *   Expected: Instance found.
 * Execute > "Run sanityApprovalRecordsCanExist"
 *   Expected: Instance found.
 */

module biodevops_human_accountability

// ---------------------------------------------------------------------------
// Signatures (cf. Base Domains and Artifact definition, Sec IV.B.1-2)
// ---------------------------------------------------------------------------

abstract sig Actor {}
sig Agent extends Actor {}
sig HumanActor extends Actor {}
sig AuthorizedHuman in HumanActor {}

abstract sig ArtifactKind {}
one sig ApprovalRecord, Code, TestResult, ValidationEvidence extends ArtifactKind {}

sig Artifact {
    kind: one ArtifactKind,
    creator: one Actor          // the provenance.creator field (Sec IV.B.2:
                                 // "provenance = <creator, timestamp, sources>")
}

// ---------------------------------------------------------------------------
// THE CORE STRUCTURAL CONSTRAINT
// We do NOT encode the desired property as a global fact (that pitfall
// is what caused the Alloy v1->v2 issue in the AI Autonomy Constraint
// model). Instead we encode the CREATION RULE as a predicate, and check
// the property as an assertion that follows from that rule, exactly as
// in the corrected autonomy model.
// ---------------------------------------------------------------------------

// STRICT creation rule: an Artifact is well-formed (creatable by the
// architecture) only if, whenever its kind is ApprovalRecord, its
// creator is an AuthorizedHuman.
pred isWellFormed_Strict[a: Artifact] {
    a.kind = ApprovalRecord => a.creator in AuthorizedHuman
}

pred allArtifactsWellFormed_Strict {
    all a: Artifact | isWellFormed_Strict[a]
}

// BROKEN creation rule (negative control): no constraint at all on who
// creates an ApprovalRecord.
pred isWellFormed_Broken[a: Artifact] {
    a in Artifact   // tautology: always holds for any Artifact atom --
                     // Alloy has no bare boolean literal usable as a
                     // pred body in this position, so we use a trivially
                     // true relational formula instead of the word "true"
}

pred allArtifactsWellFormed_Broken {
    all a: Artifact | isWellFormed_Broken[a]
}

// ---------------------------------------------------------------------------
// MAIN CHECK
// ---------------------------------------------------------------------------

assert noNonHumanApprovalRecord {
    allArtifactsWellFormed_Strict =>
        (all a: Artifact | a.kind = ApprovalRecord => a.creator in AuthorizedHuman)
}

check noNonHumanApprovalRecord for 20 Artifact, 10 Actor

// ---------------------------------------------------------------------------
// NEGATIVE CONTROL
// ---------------------------------------------------------------------------

pred negativeControlCanViolate {
    allArtifactsWellFormed_Broken and
    (some a: Artifact, ag: Agent | a.kind = ApprovalRecord and a.creator = ag)
}

run negativeControlCanViolate for 20 Artifact, 10 Actor

// ---------------------------------------------------------------------------
// SANITY CHECK: legitimate ApprovalRecords created by authorized humans must still
// be representable under the strict rule.
// ---------------------------------------------------------------------------

pred sanityApprovalRecordsCanExist {
    allArtifactsWellFormed_Strict and
    (some a: Artifact, h: AuthorizedHuman | a.kind = ApprovalRecord and a.creator = h)
}

run sanityApprovalRecordsCanExist for 20 Artifact, 10 Actor
