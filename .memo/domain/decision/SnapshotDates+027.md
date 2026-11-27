---
identity: "onto:decision:snapshot-dates"
created: 2026-11-26T01:32:32.767843+00:00
updated: 2026-11-26T01:33:14.194575+00:00
title: "A snapshot dates every claim it makes, and a state observed then takes that date"
status: accepted
date: 2026-11-26
code: DEC0027
---
# A snapshot dates every claim it makes, and a state observed then takes that date

**Status**: accepted. **Date**: 2026-11-26.

**Context**: a questionnaire (adviceos-data's needs analyses) states a
client's circumstances as at its date, and the same client answers again
later. Bindings dated only existence claims, from a scope's `valid=`. `at`
cannot carry the date, since a mapping's claims take its run time (spec-04).
And spec-02 required an interval for a `kind=state` relation, so a job or an
income observed on a date had no valid form: an interval open from that date
claims it started then, a closed one that it ended. The user asked that every
observation be dated, so that a client's salary answers can be listed across
analyses.

**Decision**: a binding's `@valid <- expr` gives every claim of a document its
`valid` (spec-04 Bindings); a scope's own `valid=` takes its place on its
existence claims, and facet applicability has none (spec-06). A `kind=state`
relation takes a point `valid` when observed as at that instant: it held then,
and the point says neither when it started nor that it ended (spec-02
Metadata). An event still takes a point only. Mapped claims keep the
intersection of their inputs' `valid`, so the date reaches the target
ontology.

**Alternatives**: the document's date as `at`, which every mapping replaces;
dating values but not the existence of states, which leaves the jobs and
incomes themselves undated; an interval open from the date, which states a
start; a contextual facet per questionnaire (`EmploymentTenure
{ctx=Engagement}`, applied first in adviceos-data), which dates only the facets
declared so and needs the context bound in every view.

**Rationale**: `valid` is when a fact holds, which is what a questionnaire's
date says. A point is the honest extent of one observation, and a point already
compares as the instant interval (`parseInterval`), so snapshots at different
dates do not conflict.

**Consequences**: claims from snapshots at different dates never conflict.
Readers that take a state's `valid` as its extent read a point as "held then",
not as a start and an end. The same change made a JSON `null` read outside a
record not present (`Onto.Present`, spec-06), which `@at <- a ?? b` over a
`null` field needed.

Related: [domain/decision:ContextualMembers+025]

Sources: `docs/specs/spec-02-observations.md#metadata`,
`docs/specs/spec-04-mapping.md#bindings`, `tests/T02-002-observations-roundtrip.py`,
`tests/T04-003-binding-parsing.py`, `tests/T06-001-hexa-binding-read.py`;
adviceos-data `TODO_ONTO.md` ("what a needs analysis states holds as at its
date"); asked for by the user, 2026-11-26
