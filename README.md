# onto

Compact text formats for conceptual models (ontologies), instance data
(observations), the mappings between systems and the identities of the records
they describe. The specifications are in
[`docs/specs`](docs/specs) and the JSON schemas in [`src/json`](src/json).

## Status

Phase 1 implements [spec-01](docs/specs/spec-01-ontology.md) in Python: parsing,
validation, normal form, printing and the JSON form of ontologies. Phase 2 is
in progress: observations parsing, ontology-backed typing, JSON conversion,
reconciliation, log/state printing, view coverage and lenient semantic gaps are
available. Spec-02 identity links, implicit instance
markers, `by`-scoped retractions and `approved` metadata are implemented. Overlays
(spec-03), bindings and mappings (spec-04), referential policies and registries
(spec-05), the identity sidecar file, `OntologyDiff`, the CLI and a JavaScript backend are not
implemented yet.

## Integrations

Integrations connect onto to other libraries. They live under
`src/py/onto/integrations/` and are optional: onto never imports them, and each
one loads its library only when it is itself imported.

- **hexa** ([spec-06](docs/specs/spec-06-hexa.md), specified, not implemented):
  compiles bindings and mappings into [hexa](../hexa/README.md) shape pipelines,
  which run them with journaled effects, replay, failure policies and a gap
  ledger. It covers reading documents into source observations, mappings between
  ontologies, re-running both, and writing documents back. In onto,
  "binding" means a document-to-ontology correspondence; in hexa it means a
  language binding.

## Layout

The `ontology/` and `observations/` packages under `src/py/onto/` each contain
`model.py`, `parser.py`, `formatter.py` and `operations.py`, plus a public
`__init__.py`. Models hold types, constants and shared value/claim helpers;
parsers read text/JSON; formatters produce canonical text/JSON; operations
validate, load and reconcile. Shared lexical utilities remain in `text.py`, and
cross-feature view reporting in `coverage.py`.

Existing `onto`, `onto.ontology` and `onto.observations` imports are preserved.
Each feature also exports an `Operator`: `OntologyOperator(ontology)` and
`ObservationsOperator(ontology, mode="strict")` from the top-level package.
Operators retain the ontology/mode context across calls; the functional API
remains available.

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

For repeated operations with one context:

```python
from onto import OntologyOperator, ObservationsOperator

ontologyOps = OntologyOperator(ontology)
text = ontologyOps.print()
obsOps = ObservationsOperator(ontology, mode="lenient")
log = obsOps.load(Source("statement.obs", observationsText))
state = obsOps.reconcile(log)
data = obsOps.toJson(state)
```

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
Retractions with `by` also match the producing process; without `by` they can
withdraw any producer's claims from that source. Withdrawals are applied to the
log's retained history before supersession, so withdrawing one producer's latest
claim does not discard another producer's earlier claim.

`a = b` and `a != b` links remain in the audit log. Reconciliation applies
surviving same-instance links in log order, then resolves claims on and references
to aliases under the canonical handle, refining its type when necessary. Links
themselves keep their original endpoints. Identity conflicts raise `FormatError`
by default; `reconcileObservations(ontology, log, mode="lenient")` warns and does
not apply the conflicting link (`!=` wins). Held links stay in the original log,
not in the applied state. Loading, reconciliation, JSON import, formatting and
coverage accept `mode="strict"|"lenient"`; strict remains the default.

State identity links print after records in log order (`at`, then statement
ordinal), keeping their original endpoints and metadata. This preserves canonical
choices on replay (including `a=b`, `c=d`, `b=d`). `!=` endpoints are sorted,
but links are not reordered by operator or handle.

Referenced handles without surviving existence claims are marked `implicit` in
state JSON and listed in `@implicit` in state text. These display markers are
ignored on input and recomputed, like conflict flags. They do not introduce types
or existence claims; referenced handles must still be typed in the document.
Referential-specific implicit-age warnings remain a later phase.

Dates and date-times are calendar-validated; timezone offsets are respected when
ordering claims, including exact sub-microsecond fractions. Unzoned date-times and date-only timestamps use UTC for comparison,
not the machine's timezone. Required attributes omitted from a document are not
treated as cardinality errors.
Integral decimal/exponent spellings are accepted for Integer values. Measurement
qualifiers are resolved before typing uses (including a local Duration unit);
`?` never overrides a known inherited qualifier. Decimal exponents outside the
standard library's supported range produce format diagnostics rather than raw
runtime exceptions. A document cannot silently change its `@scope`.

JSON import checks object members, value variants, metadata, registered instance
types and statement shapes before validating through log-form text. It preserves
original statement ordinals (text formatting renumbers them) and ignores incoming
`conflict` and `implicit` flags; reconciliation recomputes them. Noncanonical numeric JSON
strings are rejected rather than silently rewritten.

Registry-only declarations preserve types without inventing existence:

```text
@type p Person
@type scenario Planning/Scenario
@type r Household.hasMember.Person
```

`@type` carries no metadata, changes no defaults and consumes no statement
ordinal. It supports entities, associations and canonical binary relation paths,
using the ontology namespace/aliases. Compatible refinement is allowed; invalid
declarations are fatal in both modes. Retractions do not erase registry types.

The log/state printers emit necessary declarations sorted by handle after the
header/source/scope prelude and before `@implicit`. Ordinary typed mentions are
used instead whenever they can preserve the registry. Thus unused handles,
context-only handles and named binary handles without defining links survive
text/JSON round trips. JSON uses the existing `instances` map—no new claim or
member. A value-only subject still prints in line form rather than introducing
an existence header.

Decimal values remain strings, without precision loss. Exponent spelling is
normalised but retained (`1.250E+03` → `1.25e3`). Collection duplicate checks,
retractions and conflict checks compare numeric values exactly, so `1e3` and
`1000` compare equal on numeric slots, but remain distinct on Text slots.

When a multi-valued slot retains a source's complete collection and later claims,
state printing preserves that slot's log order (`at`, then statement ordinal),
including every claim's provenance. It does not merge claims into a synthetic
aggregate. Other slots remain value-sorted, and collection members stay sorted
by encoded value. Withdrawing a collection's last known member
removes that claim rather than manufacturing `[]` (confirmed absence).

### Lenient gaps

```python
log = loadObservations(ontology, Source("statement.obs", observationsText), mode="lenient")
for gap in log.gaps:
    print(gap.loc, gap.raw, gap.diagnostics)
state = reconcileObservations(ontology, log, mode="lenient")
data = observationsToJson(state)
again = observationsFromJson(ontology, data, mode="lenient")
```

Semantically invalid statements become `Gap` objects with raw source, expanded
line-form text, original location/ordinal, metadata defaults, active context and
warning diagnostics. Each statement is atomic: none of its expanded claims or
retractions applies. Valid statements continue. Valid typed mentions can still
support other statements, without introducing existence claims.

Syntax, metadata syntax/keys, headers and directive errors remain fatal; the
loader does not guess document interpretation. Strict reconciliation rejects
unresolved gaps. Lenient coverage counts only retained claims, not gaps.

Optional JSON `gaps` preserves the review material and is omitted for gap-free
documents. Import validates gap statements and diagnostics against the ontology;
it rejects gaps that have become valid rather than silently activating them.
Both text printers reject gap-bearing results: text has no inert gap syntax, and
printing a raw gap as an ordinary statement could execute a retraction under a
later ontology. Use JSON until the original input has been reviewed/reprocessed.

### View coverage

```python
from onto import observationsCoverage

items = observationsCoverage(ontology, log, "PortfolioReview")
for item in items:
    print(item.path, item.subject, item.ctx, item.statuses)
```

Coverage reconciles the log strictly without modifying it. Each `CoverageItem`
identifies a selected path, a subject and (for contextual facets) a context.
Its `statuses` retain all observed states: `supplied`, `unknown`, `absent` or
`missing`; `conflict` and `partial` flag conflicting evidence and incomplete
collections. Missing data is a coverage result, not a cardinality error.
Pass `mode="lenient"` to report retained valid claims despite unresolved gaps;
inspect the input log's `gaps` and diagnostics separately from the coverage rows.

Nested views and repeated selections are deduplicated. Structures expand to leaf
fields; recursive structures stop at the repeated type and report the remaining
container from its observed descendants. Facet attributes imply applicability.
Contextual slots are checked separately against every compatible context mentioned
in the surviving data. If no subject/context is known, `None` identifies a missing
profile request, not a new instance.

Only handles mentioned by surviving non-identity claims are checked, including
implicit references, so deleted handles and identity aliases do not create phantom
missing rows. Binary existence is reported once per selected relation type
(anonymous links count); named relation attributes and association roles are
checked per instance. Selected participants and facet contexts contribute
identity-only requests, not requests for their unrelated attributes.

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

The tests use pytest (`tests/T{spec}-{number}-{feature}-{name}.py`), run through `uv`; set `PYTEST` to use
another runner. The complete example of spec-01 and its JSON excerpt are loaded
from the specification itself, so the spec and the implementation stay in step.
