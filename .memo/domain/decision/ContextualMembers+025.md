---
identity: "onto:decision:contextual-members"
created: 2026-11-25T22:39:36.927425+00:00
updated: 2026-11-25T22:39:37.809719+00:00
title: A contextual member holds within the nearest population of its context type
status: accepted
date: 2026-11-26
code: DEC0025
---
# A contextual member holds within the nearest population of its context type

**Status**: accepted. **Date**: 2026-11-26.

**Context**: rooted views skipped every claim with a `ctx`, so a view could
not select a member of a contextual facet (`F of E {ctx=C}`): a client's
declarations in an engagement, an income's treatment in a scenario.

**Decision**: a contextual member, projected, filtered on or followed, holds
within the nearest population of type `C` bound before its subject on the
subject's path: its values are those stated within that population's instance
(spec-01 "Rooted views"). A view whose path binds none is invalid, reported
when its ontology is checked. `Field.ctx` names the facet's context type, and
`Hop.ctx` and `RootedView.contexts` the context population; both runtimes keep
only the claims within it, and facts and retrieved claims keep their `ctx`.

**Alternatives**: an explicit context on each projection, more syntax for the
usual case; any population of type `C` in the view, joined through a common
ancestor, whose facts' paths would not show how their context was bound.

**Rationale**: the gap asked for a rule binding the context to an ancestor
population of its type (adviceos-data `TODO_ONTO.md`); the nearest one is the
context the view's path is in.

**Consequences**: a view reaches a contextual subject through its context: a
client's declarations in a needs analysis need the clients reached from the
engagement.

Sources: `docs/specs/spec-01-ontology.md#rooted-views`,
`tests/T06-024-hexa-contextual-facets.py`; approved to proceed with the gap's
rule, 2026-11-26
