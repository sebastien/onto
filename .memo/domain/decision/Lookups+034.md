---
identity: "onto:decision:lookups"
created: 2026-11-27T07:33:37.416568+00:00
updated: 2026-11-27T17:19:33.573160+00:00
code: DEC0034
title: Lookups join source rows that name the same records without naming each other
status: accepted
date: 2026-11-27
---
# Lookups join source rows that name the same records without naming each other

**Status**: accepted. **Date**: 2026-11-27.

**Context**: a needs analysis lists each client's personal details and, apart,
each client's address with the time lived there. Both rows name the client and
the analysis; neither names the other. adviceos-data's residence comes from the
personal-details row (its living situation), and needed the address row's
address and time there. A mapping path follows references only, and a source
ontology faithful to the API has no reference between the rows.

**Decision**: `@lookup Owner.Name -> Type` declares `Name`, a single-valued
reference from `Owner` to the one instance of `Type` whose compared attributes
(`A <- B` lines) equal the owner's (spec-04 Lookups).
- A path of a scope over `Owner` may start with it: `Address.Details.City`.
  If a scope inherits two lookups with that name, the nearest declaration wins:
  sorting or merging files must not change which rows a lookup reads.
- None found: absent. Several, or a compared value of the owner in conflict:
  `Mapping.ReferenceAmbiguous`, never the first; a condition reading through it
  holds for none.
- A lookup names no implicit instance, so a rooted view's line reading through
  it needs a read supplying the looked-up rows and both types' compared
  attributes (spec-06).
- Lossy under reversal; coverage counts the compared attributes as conditions.

**Implementation**: a `lookup` path step (`Segment.lookup`) compiles to
`Onto.Single` over the instance found; the `Unfolder` finds it through a table
per lookup and state. `Onto.Single` now returns the absent marker for an unbound
input, which a nested derivation needs. Python and JavaScript; the bundle
carries each step's declaration.

**Alternatives**:
- a reference added to the source ontology (`CnaIndividual.Addresses`): the API
  has none, and the source ontology stays faithful to it;
- a filter in binding paths (`addresses[clientId=...]`): same objection, and it
  binds into an attribute the API does not have;
- an update scope from the address row into the residence (`into=` a lookup):
  no path continuation needed, but an address history (several rows) would
  state conflicting addresses instead of a gap;
- `ref(S, A=x).Path`: keyword arguments and paths after calls, repeated on every
  line.

**Rationale**: the join is the mapping's cleaning, declared once and read as an
ordinary path, so conditions, qualifiers, coverage and planning treat it as a
reference.

**Approval**: the user approved a source lookup resolved while the input is
unfolded, with the planner counting the rows it looks up (2026-11-27); this
entry records the syntax.

Related: [domain/decision:ReadSelection+024] [domain/component:HexaIntegration] [domain/component:JsRuntime]

Sources: `docs/specs/spec-04-mapping.md#lookups`,
`docs/specs/spec-06-hexa.md#rooted-retrieval`, `tests/T06-028-hexa-lookups.py`;
adviceos-data `TODO_ONTO.md` at `4035dc3` ("The time at an address waits on
how an address row is tied to the client's residence")
