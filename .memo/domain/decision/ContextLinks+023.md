---
identity: "onto:decision:context-links"
created: 2026-11-25T22:39:35.096466+00:00
updated: 2026-11-25T22:39:35.792038+00:00
title: "A link of a relation with a context is one fact, whichever form states it"
status: accepted
date: 2026-11-25
code: DEC0023
---
# A link of a relation with a context is one fact, whichever form states it

**Status**: accepted. **Date**: 2026-11-25.

**Context**: a relation with `{context=R, subjectRole=..., objectRole=...}`
names the association whose instances carry its links (spec-01), yet rooted
views reached a link only through relation claims, and `through` only through
association instances. adviceos-data states a client holding an asset as a
link and a liability's holder as a `Finance/Holding`, so its views selected
both.

**Decision**: in rooted views, such a link is proved by a relation claim or by
an instance of the association with both selected roles. `Field.context` names
the association and its roles for the field's two ends. Rooted evidence, in
Python and JavaScript, pairs one instance's role claims over their common
validity; a witness keeps both, retrieval returns both, and facts and path
steps name the association (`through`). The planner counts an association
scope writing both roles as a supplier of the link. `through` reaches only the
links an association states; a context whose selectors name one role stays
with relation claims.

**Alternatives**: normalising every link to one form when mapping, which
changes every mapping's output; or leaving views to select both forms.

**Rationale**: spec-01 already makes the association's instances the carriers
of the link: one fact should not depend on which form a source used.

**Consequences**: facts and path steps gain an optional `through`; a conflict
in either role claim is a conflict.

Sources: `docs/specs/spec-01-ontology.md#rooted-views`,
`docs/specs/spec-06-hexa.md#rooted-retrieval`,
`tests/T06-022-hexa-context-links.py`, commit `196eed1`
