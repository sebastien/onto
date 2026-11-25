---
identity: "onto:decision:function-semantics"
created: 2026-11-25T19:44:13.936139+00:00
updated: 2026-11-25T19:44:34.109757+00:00
title: "Function execution: half-even rounding, Cartesian application, null first"
status: accepted
date: 2026-11-12
code: DEC0010
---
# Function execution: half-even rounding, Cartesian application, null first

**Status**: accepted (approved by the user). **Date**: 2026-11-12 (commit
`6cdfb25`).

**Context**: implementing the built-ins and the `@fn` contract left execution
questions open in spec-04.

**Decision**:
- A rounded numeric result rounds half to even.
- A function given collections where it expects single values runs on every
  combination of their members (the Cartesian product), not on positional
  pairs.
- Unless declared `{nulls}`, `null` takes precedence over `?`: any `null`
  argument gives `null`, otherwise any `?` gives `?`.
- `count` and `join` give a gap for an incomplete collection, never a result
  over the known members only.

**Alternatives**: positional pairing, and results over the known members, both
rejected (below). The reason for `null` before `?` is not recorded.

**Rationale**: collections are unordered sets, so positional pairs mean
nothing; a count or join of the known members would pass for the whole.

**Consequences**: spec-06's stale sentence on null and unknown was corrected to
match on 2026-11-16. Arithmetic follows [domain/pattern:ExactValues].

Related: [domain/component:Functions]

Sources: `docs/specs/spec-04-mapping.md#contract-for-implementations`,
`docs/specs/spec-04-mapping.md#built-in-functions`, `TODO.md` at `da01e2c`
("Spec-04 implementation progress", "Integration deviation review")
