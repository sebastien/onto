# Continue: Python ontology implementation

## Conventions

- Tests are `tests/T{spec_number}-{test_number}-{feature_name}-{test_name}.py`.
- Each language/format is `src/py/onto/{feature}/[model.py,parser.py,formatter.py,operations.py]`,
  where model is the data structures, parser the parser, formatter the canonical
  formatter, and operations a collection of functions/operations to run on.
  Organise operations under an Operator class that can take a context with
  parameters/contextual information across operations.
- Integrations with other libraries live in `src/py/onto/integrations/{name}/`,
  are optional, and load their library only when imported.

## Goal and agreed scope

Implement the onto formats in Python, in phases. **Specs 01/02, spec-04 core,
referential policies, static operations and the main hexa integration slices are
implemented**, as detailed in the progress entries below. The current follow-up
is reviewing integration deviations before the deferred extensions. Referential
registries and overlays are not started. Earlier checkpoint statements below
describe their status at that time, not the current backlog.

Current layout follows the conventions above: `src/py/onto/{ontology,observations}/` each has
`model.py`, `parser.py`, `formatter.py`, `operations.py` and public `__init__.py`.
Tests use `tests/T{spec}-{number}-{feature}-{name}.py` with pytest, `pyproject.toml`
and a Makefile `test` target. Runtime dependencies should be standard-library
only; target Python >=3.14. Both Python and JavaScript backends are planned,
but only Python is being started now.

Follow the user's `review-py` conventions: tabs, module docstrings, types first,
camelCase functions/methods/fields, PascalCase classes, UPPER_CASE constants,
logical section headers, explicit `# EOF`. Do not delegate without authorization.

## Project and source material

- Working project: `/home/sebastien/Workspace/Perso/onto`.
- Original reference implementation:
  `/home/sebastien/Workspace/AdviceLink/advicelink-scratchpad/2026-11-DataModel-V2/`.
  Its `src/text.js` and `src/ontology.js` have been read. Its tests are useful
  regression material, but the current specs here are authoritative.
- Stock-exchange domain inspiration (read-only):
  `/home/sebastien/Workspace/Recovery/repos/NZX/nzxcom-apis/src/py/nzxcomapis/model`.
  Examples here must remain generic, not specific to that exchange.
- `memo/pyproject.toml` in the sibling project was inspected for layout precedent.
- `python3 --version` currently reports Python 3.15.0.

## Completed before implementation

- Neutralised specs 01–03 and ontology/observation JSON schemas: no references to
  the original product or schema service remain. Examples use `Finance`.
- Removed `layer`; attribute cardinality evidence is `cards`, matching the
  header. `card` means cardinality. `privacy` is open audience names joined by `+`.
- JSON format IDs are `onto.ontology/1` and `onto.observations/1`.
- Updated sibling `onto.vim` README/showcases/tests; its test runner passed then.
- Added `docs/specs/spec-04-mapping.md` and `src/json/mapping.schema.json`.
  These are specifications, not implemented features.
- Spec-04 covers bindings, mappings/projections, combinators, typed code functions,
  qualifier conversion, coverage, inventories, reversal and re-running.
- Latest approved spec-04 additions are written:
  - `{src=Path}` chooses which input supplies the output claim's source.
  - Reference match keys reverse to links; other referenced attributes require
    `{reverse}` to write back.
  - Inventories drive document coverage; ontology-side coverage is static;
    extractors may generate default bindings.
  - `.fn` libraries use `@functions`, `@use` and fully qualified function names;
    JSON format `onto.functions/1`.
  - Re-running compares previous output and emits retractions for missing slots.
- Structural schema checks passed for spec-04 JSON examples and hand-built
  `src`/`reverse` cases. This does not establish executable semantics.

## Phase 1 status (2026-11-11): implemented; user approved continuation to spec-02

- `src/py/onto/ontology/`, shared `text.py`, `pyproject.toml`, `Makefile` (`make test`
  runs pytest through `uv`), `tests/T01-001-ontology-parsing.py`,
  `tests/T01-002-ontology-json.py`, `README.md`.
- Tests load the spec-01 example and JSON excerpt straight from the spec.
- Audit fixes done: reuse/alias cycle guards and errors; measurement qualifier
  contradictions (`qualifier`); annotation placement table (`ANNOTATION_PLACES`);
  inherited facet vs subclass attribute collision; view `S.verb.T` with full paths
  (JSON view line `path` is the relation path; schema updated), `S.verb` reads
  inverse verbs too; view cycles are errors; strict JSON reader (exact members,
  no nulls/false flags, one type variant, valid cards/counts); CR rejected.
- Multi-file headers: same namespace + rev, and same effective defaults
  (card/cards/rel); aliases file-local but one alias = one namespace across files.
- Spec-01 example fixed: `~ Age Years <- $AsOf, DateOfBirth` (normal form puts
  `$inputs` first).

## Phase 2 status: implemented and signed off

- At sign-off, `make test`: **525 passed**, including schema contracts, Python 3.15.
- `src/py/onto/observations/`: `parseObservations`, `resolveObservations`,
  `loadObservations`, `observationsToJson`, `reconcileObservations`,
  `printObservationsLog`, `printObservationsState`, `formatObservations`,
  `observationsFromJson`; exported from
  `onto`. AST/document/log dataclasses retain locations and diagnostics.
- `tests/T02-002-observations-roundtrip.py`: complete main spec-02 example, its JSON excerpt,
  typed references (including forward reference values), ordinals, metadata,
  contexts, dates, qualifiers, collections, retractions and reconciliation.
- Reconciliation is non-mutating; source aliases compare by provenance token;
  timestamps compare actual instants (unzone/date-only uses UTC); partial sets
  accumulate, complete sets replace earlier members from that source.
- Log/state printers and strict JSON reader added. Complete spec-02 example is
  idempotent in both normal forms; JSON log import/export preserves ordinals.
  Incoming conflict flags are ignored (recomputed by reconciliation). Schema's
  `n` minimum corrected to 1, matching the spec.
- The listed conformance audit checks are complete and the user approved
  continuation after reviewing the outcome. The type-only registry representation
  decision is settled. Python 3.14 testing remains unavailable locally.
- Type-only `@type` declarations now preserve unused registry entries, context-only
  handles and named binary handles without defining links. They introduce no
  existence/facet/link claims. Value-only subjects still print in line form.
- Log src/at directives and state most-common defaults are used only when every
  claim has the metadata key, since no directive can clear src/at to absent.
- Numeric JSON spelling retains exponents as in the spec; exact Decimal-based
  equality handles exponent/plain equivalents in collections and reconciliation.
- Audited historical/supersession semantics for distinct valid intervals,
  implications of typed mentions/facet attributes, reference-only handles, and
  complete-set claims followed by member retractions (details below).

### Structural review corrections (2026-11-12)

- Reviewed the spec-04/spec-06 changes in jj `rmnzknvw` before applying fixes;
  preserved `.formats`/`$format`, optional integrations and deferred mapping
  contexts/registry support. No bindings, mappings or hexa integration were added.
- Fixed observation value quoting for opening braces at the start or after any
  whitespace, preserving values and provenance through log/state/JSON replay.
- Tightened schemas: fractional-second validity intervals, disjoint claim
  payloads, values required on claims but optional on withdrawals, derived
  dependencies, closed function signatures, concrete collection members and
  fractional-second implicit durations. Added schema/export/spec-example tests.
- Grouped constants, utilities, contextual operations and public APIs; converted
  public function comments into docstrings, completed production annotations,
  documented compatibility exports and clarified printer stage contracts.
- Shared specification extraction and semantic claim comparison in test helpers;
  retained distinct fixtures and whole-document comparisons. Split operator
  compatibility checks from delegation tests. Broad cosmetic renaming of legacy
  test helpers and blanket test annotations remain optional, not a blocker.
- `make test` uses the project's declared dev dependencies; `jsonschema` is
  test-only. The runtime remains standard-library-only. Python 3.14 was not
  available locally with downloads disabled; minimum-version testing remains.
- Clarified contextual claim metadata in specs 04/06, shared scope in the curator
  example and historical minted allocations in spec 05. Phase-2 semantic sign-off
  remains a separate user decision before starting the implementation handoff.

### Updated spec-02 alignment

- Reviewed the user's spec changes in commit `8353b6f`: spec-01 is unchanged;
  spec-02 adds `approved`, producer-scoped withdrawals, implicit markers, identity
  links and strict/lenient identity resolution (with spec-05 semantics).
- Implemented in `observations/`, tested in `tests/T02-003-observations-identities.py`:
  `same`/`distinct` parsing, typed/compatible endpoints, self-link rejection,
  JSON validation and log/state printing; identity-group application before slot
  reconciliation; canonical type refinement and rewriting of subject/reference/
  collection/role/context handles; strict conflicts raise, lenient conflicts warn
  and hold the unapplied link out of state (the original log remains unchanged).
- `@implicit` and JSON `implicit: true` are ignored on input and recomputed from
  surviving references versus existence claims. They do not introduce types;
  `@type` separately handles registry-only declarations.
- Retractions now match `by` when supplied, in addition to source/time. Raw claim
  history is retained until withdrawals have been applied, then identity links and
  supersession run; withdrawing one producer can reveal another producer's earlier
  claim rather than deleting it accidentally. `approved` is retained on withdrawals.
- `reconcileObservations(..., mode="strict"|"lenient")`, loading, JSON import,
  formatting and coverage expose strict/lenient modes (including semantic gaps).
  Referential policies/registry and implicit-age warnings are not
  implemented. Do not advertise full spec-05 support.
- **Identity state-order decision approved and implemented:** state identity links
  retain log order (`at`, then statement ordinal), after records, with original
  endpoints and metadata. Only `!=` endpoints are sorted. Specs 02 and 05 now
  agree. Removed the temporary `identity-order` rejection/replay guard and its
  unused canonical-map return value. Regression tests verify `a=b`, `c=d`, `b=d`
  retains canonical `a`, state idempotence, chronological ordering with timezone
  offsets, ordinal tie-breaking, interleaved `=`/`!=`, and preserved metadata.

### View coverage implemented

- `src/py/onto/coverage.py`: `CoverageItem` and `observationsCoverage`, exported
  from `onto`. Reports reconciled coverage per selected path/subject/context,
  retaining multiple statuses (`supplied`, `unknown`, `absent`, `missing`) and
  conflict/partial flags. Strict reconciliation is automatic and non-mutating.
- Includes nested views, wildcard/explicit facets, inherited attributes, structured
  leaves (bounded at recursive types), association roles and attributes, binary
  selections (including inverse verbs), implied facet applicability and contexts.
- Only surviving non-identity mentions define the subject/context inventory;
  no phantom missing rows for deleted or aliased handles. No known handles/contexts
  produces a `None` placeholder. Binary existence is profile-level; named binary
  attributes and association requests are per instance. Contextual slots use all
  compatible contexts in the document. Missing required data is reported, not
  rejected. No invented observation claims or new observation JSON members.
- `tests/T02-004-observations-coverage.py` includes the complete spec-01/spec-02 examples,
  source conflicts, supersession/retractions, partial/empty collections,
  implicit references, identity aliases and deterministic/pure reporting.

### Lenient semantic gaps implemented

- `Gap` (exported from `onto`) retains original raw line, expanded line-form
  statement, ordinal/location, effective metadata, active context and warning
  diagnostics. `Observations.gaps` is empty by default. Each failing statement is
  atomic: all of its expanded claims/retractions are held back. Syntax/header/
  directive and metadata parsing errors remain fatal, as do document-level
  namespace/revision mismatches. Valid typed mentions can still support other
  statements. Failed named links no longer overwrite an existing handle's type.
- `loadObservations`, `resolveObservations`, `observationsFromJson` accept `mode`;
  formatting passes it through to loading. Strict reconciliation rejects gaps;
  lenient reconciliation retains them. Coverage accepts `mode` and never counts
  gaps as supplied evidence. Read warnings/gaps separately from coverage rows.
- Spec-02 and the JSON schema define optional `gaps`, omitted when empty. JSON
  round trips preserve raw source, locations and diagnostics, revalidating gap
  text/defaults and diagnostic messages. A now-valid gap is rejected, not promoted
  to an executable claim/retraction. Structurally invalid JSON is never downgraded.
- Both public text printers refuse gap-bearing results: ordinary raw statements
  could become active under a later ontology, so pretending they are an inert
  normal form is unsafe. JSON is the gap-preserving interchange form. The private
  log renderer replays gaps only for JSON validation and returns no applied state.
- `tests/T02-005-observations-gaps.py` covers raw/body preservation, statement atomicity,
  defaults/context/ordinal snapshots, unsafe withdrawals, invalid references,
  type preservation, fatal parser boundaries, pure strict refusal, JSON round
  trips, forged gaps/diagnostics and ontology updates that could activate a gap.

### Conformance audit: fixes and review outcome

- `tests/T02-001-observations-conformance.py` follows the new `TODO.md` naming
  convention. All other tests have now been migrated too; pytest collects only
  `T*.py`.
- Fixed reference typing on named binary relation attributes: relation typing
  participates in the bounded typing pass, including uniquely selected relations
  whose endpoints are explicitly typed in reference fields. Endpoints are still
  checked, not inferred without typed evidence.
- Fixed last-member withdrawal: removing the last collection member removes the
  claim instead of synthesising `[]` and contradicting `+` cardinality or claiming
  confirmed absence. Non-mutating reconciliation remains covered.
- Integer accepts integral decimal/exponent spellings. Unrepresentable Decimal
  exponents now raise format diagnostics. Local qualifiers are used during value
  typing (notably Duration units), and `?` does not override inherited fixed
  qualifiers or create spurious conflicts.
- Timestamp/interval comparisons use exact rational UTC seconds rather than
  datetime's truncated microseconds; timezone-boundary dates do not overflow.
- Scope redefinition is rejected rather than silently changing earlier handles'
  identity scope. Directive separators accept whitespace while body indentation
  still requires two spaces. Collections/state values sort by encoded values
  without accidentally consuming a reference's first typed mention.
- A deterministic 120-document replay audit found **16 formerly lossy
  state-sorting cases** involving a complete collection followed by same-source
  member/partial claims at equal `at`. The user approved log-order preservation
  within affected multi-valued slots. Spec-02 rule 9 and the printer now retain
  all claims in those slots in `(at, ordinal)` order, with original provenance,
  resolving source aliases when detecting affected slots. Other slots and
  collection members keep value order; no aggregate claims are invented.
- Removed the temporary `collection-order` rejection. **All 120 replay cases
  now preserve claims and are idempotent without refusals**. Additional tests
  cover unknown/incomplete additions, aliases and `by`, independent member
  sorting, contexts, associations and named binary relation attributes.
- The collection-order and type-only registry decisions are now settled and
  implemented; no known normal-form representation blocker remains.
- Continued identity replay review found a supersession bug: repeated `same` or
  `distinct` evidence from one source was treated as a single-valued slot. For
  `c = a`, `b = a`, `c = a`, discarding the first link changed the canonical
  handle from `b` to `c` on state replay. Identity links now accumulate, as
  spec-02 requires; withdrawals still run first and respect producers.
- Added four regressions for strict/lenient canonical-handle replay, purity,
  text/JSON idempotence, repeated link evidence and producer-scoped withdrawals.
  An additional deterministic exploratory audit checked 2,000 identity-log
  candidates: all 1,247 strict-valid logs preserved their state and formatting
  on replay (conflicting candidates were excluded, not counted as passing).
- Completed the remaining targeted audit with 16 additional regressions:
  disjoint/overlapping validity, inclusive boundaries, sub-microsecond points and
  timezone equivalence; same-source supersession uses `at`, not `valid`, and a
  withdrawal can reveal an earlier observation. Facet attributes imply
  applicability without inventing explicit facet or existence claims, including
  unknown/absent values. Context-only/reference-only handles remain implicit
  only while surviving references name them; registry types survive withdrawal.
- Complete and partial collections retain their surviving members, completeness,
  provenance and producer metadata through member withdrawals and state/JSON
  replay. Complete collections still suppress older members; withdrawing the
  entire snapshot (including its last member) can reveal an earlier producer's
  evidence, consistent with withdrawing an observation rather than claiming
  confirmed absence. Wrong-producer withdrawals leave evidence unchanged and warn.
- A further deterministic exploratory audit checked 500 mixed identity,
  reference, named-relation and withdrawal logs in lenient mode; all preserved
  semantic claims, the full registry and idempotent formatting on state replay.
- No new production defect was found in these remaining checks. The user approved
  phase-2 sign-off and continuation after the review outcome. Python 3.14 remains
  unavailable locally; the phase-2 suite passed all 525 tests on Python 3.15.

### Feature layout migration complete

- Replaced `ontology.py` and `observations.py` with feature packages containing
  `model.py`, `parser.py`, `formatter.py`, `operations.py` and public facades.
  All original definitions were verified AST-identical after extraction, before
  removing the superseded files; the 382 existing tests passed unchanged.
- `Operator` classes in each operations module retain actual context: ontology
  for ontology operations, ontology + mode for observation operations. Top-level
  aliases are `OntologyOperator` and `ObservationsOperator`. They reuse existing
  functions instead of duplicating implementation. No abstract contexts/backends.
- Public functions/types remain available from `onto`, `onto.ontology` and
  `onto.observations`; shared text helpers and cross-feature coverage stay at the
  package root. Model modules also contain shared value/claim helper functions
  needed by parsing, formatting and reconciliation, avoiding dependency cycles.
- Renamed all old `*.test.py` files to the requested numbered convention; added
  `T01-003-ontology-operator.py` and `T02-006-observations-operator.py` for context,
  mode isolation and API/module compatibility. All feature modules' imports and
  type annotations were checked in a fresh interpreter.
- That migration introduced no new syntax or semantic rule. The subsequent
  approved type-only syntax is implemented below. Phase 2 was subsequently
  reviewed and signed off.

### Type-only declarations implemented

- User approved `@type <handle> <Type-or-S.verb.T>` to preserve type information
  without asserting existence, facets or endpoints. No metadata, default changes
  or statement ordinal. Parser AST stores `TypeDeclaration` objects separately
  from statements. Declarations support namespace/aliases, entity specialisation,
  associations and canonical forward binary type paths. Invalid declarations
  remain fatal in both modes; incompatible ordinary statements can still become
  lenient gaps. Retractions do not remove registry types.
- Printer prelude emits declarations sorted by handle only when ordinary typed
  mentions or defining named links cannot preserve the registry. They follow
  source/scope headers and precede `@implicit`. The existing JSON `instances` map
  is sufficient—no new JSON fields or synthetic claims. Strict JSON round-trip
  comparison now succeeds for previously unrepresentable registries.
- `tests/T02-007-observations-type-declarations.py` covers declaration locations,
  ordinals/defaults, forward references, refinement, aliases, fatal invalid forms,
  orphan handles, context-only implicit instances, withdrawn named-link existence
  with surviving attributes, merged named binary aliases, minimal deterministic
  output, lenient gap JSON and non-mutating/idempotent round trips. The prior test
  rejecting unused registries now asserts lossless acceptance instead.

## Later work

- Bindings/mappings/functions (spec-04) and the hexa integration (spec-06): see
  the implementation handoff below.
- Identities (spec-05): referentials, registry, identity links, resolution.
- Overlays (spec-03) and semantic diff.
- CLI (spec-07): static tooling implemented in `src/py/onto/cli/`, tested by
  `tests/T07-*`. Deferred: `bind`/`map` runs (with the hexa integration),
  `diff`, overlays, `formats update`, `.ids`/`.reg` readers.
- JavaScript backend sharing JSON contracts and conformance examples.
- Skills: `docs/skills/` (modeling, review) and `docs/ref/ref-onto-cheatsheet.md`;
  their `onto` blocks are loaded by `tests/T00-001-docs-examples.py`. Install with
  `make install-skills`.

### Modeling gaps (2026-11-16): proposed, not decided

Writing the modeling skills (`docs/skills/onto-modeling`, `onto-review`) showed
three shapes the modeling rules ask for and spec-01 cannot express. The skills
document a workaround for each; remove it from the rule file when the gap
closes. Nothing below is specified or implemented.

1. **Implemented (2026-11-16): spec-01 "Ranges", `T01-012`.** Decided: bounds
   inclusive; a single value `v` is `v..v`; `low <= high` checked (not between
   ISO durations of unknown unit); canonical value `low..high`; `T` is a built-in
   or named type, not inline, not nested; Meta `Kind Range`, `isBasedOn` the
   bound type. Prerequisite, also implemented (spec-01 "Annotations",
   `T01-011`): `{cur=?:V}` (and `unit`, `period`) takes each value's qualifier
   from vocabulary `V`, so that a structure `Amount` + `Currency` can become a
   qualified scalar without losing the currency check. Fixed on the way: an
   observed qualifier contradicting one fixed on the attribute (not the type)
   was accepted. Open: addressing the bounds (`Attr.Low`, `Attr.High`) in
   observations and mapping targets, for sources with separate columns.
   **Ranges** (rule 2.4; workaround: one `T/Range` structure per element type).
   Proposal: a built-in type constructor, not user-defined generics:
   `Price Range<D/Money/USD>`, `Age Range<Years>`.
   - `T` is orderable: `Integer`, `Number`, `Amount`, `Percent`, `Date`,
     `DateTime`, `Duration`, their aliases, or an `{ordered}` vocabulary.
     Qualifiers of `T` apply to both bounds.
   - Values reuse the `valid=` interval syntax: `10..20`, `10..`, `..20`.
   - JSON type expression `{"range": <type>}`.
   - Open: bound inclusivity (and whether it matches `valid=`); whether a
     single value `10` is the range `10..10`; `Meta/Dimension/Kind`.
2. **Partial dates** (rule 2.4; workaround: `PartialDate = Text`).
   Proposal: a `precision` measurement qualifier on `Date` rather than a new
   built-in, which would reserve a name: `Built Date {precision=Month}` accepts
   `2019-03`; `{precision=?}` accepts `2019`, `2019-03` or `2019-03-15` and the
   spelling decides. A `Date` without it stays a full day.
   - Reuses the qualifier rules (inherited through aliases, `?` filled per
     value, never contradicted).
   - Open: comparison and supersession (reading `2019-03` as the interval
     `2019-03-01..2019-03-31`); whether `valid=` accepts reduced precision;
     qualifier values (`Year|Month|Day`). General union types are not proposed.
3. **More than one supertype** (rules 7.2, 4.6; workaround: chain the
   supertypes, most generic at the root, or `{check=supertype}`). A linear chain
   works today; a cross-cutting capability (`Subject`, `Asset`, `Insurable`) on
   entities with unrelated bases does not.
   - Option A (preferred): multi-subject facets, usable as participant and
     reference types: `Subject of Customer, Order, Shipment`, then
     `Note -concerns-> Subject` meaning any instance the facet applies to. Fits
     "a role is a facet"; spec-01 already marks the single subject "(v1)".
     Open: whether domains may add subjects to a facet declared elsewhere;
     addressing (`Subject.Facet.Attr`) is unchanged; the verb-clash rule must
     treat a facet target as related to each of its subjects.
   - Option B: multiple inheritance `E < A, B`. Familiar, but needs rules for
     inherited attribute and facet collisions and widens the verb-clash rule.

Further gaps found applying the rules to the AdviceOS ontology (adviceos-data,
`ONTO_REVIEW.md`, "Limits of onto met in this work"). Proposed, not decided.
Ranked by cost: 4 and 8 are checks only (no syntax), now implemented as
described below, with these differences: the binary-relation rule replaced the
"declared in the later domain" check (a binary relation belongs to the latest of
its ends and its `context`); all `@domain` lines must be in one file and normal
form keeps their order; the `Meta` domain ranks first wherever it is declared;
`Meta/Path` values also resolve to any path `onto meta` generates. 9 and 10
reuse existing machinery; 5, 6 and 7 add syntax.

4. **Implemented (2026-11-16): spec-01 "Layering", `T01-006`.** **Domain layering is not checked** (rule 8.1; workaround: `@domain` lines in
   dependency order by hand and a script listing upward references).
   Proposal: `@ontology layering=declared` makes `@domain` declaration order the
   dependency order. `onto check` then reports, as errors:
   - a reference from an element of domain A to an element of a later domain B,
     in a type, base, facet subject, `ctx=`, participant or `Owner.Attr` reuse;
   - a relation or facet whose two domains differ and which is not declared in
     the later one (for a facet: its namespace is the contributing domain).
   Not references: vocabulary value paths (`Lending/Mortgage` as a value of a
   hierarchical vocabulary), map line values, docs. Elements outside any
   declared domain are exempt. Touchpoints: `ontology/operations.py`
   (`_validate`, one pass after the existing checks; `Model` knows each decl's
   domain from its first segment); spec-01 "Directives" (`layering` header key)
   and a diagnostic code `layering`. JSON: the header key only.
   Open: whether `layering` also orders the file loading or formatting (it
   should not); warning versus error by default.

8. **Implemented (2026-11-16): spec-01 "Meta domain", `T01-007`.** **Observations about the ontology itself are not resolved** (workaround: a
   script comparing `X:Meta/...` handles in `.obs` files with `onto meta`).
   `onto meta` generates `Meta/Concept`, `Meta/Attribute` and `Meta/Dimension`
   records with deterministic handles (`Society_Person__BirthDate`), but an
   observation file that refers to them (`q populates
   Advice_EstatePlanning__Instruments:Meta/Attribute`) only declares an empty
   instance, so a renamed attribute leaves a dangling reference silently.
   Proposal: when the ontology an observation file is checked against declares
   the Meta domain (`metaDeclarations`), the loader treats the generated
   records (`metaObservations`) as part of its context. A handle typed
   `Meta/...` that is not generated is an error (`meta.unresolved`); a value
   of type `Meta/Path` must resolve to a concept, an attribute
   (`Concept.Attr`), a facet attribute (`Concept.Facet.Attr`) or a structure
   field (`Type.Field`), else `meta.path`. Touchpoints:
   `observations/operations.py` (load with an extra resolved context),
   `meta.py` (expose the handle set and a path resolver), `cli/workspace.py`
   (context of `.obs` entries). Open: whether structure fields get their own
   `Meta/Field` records (then `ItemField` could be a reference instead of a
   path); whether `onto meta --decl` output should be checked for staleness by
   `onto check` (`meta.onto` differs from the generated declarations).

9. **Implemented (2026-11-16): spec-04 "Rules", `T04-008`; checked when the library loads, `rule=Lib/Fn` or through an ontology `@use` alias.** **A derived rule is only a token** (workaround: `~ Level <- Score {rule=?}`
   with the thresholds in the doc). Spec-04 already has function libraries
   (`.fn`, `@fn` with signature and examples). Proposal: `{rule=Lib.fn}` on a
   derived attribute names a function of a library; `onto check` with the
   library in context verifies that the function exists, that its arity matches
   the `<-` inputs, and that its result type is compatible with the attribute
   type. The library's examples are the rule's documentation and tests. A
   token without a library stays a free reference (`rule=x26`), as today.
   Touchpoints: `ontology/operations.py` (`_checkAnnotations` for `rule`),
   `functions/operations.py` (`resolveFunctions`), spec-01 annotation table and
   spec-04 "Function library". Open: how an ontology names its libraries
   (`@use Lib` of a `.fn` namespace, or the workspace); evaluation of derived
   attributes stays out of scope.

10. **Implemented (2026-11-16): generated concept, spec-01 "History", `T01-008`; fields `1 Attr`, `OccurredDate Date`, `Reason Text`; declaring the generated concept is an error.** **Dated history of a status is declared by hand** (rules 5.1-5.3;
    workaround: one `X/StatusChange` concept per lifecycle, seven in AdviceOS,
    each `1 Status T`, `OccurredDate Date`, `Reason Text` and a
    `X -hasChange-> X/StatusChange 1:*` relation). Proposal: an attribute flag
    `Status X/Status {history}` meaning "each value reached is an event with a
    date": `onto` derives the change concept `X/StatusChange` (or
    `X/<Attr>Change`) and its relation, visible in `onto meta` and JSON as
    derived declarations. Observations need nothing new: `valid=` already
    dates values, so the alternative is to state that `{history}` attributes
    are always observed with `valid=` and no concept is generated. Open:
    which of the two (generated concept versus required `valid=`); where a
    reason or actor goes; this is open decision 3 of the AdviceOS review.

5. **Implemented (2026-11-16): spec-01 "Extensions", `T01-010`.** Syntax changed
   from `T += A|B` to a vocabulary of the contributing domain,
   `Nz/IncomeMeasure = Paye|Esct {extends=Finance/Income/Measure}`: `+=` had no
   place to record the contributing domain, as files are not tied to domains.
   Decided: open targets only; the extension is closed and not itself extended;
   values must be new; children under existing values allowed (ancestors
   repeated); `{ordered}` appends; flat and hierarchical do not mix; text and
   JSON keep the extension as written, the merge is a reading (`resolveType`,
   maps, observations, `onto meta` values) and `onto meta` adds
   `Meta/Dimension -extends->`. **A later domain cannot add values to an earlier vocabulary** (rule 2.7;
   workaround: generic values renamed, country names in comments, or a
   country vocabulary with an `@map` to the generic one). Proposal:
   `Finance/Income/Measure += Paye|Esct -- NZ income measures` in a later
   domain's file, allowed only on open vocabularies (`|...`), recorded with
   the contributing domain (the values belong to `Nz`, the vocabulary stays
   `Finance`). Hierarchical vocabularies accept `+=` with a tree. Touchpoints:
   parser (`RE_` for `+=` declarations), `Model` (merge after loading, keep
   the contributor per value), `meta.py` (`Values` per contributor), spec-01
   "Vocabularies", JSON (`{"extends": path, "values": [...]}`). Open: whether
   an extension may refine an existing value (children under `Investment`);
   interaction with `{ordered}` (extensions append).

6. **A facet cannot be restricted to some instances of its subject** (workaround:
   `Property/Ownership of Finance/Holding` applies to any holding;
   `Insurance/Insured.Object` is any position). Proposal: a `when` annotation
   on facets of associations naming a participant and a type:
   `Property/Ownership of Finance/Holding {when=Position:Property/Property}`;
   for an entity subject, `{when=Property/Property}` is the subject's own
   specialisation, which is better written as a facet of that specialisation.
   Observations of the facet on a non-matching instance are errors when the
   participant's type is known. Touchpoints: `_validate` (facet branch: role
   exists, type is a specialisation of the role's type), observation loading
   (type check), spec-01 "Facets". Open: one condition or several; conditions
   on attribute values (`when=Type:Joint`) are not proposed.

7. **Implemented (2026-11-16): `{one=G}` means at most one (a group stays optional), spec-01 "Exclusive groups", `T01-009`.** **A structure cannot say "exactly one of these fields"** (workaround:
   `Insurance/Benefit` documents "Amount or PeriodicAmount, not both").
   Fields carry their own types, so an alternation on one line does not fit.
   Proposal: a group annotation on the fields: `Amount Core/Money {one=Value}` and
   `PeriodicAmount Core/MoneyFlow {one=Value}`, where fields sharing a `one=`
   group are mutually exclusive and the group's cardinality is the first
   field's (`1` required, `?` optional). Touchpoints: `_checkAttrs` (group
   consistency), observation validation (more than one of a group is an
   error), spec-01 annotation table. Open: whether the same applies to entity
   attributes; the name of the key (`one`, `xor`, `choice`).

## Spec-04 design review (2026-11-11): decided and written into the specs

The eight open semantics were reviewed with the user and resolved:

1. Retractions carrying `by` withdraw only same `src` **and** `by` (spec-02).
2. Missing input → retraction; a gap (function failure, conversion, conflicting
   input) keeps the previous claim and is reported stale.
3. Binding header `complete=document|record|none` (default `document`); scope
   `deleted=path:value`; a run reads a set of documents.
4. Mapping output `at` = run time. Safeguards: `retract=` ceiling (default
   `20%`) holds retractions; empty input; older snapshots refused.
5. Only the input that gives `src` fans out on conflicts; conflicts in other
   inputs or `when` paths make the line a gap.
6. New **spec-05 Identities**: referentials (`.ref`, policies `key=A[,B] [from=Ns]`
   or `minted [key=...]`), registry (`.reg`), `a = b` / `a != b` links in
   spec-02, resolution and identity conflicts. `{match=...}` removed from
   mappings; mappings name a `referential`; otherwise handles are
   source-qualified (`<T>_` + enc(`scope/key`)).
7. `inverse` means `f(g(y)) = y`; writing reuses the original value when it
   still reads the same, else the field's **formats** entry (`<binding>.formats`,
   learned formats, most common chosen, `pin`); `$format` in bindings. (Originally
   `.codec`/`$codec`; renamed 2026-11-12 to avoid clashing with hexa codecs.)
8. A path through a reference ending at a `{key}` attribute reverses to the
   reference; unknown targets are **implicit instances** (`@implicit` in the
   state form, `"implicit": true` in JSON).

Strict (default, offline, all-or-nothing, approvals) and lenient (online,
warnings, still holds retractions over the ceiling) modes apply to every
processor. Schemas updated: `mapping.schema.json`, `observations.schema.json`
(`same`/`distinct` claims, `implicit`), new `referential.schema.json`; spec JSON
examples validate.

Follow-up decisions (also written):

- **Approval** (spec-04 `#approval`): strict runs are approved by a person only;
  in lenient mode, held retractions are approved by a person or by the next
  `confirm` runs (default `1`) repeating them. Pending retractions a later run
  does not repeat lapse. Approved retractions keep the run's `src`, `by`, `at`
  and carry `approved=<token>` or `approved=confirm:<n>` (new spec-02 key).
- **Implicit age** (spec-05): measured on data `at` (first referencing claim →
  run), never the clock; per-type `implicit=<ISO duration>|never` in the
  referential (an `implicit`-only line is not an identity policy), else the
  run's setting, default `P7D`; a warning in both modes.

Spec-02 additions (identity links, `@implicit`, `by`-scoped retractions, link
application in the state form) affect the phase-2 observations implementation.

## hexa integration (2026-11-12): specified; implemented except the deferred items (see steps 4–6 progress)

onto bindings and mappings are to run as [hexa](../hexa/README.md) shape
pipelines through an optional integration. hexa stays domain-free; onto depends on it, never the reverse.

- **spec-06** (`docs/specs/spec-06-hexa.md`) covers bindings in the reading
  direction: ontology → slots, scope lines → selectors, tolerant shapes, record
  templates and stages; modes → policies; ledger → `BindingReport`; formats
  learning (date/date-time patterns via `parsed`); coverage of observed fields
  against inventories; re-running (stale slots from per-document gaps,
  retractions, completeness, safeguards, confirmation, `Outcome` persisted by
  the host through `OutputPreviousRead`/`RetractionsPendingRead`); mappings
  (state unfolded per scope instance into trees limited to the mapping's reach,
  metadata table keyed by tree pointer and computed by onto, `HandlesResolve` for
  key-derived/source-qualified handles and the instance correspondence,
  conflict fan-out through variant projections). Decided 2026-11-12: metadata
  outside templates, variants for fan-out, contexts deferred, registry deferred;
  writing (reverse mappings compiled as ordinary mappings via an onto
  `mappingReverse`, still to implement in core; documents written by hexa
  fragment templates, then `OriginalsRestore` against a re-read of the previous
  document, `DocumentMaterialize`, writing formats learned by walking raw fields).
- spec-04 renames: `.codec` → `.formats`, `$codec` → `$format` (schema `meta`
  enum updated), coverage "ledger" → "coverage table".
- Generic hexa additions made for it (hexa spec-004/005, language bindings
  spec-002/003): nested slot namespaces, collection captures, evidence and
  `format(value, original)`, parameterised codecs (`DatePattern`), examples,
  `transform` declarations, nested derivations, enclosing capture blocks with
  `project(..., {outer})`, holes for failed fields (`{holes}` policy),
  `tolerant(S)`, `gather($S)` under list items, `parsed($S)`, origins and
  `$Origin`.
- Deferred, in order: contextual facets in mappings, registry-backed identities
  (minted, alternate keys, aliases via `IdentityResolve`), index paths.

### Implementation handoff (2026-11-12)

The specs are complete for this round; implementation is handed to another
agent. Read spec-04, spec-05 (policies only), spec-06 and hexa spec-001/003/004/005
first. Specs are authoritative; if implementing reveals a spec problem, stop and
ask rather than diverging.

**Approval received:** phase 2 (observations) was signed off after the listed
conformance audit and review; the user approved starting this handoff.

### Spec-04 implementation progress

- Read spec-04, spec-05 policies, spec-06 and hexa specs 001/003/004/005.
  hexa remains read-only; its implementation/integration is not part of this slice.
- Implemented the shared expression grammar in `src/py/onto/expressions.py`,
  alongside the existing shared `text.py` and `coverage.py` utilities. Expressions
  use the spec's JSON AST directly, not a second intermediate representation.
  Public APIs (also exported from `onto`): `parseExpression`, `printExpression`,
  `expressionFromJson` and `Expression`.
- Supports binding document paths (root, ancestors, wildcards, indexes, quoted
  fields), mapping metadata, literals with exact decimal spelling, namespaced
  calls and coalescing. Parsing/printing distinguish whole binding quoted fields
  from literal string arguments; `field=False` handles annotation expressions.
  Strict JSON import checks exact variants, member types and text replay; it
  rejects non-round-trippable nodes instead of silently changing their meaning.
- `tests/T04-001-expressions-parsing.py`: 111 tests, including every assigned
  expression in the four complete binding/mapping example files from spec-04,
  schema validation, nested/escaped strings, context boundaries, malformed input,
  non-canonical JSON and non-mutating independent copies. Tests were written
  before implementation. Full `make test`: **636 passed** on Python 3.15.
- The shared expression helpers alone are syntax/interchange only; binding,
  mapping and referential declaration validation are implemented below.
  Pure function calls and conformance are implemented below; expression/claim
  execution and integration remain unimplemented.
- Added `src/py/onto/functions/` with the required model/parser/formatter/operations
  layout and public facade. `parseFunctions` retains locations and raw examples;
  `resolveFunctions`/`loadFunctions` resolve signature types against supplied
  ontologies, type examples using the existing observations reader, and check
  inverse signatures. `printFunctions`, `formatFunctions`, `functionsToJson` and
  `functionsFromJson` provide normal form and strict, detached JSON replay.
  `FunctionsOperator` (also `Operator` in the feature package) retains ontology
  context. APIs are exported from `onto` and `onto.functions`.
- `tests/T04-002-functions-library.py`: 70 tests, including complete `markets.fn`
  normal form/JSON/schema round trips, file-local aliases across library files,
  forward inverses, decimals/collections/reference values, example-local reference
  registries, malformed input, strict JSON and purity/context isolation. All
  **706 tests pass** on Python 3.15. No function implementation is executed;
  executable example/inverse conformance remains step 3, not declaration loading.
- Resolved the `any` example ambiguity with the conservative option after the
  user deferred the design choice: `any`/`any*` are built-in contract notation
  only; declared `@fn` signatures require concrete types. This preserves the
  observation rule that types determine whether a bare value is text or a
  reference, without inventing new literal syntax. Spec-04, the signature schema,
  parser and schema-contract tests now agree. Removed the temporary semantic
  clarification gate and unused generic-type machinery.
- Reviewed function-library replay: JSON collection order is normalized rather
  than treated as example meaning; text delimiters (including an opening bracket
  within text) are quoted safely; canonical alias choice is independent of file
  and alias declaration order. Added regressions for each and clarified example
  text quoting in spec-04. The concrete function-library declaration slice is
  reused by bindings below; execution remains step 3.
- Added `src/py/onto/binding/` with model/parser/formatter/operations and public
  facade. APIs exported from `onto` and `onto.binding`: `parseBinding`,
  `resolveBinding`, `loadBinding`, `formatBinding`, `printBinding`, `bindingToJson`,
  `bindingFromJson`, the binding dataclasses and `BindingOperator`. The operator
  retains the source ontology, optional function libraries and extra ontologies
  used by signatures. Source locations and diagnostics survive declaration loading.
- Complete `exchange.bind` and `sheet.bind` load against their spec ontologies,
  print exactly as their normal-form examples and round-trip through schema-valid
  JSON. Supports nested/quoted expressions in annotations, conditions, `@at`, CSV
  columns, exclusions/docs, facets, roles, forward/inverse binary verbs, and local
  or imported functions and ontology maps. Extracted shared function header,
  example and block helpers rather than duplicating the `.fn` grammar/formatter.
- Binding resolution checks header domains (revision differences warn), ontology
  targets, duplicate assignments, function names/arity and statically known type
  or collection mismatches. References are fully qualified in JSON and shortened
  only for text. Enclosing-instance references require a defining parent scope;
  root objects, list/indexed records and equivalent `$` paths are covered.
  Contextual facets require a scope context; known incompatible context/reference
  types fail. Document-only exclusions cannot read ancestor records.
- `tests/T04-003-binding-parsing.py`: 70 tests, written before implementation and
  fixes, covering spec fixtures, text/JSON purity and replay, imports/aliases,
  context isolation, malformed declarations and strict JSON. Fresh full
  `make test`: **776 passed** on Python 3.15; `git diff --check` passes. Python
  3.14 remains unavailable locally. No documents are read and no functions,
  bindings or run policies are executed. Dynamic document checks, coverage,
  formats and hexa remain later steps. Mapping declarations follow below.
- Added `src/py/onto/mapping/` with the required feature layout and public facade.
  `parseMapping`, `resolveMapping`, `loadMapping`, `formatMapping`, `printMapping`,
  `mappingToJson`, `mappingFromJson`, mapping dataclasses and `MappingOperator`
  are exported from `onto` and `onto.mapping`. Operators retain both ontologies,
  imported function/type contexts and an explicit set of known referential names.
- Complete `exchange-finance.map` and `finance-sheet.map` load and round-trip
  through schema-valid JSON and canonical text. The import's aligned docs are
  normalized to one separator, as the inherited spec-01 normal-form rules require.
  The JSON excerpt is tested with its omitted local map and issuer correspondence
  supplied, rather than pretending it is a semantically complete standalone file.
- Static checks cover source/target types, inherited/facet/structured/reference
  paths, association roles and binary verbs/cardinalities; function/map names and
  signatures; duplicate targets; fixed qualifier contradictions; `src` expression
  membership; `reverse` reference reach; candidates; conditions; and view reach
  through references and nested views. Explicit or inferred contextual inputs
  retain their context type through correspondence checks. No execution is added.
- Reference correspondence is translated before output type checks. Multiple
  applicable `->` scopes are errors; no correspondence warns of future run-time
  gaps, without inventing target instances. Unmapped references cannot bypass
  scalar-target type checks. Source and target models remain separate for
  same-namespace revision mappings, including vocabulary-map validation.
- Reused binding call typing and annotation splitting, function declarations and
  codecs, ontology map validation/normalization, and existing view selections.
  Added `Model.namespaces()` so imported declarations physically carried by an
  ontology (as `Dimensions` is in the Finance example) are recognized by function,
  binding and mapping contexts. Existing feature tests remain green.
- `tests/T04-004-mapping-parsing.py`: 67 tests. Fresh full `make test`:
  **843 passed** on Python 3.15; `git diff --check` passes. Minimum-version
  testing still needs Python 3.14. At this checkpoint, referential names were
  checked only for declaration interchange; loaded policy/key checks follow below.
  Execution, inverse
  conformance, coverage/reversal, formats, run policies and hexa remain deferred.
- Added `src/py/onto/referential/` with the required feature layout. Public APIs
  from `onto` and `onto.referential`: `parseReferential`, `validateReferential`,
  `loadReferential`, `formatReferential`, `printReferential`, `referentialToJson`,
  `referentialFromJson`, `referentialPolicy`, `referentialImplicit`, `Referential`
  and `ReferentialOperator`. The root policy type is `ReferentialPolicy` (the
  feature model calls it `Policy`). All runtime code remains standard-library-only.
- Full spec-05 text and JSON examples round-trip, preserving key order, source
  restrictions, minted/alternate-key declaration metadata, fractional-second
  implicit durations and docs. Multi-file headers/revisions agree; aliases are
  file-local and cannot redefine one alias to another namespace across files.
  Normal form is independent of file order. Strict JSON validates exact members,
  non-null optionals, true flags and policy variants before text replay.
- Policy validation checks entity/association types, `{key}` attributes (including
  inherited keys), known source ontologies, duplicate identities/ages and forbidden
  subclass identity overrides. Age-only declarations do not introduce an identity
  policy or mask a base policy; ages inherit independently from the nearest base.
  Separate identity/age rows retain their docs instead of being merged silently.
  Revision warnings concern ontologies supplying covered types, not unrelated
  input-provider ontologies; revalidation recomputes them without duplication.
- Mappings now require `referentials=[loadedReferential]`; the temporary name-set
  input no longer pretends to validate policies. Selected policies are revalidated
  against the actual target revision (including changed key annotations). Duplicate
  referential names fail. An effective inherited key policy requires some assigned
  policy key, including for `from`-restricted policies as spec-04 validation states;
  candidate-only assignments count only when enabled. Minted/age-only rows do not
  require derived keys. Updated mapping spec fixtures to provide actual policies
  and the JSON excerpt's omitted `Isin` assignment.
- `tests/T05-002-referential-policies.py`: 63 tests covering declarations, inheritance,
  strict JSON, purity, context isolation, lookup metadata and mapping key checks.
  Fresh full `make test`: **906 passed** on Python 3.15; `git diff --check` passes.
  Python 3.14 remains unavailable locally. No registries, minted allocation,
  alternate-key resolution, handle generation, implicit-age run warnings or hexa
  were implemented. Next: step 3, exact-decimal built-in/function evaluation and
  executable example/inverse conformance.
- Completed the core function-execution slice in `functions/runtime.py`.
  `FunctionEvaluator` and `FunctionResult` are exported from `onto` and
  `onto.functions`; `FunctionsOperator.evaluator(...)` shares its ontology
  context and `.conformance(library, implementations)` runs explicit checks.
  Declaration loading still never executes implementation code.
- User-approved spec-04 clarifications: rounded results use half-even; scalar
  application over several collection arguments uses their Cartesian product,
  not positional pairing. Follow-up execution questions were approved too:
  `null` takes precedence over `?` (except `{nulls}`), and `count`/`join` give gaps
  for incomplete collections rather than pretending the known members are all.
- Built-ins cover text/Unicode transforms, split/join/count, numeric/text
  conversion, date-pattern parsing/formatting and epoch/date conversion. Decimal
  arithmetic is isolated from ambient precision/rounding: sum, multiply and
  subtract are exact; terminating division is exact, otherwise 16 significant
  digits with half-even. No arithmetic computes through binary floats.
  Exact operations trap inexactness/underflow beyond Decimal's representable
  range, returning a gap instead of silently producing zero.
- Registered library functions use full paths, local functions use names;
  loaded ontology maps and explicit local maps support lookup. Arguments and
  results are validated with observations encoding and concrete ontology-backed
  signatures. Implementation inputs/results are detached. Domain exceptions,
  invalid result types and missing/ambiguous map entries become reasoned gaps;
  unresolved names, arity errors and missing implementations are configuration
  errors. `ref` explicitly returns a gap without binding execution context; no
  handle generation or registry work was added.
- `evaluate` returns an individual `FunctionResult` for every Cartesian
  application, including individual failures and incomplete-input metadata;
  collection-typed arguments/results remain whole encoded values. It deliberately
  does not assemble claims or merge fan-out outcomes; that belongs to the later
  binding/mapping executor. Conformance checks every example, compares numeric
  values and sets semantically, and checks `f(inverse(y)) = y` without requiring
  restoration of input spelling. Failures are accumulated with example locations.
- `tests/T04-005-function-execution.py`: 69 tests, including the complete Markets
  library, explicit inverse-only failures, ambient decimal-context isolation,
  cancellation, exact long quotients, Cartesian calls, partial collections,
  nulls, malformed values, output signatures, local functions/maps and purity.
  Fresh full `make test`: **975 passed**; `git diff --check` passes. Python 3.14
  remains unavailable locally. Binding/mapping execution, claim provenance,
  reversal restrictions, registries and hexa remain deferred. Next: step 4,
  static coverage/inventories, default bindings and mapping reversal/loss reports.

### Steps 4–6 progress (2026-11-12): static operations and the hexa integration

- **Step 4 (onto core, no hexa).** `inventory/` (`parseInventory`, `printInventory`,
  `documentFields`, `inventoryFromDocuments`, `defaultBinding`), `formats/`
  (`parseFormats`, `printFormats`, `formatsUpdate`: tallies, most frequent chosen
  unless pinned, changes listed), coverage rows and `printCoverageTable` in
  `coverage.py`, `bindingCoverage` (ontology side, document side against an
  inventory, uninventoried reads) and `mappingCoverage` (statuses ranked direct >
  transformed > condition > ambiguous, view-restricted, unassigned `To` elements),
  `mappingReverse` → `(Mapping, [LossyLine])` with the generated forms of spec-06.
  The spec tables/examples are reproduced (coverage table, lossy lists of both
  example mappings). Tests `T04-006-coverage-static.py`, `T04-007-mapping-reversal.py`.
- **Step 5 (hexa).** Not modified: `../hexa` already provides what the integration
  needs (another session is moving it to `src/py/hexa`; pytest's `pythonpath`
  now includes `../hexa/src/py`). hexa ships no runner for vocabulary examples, so
  `vocabularyConformance()` runs every `Onto` codec/transform example instead.
- **Step 6 (integration)**, `src/py/onto/integrations/hexa/`, tests `T06-001..005`
  (skipped without hexa): vocabulary (codes, constraints, codecs, transforms
  wrapping `FunctionEvaluator`); binding compiler and `BindingRead` (spec-06
  Dividend record and `DatePattern.Invalid` hole reproduced); `$format` reading,
  format tallies, observed fields, writing-format discovery; `BindingRun`/
  `MappingRun` re-running (stale slots, completeness, deleted records, ceiling,
  empty input, older snapshots, `replaces`/`of`, lenient confirmation, lapsing,
  person approval, `Outcome`); mappings (`HandlesResolve` key-derived/source-
  qualified, unfolding with metadata tables, conflict variants, mixed provenance,
  qualifier/integer/vocabulary conversions, `MappingRun`); writing
  (`compileWrite`/`BindingWrite`, originals, formats, nested placement, CSV
  columns, parentless records, null policies) and reverse mappings run end to end
  (Finance → Sheet CSV → Sheet → Finance trades through `Isin`).
- **Integration representation differences (folded into spec-06, 2026-11-16):**
  1. Positions are `either(Null, tolerant(P))`, not `tolerant(P | Null)`: hexa reports
     a union whose branches fail differently as `Issue.Mismatch`, hiding codec reasons.
  2. Nested scope paths are selected level by level: hexa's selector fails as a whole
     on one missing path, which lost every dividend when one instrument had none.
  3. Stages are named but not registered (`StageNamespace`, not hexa `stages`): hexa
     registers stage and namespace names process-wide, so two programs with the same
     scope types (or a recompile) would clash.
  4. hexa derivations cannot leave a key out without a hole, so transforms return a
     marker (`{"absent": true}`) that `ClaimsEmit` drops; `Onto.Ref` values carry an
     internal `type` (stripped before claims) to type implicit instances.
  5. Integer attributes read through `Onto.IntegerText` (hexa refuses `DecimalText`'s
     canonical `Decimal` for a `Decimal where Integral` slot). Extra transforms:
     `Read`, `Set`, `Field`, `Nullable`, `At`, `Given`, `Members`.
  6. Transform gap codes live under the transform (`Onto.Handle.KeyMissing`); reports
     map them to `Binding.*`/`Mapping.*`. **Function dispatch isolation fixed
     (2026-11-16):** transforms/codecs now carry their evaluator instead of using
     a process-wide call table. Compiling another program cannot replace their
     implementations or inverse functions. Function transforms and codecs can
     share a name without competing in hexa's registry.
  7. Facet claims share their header's `n` (or carry an existence claim): `h[F]` in
     spec-02 text also asserts existence, so JSON otherwise fails its round trip.
  8. **Resolved (2026-11-16):** writing formats include `decimals:N`, `padded`,
     `case:upper`, `case:lower` and `trim`, with padding taking precedence over case.
- Still deferred: registry identities (minted, alternate keys), index steps,
  `key=A,B` policies, hexa-side conformance runner. Contextual mappings are
  implemented below.

### Integration deviation review (2026-11-16)

- Baseline: 1,368 tests passed. Reproduced the shared-dispatch defect with two
  programs using different implementations of the same function: both ran the
  most recently compiled implementation. Also reproduced a hexa name collision
  when that function was used as a transform and a codec in the same process.
- Removed the mutable dispatch table and evaluator-dependent caches. Compiled
  transforms/codecs are program-local copies of registered generic prototypes,
  with stable names/reason codes and their own evaluator and canonical shape.
  No hexa files were changed. `T06-001` regressions cover equal encodings,
  concurrent reads, retained older programs, transform/codec coexistence and
  inverse writing after another writer compiles.
- Deviation 1 preserves codec gap reasons; deviation 2 preserves unaffected
  nested records; deviation 3 avoids process-wide stage-name collisions.
  These are implementation adaptations, not reasons to weaken the semantics.
  Their representations are now documented in spec-06, including the compiled
  Dividend shape example.
- Deviation 4 uses internal absence/reference-type markers, stripped before
  observation interchange. Deviation 5 uses an Integer-specific codec and
  auxiliary transforms. These, deviation 6's report-code translation and
  deviation 7's facet/existence statement ordinals are now documented in
  spec-06. The unsafe shared function dispatch is no longer an accepted limitation.
- Deviation 8 resolved after user approval: decimal text contributes
  `decimals:N`; otherwise padding wins over uniform case, with mixed-case and
  uncased text contributing `trim`. Spec-06 documents the single-format
  precedence. `T06-002` covers Unicode case, uncased/empty text, padding and
  numeric boundaries, learning/updating and writing with the learned formats.
  Original spellings still win over a competing chosen case when unchanged.
  Full `make test`: 1,438 passed; no changes to hexa.
- Corrected spec-06's stale null/unknown sentence to match the approved spec-04
  contract: null takes precedence. `T06-004` tests both input orders, unknown
  without null, input purity and facet/existence ordinals with shared and
  different provenance.
- Contextual mapping facets are implemented below. Next: registry identities
  and index paths.

### Contextual mappings implemented (2026-11-16)

- Mapping paths retain their contextual facet type. Attribute-slot selection
  filters by context; finite reach discovers contexts through references.
  Global lines emit once; contextual reads unfold in source-context handle order,
  with no cross-context value mixing. Contextual scope conditions and metadata
  expressions run per context. Identical existence claims are not repeated.
- Contexts translate through the instance correspondence. Scope `ctx=` replaces
  the inherited context; conflicting override inputs cannot be hidden by
  coalescing. Only contextual facet/attribute claims carry `ctx`, never existence
  or non-contextual claims. Context-only handles retain types without synthetic
  existence. Missing correspondence produces gaps instead of context-free claims.
- Re-running matches stale slots by output context and actual source-input
  provenance. It can retain one context while retracting another. Scope-condition
  conflicts protect existence and affected slots. Failed conflict variants are
  reported and held stale, not silently withdrawn. Retractions retain context
  registry types even if the new input no longer names them.
- `tests/T06-006-hexa-contexts.py`: 19 regressions, including input purity,
  reference reach, collections, null/unknown/zero, conditional facets, explicit
  contexts, context-only instances, conflicts, mixed sources and re-running.
  Spec-06 now documents the execution path; no hexa changes or dependencies.
  Full `make test`: **1,462 passed** on Python 3.15; `git diff --check` passes.
  Python 3.14 validation remains outstanding.

### Index steps implemented (2026-11-17)

- Needed by the AdviceLink CRM API (adviceos-data), which returns related rows
  as 2-element arrays (`[member, client]`); without index steps neither half
  could be bound. No hexa change: hexa spec-004 rules out index access and
  matches fixed positions with `Tuple` and `rest`, which serves this case.
- A scope path's selector stops before its first index step; the rest prefixes
  every path its lines read (`rows[*][0]` selects `rows/*`). Relative keys hold
  positions as integers; a node of positions compiles to `Tuple(..., rest(Any))`
  with `Any` where unread. `Onto.Field` indexes lists, for paths read below a
  captured field. Field slots name positions `At<n>`.
- Still unsupported: an index step before `[*]` in a scope path, and a value read
  both as a position and as a field (`Binding.PathUnsupported`). Writing is
  unchanged.
- `tests/T06-007-hexa-index-steps.py`: 7 tests (selectors, tuple shapes, pairs
  read into two types, body positions, short lists, missing positions, the two
  unsupported cases). `T06-001`'s unsupported-index test now covers `a[0].b[*]`.
  Spec-06 Selector, Shape and Deferred updated. Full `make test`: **1,469 passed**.
- Two spec-04 conformance fixes found binding the same API, in
  `tests/T06-008-hexa-binding-values.py` (5 tests):
  - `ref(Type, key)` applies to each member of a collection key (`ref(Adviser,
    advisers[*].id)` into a multi-valued attribute), as spec-04 requires of any
    function given a collection; it gave `Ref.TypeMismatch`.
  - A selected record that is JSON `null` makes no instance and no gap (spec-04
    presence); it was a `TypeMismatch` gap. Documented in spec-06 Selector.
  Full `make test`: **1,474 passed**.

### Type-directed instance correspondence (2026-11-17)

- Approved by the user while mapping the AdviceLink CRM to AdviceOS: a client row
  is both a `Society/Person` and a `Client/Relationship`, and spec-04 made any
  reference to a source type with several `->` lines an error.
- spec-04 Instances: each `->` line makes its own target instance; a reference
  translates through the line whose target type the receiving attribute, role or
  verb accepts (or one it specialises); several or none fitting is an error (two
  lines to the same type stay ambiguous). `$` alone in a mapping is the scope
  instance as a reference (`Client <- $`), so a second scope can name the first
  scope's target instance.
- Static: `mapping.operations.correspondenceTarget` (shared with the compiler),
  `translate(inferred, accepted)`, `acceptedTypes`. `$` parses in mappings only
  alone; coverage ignores it.
- Runtime: `HandlesResolve` keeps `targets[source][targetType]` beside the
  first-scope `correspondence`; `$target` is per scope; references to such
  instances carry `targets`; `Onto.CorrespondAs(value, type)`; `$self` root when
  a scope reads `$`. Spec-06 updated.
- `tests/T06-009-hexa-mapping-correspondence.py` (6 tests); `T04-001` now accepts
  `$` alone in mappings. Full `make test`: **1,481 passed**.
- Found running the AdviceLink mapping:
  - A reference to an instance its scope's `when` skips had no type in the
    output log (`observationsFromJson` failed on the untyped handle). References
    now carry their target type (`targetType`; `Correspond`/`CorrespondAs` keep
    it), so such targets are typed implicit instances; links record it too.
  - Source-qualified handles (approved by the user): `<T>_` + enc(`<scope>/<S>/<key>`),
    adding the source type, since two source types mapped to one target type
    (a CRM client and user with the same id) produced one handle. Spec-04,
    spec-05 examples and spec-06 updated; handle assertions in `T06-004`,
    `T06-005`, `T06-006` and `T06-009` updated to the new form.
  Full `make test`: **1,482 passed**.
- `Onto.CorrespondAs` returned hexa's missing marker for an absent reference
  instead of `ABSENT_VALUE`, failing the record's template (`Issue.Mismatch`).
  `T06-009` covers an absent reference. Full `make test`: **1,483 passed**.

Work in this order; each step is test-first and leaves `make test` green.

1. **spec-04 models and parsers (onto core).** Packages `binding/`, `mapping/`,
   `functions/` under `src/py/onto/`, each with `model.py`, `parser.py`,
   `formatter.py`, `operations.py` and an `Operator`, per the conventions above.
   Text ↔ model ↔ JSON (`onto.binding/1`, `onto.mapping/1`, `onto.functions/1`,
   validated against `src/json/mapping.schema.json`), normal form, and the
   spec-04 validation errors/warnings. Resolution of names against loaded
   ontologies and libraries. Tests `T04-*`, starting from the spec-04 examples
   (`exchange.bind`, `markets.fn`, `exchange-finance.map`, `finance-sheet.map`,
   `sheet.bind`).
2. **Referentials (spec-05), policies only.** `referential/` package parsing
   `.ref` (JSON `referential.schema.json`); `key=A` and `key=A from=Ns` used by
   the integration. Registry, minted handles and alternate keys stay deferred.
3. **Functions (onto core).** The spec-04 built-in functions with exact decimal
   arithmetic (`decimal`, never float), `@fn`/`@map` evaluation contract, and a
   conformance runner executing every example and inverse round trip. The
   integration wraps these; it must not reimplement them.
4. **Static operations (onto core).** Static coverage and the coverage table
   (spec-04 Coverage, inventories), default bindings, and `mappingReverse` with
   its lossy report (spec-04 Reversal). These need no hexa.
5. **hexa Python library** (separate repo `../hexa`, package `hexa`, spec-003).
   The integration needs: shapes and matching (including `tolerant`, `gather`,
   collection captures, nested slot namespaces), codecs (table, code,
   parameterised, examples, `format(value, original)`), transforms and nested
   derivations, `capture`/`expand`/`project` with holes, `outer` and `parsed`,
   selectors with enclosing capture blocks, `$Location`/`$Origin`, combinators
   (`stages`, `pipe`, `lift`, `select`, `each`, `collect`, `recover`), the runtime
   (effects, `join`, ledger, journal and replay, origins) and the conformance
   runner. Use `hexa/examples/mortgage-people` fixtures as its first acceptance
   test. Confirm with the user whether that agent also owns hexa.
6. **Integration** in `src/py/onto/integrations/hexa/` (spec-06 Layout), loading
   hexa lazily (`IntegrationUnavailable`); onto core never imports it. Tests
   `T06-*`, skipped when hexa is missing. Sub-steps, each a vertical slice:
   1. vocabulary + binding compiler + `BindingRead`: the spec-04 feed read into
      the `Exchange` log, including the spec-06 `Dividend` record and a
      `DatePattern.Invalid` hole;
   2. formats learning and observed-field coverage;
   3. `BindingRun` re-running: stale slots, completeness, safeguards,
      confirmation, `Outcome` (fake host store via `OutputPreviousRead`);
   4. mappings: `HandlesResolve`, unfolding, metadata, variants; the spec-04
      `Exchange -> Finance` claims, plus a conflicting `Class` case;
   5. writing: reverse mappings through `mappingReverse`, `BindingWrite` with
      originals restored (the spec-06 writing example) and CSV for `sheet.bind`.

Constraints: Python ≥ 3.14, standard library only (hexa is the integration's only
dependency, and optional), review-py conventions (tabs, module docstrings,
camelCase functions, `# EOF`), JSON values with decimals as strings, no network
in tests, replay journals instead of live effects.

### Write-back safety, exclusive lines and named bindings (2026-11-18)

Found mapping the AdviceLink CRM to AdviceOS (adviceos-data `TODO_ONTO.md`):

- **Derived targets are not written back.** `mapping/reversal.py` reports a line
  lossy ("derived target, not written back") when its target is derived in the
  output ontology or its reverse assigns a derived attribute of the input;
  `integrations/hexa/writing.py` never writes a derived binding target (spec-04
  Reversal). Tests: `T04-007`, `T06-005`.
- **Exclusive lines.** One target may be assigned by lines whose `when` read one
  path with distinct values, plus at most one default without `when`
  (`checkExclusive`, spec-04 Instances). Each compiles to its own record key
  (`LineInfo.slot`, `Key#n`); the default is guarded by `Onto.WhenNone`, reads the
  condition path (a conflict there is a conflicting input) and is lossy under
  reversal. The formatter orders the default first, then by condition value.
  Bindings keep one line per target. Tests: `T06-013`.
- **Structure targets rejected by check** (`checkScalarTarget`), for bindings and
  mappings, matching the compiler's "no scalar value type". Tests: `T04-003`, `T04-004`.
- **Named bindings.** Header `name=<token>`; claims and re-run requests use
  `by=bind:<Namespace>/<name>` (`bindingBy`). Tests: `T06-003`.
- **`into` over a collection.** A multi-valued selector selects its one member
  (`Onto.Single`); several or an incomplete set are `Mapping.ReferenceAmbiguous`.
  Tests: `T06-012`.
- **`Range<T>` in function signatures** (`SignatureType.range`, JSON `range: true`).
  Tests: `T04-002`.
- **Source references.** `ref(S, Key)` in a mapping (`S` from `From`, distinct from
  `To`): resolved while unfolding (`MappingScopePlan.sourceRefs`, root slots
  `$ref<n>`) to `<S>_<key>`, translated through the correspondence; instances it
  names that the state lacks are added as implicit (`implicitReferences`).
  Generated reverses keep `ref(T, Key)` over target types. A line whose `when`
  is false (or a default whose sibling matched) reports no projection gaps
  (`lineApplies`). Tests: `T06-014`.
- **Chosen targets.** `{as=T}` on a mapping line translates its reference to the
  target of type `T` (`chosenTarget`, `Onto.CorrespondEmitted`): a target the
  scope's `when` skips is a gap (`HandlesResolve` records `skipped`), an
  instance known only by reference takes `T`. Tests: `T06-014`.
- **Mappings over several files** (spec-04, spec-07): files with one `@mapping
  From -> To` header are one mapping (`parseMappings`, then one `resolveMapping`;
  `loadMapping` takes a source or a list). The CLI groups them like ontologies.
  Tests: `T04-004`, `T07-001`.
- **`onto run`** (spec-07): one-shot binding and mapping runs through the hexa
  integration (`Commands.cmdRun`, `mergedLogs`); gaps are `run.gap` warnings,
  errors with `--strict`. `bin/onto` adds a sibling `../hexa/src/py` to the path.
  Tests: `T07-002`.
- **Workspace exclusions.** `cli/ignore.py`: `.gitignore` then `.ontoignore` per
  directory, gitignore patterns (no global excludes), excluded directories
  pruned; named files still read (spec-07 Indexing). Tests: `T07-001`.
- **Index steps before `[*]`** in binding scope paths (`groups[0].items[*]`): a
  selector level `*` filtered by position (`ScopeProgram.picks`, `selectStage`),
  counted as a record level; writing pads the list. hexa is unchanged (its
  spec-004 has no index access by design). Tests: `T06-001`, `T06-007`.
- **Conditional facets.** `{when=Attr:Value}` on a facet (spec-01): checked on
  declaration (`_checkFacetCondition`: a single-valued, observed scalar attribute
  of the subject and a value of its type) and in observations
  (`_checkFacetConditions`, code `when`, per source, overlapping `valid`).
  Tests: `T01-013`.
- **Keyed structures.** A structure's `{key}` vocabulary field keys the elements
  of a multi-valued attribute: attribute paths `Phones[Mobile].Number`
  (`RE_ELEMENT_PATH`, `unkeyed`, `Model.elementKey`, `Model.elementPathError`),
  in observations (statements, JSON, schema; retraction by element or attribute),
  binding and mapping targets, and mapping paths (`{key: ...}` steps,
  `keyedSteps`). Unkeyed multi-valued structures warn (`key`). Hexa slot names
  write keys as `Phones.KeyMobile`. Tests: `T02-009`, `T06-015`.

## Workspace hygiene

The project now is a Git repository. Do not modify the original
reference project. Earlier backups of the pre-neutralisation docs were made at
`/tmp/onto-specs-backup`, `/tmp/onto-json-backup`, `/tmp/onto.vim-tests-backup`.
For any new temporary work, prefer the approved `/tmp/opencode` directory.
