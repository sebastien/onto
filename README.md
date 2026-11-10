# onto

Compact text formats for conceptual models (ontologies), instance data
(observations) and the mappings between systems. The specifications are in
[`docs/specs`](docs/specs) and the JSON schemas in [`src/json`](src/json).

## Status

Phase 1 implements [spec-01](docs/specs/spec-01-ontology.md) in Python: parsing,
validation, normal form, printing and the JSON form of ontologies. Observations
(spec-02), overlays (spec-03), bindings and mappings (spec-04), the identity
sidecar file, `OntologyDiff`, the CLI and a JavaScript backend are not
implemented yet.

## Python API

Python ≥ 3.14, standard library only.

```python
from onto import Source, loadOntology, formatOntology, ontologyToJson, ontologyFromJson

sources = [Source("finance.onto", text)]       # one or several files of one ontology
ontology = loadOntology(sources)               # parse + validate; raises FormatError
text = formatOntology(sources)                 # normal-form text
data = ontologyToJson(ontology)                # JSON form (`onto.ontology/1`)
again = ontologyFromJson(data)                 # strict: rejects anything that does not round-trip
```

`FormatError.diagnostics` lists every error and warning, each with a `code`,
`message` and source `loc`. `parseOntology`, `validateOntology`,
`normaliseOntology` and `printOntology` expose the individual stages;
`Model` answers lookups (lineage, facets, attributes, resolved types).

## Implementation choices

Where spec-01 leaves room, the implementation decides:

- Files of one ontology must share the namespace and `rev`, and their header
  defaults must agree in effect (`card`, `cards`, `rel`), since one normal form
  is printed with one header. Aliases are file-local, but one alias cannot mean
  different namespaces in different files.
- A view that includes itself, directly or through other views, is an error.
- In JSON, a view line selecting `S.verb.T` uses the relation path as its `path`.
- CR line endings are rejected (the spec requires LF).

## Tests

```sh
make test
```

The tests use pytest (`tests/*.test.py`), run through `uv`; set `PYTEST` to use
another runner. The complete example of spec-01 and its JSON excerpt are loaded
from the specification itself, so the spec and the implementation stay in step.
