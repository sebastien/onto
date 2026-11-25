---
identity: "onto:pattern:exact-values"
created: 2026-11-25T19:44:11.713637+00:00
updated: 2026-11-25T19:44:27.012499+00:00
title: Exact values
---
# Exact values

**Context**: observations compare values across sources and times, and
function implementations must agree on every example. Binary floating point
and truncated timestamps break both.

**Approach**:
- Numbers are decimals, in JSON as canonical decimal strings. Exponent
  spellings are kept, and equality is numeric, in collections and in
  reconciliation alike.
- Arithmetic runs in an explicit decimal context, isolated from the ambient
  precision and rounding: sums, products and differences are exact; a
  division is exact when it terminates, else rounded to 16 significant digits,
  half-even. An exact operation that would round or underflow is a gap, never
  a silent zero.
- Timestamps and intervals compare as exact rational UTC seconds, not
  `datetime`'s microseconds; values without a zone, and dates, read as UTC.
- `Integer` accepts integral decimal and exponent spellings.

**Trade-offs**: slower than floats, and every runtime needs exact decimals
(the JavaScript runtime has its own built-ins, checked against Python's).

**Example**: `src/py/onto/functions/runtime.py` evaluates built-ins in a
`localcontext` with `ROUND_HALF_EVEN` that traps `Inexact` and `Underflow`;
`timestampValue` in `src/py/onto/observations/model.py` returns a `Fraction`.

Related: [domain/decision:FunctionSemantics+010]

Sources: `docs/specs/spec-04-mapping.md#contract-for-implementations`,
`src/py/onto/functions/runtime.py`, `src/py/onto/observations/model.py`,
`TODO.md` at `da01e2c` ("Phase 2 status", "Conformance audit", "Spec-04
implementation progress")
