# onto

Compact text formats for conceptual models (ontologies), instance data
(observations), the mappings between systems and the identities of the records
they describe. The specifications are in
[`docs/specs`](docs/specs) and the JSON schemas in [`src/json`](src/json).

## Status

Phase 1 implements [spec-01](docs/specs/spec-01-ontology.md) in Python: parsing,
validation, normal form, printing and the JSON form of ontologies. Phase 2 is
signed off: observations parsing, ontology-backed typing, JSON conversion,
reconciliation, log/state printing, view coverage and lenient semantic gaps are
available. Spec-02 identity links, implicit instance
markers, `by`-scoped retractions and `approved` metadata are implemented. Spec-04
implementation has started with shared expressions, function-library, binding and mapping
declarations, canonical printing and strict JSON import. `onto.functions`
supports concrete built-in/named signatures, typed examples and inverse-signature
checks; unrestricted `any` is reserved for the built-in contracts. Pure function
execution and executable example/inverse conformance are available. Bindings and
mappings support declaration loading, static
validation and text/JSON normal forms; execution is not implemented yet.
Referential declarations (spec-05) now support policy validation, inheritance and
mapping key checks. Registries, minted allocation, alternate-key matching and
implicit-age run warnings remain unimplemented, as do overlays (spec-03), the
identity sidecar file, `OntologyDiff`, the CLI and a JavaScript backend.

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

The `ontology/`, `observations/`, `functions/`, `binding/`, `mapping/` and `referential/` packages under
`src/py/onto/` each contain
`model.py`, `parser.py`, `formatter.py` and `operations.py`, plus a public
`__init__.py`. Models hold types, constants and shared value/claim helpers;
parsers read text/JSON; formatters produce canonical text/JSON; operations
validate, load and reconcile. Shared lexical utilities remain in `text.py`, and
cross-feature view reporting in `coverage.py`. `expressions.py` holds the shared
spec-04 expression grammar used by bindings and mappings.

Existing `onto`, `onto.ontology` and `onto.observations` imports are preserved.
Each feature also exports an `Operator`: `OntologyOperator(ontology)` and
`ObservationsOperator(ontology, mode="strict")`, plus
`FunctionsOperator(ontologies)`, `BindingOperator(ontology)` and
`MappingOperator(fromOntology, toOntology)` and `ReferentialOperator(ontologies)`
from the top-level package.
Binding/mapping operators optionally retain imported libraries and extra type
ontologies as well.
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

The top-level `onto` exports are the recommended API. Feature packages also
retain grammar constants, lexical helpers and low-level printers as compatibility
exports; package-private `_name` helpers may be shared between feature modules.
Stateless functions remain available alongside context-retaining operators.

`printOntology` renders an already normalized ontology; `OntologyOperator.print`
normalizes first. Observation log printing takes a typed log, while state
printing takes a reconciled state. Neither text printer accepts unresolved gaps;
use JSON to preserve those review records.

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

### Shared expressions (first spec-04 slice)

```python
from onto import parseExpression, printExpression, expressionFromJson

expr = parseExpression("multiply(Price, Quantity)")  # mapping syntax
path = parseExpression('row."asset class"', binding=True)
text = printExpression(path, binding=True)
again = expressionFromJson(expr)                     # independent validated copy
```

Expressions use the JSON nodes of `mapping.schema.json`. `binding=True` admits
document paths (`[*]`, indexes, `$`, `^`) and `$format`; mapping expressions
instead admit `$valid`, `$at` and `$src`. A whole quoted binding expression is
a field name; strings inside calls or `??` are literals. For binding annotation
expressions such as `id=`, pass `field=False` to keep a whole string literal.
Invalid or non-round-trippable expressions raise `ValueError`. These helpers
do not resolve names, type-check against ontologies or evaluate functions.

### Function-library declarations (spec-04)

```python
from onto import Source, loadFunctions, printFunctions, functionsToJson, functionsFromJson

library = loadFunctions([dimensionsOntology], [Source("markets.fn", libraryText)])
text = printFunctions(library)
data = functionsToJson(library)                 # onto.functions/1
again = functionsFromJson([dimensionsOntology], data)
```

`parseFunctions` retains source locations and raw examples; `resolveFunctions`
checks them against supplied ontologies. Libraries may span files with matching
namespace/revision and file-local aliases. Loading validates signature types,
example encodings and reversed inverse signatures, but does not execute any
implementation or check executable inverse round trips. Declared signatures use
concrete types (`Text`, `Integer`, named types/references, or `T*` collections);
`any` and `any*` are built-in notation only. Invalid libraries raise `FormatError`.

### Function execution and conformance

```python
from onto import FunctionEvaluator

evaluator = FunctionEvaluator()
result, = evaluator.evaluate("sum", ["0.1", "0.2"])
assert result.reason is None and result.value == "0.3"

# Implementations take observations-encoded values, not Python floats.
evaluator = FunctionEvaluator(
    [dimensionsOntology], [library], implementations=implementations,
)
checked = evaluator.conformance(library)  # all examples plus f(inverse(y)) = y
```

Register library implementations by full path (`Markets/FrequencyFromInterval`),
and local implementations by name. Supply local declarations with
`functions=binding.functions` or `functions=mapping.functions`; local value maps
use `maps=mapping.maps`. Ontology value maps are found in the supplied ontologies.
Calls use already-resolved names, not file-local aliases. `FunctionsOperator`
also exposes `evaluator(...)` and `conformance(library, implementations)`.

`evaluate` returns one `FunctionResult` per Cartesian application. Each result
has a typed, detached `value`, or a gap `reason`; `partial` records incomplete
lifted inputs. Collection-typed arguments/results stay observations-encoded
collections. Claim assembly and merging application outcomes remain the future
binding/mapping executor's responsibility. Unknown names, wrong arity and missing
implementations raise `ValueError`; domain errors (including implementation
exceptions and invalid output encodings/types) return gap reasons. Conformance
collects located failures in `FormatError`; loading declarations stays non-executing.

Arithmetic never uses binary floats or the caller's decimal precision: sums,
products, subtraction and terminating quotients are exact; non-terminating
quotients use 16 significant digits, half-even. `null` propagates before `?`,
unless the declaration has `{nulls}`. `count`/`join` reject incomplete collections.
`ref` requires the deferred binding execution context and currently returns a gap.

### Binding declarations (spec-04)

```python
from onto import Source, loadBinding, printBinding, bindingToJson, bindingFromJson

binding = loadBinding(sourceOntology, Source("exchange.bind", bindingText))
text = printBinding(binding)
data = bindingToJson(binding)                   # onto.binding/1
again = bindingFromJson(sourceOntology, data)
```

`parseBinding` retains locations and untyped local function examples;
`resolveBinding` checks them against the source ontology. Optional `libraries`
and extra `ontologies` provide imported functions and signature types. Validation
checks header domains, target names/duplicates, function names/arity, known
expression types and collection cardinality, references and enclosing scopes.
Revision differences warn. Contextual facets need a scope context expression.

Printing is canonical and JSON import checks exact members and lossless text
replay. These operations do not read JSON/CSV data, execute functions, learn
formats, compute coverage or produce observations. Document-dependent checks and
run policies belong to the later execution/integration steps.

### Mapping declarations (spec-04)

```python
from onto import Source, loadMapping, printMapping, mappingToJson, mappingFromJson

mapping = loadMapping(fromOntology, toOntology, Source("projection.map", mappingText))
text = printMapping(mapping)
data = mappingToJson(mapping)                   # onto.mapping/1
again = mappingFromJson(fromOntology, toOntology, data)
```

`parseMapping` retains source locations and local `@fn`/`@map` declarations;
`resolveMapping` validates scopes, paths through structures/references, types,
cardinality, view restrictions, targets and reference correspondence. Local and
imported functions, conditions, contexts, candidates, exclusions, `src` and
`reverse` annotations are retained and checked. Unmapped references warn that
execution would produce a gap; ambiguous correspondence is an error.

Optional `libraries` and extra `ontologies` supply imported declarations.
`referentials=[marketIds]` supplies **loaded referentials**, not names. Policies
are revalidated against the actual target ontology revision. A target with an
effective inherited key policy must assign at least one of its keys; disabled
candidate lines do not count. This static check also applies to `from`-restricted
key policies; that restriction controls handle derivation later, not whether a
key is assigned. Minted and implicit-only declarations do not impose this check.
The temporary names-only API is no longer accepted. These APIs do not execute
mappings, propagate claim metadata, reverse mappings or produce observations.

### Referential policy declarations (spec-05)

```python
from onto import Source, loadReferential, referentialToJson, referentialPolicy, referentialImplicit

ontologies = [financeOntology, exchangeOntology]
marketIds = loadReferential(ontologies, [Source("market-ids.ref", referentialText)])
data = referentialToJson(marketIds)             # onto.referential/1
policy = referentialPolicy(ontologies, marketIds, "Finance/Instrument")
age = referentialImplicit(ontologies, marketIds, "Finance/Instrument")
```

`parseReferential`, `validateReferential`, `printReferential`, `formatReferential`
and `referentialFromJson` expose the stages. Files share a namespace/revision and
have file-local aliases. Keys must name `{key}` attributes, including inherited
ones; the first key stays primary. Identity policies cannot override a base's
policy. Implicit-age declarations inherit independently, nearest first, and do
not mask an inherited identity policy. Queries use fully qualified type paths.

The complete spec example round-trips, including minted/alternate-key declaration
metadata. No registry is read, no handle is allocated and no alternate key is
matched. Implicit ages are returned as metadata only; no clock or age-warning
processor is implemented.

### Observations (spec-02)

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

The tests use pytest (`tests/T{spec}-{number}-{feature}-{name}.py`), run through
`uv` with the project's development dependencies; set `PYTEST` to use another
runner. `jsonschema` is test-only; onto retains no runtime dependencies.
The complete example of spec-01 and its JSON excerpt are loaded
from the specification itself, so the spec and the implementation stay in step.
