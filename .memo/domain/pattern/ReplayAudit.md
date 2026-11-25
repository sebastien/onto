---
identity: "onto:pattern:replay-audit"
created: 2026-11-25T19:44:11.487836+00:00
updated: 2026-11-25T19:44:26.818250+00:00
title: Deterministic replay audits
---
# Deterministic replay audits

**Context**: normal forms promise that a printed state loads back to the same
state, and that text and JSON convert losslessly. Hand-written cases miss the
interactions between supersession, collections, identity links and
withdrawals.

**Approach**: generate many small documents from a seeded random source over a
fixed set of statements, and check for each that JSON round-trips, that the
printed state reloads to the same semantic claims, and that formatting is
idempotent. Invalid candidates (conflicting identity logs, for example) are
excluded, not counted as passing. Each failure becomes a targeted regression;
the audit itself may stay in the suite.

**Trade-offs**: an audit explores only its set of statements; passing is
evidence, not proof.

**Example**:
- 120 generated logs (`Random(13)`, kept in
  `tests/T02-001-observations-conformance.py`) found 16 states that lost claims
  on replay ([domain/decision:CollectionLogOrder+006]).
- A continued identity replay review found repeated `=` evidence from one
  source superseding itself, which changed a canonical handle on replay; links
  now accumulate ([domain/decision:IdentityLogOrder+004]). After the fix, 2,000
  identity-log candidates (1,247 strict-valid) and 500 mixed logs replayed
  without loss.

Related: [domain/pattern:SpecExamplesAsTests]

Sources: `tests/T02-001-observations-conformance.py`, `TODO.md` at `da01e2c`
("Conformance audit: fixes and review outcome")
