---
identity: "onto:decision:read-selection"
created: 2026-11-25T22:39:36.010419+00:00
updated: 2026-11-27T20:37:28.864473+00:00
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

**Amendment (2026-11-28)**: rows reached backwards are read first from the
reads keyed by their parent population, whose input corresponds to the
parent's type; then reachability and catalogue order decide, as before. A
read of another key states the link only for the rows it happens to read. In
adviceos-data, a group's timeline and a client's comment list both state links
from notes to clients and groups: before, the read reachable first took both
populations, so a client page read a group's interactions from the client's
notes, and a group's members' notes came from the group's timeline. Without a
selection, a matter's note list no longer supplies its clients' notes either
(`tests/T06-023`). The user chose this over declaring, on each read, the links
it reads completely, which repeats what its key says.

Sources: `docs/specs/spec-06-hexa.md#rooted-retrieval`,
`tests/T06-023-hexa-read-selection.py`, commit `09545f0`
