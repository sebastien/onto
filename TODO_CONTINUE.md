# Continue: Python ontology implementation

## Goal and agreed scope

Implement the onto formats in Python, in phases. **The current phase is spec-01
only:** ontology parsing, validation, normal form, printing and JSON conversion.
Review this phase before implementing observations, bindings/mappings or overlays.

Agreed layout: `src/py/onto/`, `pyproject.toml`, `tests/*.test.py` with pytest,
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

- `src/py/onto/{text,ontology,__init__}.py`, `pyproject.toml`, `Makefile` (`make test`
  runs pytest through `uv`), `tests/ontology.test.py`, `tests/json.test.py`, `README.md`.
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

## Phase 2 status: first slice implemented — not a complete spec-02 delivery

- Latest `make test`: **254 passed** (all phase-1 and phase-2 tests), Python 3.15.
- `src/py/onto/observations.py`: `parseObservations`, `resolveObservations`,
  `loadObservations`, `observationsToJson`, `reconcileObservations`,
  `printObservationsLog`, `printObservationsState`, `formatObservations`,
  `observationsFromJson`; exported from
  `onto`. AST/document/log dataclasses retain locations and diagnostics.
- `tests/observations.test.py`: complete main spec-02 example, its JSON excerpt,
  typed references (including forward reference values), ordinals, metadata,
  contexts, dates, qualifiers, collections, retractions and reconciliation.
- Reconciliation is non-mutating; source aliases compare by provenance token;
  timestamps compare actual instants (unzone/date-only uses UTC); partial sets
  accumulate, complete sets replace earlier members from that source.
- Log/state printers and strict JSON reader added. Complete spec-02 example is
  idempotent in both normal forms; JSON log import/export preserves ordinals.
  Incoming conflict flags are ignored (recomputed by reconciliation). Schema's
  `n` minimum corrected to 1, matching the spec.
- Still TODO before phase-2 review: lenient gaps, view coverage, full conformance
  audit; settle representation cases below.
- JSON import explicitly rejects unused registry entries and named binary handles
  without defining links: text cannot encode their type without inventing claims.
  Reconciliation can leave such entries; printers emit facts only, so a standalone
  text round trip can lose those unused types. Need a format decision, not a fake
  existence claim. Value-only subjects print in line form for the same reason.
- Log src/at directives and state most-common defaults are used only when every
  claim has the metadata key, since no directive can clear src/at to absent.
- Numeric JSON spelling retains exponents as in the spec; exact Decimal-based
  equality handles exponent/plain equivalents in collections and reconciliation.
- Also audit historical/supersession semantics for distinct valid intervals,
  implications of typed mentions/facet attributes, reference-only handles, and
  complete-set claims followed by member retractions before writing printers.

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

The parent workspace is not a Git repository. Do not modify the original
reference project. Earlier backups of the pre-neutralisation docs were made at
`/tmp/onto-specs-backup`, `/tmp/onto-json-backup`, `/tmp/onto.vim-tests-backup`.
For any new temporary work, prefer the approved `/tmp/opencode` directory.
