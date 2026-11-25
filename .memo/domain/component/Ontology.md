---
identity: "onto:component:ontology"
created: 2026-11-25T19:44:09.892142+00:00
updated: 2026-11-25T19:44:25.019798+00:00
title: Ontology component
---
# Ontology component

**Owns** the ontology format (spec-01): parsing, semantic validation, the
canonical text and JSON forms, the semantic model other features query, the
generated `Meta` domain and semantic diffs.

- *Package*: `src/py/onto/ontology/` (`model.py`, `parser.py`, `formatter.py`,
  `operations.py`), plus `rooted.py` (rooted views resolved to typed
  populations and paths) and `changes.py` (model-first comparison). `meta.py`
  at the root describes an ontology as observations of its `Meta` domain.
- *Interfaces*: `parseOntology`, `loadOntology`, `validateOntology`,
  `printOntology`, `formatOntology`, `ontologyToJson`, `ontologyFromJson`,
  `normaliseOntology`, `ontologyDiff`, `printOntologyDiff` and `Operator`
  (`OntologyOperator`, holding the ontology). `Model` answers the semantic
  lookups of every other feature (types, inheritance, facets, relations,
  namespaces carried by imports, keyed elements).
- *Multi-file*: the files of one namespace share revision and header defaults;
  aliases are file-local, and one alias names one namespace across files.
- *Derived readings*: vocabulary extensions, `{history}` change concepts and the
  `Meta` declarations are derived when loading and never written back
  ([domain/decision:VocabularyExtensions+015], [domain/decision:HistoryConcept+013]).
- *Boundaries*: knows nothing of observations or execution. Checks that need
  another feature run from that feature: `rule=` from function libraries, `Meta`
  references from observations.

Sources: `docs/specs/spec-01-ontology.md`, `docs/specs/spec-07-cli.md` (`snap`,
`diff`, `meta`), `src/py/onto/ontology/`, `src/py/onto/meta.py`
