# Continue: Python ontology implementation

## Goal and agreed scope

Implement the onto formats in Python, in phases. **The current phase is spec-02
observations**, including its recent identity-link and implicit-instance additions.
Spec-01 has been implemented and reviewed. Finish and review observations before
implementing bindings/mappings, referential policies/registries or overlays.

Current layout follows `TODO.md`: `src/py/onto/{ontology,observations}/` each has
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

## Phase 2 status: implementation progressing — conformance audit pending

- Latest `make test`: **426 passed** (all phase-1 and phase-2 tests), Python 3.15.
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
- Still TODO before phase-2 review: finish the conformance audit and review the
  phase-2 outcome. The type-only registry representation decision is now settled.
- Type-only `@type` declarations now preserve unused registry entries, context-only
  handles and named binary handles without defining links. They introduce no
  existence/facet/link claims. Value-only subjects still print in line form.
- Log src/at directives and state most-common defaults are used only when every
  claim has the metadata key, since no directive can clear src/at to absent.
- Numeric JSON spelling retains exponents as in the spec; exact Decimal-based
  equality handles exponent/plain equivalents in collections and reconciliation.
- Also audit historical/supersession semantics for distinct valid intervals,
  implications of typed mentions/facet attributes, reference-only handles, and
  complete-set claims followed by member retractions before phase-2 sign-off.

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

### Conformance audit: fixes and remaining decisions

- `tests/T02-001-observations-conformance.py` follows the new `TODO.md` naming
  convention. All other tests have now been migrated too; pytest collects only
  `T*.py`. Do not overwrite or delete the user-authored `TODO.md` file.
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
  approved type-only syntax is implemented below; conformance review still
  precedes phase-2 sign-off.

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

- Finish observations (spec-02), as listed above.
- Bindings/mappings/functions (spec-04), initially a worked generic-exchange
  vertical slice, then coverage, libraries, reversal and re-running.
- Identities (spec-05): referentials, registry, identity links, resolution.
- Overlays (spec-03), semantic diff and CLI.
- JavaScript backend sharing JSON contracts and conformance examples.

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
   still reads the same, else the field's **codec** (`<binding>.codec`, learned
   formats, most common chosen, `pin`); `$codec` in bindings.
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

## Workspace hygiene

The project now is a Git repository. Do not modify the original
reference project. Earlier backups of the pre-neutralisation docs were made at
`/tmp/onto-specs-backup`, `/tmp/onto-json-backup`, `/tmp/onto.vim-tests-backup`.
For any new temporary work, prefer the approved `/tmp/opencode` directory.
