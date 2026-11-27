---
identity: "onto:decision:read-selection"
created: 2026-11-25T22:39:36.010419+00:00
updated: 2026-11-25T22:39:36.718175+00:00
title: "A read declares what its request selects, and rows are read with their own key"
status: accepted
date: 2026-11-26
code: DEC0024
---
# A read declares what its request selects, and rows are read with their own key

**Status**: accepted. **Date**: 2026-11-26.

**Context**: reads of one binding that differ only by request key (comment
lists filed under a client or under a mortgage) looked the same to the
planner, which took the first read of a row's type for every filing: a
client's notes were planned from the mortgage's list and never read.

**Decision**: `ViewRead(selects=...)` declares, per source entity, a condition
its rows satisfy (values of single-valued attributes, joined by `&`). The
planner skips a read for a mapping candidate whose scope or line condition the
selection refutes (`conditionOutcome`: a condition holds, fails or may hold).
The rows of a population reached backwards are those of the read stating their
link, and reads keyed like that one come first for the population's other
obligations; among reads of one key, catalogue order decides. A candidate's
footprint also counts the paths of compound conditions.

**Alternatives**: catalogue order alone ("does not reorder eligible reads", a
review's choice): another key's read then supplied a population's attributes
and, failing, hid them (`tests/T06-023`). Preferring the read of the rows even
over reads of its key: a dedicated read listed first lost its rows' values
(`tests/T06-022`, reverse-hop test).

**Rationale**: a read of another key reads other rows, and spec-06 holds that
a failed read cannot hide another's facts.

**Consequences**: hosts declare what a request selects; without a declaration
the planner behaves as before.

Sources: `docs/specs/spec-06-hexa.md#rooted-retrieval`,
`tests/T06-023-hexa-read-selection.py`, commit `09545f0`
