---
identity: "onto:pattern:feature-package"
created: 2026-11-25T19:44:11.132437+00:00
updated: 2026-11-25T19:44:26.388540+00:00
title: Feature packages
---
# Feature packages

**Context**: every format (ontologies, observations, bindings, mappings,
function libraries, referentials, inventories, formats files) needs a model, a
parser, a canonical printer, JSON interchange and operations over loaded
documents, with the same conventions in each.

**Approach**: one package per feature, `src/py/onto/<feature>/`:

| Module | Holds |
|---|---|
| `model.py` | Data structures, plus the value and claim helpers that parsing, printing and reconciling share, so that those modules need not import each other |
| `parser.py` | Text parsing and strict JSON decoding, keeping source locations |
| `formatter.py` | The canonical text form and detached JSON encoding |
| `operations.py` | Resolution against the loaded context, validation and the feature's operations, under an `Operator` class |
| `__init__.py` | The public facade; `onto` re-exports it |

- The `Operator` holds the actual context of its operations and nothing more:
  the ontology for ontology operations, the ontology and mode for observations,
  both ontologies, libraries and referentials for mappings. It reuses the
  functional forms rather than duplicating them; `onto` exports it under the
  feature's name (`OntologyOperator`, `ObservationsOperator`, ...).
- Larger features add modules (`runtime.py`, `reversal.py`, `coverage.py`,
  `rooted.py`, `changes.py`). Cross-feature helpers live at the package root.
- Integrations live in `src/py/onto/integrations/<name>/`, import their library
  only when imported, and raise `IntegrationUnavailable` without it.

**Trade-offs**: more files per feature, and models that carry helpers besides
data. No abstract contexts or backends were introduced: an operator holds only
what its operations use.

**Example**: `src/py/onto/mapping/` adds `reversal.py` and `coverage.py`; its
`Operator` holds both ontologies, the function libraries and the loaded
referentials.

Sources: `TODO.md` at `da01e2c` ("Conventions", "Feature layout migration
complete"), `src/py/onto/`
