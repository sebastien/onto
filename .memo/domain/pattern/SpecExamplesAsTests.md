---
identity: "onto:pattern:spec-examples-as-tests"
created: 2026-11-25T19:44:11.314111+00:00
updated: 2026-11-25T19:44:26.624170+00:00
title: Specification examples as tests
---
# Specification examples as tests

**Context**: the specifications are authoritative, and their examples are the
clearest statement of intended behaviour. An example that drifts from the
implementation misleads people and agents alike.

**Approach**:
- Tests load examples from the specifications instead of copying them:
  `specExample(name, index, kind)` in `tests/helpers.py` returns a fenced block
  of a spec. Complete examples (`exchange.bind`, `markets.fn`,
  `exchange-finance.map`, ...) must load, print as their normal forms and
  round-trip through schema-valid JSON.
- `tests/T00-001-docs-examples.py` loads every `onto` block of the skills and
  the cheatsheet.
- Test files are numbered by specification, `tests/T{spec}-{n}-{feature}-{name}.py`;
  pytest collects only `T*.py`. Tests are written before the implementation,
  and each step leaves `make test` green.
- Tests use no network: effects are answered from recorded journals or a local
  server. hexa tests are skipped when hexa is not installed.
- `make test-js` records every binding, mapping and view run of the Python
  suite (`tests/conformance.py`) and replays it on the JavaScript runtime.

**Trade-offs**: an edit to a specification example can break tests far from
the change, so editing a specification is deliberate.

**Example**: `tests/T04-003-binding-parsing.py` loads the `Exchange` and `Sheet`
ontologies with `specExample("spec-04-mapping", ...)` and checks the spec's
bindings against them.

Related: [domain/pattern:ReplayAudit]

Sources: `tests/helpers.py`, `tests/T00-001-docs-examples.py`,
`docs/specs/spec-06-hexa.md#bundles-and-the-javascript-runtime`, `TODO.md` at
`da01e2c` ("Conventions", "Implementation handoff")
