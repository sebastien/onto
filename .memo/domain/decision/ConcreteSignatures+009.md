---
identity: "onto:decision:concrete-signatures"
created: 2026-11-25T19:44:13.754970+00:00
updated: 2026-11-25T19:44:33.908642+00:00
title: Declared function signatures use concrete types
status: accepted
date: 2026-11-12
code: DEC0009
---
# Declared function signatures use concrete types

**Status**: accepted (the conservative option, taken when the user deferred
the choice). **Date**: 2026-11-12 (functions declarations, commit `c27d205`).

**Context**: spec-04 writes the built-in contracts with `any` and `any*`, and
one example suggested declared `@fn` signatures could use them too. But a
function's examples are read by type: a bare `p` is text for `Text` and a
reference for an entity type.

**Decision**: `any` and `any*` are notation for the built-in contracts only;
declared `@fn` signatures require concrete types.

**Alternatives**: generic signatures with `any`, which would need new literal
syntax, or inference from spelling, to type their examples; not adopted.

**Rationale**: keeps the observations rule that a value's type decides whether
a bare value is text or a reference, without inventing literal syntax.

**Consequences**: spec-04, the signature schema and the parser agree; a
temporary clarification gate and unused generic-type code were removed. The
user may still revisit generic signatures.

Sources: `docs/specs/spec-04-mapping.md#declarations`, `TODO.md` at `da01e2c`
("Spec-04 implementation progress")
