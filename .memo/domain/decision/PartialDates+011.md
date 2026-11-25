---
identity: "onto:decision:partial-dates"
created: 2026-11-25T19:44:14.124289+00:00
updated: 2026-11-25T19:44:34.312325+00:00
title: "Partial dates as a precision qualifier on `Date`"
status: proposed
date: 2026-11-16
code: DEC0011
---
# Partial dates as a precision qualifier on `Date`

**Status**: proposed (not decided). **Date**: 2026-11-16 (modeling gap 2,
found writing the modeling skills).

**Context**: the modeling rules ask for values in their real precision (rule
2.4), but a `Date` is always a full day: a year built or a month of birth
cannot be stated. Workaround: alias `Text` once (`PartialDate = Text`), with
the format in its doc (`docs/skills/onto-modeling/rules/values.md`, 2.4).

**Proposal**: a `precision` measurement qualifier on `Date` rather than a new
built-in type: `Built Date {precision=Month}` accepts `2019-03`;
`{precision=?}` accepts `2019`, `2019-03` or `2019-03-15`, the spelling
deciding. A `Date` without it stays a full day. The qualifier rules apply:
inherited through aliases, `?` filled per value, never contradicted.

**Alternatives**: a new built-in type, which would reserve a name; general
union types, not proposed.

**Open questions**: comparison and supersession (reading `2019-03` as the
interval `2019-03-01..2019-03-31`); whether `valid=` accepts reduced
precision; the qualifier's values (`Year|Month|Day`).

Sources: `TODO.md` at `da01e2c` ("Modeling gaps", 2),
`docs/skills/onto-modeling/rules/values.md`
