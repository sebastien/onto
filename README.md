# onto

Compact text formats for conceptual models (ontologies), instance data
(observations), the mappings between systems and the identities of the records
they describe. The specifications are in
[`docs/specs`](docs/specs) and the JSON schemas in [`src/json`](src/json).

## Status

Phase 1 implements [spec-01](docs/specs/spec-01-ontology.md) in Python: parsing,
validation, normal form, printing and the JSON form of ontologies. Phase 2 is
in progress: observations parsing, ontology-backed typing, JSON conversion,
reconciliation and log/state printing are available. Lenient gaps and view
coverage are not yet implemented, nor are the identity links, implicit
instances and `by`-scoped retractions added to spec-02 with spec-05. Overlays
(spec-03), bindings and mappings (spec-04), identities and referentials
(spec-05), the identity sidecar file, `OntologyDiff`, the CLI and a JavaScript backend are not
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

### Observations (partial spec-02)

```python
from onto import (
    loadObservations, reconcileObservations, observationsToJson,
    observationsFromJson, printObservationsLog, printObservationsState,
)

log = loadObservations(ontology, Source("statement.obs", observationsText))
state = reconcileObservations(ontology, log)    # does not mutate the log
data = observationsToJson(state)               # JSON-ready data
again = observationsFromJson(ontology, data)    # strict import through text validation
auditText = printObservationsLog(ontology, log)
stateText = printObservationsState(ontology, state)
```

`parseObservations` and `resolveObservations` expose the individual stages.
`formatObservations(ontology, source, form="state")` combines loading,
reconciliation and printing; `form="log"` retains the audit log.
Logs retain all claims, retractions and 1-based statement ordinals. Reconciliation
applies source-scoped retractions and supersession, retains partial collection
members, and marks conflicting single-valued claims across sources. Source aliases
are compared by provenance token. Unmatched retractions add warning diagnostics.

Dates and date-times are calendar-validated; timezone offsets are respected when
ordering claims. Unzoned date-times and date-only timestamps use UTC for comparison,
not the machine's timezone. Required attributes omitted from a document are not
treated as cardinality errors.

JSON import checks object members, value variants, metadata, registered instance
types and statement shapes before validating through log-form text. It preserves
original statement ordinals (text formatting renumbers them) and ignores incoming
`conflict` flags; reconciliation recomputes conflicts. Noncanonical numeric JSON
strings are rejected rather than silently rewritten.

**Remaining text-representation edge:** JSON import rejects registries containing
unused handles, or a named binary handle without a surviving defining link.
Reconciliation may produce these registries, but text has no type-only directive
to preserve them without inventing claims. Log/state printing emits facts only;
it does not preserve unused registry entries. A surviving value-only subject is
printed in line form rather than introducing a new existence header. These cases
need a format decision before phase 2 is considered complete.

Decimal values remain strings, without precision loss. Exponent spelling is
normalised but retained (`1.250E+03` → `1.25e3`). Collection duplicate checks,
retractions and conflict checks compare numeric values exactly, so `1e3` and
`1000` compare equal on numeric slots, but remain distinct on Text slots.

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
