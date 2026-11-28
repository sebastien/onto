---
identity: "onto:decision:list-reads"
created: 2026-11-28T00:20:01.242713+00:00
updated: 2026-11-28T00:20:14.761989+00:00
code: DEC0038
title: "List reads match text in part, take a sort direction, and travel compiled"
status: accepted
date: "2026-11-28"
---
# List reads match text in part, take a sort direction, and travel compiled

**Status**: accepted. **Date**: 2026-11-28.

**Context**: adviceos-crm's prototype needs its client groups listed before
advisers sign in, from the CRM's `POST /group/list`, without store indexes
(spec-09 "List views"). The endpoint matches a group's name in part, without
case (`name`), sorts by one field (`sortBy`) in a direction (`reverse`), and
pages from `0`. spec-09's list reads had only `eq`, `in` and `exists` filters,
a sort field without a direction, and an unnumbered first page. Key queries
were to be compiled by Python, yet a browser runs them in JavaScript, which
cannot reverse mapping lines.

**Decision**:
- A list read filter may take `contains`: text the system matches in part, as
  the system does. Key queries take it on system-held fields.
- A `Direction` parameter names the values the endpoint takes for ascending and
  descending sorts. A list read takes one sort field.
- A page parameter names the first page's number (`0` by default); a query's
  pages count from 1.
- Python compiles each list view's queries once: its list read, each
  filterable field's parameter, operators and reversed values (a value map's
  inverse; a plain line's value unchanged), each sortable field's spelling,
  and the direction and page parameters. The bundle carries them, so every
  runtime compiles a query from the same table.
- A list view's seed is its query. The list read is the plan's first step and
  provides the view's key; the reads of each row take the keys it found, as
  reads take a provided key. Facts name their row.

**Not done**: store-held predicates, `KeyQuery` on the server, and `not`,
which need store indexes (O3); several sort fields; `more` for population
pages within rows.

**Alternatives**:
- reversing lines in JavaScript: a second implementation of spec-04 Reversal;
- a separate list run before the page run: two journals, and the list read
  outside the replayed effects.

**Approval**: the user approved CRM-backed lists ahead of store indexes
(2026-11-28).

Related: [domain/decision:Sessions+028]

Sources: `docs/specs/spec-09-sessions.md#list-reads`,
`docs/specs/spec-09-sessions.md#key-queries`; adviceos-data
`ref-advicelink-api-internal.json` (`Group.GroupFilter`)
