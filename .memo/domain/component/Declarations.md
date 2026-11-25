---
identity: "onto:component:declarations"
created: 2026-11-25T19:44:10.432426+00:00
updated: 2026-11-25T19:44:25.596810+00:00
title: Declarations component
---
# Declarations component

**Owns** the static side of integration (spec-04, and spec-05 policies):
binding, mapping and referential declarations, their checks against the
ontologies and libraries in context, and the operations that need no data:
coverage, inventories, default bindings, formats files and reversal.

- *Packages*: `binding/` (with `coverage.py`), `mapping/` (with `coverage.py`
  and `reversal.py`), `referential/`, `inventory/` and `formats/`, each a
  [domain/pattern:FeaturePackage]; at the root, `expressions.py` (the shared
  expression grammar, whose JSON form is the AST) and `conditions.py` (`when`
  and `deleted` conditions).
- *Interfaces*: per format, `parse…`, `resolve…`, `load…`, `print…`,
  `format…`, `…ToJson` and `…FromJson`, and an `Operator` holding its context:
  `BindingOperator` (source ontology, libraries), `MappingOperator` (both
  ontologies, libraries, loaded referentials), `ReferentialOperator`. Static
  operations: `bindingCoverage`, `mappingCoverage`, `printCoverageTable`,
  `inventoryFromDocuments`, `defaultBinding`, `formatsUpdate` and
  `mappingReverse`, which returns the reverse mapping and its lossy lines.
- *Checks*: targets and paths through inheritance, facets, structures,
  references, roles and verbs; function and map signatures; qualifiers;
  conditions; reference correspondence
  ([domain/decision:TypedCorrespondence+018]; `correspondenceTarget` is shared
  with the compiler); exclusive lines; key policies a mapping relies on. A
  mapping may span several files with one header.
- *Boundaries*: no execution; the hexa integration runs what these packages
  check ([domain/component:HexaIntegration]). Referentials are policies only:
  no registry, minted handles or alternate keys
  ([domain/decision:ReferentialIdentities+002],
  [domain/decision:CompositeKeys+022]).

Sources: `docs/specs/spec-04-mapping.md`, `docs/specs/spec-05-identities.md`,
`src/py/onto/binding/`, `src/py/onto/mapping/`, `src/py/onto/referential/`,
`src/py/onto/inventory/`, `src/py/onto/formats/`
