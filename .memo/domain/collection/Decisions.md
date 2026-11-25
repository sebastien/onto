---
identity: "onto:collection:decisions"
created: 2026-11-25T19:44:09.491356+00:00
updated: 2026-11-25T19:44:24.631029+00:00
title: Decisions
prefix: DEC
type: decision
---
# Decisions

The durable design choices behind the onto implementation, one entry per
decision with a public code (`DEC0001`, ...). Membership is implicit from the
code prefix.

```sh
memo list decision:
memo facets 'decision:' --by meta.status
memo list 'kind=decision+meta.status=proposed'
```

Accepted decisions are already written into the specifications; their entries
keep what the specifications leave out: alternatives, rationale, approval and
evidence. Proposed decisions hold the design of open gaps until they are
decided; `TODO.md` lists them as open work.

Each decision records status, date, context, the choice (or proposal),
alternatives, rationale and consequences. Where the notes recorded no
rationale or alternative, the entry says so rather than inventing one. When a
choice changes, a successor decision is added and the earlier one is marked
`superseded`, keeping its rationale.

The sequence follows the date each choice was recorded, then the commit that
introduced it. Dates come from the implementation notes in `TODO.md` (at
`da01e2c`); where those give none, from that commit, named in the entry.

Sources: `TODO.md` at `da01e2c`
