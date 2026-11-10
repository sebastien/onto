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

## Phase 1 status (2026-11-11): implemented, 121 tests passing — awaiting user review

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

## Later phases (not started)

- Observations (spec-02): parsing/typing, claims, contexts, time, reconciliation,
  conflicts, retractions, state/log forms and JSON.
- Bindings/mappings/functions (spec-04), initially a worked generic-exchange
  vertical slice, then coverage, libraries, reversal and re-running.
- Overlays (spec-03), identities, semantic diff and CLI.
- JavaScript backend sharing JSON contracts and conformance examples.

## Design cautions for later spec-04 work

The spec was drafted without a running engine. Review questionable semantics
before implementation instead of silently encoding them: reliable ownership of
retractions (spec-02 uses `src`, not `by`), gaps versus true removals, complete
snapshots versus partial feeds, timestamps on recomputation, preserving
conflicting claims after combining inputs, globally stable handles, lossy
built-ins advertised as inverses, and reference-key availability during reverse
projections. Raise proposed semantic changes with the user.

## Workspace hygiene

The parent workspace is not a Git repository. Do not modify the original
reference project. Earlier backups of the pre-neutralisation docs were made at
`/tmp/onto-specs-backup`, `/tmp/onto-json-backup`, `/tmp/onto.vim-tests-backup`.
For any new temporary work, prefer the approved `/tmp/opencode` directory.
