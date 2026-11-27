---
identity: "onto:decision:named-references"
created: 2026-11-27T07:33:36.078422+00:00
updated: 2026-11-27T07:33:36.890769+00:00
code: DEC0033
title: "A line's name chooses which named scope a reference translates through"
status: accepted
date: 2026-11-27
---
# A line's name chooses which named scope a reference translates through

**Status**: accepted. **Date**: 2026-11-27.

**Context**: named scopes give one source row several targets of one type
(`Row -> Goal {name=Main}`, `{name=Short}`). A receiver accepting several of
them was ambiguous, and choosing one was "not yet supported" (spec-04
Instances). adviceos-data needs it to map a needs analysis's answers: one
question row states several items and an answer to each, and each answer names
its own item.

**Decision**: a mapping line's `{name=N}` translates its reference through the
scope line named `N`, among those of the reference's source type whose target
the receiver accepts (spec-04 Instances). As with `{as=T}`, a target that
scope's `when` or `present` skips is a gap (`Mapping.ReferenceUnmapped`), never
another target. `name` and `as` are exclusive: the name already chooses the
type. Lossy under reversal.

**Implementation**: `HandlesResolve` records, for each source instance, the
targets its named scopes emitted (`named`); a reference carries them as
`scopes`, and `Onto.CorrespondNamed` picks one by program scope, in Python and
JavaScript.

**Alternatives**:
- the scope name in `as=` (`as=Goal@Short`): one annotation with two
  grammars;
- an implicit rule (a reference from a scope named `N` prefers the scope named
  `N`): it reads as magic and breaks when names differ.

**Rationale**: names are already the stable identity of repeated scopes; the
line says which one it means, as `{as=T}` says which type.

**Approval**: the user approved implementing it, with lookups and target
references, to clear adviceos-data's `TODO_ONTO.md` (2026-11-27); this entry
records the design.

Related: [domain/decision:TypedCorrespondence+018] [domain/component:HexaIntegration] [domain/component:JsRuntime]

Sources: `docs/specs/spec-04-mapping.md#instances`,
`tests/T06-027-hexa-named-references.py`; adviceos-data `TODO_ONTO.md` at
`4035dc3` ("Named-reference selection")
