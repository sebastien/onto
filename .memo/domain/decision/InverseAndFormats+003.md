---
identity: "onto:decision:inverse-and-formats"
created: 2026-11-25T19:44:12.694120+00:00
updated: 2026-11-25T19:44:32.560996+00:00
title: "Inverses restore values; formats files restore spellings"
status: accepted
date: 2026-11-11
code: DEC0003
---
# Inverses restore values; formats files restore spellings

**Status**: accepted. **Date**: 2026-11-11 (spec-04 design review with the
user); renamed from `.codec` to `.formats` on 2026-11-12.

**Context**: writing a document back requires undoing each line's functions,
and the receiving system expects values spelled as it writes them itself.

**Decision**:
- `g` is an inverse of `f` when `f(g(y)) = y` for every `y` that `f`
  produces: writing a value back and reading it again gives the same value.
  It need not restore the original spelling.
- Writing reuses a field's original value when reading it still gives the
  value to write; otherwise the value is spelled with the format the field's
  entry in the formats file chose: learned from the documents read, the most
  frequent unless a person pinned one.
- The learned spellings live in `<binding>.formats`, read in a binding line
  with `$format`. They were first `.codec` and `$codec`, renamed on 2026-11-12
  so as not to clash with hexa's codecs.

**Alternatives**: not recorded; the `.codec` name was dropped for the clash.

**Rationale**, as spec-04 puts it: a line that loses only spelling
(formatting, case, order, whitespace) is not lossy, since writing restores
spelling, from the original value or from what the system was seen to write.
Inverses therefore only need to restore values, which a conformance run checks
on every example.

**Consequences**: formats learning and writing are implemented in the hexa
integration ([domain/decision:WritingFormatPrecedence+016]); the JavaScript
runtime neither learns formats nor writes.

Sources: `docs/specs/spec-04-mapping.md#declarations`,
`docs/specs/spec-04-mapping.md#writing`,
`docs/specs/spec-04-mapping.md#formats`, `docs/specs/spec-06-hexa.md#spelling`,
`TODO.md` at `da01e2c` ("Spec-04 design review", decision 7)
