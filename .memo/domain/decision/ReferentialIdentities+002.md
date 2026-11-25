---
identity: "onto:decision:referential-identities"
created: 2026-11-25T19:44:12.522133+00:00
updated: 2026-11-25T19:44:32.343200+00:00
title: "Identity belongs to referentials, not to mappings"
status: accepted
date: 2026-11-11
code: DEC0002
---
# Identity belongs to referentials, not to mappings

**Status**: accepted. **Date**: 2026-11-11 (spec-04 design review with the
user; spec-05 written for it).

**Context**: mappings matched instances with a `{match=...}` annotation. The
review moved identity out of them.

**Decision**:
- A new specification, spec-05 Identities: referentials (`.ref`) with a policy
  per type (`key=A`, `key=A from=Ns`, `minted`), a registry (`.reg`) for the
  correspondences data cannot give back, and identity links `a = b` and
  `a != b` as observations (spec-02).
- `{match=...}` is removed. A mapping names a `referential`; without one, or
  for a type without a policy, handles are source-qualified.
- A path through a reference ending at a `{key}` attribute reverses to the
  reference. A referenced instance that nothing has stated yet is an
  *implicit instance* (`@implicit` in the state form, `"implicit": true` in
  JSON).
- Implicit age is measured on the data's `at`, from the first referencing
  claim to the run, never on the clock; per type `implicit=<duration>|never`
  in the referential, else the run's setting (default `P7D`); a warning in both
  modes.

**Alternatives**: matching inside mappings (`{match=...}`), removed.

**Rationale**: identity is explicit: two handles are one instance only when
their spelling or a recorded identity link says so, and links carry
provenance like any claim. Source-qualified handles name their source, so
records never merge by accident. Measuring age on the data makes replaying a
log report the same warnings.

**Consequences**: only policies are implemented
([domain/component:Declarations]); registries, minted handles, alternate and
composite keys are open ([domain/decision:CompositeKeys+022]).
Source-qualified handles later gained the source type
([domain/decision:SourceQualifiedHandles+019]).

Sources: `docs/specs/spec-05-identities.md`,
`docs/specs/spec-04-mapping.md#instances`, `docs/doc-overview.md` (Approach),
`TODO.md` at `da01e2c` ("Spec-04 design review", decisions 6 and 8, and
"Implicit age")
