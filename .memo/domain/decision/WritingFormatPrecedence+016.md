---
identity: "onto:decision:writing-format-precedence"
created: 2026-11-25T19:44:15.008074+00:00
updated: 2026-11-25T19:44:35.382759+00:00
title: One learned writing format per raw value
status: accepted
date: 2026-11-16
code: DEC0016
---
# One learned writing format per raw value

**Status**: accepted (approved by the user; integration deviation 8).
**Date**: 2026-11-16 (commit `16f73bb`).

**Context**: learning writing formats from the documents read first
recognised `decimals:N`, `trim` and `padded`, but not case. Adding
`case:upper` and `case:lower` needed a precedence, since one raw value can
match several formats.

**Decision**: each raw text value contributes one format. Decimal text
contributes `decimals:N`; otherwise leading or trailing whitespace contributes
`padded`, before any case check; otherwise text whose cased characters are all
upper or all lower case contributes `case:upper` or `case:lower`; mixed-case
text and text without cased characters (empty text included) contribute
`trim`. Original spellings still take precedence over the chosen format when
the value is unchanged.

**Alternatives**: not recorded.

**Rationale**: one format per value keeps the tallies, and so the chosen
format, well defined.

**Consequences**: tests cover Unicode case, uncased and empty text, padding and
numeric boundaries, learning, updating and writing with the learned formats
(`tests/T06-002-hexa-formats-fields.py`).

Related: [domain/decision:InverseAndFormats+003]

Sources: `docs/specs/spec-06-hexa.md#spelling`, `TODO.md` at `da01e2c`
("Integration deviation review", deviation 8)
