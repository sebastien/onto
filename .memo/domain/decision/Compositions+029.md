---
identity: "onto:decision:compositions"
created: 2026-11-26T04:47:39.740757+00:00
updated: 2026-11-26T04:59:24.307603+00:00
title: "A composition marks what goes with what; a view takes a key only along a link it follows or a composition"
status: accepted
date: 2026-11-26
code: DEC0029
---
# A composition marks what goes with what; a view takes a key only along a link it follows or a composition

**Status**: accepted. **Date**: 2026-11-26.

**Context**: rooted retrieval discovers keys through reads (`provides`), and a
discovered key needed one provider in the whole catalogue reachable from a seed.
adviceos-data needed a second way to discover needs analyses, a client's list
of them, for a client's history: the diary note, which reaches a mortgage's
clients, would then have found analyses both as the mortgage's own and as every
analysis of its clients, and the planner rejected the catalogue. Every link
counted the same, so nothing said the first was the one the note is about. The
user's point: some links are stronger than others, as some attributes are keys;
a composition is such a link, as an arm goes with its body while what it
carries does not.

**Decision**: `{part}` on a binary relation makes each object a part of its
subject, with one whole (`L` is `1` or `?`; spec-01 Binary shorthand). A read
names the link it discovers its key along (`ViewRead.via`, a target relation as
a view spells it), checked to lead from its input to that key. A view takes the
key from such a read only when one of its populations is bound through that
relation, either way (or through its context association, in by one selected
role and out by the other, as `through` does), or when the relation is a
composition: a view reaches what
its populations reach and the parts and wholes of those (spec-06 Rooted
retrieval). A read without `via` provides its key to every view, as before.
Each view's reads, and the read providing each key, are computed when the
operator is built, and a view with two providers of a key is rejected then. A
run takes each read's provider from its plan step, not from the first read
discovering its key; the bundle carries each view's steps (`onto.view-bundle/2`).

**Alternatives**: choosing a provider by the view's path alone, which cannot
reach a whole the view needs without naming it (the analysis whose rows state
its clients' names); `{key}` on relations, which already means identity on a
reference (a needs-analysis section is identified by its analysis), whereas an
application is not identified by the analysis it is part of; inferring
composition from cardinality, which cannot tell a mortgage's deals (its parts)
from a client's analyses (not its parts), both several; the union of every
provider's keys, which would read every analysis of a mortgage's clients.

**Rationale**: composition is the domain's own statement of what belongs
together, so it bounds what a view reads without the view naming it; an
ordinary link is followed only on purpose.

**Consequences**: the diary note reads only its mortgage's analysis, and a
history view that follows a client's analyses reads all of them. A view
following two links to one key is still rejected; taking the union of their
keys would be a later decision. A population reached through an ordinary link
(the clients' jobs) holds what the view's reads find, not every such record.

Related: [domain/decision:ReadSelection+024], [domain/decision:ContextLinks+023]

Sources: `docs/specs/spec-01-ontology.md#binary-shorthand`,
`docs/specs/spec-06-hexa.md#rooted-retrieval`, `tests/T01-001-ontology-parsing.py`,
`tests/T06-025-hexa-part-links.py`; adviceos-data `TODO_ONTO.md` ("A client's
history"); proposed by the user ("some relations should be keys", composition
as an arm to a body), 2026-11-26
