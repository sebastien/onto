---
identity: "onto:decision:facet-participant-condition"
created: 2026-11-25T19:44:14.652899+00:00
updated: 2026-11-25T19:44:34.964893+00:00
title: "Facets limited by a participant's type"
status: proposed
date: 2026-11-16
code: DEC0014
---
# Facets limited by a participant's type

**Status**: proposed (not decided). **Date**: 2026-11-16 (modeling gap 6,
found applying the modeling rules to the AdviceOS ontology).

**Context**: a facet applies to every instance of its subject:
`Property/Ownership of Finance/Holding` applies to any holding, and
`Insurance/Insured.Object` is any position. The conditional facets implemented
on 2026-11-18 (`{when=Attr:Value}`) restrict a facet by a *value* of its
subject, not by the *type* of one of its participants.

**Proposal**: a `when` annotation on facets of associations, naming a
participant and a type:
`Property/Ownership of Finance/Holding {when=Position:Property/Property}`.
For an entity subject, the condition would be the subject's own
specialisation, better written as a facet of that specialisation. Observations
of the facet on a non-matching instance are errors when the participant's type
is known. Touchpoints: facet validation (the role exists; the type specialises
the role's type), observation loading, spec-01 "Facets".

**Open questions**: one condition or several. Noted while migrating these
notes (2026-11-26): value conditions now use the same `when=Name:Value`
spelling, so the two kinds of test must stay distinguishable.

Sources: `TODO.md` at `da01e2c` ("Modeling gaps", 6),
`docs/specs/spec-01-ontology.md#conditional-facets`
