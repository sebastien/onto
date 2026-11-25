---
identity: "onto:decision:run-semantics"
created: 2026-11-25T19:44:12.322469+00:00
updated: 2026-11-25T19:44:32.131640+00:00
title: "Runs withdraw what they no longer produce, behind safeguards"
status: accepted
date: 2026-11-11
code: DEC0001
---
# Runs withdraw what they no longer produce, behind safeguards

**Status**: accepted. **Date**: 2026-11-11 (spec-04 design review with the
user; written into specs 02 and 04).

**Context**: observations accumulate and are never overwritten. A binding or
mapping run must therefore withdraw what it claimed before and no longer
claims, or a removed field or a delisted instrument survives in the state
forever; but a bad input (a truncated download, an empty page, a feed in a new
format) must not erase what is known. The review settled spec-04's open run
semantics.

**Decision**:
- A retraction carrying `by` withdraws only claims with the same `src` *and*
  `by`: one process re-running never withdraws another's claims for the same
  source.
- An absent input gives a retraction; a *gap* (a function failed, a value did
  not convert, an input conflicted) keeps the previous claim, reported stale.
- The binding header `complete=document|record|none` (default `document`) says
  what a run's documents claim; a scope's `deleted=path:value` retracts reported
  deletions; a run reads a set of documents.
- A mapped claim's `at` is the run's time. Safeguards: a `retract=` ceiling
  (default `20%`) holds retractions; empty input and older snapshots are errors
  in strict mode.
- On a conflicting input, only the input that gives the claim its `src` fans
  out, one claim per value; a conflict in any other input, or in a `when`
  path, makes the line a gap.
- Strict mode (the default; offline, all or nothing) and lenient mode (online,
  warnings, still holding retractions over the ceiling) apply to every
  processor. Held retractions are approved by a person, or, in lenient mode, by
  the next `confirm` runs (default `1`) repeating them; retractions a run does
  not repeat lapse. Approved retractions keep the run's `src`, `by` and `at`
  and carry `approved=<token>` or `approved=confirm:<n>` (a new spec-02 key).

**Alternatives**: not recorded, beyond those the specification rules out
below.

**Rationale**, as the specification gives it: a truncated download is
transient, a real removal persists, so repetition is the evidence for
approval. A gap means the source still says something the run could not
translate, so its previous claim stays. Taking the run's time lets a
recomputed value supersede the previous one, and a claim produced again after
a retraction is never hidden by it. Fanning out a conflict in another input
would attribute several outputs to one source, where they would supersede each
other and the conflict would be lost. A strict run is all or nothing, so an
offline batch is never half applied.

**Consequences**: hosts persist the previous output and pending retractions
(`Outcome`, `OutputPreviousRead`, `RetractionsPendingRead`); `onto run` stays
one-shot until the CLI has a store.

Related: [domain/decision:ReferentialIdentities+002],
[domain/component:HexaIntegration]

Sources: `docs/specs/spec-04-mapping.md#re-running`,
`docs/specs/spec-04-mapping.md#run-modes`,
`docs/specs/spec-04-mapping.md#claims-and-metadata`,
`docs/specs/spec-02-observations.md#retraction`, `TODO.md` at `da01e2c`
("Spec-04 design review", decisions 1 to 5 and "Approval")
