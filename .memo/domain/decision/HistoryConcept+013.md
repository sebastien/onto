---
identity: "onto:decision:history-concept"
created: 2026-11-25T19:44:14.477779+00:00
updated: 2026-11-25T19:44:34.717703+00:00
title: "`{history}` generates a change concept"
status: accepted
date: 2026-11-16
code: DEC0013
---
# `{history}` generates a change concept

**Status**: accepted. **Date**: 2026-11-16 (modeling gap 10; commit
`89c01d9`).

**Context**: a status whose past values matter was declared by hand: one
`X/StatusChange` concept per lifecycle (seven in the AdviceOS ontology), each
with `1 Status T`, `OccurredDate Date`, `Reason Text` and a
`X -hasChange-> X/StatusChange 1:*` relation. This was open decision 3 of the
AdviceOS review.

**Decision**: the attribute flag `{history}` generates, for `Owner.Attr`, the
concept `Owner/AttrChange` (fields `1 Attr`, `OccurredDate Date`,
`Reason Text`) and the relation `Owner -hasChange/isChangeOf-> Owner/AttrChange 1:*`.
Declaring the generated concept is an error: the flag is its only source.
Normal form and JSON keep only the flag; the declarations are derived again
when loading.

**Alternatives**: no generated concept; instead, `{history}` attributes would
always be observed with `valid=`, which already dates values.

**Rationale**: not recorded beyond the choice.

**Consequences**: each value reached is a record with its date and reason,
usable in observations and described by `onto meta`. A history needing more
than a date and a reason (an actor, say) is declared by hand, without the
flag.

Sources: `docs/specs/spec-01-ontology.md#history`, `TODO.md` at `da01e2c`
("Modeling gaps", 10)
