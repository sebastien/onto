---
identity: "onto:decision:multiple-supertypes"
created: 2026-11-25T19:44:14.300161+00:00
updated: 2026-11-25T19:44:34.517007+00:00
title: More than one supertype
status: proposed
date: 2026-11-16
code: DEC0012
---
# More than one supertype

**Status**: proposed (not decided). **Date**: 2026-11-16 (modeling gap 3,
found writing the modeling skills).

**Context**: specialisation is single. A linear chain of supertypes works, but
not a cross-cutting capability (`Subject`, `Asset`, `Insurable`) shared by
entities with unrelated bases. Workaround: chain the supertypes, the most
generic at the root, or keep the relation on the root and flag it
`{check=supertype}` (`docs/skills/onto-modeling/rules/relations.md`, 7.2;
rule 4.6).

**Options**:
- *A, preferred*: multi-subject facets, usable as participant and reference
  types: `Subject of Customer, Order, Shipment`, then
  `Note -concerns-> Subject` meaning any instance the facet applies to. It
  fits "a role is a facet", and spec-01 already marks the single subject as
  "(v1)".
- *B*: multiple inheritance, `E < A, B`. Familiar, but it needs rules for
  inherited attribute and facet collisions, and widens the verb-clash rule.

**Open questions** (option A): whether domains may add subjects to a facet
declared elsewhere; addressing (`Subject.Facet.Attr`) stays unchanged; the
verb-clash rule must treat a facet target as related to each of its subjects.

Sources: `TODO.md` at `da01e2c` ("Modeling gaps", 3),
`docs/specs/spec-01-ontology.md#facets`,
`docs/skills/onto-modeling/rules/relations.md`
