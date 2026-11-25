---
identity: "onto:decision:typed-correspondence"
created: 2026-11-25T19:44:15.372290+00:00
updated: 2026-11-25T19:44:35.822964+00:00
title: "One target instance per `->` line, chosen by the receiving type"
status: accepted
date: 2026-11-17
code: DEC0018
---
# One target instance per `->` line, chosen by the receiving type

**Status**: accepted (approved by the user). **Date**: 2026-11-17.

**Context**: mapping the AdviceLink CRM to AdviceOS, a client row is both a
`Society/Person` and a `Client/Relationship`, but spec-04 made any reference to
a source type with several `->` lines an error.

**Decision**: each `->` line makes its own target instance. A reference
translates through the line whose target type the receiving attribute, role or
verb accepts (that type or one it specialises); several fitting lines, or
none, are an error. `$` alone in a mapping is the scope instance as a
reference (`Client <- $`), so a second scope can name the first scope's target.
`{as=T}` (2026-11-18) chooses among several fitting targets.

**Alternatives**: the earlier rule, under which any reference to a source type
with several `->` lines was an error.

**Rationale**: one source record may describe several things, and the
receiver's type says which one it means; no handle is chosen arbitrarily.

**Consequences**: two lines to the same target type stay ambiguous.
References carry their target type, so a target that a scope's `when` skips is
still typed, as an implicit instance. Static checks and the compiler share
`correspondenceTarget`.

Sources: `docs/specs/spec-04-mapping.md#instances`, `TODO.md` at `da01e2c`
("Type-directed instance correspondence", "Write-back safety, exclusive lines
and named bindings")
