---
identity: "onto:decision:type-only-declarations"
created: 2026-11-25T19:44:13.397269+00:00
updated: 2026-11-25T19:44:33.486991+00:00
title: "`@type` records a handle's type without asserting existence"
status: accepted
date: 2026-11-11
code: DEC0007
---
# `@type` records a handle's type without asserting existence

**Status**: accepted (approved by the user). **Date**: 2026-11-11 (commit
`066d68d`).

**Context**: some handles have a type but no surviving typed mention: one only
referenced, one used only as a context, a named binary link whose existence was
withdrawn. Printing lost their type, so such registries were rejected as
unrepresentable.

**Decision**: `@type <handle> <Type-or-S.verb.T>` declares a type only: no
existence, facet or link claim, no metadata and no statement ordinal.
Printers emit declarations, sorted by handle, only when typed mentions or
defining links cannot preserve the registry. JSON needs nothing new: its
`instances` map already carries types.

**Alternatives**: rejecting unrepresentable registries (the earlier
behaviour); synthetic claims carrying the type, rejected
([domain/antipattern:InventedEvidence]); new JSON members, unnecessary.

**Rationale**: text and JSON must round-trip losslessly without asserting
anything the log does not say.

**Consequences**: retractions do not remove registry types; invalid
declarations are fatal in both modes.

Sources: `docs/specs/spec-02-observations.md#type-only-declarations`,
`TODO.md` at `da01e2c` ("Type-only declarations implemented")
