# Continue: onto implementation

## Where things are

- **Working rules** (conventions, constraints, workspace hygiene): learnings of
  the project agent, loaded with `memo agent wake` (see `AGENTS.md`).
- **Design knowledge**: the knowledge store `.memo/`. Start with
  `memo read domain/architecture:Onto`; decisions and their rationale are
  listed by `memo list decision:`; `usage/guide:Conventions` explains the store.
- **Specifications** (`docs/specs/`) are authoritative; `docs/doc-overview.md`
  introduces the concepts.
- This file holds **open work only**. Finished work is described by the specs
  and tests; the implementation notes up to 2026-11-26 are in git (`TODO.md`
  at commit `da01e2c`).

## Status (2026-11-26)

Implemented in Python: ontologies (spec-01), with the `Meta` domain and
semantic diff; observations (spec-02); bindings, mappings and function
libraries (spec-04); referential policies (spec-05); the hexa integration,
including rooted views (spec-06); and the CLI (spec-07). The JavaScript runtime
(`src/js/onto/`) executes bundles that Python compiles. `make test`: 1,968
passed on Python 3.15. Not started: overlays (spec-03) and registry-backed
identities (spec-05).

## Open work

1. **Registry-backed identities** (spec-05): the `.reg` reader, minted handles,
   alternate keys (`key=A,B`), the `IdentityResolve` host operation and
   implicit-age warnings. Composite keys are a separate proposal
   (`domain/decision:CompositeKeys+022`).
2. **Overlays** (spec-03) and `onto overlay`.
3. **CLI**: `onto formats update`, and re-running against a host store
   (spec-07 "Deferred").
4. **Declared response checks** for view reads, so that hosts need no code but
   their credentials (`domain/decision:DeclaredResponseChecks+021`).
5. **JavaScript beyond execution**, if still wanted: parsers, compilers,
   writing (`compileWrite`), re-running (`BindingRun`, `MappingRun`, approval),
   inventory fields and writing-format learning are Python-only.
6. **Small open questions**:
   - addressing a range's bounds (`Attr.Low`, `Attr.High`) in observations and
     mapping targets, for sources with separate columns;
   - `Meta/Field` records for structure fields (then `ItemField` could be a
     reference instead of a path), and whether `onto check` should flag stale
     `onto meta --decl` output;
   - describing a binary relation's participation counts (`L:R`) in `Meta`;
   - a value read both as a list position and as a field
     (`Binding.PathUnsupported`).
7. **Python 3.14**: run the suite on the minimum supported version; only 3.15
   is installed locally.

## Modeling gaps

Shapes the modeling rules ask for that onto cannot express yet. The modeling
skill (`docs/skills/onto-modeling`) documents a workaround for each; remove it
from the rule file when the gap closes. Each decision entry holds the proposal
and its open questions.

- **Partial dates** (rule 2.4): a `precision` qualifier on `Date`
  (`domain/decision:PartialDates+011`).
- **More than one supertype** (rules 7.2 and 4.6): multi-subject facets,
  preferred to multiple inheritance (`domain/decision:MultipleSupertypes+012`).
- **Facets limited by a participant's type**: `{when=Participant:Type}` on
  facets of associations (`domain/decision:FacetParticipantCondition+014`).

## Elsewhere

- hexa: a runner for vocabulary examples; onto's `vocabularyConformance()`
  stands in until hexa has one.
- adviceos-data: move its read catalogue to request templates and its checks
  to `check`.
