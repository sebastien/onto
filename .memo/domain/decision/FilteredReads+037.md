---
identity: "onto:decision:filtered-reads"
created: 2026-11-27T18:33:34.415947+00:00
updated: 2026-11-27T19:16:59.533406+00:00
code: DEC0037
title: "A population's filters narrow its rows before a read is chosen for them"
status: accepted
date: 2026-11-28
---
# A population's filters narrow its rows before a read is chosen for them

**Status**: accepted. **Date**: 2026-11-28.

**Context**: the rows of a population are those of the first read, in
catalogue order, whose bindings state its link (spec-06 "Rooted retrieval",
[domain/decision:ReadSelection+024]). Two adviceos-data views went wrong with
the order:
- **File notes.** A client's file notes (`client <- concerns where
  Type=FileNote`) and the meetings they took part in come from two lists,
  both stating `concerns` links. Records map their type through a value map
  whose values never include `FileNote`. Yet with the meeting list first, the
  notes took its rows: the client's four file notes were reported `empty`,
  without an error.
- **Dependants.** A household's dependants (`household <- Household where
  Role=Dependant`, then `-> Member`) were taken from the clients' memberships
  too, which state no role. Their names were planned from a read naming clients
  only, and the section listing dependants was never read.

**Decision**: a population's value filters narrow its source row types before
the read of its link is chosen (spec-06). A line gives its literal's value, a
value map's line the values it maps to, any other line any value. A type no
line gives the member cannot pass, since missing evidence never satisfies a
filter (spec-01). Ancestor tests (`@ancestor`) do not narrow.

**Not done**: narrowing a map's values by a read's `selects`, proposed first.
Row types are per type, not per read, and neither case needed it.

**Implementation**: `correspondences` records, per field, each line's subject
type and values (`lineValues`); `passing` narrows a link hop's row types. The
JavaScript runtime takes the planner's choices from the bundle (`matches`), so
only Python changed.

**Alternatives**:
- catalogue order, as before: a silent wrong answer when the catalogue is
  reordered;
- declaring on each read the values its rows map to: it repeats the mapping.

**Approval**: the user approved implementing it (2026-11-28).

Related: [domain/decision:ReadSelection+024] [domain/component:HexaIntegration]

Sources: `docs/specs/spec-06-hexa.md#rooted-retrieval`,
`tests/T06-029-hexa-filtered-reads.py`; adviceos-data `recorded.py`
(`ClientComments`, `ClientMeetings`), decisions `DEC0024` and `DEC0027`
