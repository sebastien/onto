---
identity: "onto:decision:index-steps-as-tuples"
created: 2026-11-25T19:44:15.190473+00:00
updated: 2026-11-25T19:44:35.584472+00:00
title: "Index steps compile to tuples and selector levels, without changing hexa"
status: accepted
date: 2026-11-17
code: DEC0017
---
# Index steps compile to tuples and selector levels, without changing hexa

**Status**: accepted (written into spec-06). **Date**: 2026-11-17; index steps
before `[*]` on 2026-11-18.

**Context**: the AdviceLink CRM API returns related rows as two-element arrays
(`[member, client]`); without index steps, neither half could be bound. hexa
selectors have no index access, by design (hexa spec-004).

**Decision**: the integration reads positions with shapes. A scope path's
selector stops before its first index step after the last `[*]`, and the rest
prefixes every path its lines read (`rows[*][0]` selects `rows/*`). Positions
nest in `Tuple(S0, ..., Sn, rest(Any))`, with `Any` where nothing is read. An
index step before `[*]` (`groups[0].items[*]`) is a selector level of its own,
filtered by position. hexa is unchanged.

**Alternatives**: index access in hexa selectors, which hexa spec-004 rules
out.

**Rationale**: hexa already matches fixed positions with `Tuple` and `rest`,
which serves this case, so onto adapts on its side
([domain/decision:HexaExecution+008]).

**Consequences**: field slots name positions `At<n>`. A value read both as a
list position and as a field fails to compile (`Binding.PathUnsupported`),
still open. Writing pads a list to place records at a position.

Sources: `docs/specs/spec-06-hexa.md#selector`,
`docs/specs/spec-06-hexa.md#shape`, `TODO.md` at `da01e2c` ("Index steps
implemented", "Write-back safety, exclusive lines and named bindings")
