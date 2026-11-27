---
identity: "onto:decision:target-references"
created: 2026-11-27T07:33:38.754183+00:00
updated: 2026-11-27T07:33:39.598841+00:00
code: DEC0035
title: A mapping names reference data of its target by referential key
status: accepted
date: 2026-11-27
---
# A mapping names reference data of its target by referential key

**Status**: accepted. **Date**: 2026-11-27.

**Context**: adviceos-data keeps a practice's reference questions as target
observations (`questions.obs`), apart from what the mappings produce. Mapping a
needs analysis's answers needs each item to name its reference question.
`ref(T, Key)` was compiled for generated reverses only: in a forward mapping,
`ref` named a source type and took a key path.

**Decision**: `ref(T, Key)`, with `T` a type of `To` that `From` does not have,
names the target instance whose key, under the referential's `key=` policy for
`T`, is `Key`: a literal or one path to a text or number (spec-04 Instances).
Its handle is the one the policy derives, whether or not the mapping produces
the instance, which stays implicit until a source states it. A type without
such a policy is an error. Lossy under reversal. It prints with the `To` namer.

**Alternatives**: a constant source-qualified handle, which would never meet
the reference data's own handles; scope lines minting the questions from each
answer row, which states reference data once per answer.

**Rationale**: a referential key is the stable, source-independent name of a
target instance: reference data and mapped output meet on it.

**Approval**: the user approved implementing it (2026-11-27).

Related: [domain/decision:ReferentialIdentities+002] [domain/component:HexaIntegration]

Sources: `docs/specs/spec-04-mapping.md#instances`,
`docs/specs/spec-05-identities.md#referentials`,
`tests/T06-026-hexa-target-references.py`
