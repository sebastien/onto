---
identity: "onto:decision:collection-log-order"
created: 2026-11-25T19:44:13.219103+00:00
updated: 2026-11-25T19:44:33.263323+00:00
title: Order-sensitive collection slots keep log order
status: accepted
date: 2026-11-11
code: DEC0006
---
# Order-sensitive collection slots keep log order

**Status**: accepted (approved by the user after the phase-2 conformance
audit). **Date**: 2026-11-11 (commit `066d68d`).

**Context**: a deterministic replay audit of 120 generated logs found 16 whose
state form lost claims: a source's complete collection followed, at the same
`at`, by that source's member, partial or unknown claims. Sorting by value put
the later additions before the complete collection, which discarded them on
replay.

**Decision**: when a multi-valued slot retains a source's complete collection
and later claims, every claim on that slot prints in log order (`at`, then
statement ordinal), each with its own metadata (spec-02 normal form, rule 9).
Other slots keep value order, and members inside a collection stay sorted.
Source aliases are resolved when finding the affected slots.

**Alternatives**:
- A temporary `collection-order` rejection, refusing to print such states;
  removed.
- An aggregate claim for the slot: rejected, it invents evidence
  ([domain/antipattern:InventedEvidence]).

**Rationale**: the state form must replay to the same state, with provenance
kept per claim.

**Consequences**: all 120 audit cases keep their claims and format
idempotently; the audit stays in `tests/T02-001-observations-conformance.py`
([domain/pattern:ReplayAudit]).

Sources: `docs/specs/spec-02-observations.md#normal-forms` (rule 9),
`TODO.md` at `da01e2c` ("Conformance audit: fixes and review outcome")
