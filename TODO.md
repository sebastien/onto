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

## Status (2026-11-28)

Implemented in Python: ontologies (spec-01), with the `Meta` domain and
semantic diff; observations (spec-02); bindings, mappings and function
libraries (spec-04); referential policies (spec-05); the hexa integration,
including rooted views (spec-06); and the CLI (spec-07). The JavaScript runtime
(`src/js/onto/`) executes bundles that Python compiles. The observation
store's core (spec-08: store files, appends, reads) runs in Python and in
JavaScript, with an HTTP handler, a client and a Cloudflare adapter; sessions
(spec-09) plan and read page views and route changes, in Python and JavaScript. `make test`:
2,274 passed on Python 3.15. Not started: overlays (spec-03), registry-backed
identities (spec-05) and operations (spec-10).

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
8. **Observation store** (spec-08), beyond its core: lifecycle, redaction,
   purge, merges, the reference index, erasure and the change feed, then
   indexes, in Python and JavaScript, with the Cloudflare adapter's scope
   objects; and the `Meta` checks in the JavaScript store's validation
   (`domain/decision:ObservationStore+026`).
9. **Sessions** (spec-09), beyond page views and changes (done in Python and
   JavaScript): list views and list reads, key queries, `more` for the next
   page, notices, a population both a system and the store supply, and
   journaling the store's operations as hexa effects
   (`domain/decision:Sessions+028`).
10. **Operations** (spec-10): the widened reversal, operations in the
    catalogue, writing system-held slots from sessions, and writing in
    JavaScript, with the amendments to spec-04, spec-06 and spec-09
    (`domain/decision:Operations+030`).
11. **Extraction from OpenAPI** (spec-04 "Inventories"): a source ontology,
    inventories and the `.ids` sidecar from an OpenAPI description; wanted
    once a second OpenAPI source appears
    (`domain/decision:OpenApiExtraction+031`).
12. **Histories** (spec-09 History): newest-first log reads with `was`
    (spec-08), the `history` role in spec-06's catalogue, and `history` in
    sessions, in Python and JavaScript; after the AdviceOS read path's first
    milestone (`domain/decision:FactHistory+036`).

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
