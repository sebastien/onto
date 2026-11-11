# Running bindings and mappings on hexa

How [bindings](spec-04-mapping.md#bindings) and
[mappings](spec-04-mapping.md#mappings) run as
[hexa](../../../hexa/docs/specs/spec-001-shape_pipelines.md) programs. spec-04
defines what they mean; this spec defines one way to execute them, by compiling
them into hexa shapes, selectors, templates, codecs and stages. hexa then
provides retrieval, effects, the journal and replay, failure policies and the run
ledger, identically in its JavaScript and Python language bindings.

hexa knows nothing about onto. Everything here is built from generic hexa
constructs: nested slot namespaces, enclosing captures, tolerant positions,
holes, nested derivations, parameterised codecs, examples and origins
([hexa spec-004](../../../hexa/docs/specs/spec-004-shape_pipelines_shapes.md),
[spec-005](../../../hexa/docs/specs/spec-005-shape_pipelines_stages.md)).

**Scope.** This version covers bindings in the reading direction (documents to
source observations, in the log form of
[spec-02](spec-02-observations.md#json-form)), with [formats](#formats) learning,
[coverage](#coverage) and [re-running](#re-running); [mappings](#mappings)
between ontologies, sharing re-running; and [writing](#writing): reversed mappings
and documents written by bindings. Contextual facets in mappings and
registry-backed identities are [deferred](#deferred).

## Terms

Both specs use some of the same words for different things:

| Word | In onto | In hexa |
| --- | --- | --- |
| Binding | Correspondence between document fields and a source ontology (`.bind`) | A language binding (JavaScript, Python) |
| Projection | A mapping from a curated ontology to an output ontology | A shape and a template read as one function |
| Codec | Not used (the learned spellings are [formats](spec-04-mapping.md#formats)) | A `parse`/`format` pair between a source format and a canonical value |
| Coverage | Static status of each element: `direct`, `transformed`, ... | Per-value status: `Supplied`, `NotSupplied`, ... |
| Gap | A value that could not be translated; the claim is omitted | An expected absence, reported in the ledger |

In this spec, "binding" means an onto binding unless it says "language binding".
The sections from [Correspondence](#correspondence) to the
[binding example](#binding-example) describe bindings; [Mappings](#mappings)
builds on them.

## Integration

The integration lives in `src/py/onto/integrations/hexa/` and is optional:

- Nothing else in onto imports hexa. `import onto` works without hexa installed.
- `onto.integrations.hexa` imports the `hexa` package
  ([language binding](../../../hexa/docs/specs/spec-003-shape_pipelines_python.md))
  when it is first imported. Without it, that import raises
  `IntegrationUnavailable` (a subclass of `ImportError`) naming the missing package.
- The integration depends on hexa's public API only and declares its vocabulary
  (below) in a hexa vocabulary of its own. It never patches hexa.
- Bindings, mappings, function libraries and referentials must be parsed into
  their spec-04 and spec-05 models first; the integration reads those models (or
  their JSON forms) and never parses text itself.

```python
import asyncio
from hexa.runtime import run
from onto.integrations.hexa import HexaBindingOperator

ops = HexaBindingOperator(ontology, mode="lenient")
program = ops.compile(binding, formats=formats, inventory=inventory)
result = asyncio.run(run(env, program.stages.BindingRead, documents))
log, report = ops.result(program, result)
```

- `HexaBindingOperator(ontology, mode="strict")` holds the source ontology and the
  [mode](#modes), like onto's other operators. The functional forms are
  `bindingCompile(ontology, binding, formats=None, inventory=None,
  mode="strict")` and `bindingResult(ontology, program, result)`.
- `compile` takes a binding in its spec-04 model or JSON form, and optionally the
  binding's [formats file](spec-04-mapping.md#formats) and the document format's
  [inventory](spec-04-mapping.md#inventories). It returns a
  `BindingProgram` with `slots`, `shapes`, `templates`, `vocabulary` and `stages`,
  a frozen hexa stage namespace. Compiling is pure; it never reads documents.
  Compiling the same inputs twice gives programs whose hexa encodings are equal.
- `documents` is a list of `{src, document}`: the provenance token and the parsed
  JSON value (or, for CSV, the list of row objects) of each document of the run.
  Hosts usually produce it with their own `Retrieve` stage, piped before
  `BindingRead`, so that documents come from journaled effects and records carry
  origins.
- `result` validates the output through `observationsFromJson` and returns the
  observations log and a `BindingReport`. An output that does not validate is a
  defect of the integration, never a data error.
- `formatsUpdate(previous, report)` (functional form `bindingFormatsUpdate`)
  returns the updated formats file and its changes ([Formats](#formats)).
- `program.stages.BindingRun` extends `BindingRead` with
  [re-running](#re-running) and returns an `Outcome` for the host to persist;
  `approve(outcome, token)` (functional form `bindingApprove`) produces the log
  of a pending outcome approved by a person.

Mappings have the same shape of API:

```python
from onto.integrations.hexa import HexaMappingOperator

ops = HexaMappingOperator(fromOntology, toOntology, referential=None, mode="strict")
program = ops.compile(mapping, libraries=[markets])
result = asyncio.run(run(env, program.stages.MappingRead, state))
log, report = ops.result(program, result)
```

- `compile` takes the mapping, the function libraries it uses and, through the
  operator, the referential its header names. It returns a `MappingProgram`.
  Functional forms: `mappingCompile`, `mappingResult`, `mappingApprove`.
- `state` is the reconciled input state (`reconcileObservations`), or its JSON
  form. `MappingRun` adds re-running and returns an `Outcome`.
- `compileWrite(binding, inventory=None, formats=None)` on the binding operator
  returns a `BindingWriteProgram` ([Writing](#writing)); its `BindingWrite` stage
  takes a state and returns `{documents, report}`.

### Layout

| Module | Contents |
| --- | --- |
| `__init__.py` | Lazy import of hexa, `IntegrationUnavailable`, public API |
| `model.py` | `BindingProgram`, `MappingProgram`, `BindingReport`, `MappingReport`, `ReportGap`, `Outcome` |
| `vocabulary.py` | The `Onto` constraints, codecs and transforms, with their examples |
| `compiler.py` | Ontology → slots; binding and mapping → selectors, shapes, templates; reach and line inputs |
| `unfold.py` | `HandlesResolve`, `InstancesUnfold`, metadata tables, conflict variants |
| `writing.py` | Reverse-mapping forms, fragments, `OriginalsRestore`, `DocumentMaterialize`, `DocumentFormatsDiscover` |
| `stages.py` | `DocumentRecordsCollect`, `DocumentFieldsDiscover`, `ClaimsEmit`, the stage namespace |
| `runs.py` | Previous output, stale slots, retractions, safeguards, approval |
| `operations.py` | `HexaBindingOperator`, `HexaMappingOperator` and their functional forms |

Tests follow the onto convention, `tests/T06-<n>-hexa-<name>.py`, and are skipped
when hexa is not installed. Each `Onto` vocabulary entry is also checked by
hexa's conformance run over its examples.

## Correspondence

| spec-04 | hexa |
| --- | --- |
| Source ontology `Exchange` | Slot namespace `Exchange`, one nested namespace per type |
| Attribute `Instrument.Isin` | Slot `Exchange.Instrument.Isin` |
| Scope line `Type <- path` | A selector, a shape and a record template, run as `each(project(...))` |
| Body line `Attr <- expr` | A tolerant position in the shape and a key of the template |
| `^` | Enclosing capture blocks in the selector |
| `$` (document root), `@at` | A capture block opening the selector |
| Built-in function, `@fn`, `@map` | Registered derivation, or codec when it has an inverse |
| `date(x, "YYYYMMDD")`, `date(x, $format)` | `via DatePattern("YYYYMMDD")`, a union of `DatePattern` instances |
| Gap | A hole, reported in the ledger with its reason |
| Strict and lenient [run modes](spec-04-mapping.md#run-modes) | Item policies |
| Run | One `BindingRead` over a set of documents |

## Slots

`bindingCompile` declares two kinds of slots.

**Attribute slots** hold the values claims are made of. For every attribute of
the source ontology there is a slot named by the namespace, the type's path and
the attribute path of spec-02 claims (`p`): `Exchange.Dividend.Amount`,
`Exchange.Instrument.Bond.CouponRate`, `Exchange.Person.Name.Surname`. Since `p`
is unique within a type, so is the slot name.

An attribute slot's canonical value is the attribute's
[spec-02 JSON value](spec-02-observations.md#json-form), so captured values,
derivation results and claim values are the same data:

| Ontology type | Canonical shape |
| --- | --- |
| `Text` | `Text` |
| Closed vocabulary `A\|B` | `either("A", "B")` |
| Open vocabulary `A\|B\|...` | `Text` |
| `Integer` | `Decimal where Integral` |
| `Number`, `Amount`, `Percent`, numeric `Duration` | `Decimal` |
| `Duration` with an unknown unit | `Text where IsoDuration` |
| `Boolean` | `Bool` |
| `Date` | `DateTime where DateOnly` |
| `DateTime` | `DateTime where Timed` |
| Reference to `T` | `{ref: Text}` |
| Multi-valued attribute of `S` | `{set: [S], partial?: true}` |

- hexa `Decimal` is exponent-free. Every hexa decimal is a canonical spec-02
  number, and spec-02 compares numbers by value, so bindings never produce an
  exponent spelling.
- Structure attributes have one slot per field path; the structure has none.
- Qualifiers (`cur`, `unit`, `scale`) do not change the shape. Bindings read
  values as the source ontology describes them, so no qualifier conversion is
  involved.

**Field slots** hold source fields that are not claimed directly: arguments of
functions, the parts of `??`, `id`, `valid`, `ctx`, `when` and `deleted` paths, and
`^` paths. They live in the generated namespace
`Bind.<Type>.Fields`, named after the field path in PascalCase (`exDate` →
`Bind.Dividend.Fields.ExDate`, `bond.couponRate` →
`Bind.Instrument.Fields.BondCouponRate`); enclosing records add `Outer`,
`Outer2`, and so on for each `^`. Their canonical shape is `Any`. A function
reads its arguments in the observations value encoding of its parameter types,
as spec-04 [typing](spec-04-mapping.md#typing) requires, and raises a gap when it
cannot.

`Bind.At` holds the document's `@at` value.

## Compiling a scope line

Each scope line compiles to one selector, one shape, one record template and one
pair of stages `<Type>RecordsSelect = select(Selector)` and
`<Type>RecordsProject = each(project(Shape, Template, {outer}), Policy)`. A type
with several scope lines gets one pair per line, numbered in normal-form order
(`Instrument1RecordsSelect`, ...).

### Selector

The scope path becomes a hexa selector: `.` and `[*]` become `/` and `/*`, and
`$[*]` (CSV rows) becomes `*`.

- Fields read through `^` are captured by a block after the enclosing record's
  segment: `instruments[*].dividends[*]` read with `^.isin` becomes
  `instruments/*/{isin?: $Bind.Dividend.Fields.Outer.Isin}/dividends/*`. Block keys
  are optional, so an enclosing record without the field still supplies its
  children; lines that need the field have a hole.
- `^` used as a whole reads the enclosing scope line's `id` inputs, so they are
  captured the same way.
- `@at <- expr` and `$`-rooted paths are captured by a block opening the selector:
  `{asOf?: $Bind.At}/instruments/*`.
- Index steps (`a[0]`) are not supported: hexa selectors and shapes have no
  index access, so compiling a binding that uses one fails with
  `Binding.PathUnsupported`.

### Shape

The shape is a loose struct of every path the scope's lines read, nested as in the
document, with every key optional. Each leaf is a **position**:

```text
key?: tolerant(P | Null)
P   = $Slot                 a direct read
    | $Slot via Codec       a read through a codec (below)
    | either(P1, P2, ...)   $format: the chosen format first, then the others seen
```

- `tolerant` makes a value that does not match, or does not parse, a hole for the
  lines that read it: their claims are omitted and a gap is reported, while the
  record's other claims are made. This is spec-04's "a value did not convert" gap.
- A JSON `null` matches the `Null` branch and binds nothing, so it says nothing.
  A line annotated `{null=absent}` or `{null=unknown}`, or a binding header with
  `null=`, instead compiles its position as
  `tolerant(P | $Bind.<Type>.Nulls.<Attr>)`, a marker slot whose canonical
  shape is `Null`; the template turns it into `null` or `{unknown: true}`.
- A path read by several lines is one position. When the lines need different
  slots, the position captures the field slot and each line reads it through its
  own derivation.
- Paths and quoted field names keep their source spelling as struct keys.
- A body path through `[*]` nests a list in the shape and gathers the position
  below it: `a[*].b` becomes `a?: tolerant([{b?: gather(P), ...}] | Null)`, and
  `a[*].b[*]` becomes `a?: tolerant([{b?: [gather(P)], ...}] | Null)`. The slot is
  a collection slot. A missing `a` leaves it unbound (no claim); an empty `a`
  binds `[]`, the known-empty collection.

### Template

The record template produces one **record** per occurrence:

```text
{type, handle, at?, valid?, ctx?, deleted?, values: {Path: Value, ...},
 facets: {Facet: true, ...}, links: {verb: Value, ...},
 formats: {FieldPath: Format, ...}, source, origin?}
```

- `handle` is `Onto.Handle("<Type>", <id expression>)`, the spec-04 handle
  encoding. Its slot inputs are optional references, so an absent key reaches
  `Onto.Handle`, which raises `Binding.KeyMissing`; a key that failed to read keeps
  its own reason. Either way `handle` is a hole, and `ClaimsEmit` skips a record
  without a handle: its gap is already in the ledger.
- `values`, `facets` and `links` hold one key per body line. Absent and hole keys
  are left out; the claim is not made.
- `source` is `$Location` and `origin` is `$Origin?`. Both are value-free.
- `{when=path:value}` wraps the line's value: `Onto.When(Onto.TextEquals($F, "value"),
  Value)`, which is absent when the condition fails. On a `[Facet]` line it
  wraps `true`.
- `deleted=path:value` compiles to `deleted: Onto.TextEquals($F, "value")`.
- `formats` has one key per field read with `$format`, the field's binding path
  (`instruments[*].dividends[*].payableDate`), holding
  `Onto.FormatName(parsed($S))`: the formats-file name of the pattern that parsed
  it. Format names are not source data.

### Expressions

| Expression | Position | Template value |
| --- | --- | --- |
| `path`, into an attribute | `$Exchange.T.Attr` with the type's read codec | `$Exchange.T.Attr?` |
| `f(path)`, `f` with an `inverse`, into an attribute | `$Exchange.T.Attr via F` | `$Exchange.T.Attr?` |
| Any other call | Field slots for its paths | `F(args...)`, nested |
| `x ?? y` | Field slots for both | `Onto.Coalesce(x, y)` |
| `a[*]`, `a[*].b`, into a multi-valued attribute | A collection slot, gathered | `Onto.Set($Bind.T.Fields.AB?)` |
| `ref(Type, expr)` | Field slots | `Onto.Ref("<Type>", expr)` |
| `^` | Enclosing `id` inputs | `Onto.Ref("<Enclosing type>", <enclosing id>)` |
| Literal | — | The literal, in its spec-02 encoding |
| `date(x, $format)`, `datetime(x, $format)` | A union of pattern codecs ([Formats](#formats)) | As for a codec read |

- **Read codecs** implement spec-04's rule that document scalars are read in the
  observations value encoding of the target type. Numeric types read through
  `DecimalText`, which accepts JSON numbers and decimal text. Other types read
  directly, since their JSON and canonical forms coincide.
- **Functions with an inverse** compile to codecs so that the writing pass,
  when it is specified, reuses them. Built-in pairs map to codecs as follows:
  `date(a, format)` and `format` to hexa's `DatePattern(format)`; `number` and
  `text` to `DecimalText`; `date(a)` and `epoch` to `Onto.EpochDate`; `split`
  and `join` to `Onto.SplitText(sep)`. A declared `@fn` with an `inverse` compiles
  to a codec named by its path (`Markets.FrequencyFromInterval`), and an `@map`
  whose lines are all `exact` and one-to-one compiles to a table codec.
- **Other functions** compile to derivations of transforms with the same names:
  built-ins under `Onto` (`Onto.Concat`, `Onto.Trim`, ...), and library functions
  and maps under their paths, with `/` written `.`
  (`Markets.FrequencyFromInterval`). They follow the spec-04
  [contract](spec-04-mapping.md#contract-for-implementations), which is also the
  hexa transform contract: pure, values in spec-02 JSON encoding, failure as a
  gap with a reason.
- **Examples** of every `@fn` become hexa examples of its codec or derivation, so
  hexa's conformance run is spec-04's.
- A function applied to a collection where it expects a single value is applied
  to each member (spec-04). The compiled derivation does this, not hexa.

### Vocabulary

The integration declares its constraints, codecs and transforms under `Onto`, and
its codes under `Binding` and `Mapping`:

| Kind | Names |
| --- | --- |
| Constraints | `Integral`, `IsoDuration` |
| Codecs | `EpochDate`, `SplitText(Separator)`, `DateTimePattern(Pattern)`, `DecimalNumber`, `DecimalPlaces(Places)`, `Case(Case)` |
| Transforms | `Handle`, `SourceHandle`, `Ref`, `Correspond`, `Coalesce`, `When`, `TextEquals`, `Valid`, `Set`, `FormatName`, `QualifierConvert`, `ToInteger`, `ToVocabulary`, `HandleKey`, and the spec-04 built-in functions in PascalCase (`Concat`, `Trim`, `Multiply`, ...) |
| Codes | `Binding.KeyMissing`, `Binding.TypeMismatch`, `Binding.PathUnsupported`, `Binding.InputEmpty`, `Binding.SnapshotOlder`, `Binding.ParentMissing`; `Mapping.InputConflicting`, `Mapping.ReferenceUnmapped`, `Mapping.NotIntegral`, `Mapping.ValueUnmapped`, `Mapping.KeyReference`, `Mapping.ContextUnsupported`, `Mapping.PolicyUnsupported` |

Each has examples. Built-in functions keep their spec-04 examples and add those
the table in spec-04 implies.

## Run

```text
BindingRead: DocumentsRead → ClaimsEmit
DocumentsRead: each(DocumentRecordsCollect), with DocumentFieldsDiscover when an inventory is given
DocumentRecordsCollect: <Type>RecordsSelect → <Type>RecordsProject, for each scope line
```

| Stage | Input → output | Policy |
| --- | --- | --- |
| `<Type>RecordsSelect` | Document → `[Occurrence]` | A missing scope path is a gap |
| `<Type>RecordsProject` | `[Occurrence]` → `[Record]` | Holes per field; records per [mode](#modes) |
| `DocumentRecordsCollect` | `{src, document}` → `{src, records, gaps}` | Hand-written: runs every scope line, in normal-form order, inside `collect` |
| `DocumentFieldsDiscover` | `{src, document}` → `{src, fields}` | Hand-written, pure; only with an inventory |
| `DocumentsRead` | `[{src, document}]` → `[{src, records, gaps, fields?}]` | `Policy.Abort` |
| `ClaimsEmit` | `[{src, records, gaps, fields?}]` → `{log, stale, formats, fields?}` | Hand-written; yields `ClockRead` when no `@at` is given |
| `BindingRead` | `[{src, document}]` → `{value, ledger}` | `collect` |

- The environment needs the host operation `ClockRead() → DateTime`, used only
  when the binding has no `@at`, and, for `BindingRun`, `OutputPreviousRead` and
  `RetractionsPendingRead` ([Re-running](#re-running)), and for `BindingWrite`,
  `DocumentPreviousRead` ([Writing](#writing)). Retrieval operations are
  the host's own, in the stages it pipes before `BindingRead`.
- `DocumentRecordsCollect` wraps its scope lines in `collect`, so the gaps it
  returns are those of its own document: ledger locations are pointers into one
  document, and would be ambiguous across the run.
- `ClaimsEmit` returns the run's spec-02 log in JSON form as `log`, the
  [stale](#stale-slots) slots as `stale`, the format tallies as `formats`, and the
  observed fields as `fields`. In the log, `obs` names the source ontology with
  the binding's `scope`; each document's `src` becomes a source alias; each record's existence claim, values, facets and links follow in record
  order, with ordinals `n` assigned in that order. A deleted record produces the
  retraction `- h` instead.
- Metadata: `src` is the document's token, `at` the record's `at` or the run's
  time from the `ClockRead` effect (so replay reproduces it), `by` is
  `bind:<Namespace>`, and `valid` comes from the record. A record's `ctx` is a
  default only for contextual facet applicability and value claims, never for
  existence or non-contextual claims (spec-02).
- Instances referenced through `ref` and not produced by any record are typed by
  `@type` declarations; they are [implicit](spec-02-observations.md#implicit-instances).

### Modes

| Failure | Strict | Lenient |
| --- | --- | --- |
| A field that does not match or convert (tolerant position, derivation gap) | Claim omitted, gap reported | Same |
| A record without a key | Record omitted, `Binding.KeyMissing` reported | Same |
| A scope occurrence that is not an object | `Binding.TypeMismatch`; the run aborts | Record omitted, gap reported |
| A missing scope path | Gap reported; no records | Same |

Strict runs use `each(..., Policy.Abort, {on: [Failure.Shape]})`, lenient runs
`Policy.Drop`. Both report gaps as warnings, as spec-04 requires.

### Report

`bindingResult` turns the hexa ledger and the `ClaimsEmit` output into a
`BindingReport` with `gaps`, `formats` ([Formats](#formats)) and, with an
inventory, `fields` ([Coverage](#coverage)). Each gap has the
target as an onto path (`Exchange/Dividend.PayableDate`, or the type for a
record), the handle when the record had one, the reason (a hexa or onto code:
`DatePattern.Invalid`, `Issue.Mismatch`, `Binding.KeyMissing`), the document's
`src`, the location in the document and, when known, the origin. The report never
contains source values.

The report keeps holes separate from absent fields. This is the distinction
spec-04 [removals](spec-04-mapping.md#removals-and-gaps) needs: a later run must
keep a claim whose input produced a gap, and retract one whose input is gone.

## Formats

A field read with `$format` is read in any format the binding knows for it, and
each run counts the formats it saw, so the [formats file](spec-04-mapping.md#formats)
can be updated.

**Reading.** The position is a union of pattern codecs, in this order:

1. the field's chosen format;
2. the other formats seen for it, most frequent first, then by name;
3. the integration's candidate patterns not already listed, in a fixed order:
   `YYYY-MM-DD`, `YYYYMMDD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `DD.MM.YYYY`, `YYYY/MM/DD`
   for dates, and the same followed by `Thh:mm:ss`, `Thh:mm:ssZ` and ` hh:mm:ss`
   for date-times.

Dates use hexa's `DatePattern`; date-times use `Onto.DateTimePattern`, which
adds `hh`, `mm`, `ss` and `Z` as in spec-04's `datetime`. hexa takes the first
matching branch, so an ambiguous value (`01/02/2026`) reads in the format
already chosen or seen. A source switching between ambiguous formats is therefore
detected only when its unambiguous values outnumber the values read in the
chosen format.

**Counting.** `ClaimsEmit` tallies the record `formats` keys, and `bindingResult`
reports them as `report.formats`: for each field path, the count of each format
in this run. Records skipped for lacking a handle still count; records dropped
as a whole by their item policy do not.

**Updating.** `ops.formatsUpdate(previous, report)` returns the new formats file
and its changes:

- each format's count is added to its `seen` count;
- the chosen format becomes the most frequent, unless the field is pinned;
- a change of chosen format is listed in `changes`, as spec-04
  [run modes](spec-04-mapping.md#run-modes) require: a strict host applies the
  new file only after approval; a lenient host applies it and reports the
  warnings.

Only date and date-time patterns are learned. The file's other formats
(`decimals:N`, `case`, `trim`, `sep`) describe how to write values, which belongs
to the writing pass; they are kept unchanged.

## Coverage

Coverage has two sides (spec-04 [coverage](spec-04-mapping.md#coverage)).

- **Static coverage** of the ontology and of the inventory needs no documents:
  onto computes it from the binding, the ontology and, when given, the inventory.
  It is not part of the integration.
- **Observed fields** need documents. When `compile` receives an `inventory`, the
  run adds the hand-written stage `DocumentFieldsDiscover`, which lists the field
  paths of each document in inventory syntax (`instruments[*].bond.couponRate`)
  and their JSON types. `report.fields` lists the fields seen but missing from the
  inventory, with the number of documents they occur in, and the inventory fields
  whose type differs from what was seen. Paths and types are not source data.

## Re-running

A run withdraws what the binding's previous run claimed for the same source and
no longer claims (spec-04 [re-running](spec-04-mapping.md#re-running)). This is
onto logic over observations, run as stages after `BindingRead`; hexa contributes
the effects, the journal and per-document gaps.

```text
BindingRun: BindingRead → OutputPreviousRetrieve → RetractionsCompose
            → RetractionsAdmit → OutcomeMaterialize
```

| Stage | Input → output | Policy |
| --- | --- | --- |
| `OutputPreviousRetrieve` | Run → run with `previous` per source | Yields `OutputPreviousRead` and `RetractionsPendingRead` |
| `RetractionsCompose` | Run → run with `claims` and `retractions` | Pure (`lift`); [safeguards](#safeguards) raise |
| `RetractionsAdmit` | Run → `{admitted, held}` | Ceiling and confirmation |
| `OutcomeMaterialize` | → `Outcome` | Pure (`lift`) |

### Previous output

`documents` items may carry `replaces`, the `src` token of the snapshot they
supersede (spec-04 snapshots with one token per date). For each document,
`OutputPreviousRead({by, src})` returns the previous output: the log of claims
and retractions with that `by` and `src` (or `replaces`), or `null` when there is
none. The integration reconciles it with `reconcileObservations` into the
previous state. `RetractionsPendingRead({by, src})` returns the retractions
held by earlier runs and not yet approved or lapsed, each with its count of
confirming runs.

Both are host operations: the host owns the store. Through the journal, a
replayed run sees the same previous output.

### Stale slots

A slot is **stale** when its input produced a gap rather than disappearing.
`ClaimsEmit` derives stale slots from each document's gaps, matching ledger
`source` to record `source`:

- a gap at template path `values.<Attr>`, `facets.<Facet>` or `links.<verb>`
  makes that slot of the record's handle stale;
- a gap at `handle` leaves the instance unidentified. No instance of that scope
  type is retracted by this run for that document, since the missing one cannot be
  told apart; slot retractions of identified instances proceed.

Stale slots are never retracted; the report lists them with their reasons, as
spec-04 [removals](spec-04-mapping.md#removals-and-gaps) requires.

### Composing

`RetractionsCompose` compares, per source, the run's output with the previous
state, by slot: subject, attribute path, facet or relation, and context.

- **Changed or new values** are claimed. A claim equal to the previous state's
  claim for its slot (value and metadata other than `at`) is left out, so a run
  over unchanged input produces nothing new.
- **Absent slots** get a retraction with the run's `src`, `by` and `at`, as
  spec-04 lists them (`- h.Attr`, `- h[F]`, `- s verb o`, `- h`), with
  `{of=<replaced token>}` when the document `replaces` one. Completeness limits
  them: `complete=document` retracts slots and instances, `record` only slots of
  instances present in the run, `none` nothing.
- **Deleted records** (`deleted=path:value`) produce `- h` whatever `complete`
  says.
- Stale slots and unidentified instances are excluded.

### Safeguards

| Condition | Strict | Lenient |
| --- | --- | --- |
| `complete=document` and no record in the run | `Failure.Contract` `Binding.InputEmpty` | No retractions; warning |
| A document's `at` earlier than its previous output's | `Failure.Contract` `Binding.SnapshotOlder` | Only claims the previous output lacks; no retractions; warning |
| Retractions over the `retract` ceiling | Held; the run is pending | Held; claims are written |
| A chosen format changes ([Formats](#formats)) | The run is pending | Applied; warning |

The ceiling compares a source's retractions with the number of slots in its
previous state; a source without previous output has no ceiling.

### Approval

`RetractionsAdmit` splits retractions into admitted and held:

- In lenient mode, a held retraction that was pending from earlier runs and is
  computed again gains one confirmation. Once it has `confirm` confirmations
  (default `1`), it is admitted with `approved=confirm:<n>` and its original
  `src`, `by` and `at`. Pending retractions this run does not compute again lapse.
- Retractions approved by a person are applied by the host, outside a run, with
  `approved=<token>`; `ops.approve(outcome, token)` produces that log.

### Outcome

`OutcomeMaterialize` returns the `Outcome`, which the host persists:

```text
{status: Applied | Pending, log, held, lapsed, report}
```

- `Applied`: append `log` (claims and admitted retractions) to the store, and
  record `held` as pending.
- `Pending` (strict only): write nothing; `log` and `held` wait for a person's
  approval, after which the host appends both. A strict run is all or nothing.
- `lapsed` lists pending retractions to discard.
- `report` is the `BindingReport`, extended with stale slots, held, confirmed and
  lapsed retractions, and the safeguards that applied.

## Binding example

The `Dividend` scope line of spec-04's `exchange.bind`:

```text
Dividend <- instruments[*].dividends[*] {id=concat(^.isin, "/", exDate), valid=exDate}
  Amount <- amount
  Currency <- currency
  Instrument <- ^
  PayableDate <- date(payableDate, "YYYYMMDD")
  TaxCredit <- taxCredit
```

compiles to:

```text
DividendRecordsSelect = select(instruments/*/{isin?: $Bind.Dividend.Fields.Outer.Isin}/dividends/*)

DividendRow = {exDate?:      tolerant($Bind.Dividend.Fields.ExDate | Null),
               amount?:      tolerant(($Exchange.Dividend.Amount via DecimalText) | Null),
               currency?:    tolerant($Exchange.Dividend.Currency | Null),
               payableDate?: tolerant(($Exchange.Dividend.PayableDate via DatePattern("YYYYMMDD")) | Null),
               taxCredit?:   tolerant(($Exchange.Dividend.TaxCredit via DecimalText) | Null), ...}

DividendRecord = {type: "Exchange/Dividend",
                  handle: Onto.Handle("Dividend", Onto.Concat($Bind.Dividend.Fields.Outer.Isin?, "/",
                                                              $Bind.Dividend.Fields.ExDate?)),
                  valid: Onto.Valid($Bind.Dividend.Fields.ExDate?),
                  values: {Amount: $Exchange.Dividend.Amount?,
                           Currency: $Exchange.Dividend.Currency?,
                           Instrument: Onto.Ref("Instrument", $Bind.Dividend.Fields.Outer.Isin?),
                           PayableDate: $Exchange.Dividend.PayableDate?,
                           TaxCredit: $Exchange.Dividend.TaxCredit?},
                  facets: {}, links: {}, formats: {},
                  source: $Location, origin: $Origin?}

DividendRecordsProject = each(project(DividendRow, DividendRecord, {outer: [Bind.Dividend.Fields.Outer.Isin]}),
                              Policy.Drop)    // lenient
```

For the feed of spec-04, the dividend of `US0000000001` gives the record:

```json
{"type": "Exchange/Dividend", "handle": "Dividend_US0000000001_2F2026_2D09_2D01",
 "valid": "2026-09-01",
 "values": {"Amount": "0.42", "Currency": "USD", "Instrument": {"ref": "Instrument_US0000000001"},
            "PayableDate": "2026-09-15", "TaxCredit": "0.05"},
 "facets": {}, "links": {}, "formats": {},
 "source": "/instruments/0/dividends/0"}
```

A `payableDate` of `"2026-02-30"` would leave out `PayableDate` only, and report
`DatePattern.Invalid` at `Exchange/Dividend.PayableDate` for that handle.

## Mappings

A [mapping](spec-04-mapping.md#mappings) reads a reconciled state, which is a
graph, and hexa projects trees. The integration therefore **unfolds** each scope
instance into a tree holding exactly what the mapping's lines read, projects it
with hexa as for bindings, and computes claim metadata itself.

```text
MappingRead: HandlesResolve → InstancesUnfold → <S><T>RecordsProject → <S><T>VariantsProject
             → ClaimsEmit
MappingRun:  MappingRead → (the re-running stages of bindings)
```

This version supports `key=A` and `key=A from=Ns` policies, and mappings without
a referential (source-qualified handles). Contextual facets, minted handles,
alternate keys and registry lookups are [deferred](#deferred); a mapping using
them fails to compile with `Mapping.ContextUnsupported` or
`Mapping.PolicyUnsupported`. No new hexa construct is needed: unfolding, metadata
and fan-out are onto code around ordinary projections.

### Reach

When the mapping is compiled, each scope `S -> T` gets its **reach**: every path
its lines read, including `when`, `ctx`, `valid` and `src` paths, the key lines of
`T`'s policy, and the `$` metadata. Paths through references extend the reach into
the referenced type. The reach is finite even when references form cycles, since
it is the union of finitely many paths.

Each line also gets its **inputs**: the claims along every path it reads,
including those of `when`. A path's last claim is its **source input**. The line's
source input is that of its `{src=Path}`, or else of its first path.

### Unfolding

`InstancesUnfold` turns each instance of `S` (and of its specialisations) in the
state into a tree:

```text
{$handle, $type, $scope, $target, $valid?, $at, $src, Attr: Value, ...}
```

- `$handle` and `$type` are the instance's; `$scope` is the state's `@scope`;
  `$target` is the handle of its target instance ([Handles](#handles)); `$valid`,
  `$at` and `$src` come from its existence claim, `$src` as the provenance token.
- Keys are attribute paths as in spec-02 claims (`p`, e.g. `Bond.CouponRate`),
  binary relations by verb, and the roles of an n-ary relation instance by role
  name. Only keys in the reach are present.
- Values are [spec-02 JSON values](spec-02-observations.md#json-form), including
  `null` and `{"unknown": true}`.
- A reference becomes `{ref, target?, of?}`: `target` is the handle that the
  instance correspondence gives the referenced instance, when its type has a `->`
  line, and `of` is the referenced instance's tree, limited to the reach. A
  multi-valued attribute or relation is `{set: [...], partial?}` of such values.
- A slot holding conflicting claims is left out of the tree and its pointer listed
  in the occurrence's `conflicts`.

Alongside the tree, the unfold builds a **metadata table** from tree pointers to
the metadata of the claim each value came from: `{src, at, valid?, conf?}`, with
`src` as the provenance token. A conflicting slot's pointer maps to the list of
its claims, each with its value and metadata.

Occurrences are `{tree, meta, conflicts}`, listed per scope in handle order.
Unfolding is pure; it runs as a `lift` stage.

### Handles

`HandlesResolve` gives every scope instance its target handle before unfolding,
since references need the targets of the instances they point to.

- When `T`'s policy derives the handle from a key `A` (with `from`, only when
  the mapping's `From` is that namespace), the handle template is
  `Onto.Handle("<T>", <expression of the line assigning A>)`, projected over a
  first unfold limited to the paths that line reads.
- Otherwise the handle is source-qualified:
  `Onto.SourceHandle("<T>", $Map.Root.Scope, $Map.Root.Handle, "<S>")`, which
  encodes `<scope>/<key>` with the source handle's key, as spec-04 specifies.
- A key line whose expression reads a reference's target cannot be resolved
  before the targets exist: it fails to compile with `Mapping.KeyReference`.
- An instance whose handle is a hole gets no target. It produces nothing, and
  references to it are gaps (`Mapping.ReferenceUnmapped`).

The pairs of source and target handles are the instance correspondence. They are
reported with the run, and used by the unfold for `$target` and `target`.

### Compiling a scope

A scope compiles as a binding scope line does, over trees instead of documents:

- Attribute slots come from the `From` ontology. Their canonical shape adds
  `Null` and `{unknown: true}` to the type's shape, since state values may be
  either. Positions are `tolerant(P)`; there is no read codec, since state values
  are already canonical. Reference positions capture their `{ref, target}` value
  into a field slot.
- Every call compiles to a derivation, including functions with an inverse:
  in a mapping a conversion changes the type, so its result never fits the
  source attribute's slot. Built-in functions are the `Onto` transforms (`date`
  is `Onto.Date`); `@fn`, `@map` and library functions are transforms under their
  names. Reversal will use the inverse pairs, not the compiled codecs.
- `?` and `null` arguments make an `Onto` transform return `?` or `null`
  (`?` when both occur), except for functions declared `{nulls}`, which receive
  them. Bindings never pass them, so the same transforms serve both.
- Typing conversions from spec-04 [typing](spec-04-mapping.md#typing) become
  transforms when a check at compile time does not suffice:
  `Onto.QualifierConvert(x, From, To)` for `scale` and `unit`, with the qualifiers
  as literal objects; `Onto.ToInteger(x)` for Number to Integer
  (`Mapping.NotIntegral`); `Onto.ToVocabulary(x, [Values])` for Text to a
  vocabulary (`Mapping.ValueUnmapped`). Reference translation is
  `Onto.Correspond(r)`, which returns `{ref: target}`, or raises
  `Mapping.ReferenceUnmapped` when the reference has no target.
- The record's `handle` is `$Map.Root.Target`, captured from `$target`. Root
  keys starting with `$` are written `$$` in hexa's JSON encoding.
- Scope `{when}` is evaluated by `InstancesUnfold`: instances whose condition
  fails are not unfolded, and a conflicting condition is a gap
  (`Mapping.InputConflicting`) for the instance. Scope `{valid}` and `{ctx}` give
  the record's `valid` and `ctx`.
- Lines marked `candidate` compile only with `candidates=true`. A line reading
  outside the mapping's `view` is a compile error, as spec-04 requires.

### Conflicts

spec-04: a conflicting input fans out into one claim per value when it is the
line's source input; any other conflicting input, including a `when` path, makes
the line a gap.

- The main projection sees no conflicting value. `ClaimsEmit` drops every line
  whose inputs include a conflicting pointer and reports `Mapping.InputConflicting`
  for it. It does so even when the line produced a value, so that `x ?? y` never
  falls through to `y` because `x` was in conflict.
- `<S><T>VariantsProject` fans out. For each conflicting pointer that is the
  source input of some lines, and each of its claims, it projects a copy of the
  tree holding that claim's value, through a template limited to those lines.
  Lines in a variant with another conflicting input are still dropped as gaps.
- Each variant claim takes its metadata from its own value's claim, so the
  conflict is kept, with one claim per source, as spec-04 requires.

### Claims and metadata

`ClaimsEmit` turns records into claims as for bindings. Metadata follows spec-04
[claims and metadata](spec-04-mapping.md#claims-and-metadata), computed from each
line's inputs in the metadata table:

- `src`: the inputs' source when they share one; otherwise the source of the
  line's source input, with the other sources reported as mixed provenance.
- `valid`: the intersection of the inputs' `valid`; `conf`: the lowest.
- `at`: the run's time from `ClockRead`; `by`: `map:<From>-><To>`.
- A line without inputs (a literal) takes the metadata of the scope instance's
  existence claim, as does the existence claim of the target instance, whose
  `valid` is the source's unless the scope sets one.
- A `links` key holding an inverse verb (`issuedBy`) is claimed with the
  ontology's forward verb and swapped endpoints.

### Modes and report

Inputs are validated state, so no input element is unknown and both modes treat
gaps alike: the claim is omitted and the gap reported. Modes matter for
re-running and approval, which mappings share with bindings, with the input
complete by construction (`complete=document`). The `MappingReport` lists gaps by
target path, mixed provenance, the instance correspondence and, after re-running,
stale slots and held retractions.

### Mapping example

The `Instrument -> Instrument` scope of spec-04's `exchange-finance.map`, with the
referential `MarketIds` (`F/Instrument key=Isin`, `F/Company key=Code
from=Exchange`). `HandlesResolve` gives `Issuer_C_2D17` the target `Company_ACME`
and `Instrument_US0000000019` the target `Instrument_US0000000019`. The unfolded
tree of the bond, and its metadata table (all claims from the feed, source alias
`f`):

```json
{"$handle": "Instrument_US0000000019", "$type": "Exchange/Instrument", "$scope": "Exchange",
 "$target": "Instrument_US0000000019", "$at": "2026-11-10", "$src": "feed:instruments/2026-11-10",
 "Class": "F", "Code": "ACM30", "CouponRate": "0.0525", "Isin": "US0000000019",
 "MaturityDate": "1907712000", "Name": "Acme 5.25% 2030", "PaymentInterval": "6",
 "Issuer": {"ref": "Issuer_C_2D17", "target": "Company_ACME"}}
```

```json
{"/Class": {"src": "feed:instruments/2026-11-10", "at": "2026-11-10"}, "/Code": {...}, ...}
```

compiles to:

```text
InstrumentTree = {$target?: $Map.Root.Target,
                  Class?: tolerant($Exchange.Instrument.Class),
                  Code?: tolerant($Exchange.Instrument.Code),
                  CouponRate?: tolerant($Exchange.Instrument.CouponRate),
                  Isin?: tolerant($Exchange.Instrument.Isin),
                  Issuer?: tolerant($Map.Instrument.Fields.Issuer),
                  MaturityDate?: tolerant($Exchange.Instrument.MaturityDate),
                  Name?: tolerant($Exchange.Instrument.Name),
                  PaymentInterval?: tolerant($Exchange.Instrument.PaymentInterval), ...}

Bond(V) = Onto.When(Onto.TextEquals($Exchange.Instrument.Class?, "F"), V)

InstrumentRecord = {type: "Finance/Instrument", handle: $Map.Root.Target,
  values: {AssetClass: AssetClassFromCode($Exchange.Instrument.Class?),
           Bond.CouponRate: Bond(Onto.QualifierConvert($Exchange.Instrument.CouponRate?,
                                                       {scale: "1"}, {scale: "100"})),
           Bond.InterestFrequency: Bond(Markets.FrequencyFromInterval($Exchange.Instrument.PaymentInterval?)),
           Bond.MaturityDate: Bond(Onto.Date($Exchange.Instrument.MaturityDate?)),
           Code: $Exchange.Instrument.Code?, Isin: $Exchange.Instrument.Isin?,
           Name: $Exchange.Instrument.Name?},
  facets: {Bond: Bond(true)},
  links: {issuedBy: Onto.Correspond($Map.Instrument.Fields.Issuer?)},
  formats: {}, source: $Location}

InstrumentInstrumentRecordsProject = each(project(InstrumentTree, InstrumentRecord), Policy.Drop)
```

`Bond(V)` is notation for the `when` wrapper, written out in the compiled
template. `AssetClassFromCode` has a `broader` line, so it is a transform, not a
codec. The record gives the claims of spec-04's example: `[Bond]`, `AssetClass
Bond`, `Bond.CouponRate 5.25`, `Bond.InterestFrequency Biannually`,
`Bond.MaturityDate 2030-06-15`, `Code`, `Isin`, `Name`, and
`Company_ACME issues Instrument_US0000000019`, each with `src` `f`, `at` the
run's time and `by=map:Exchange->Finance`.

Had two sources disagreed on `Class`, the variants would give two `AssetClass`
claims, one per source, since `Class` is that line's source input. The `Bond`
facet and the three `Bond.*` lines read `Class` only in `when`, so they would be
gaps, reported as `Mapping.InputConflicting`.

## Writing

Writing is the reading direction reversed (spec-04 [reversal](spec-04-mapping.md#reversal)
and [writing](spec-04-mapping.md#writing)). A projection is a mapping into an
output ontology followed by a binding used for writing; reading data back is
the reverse mapping. Both reuse the machinery above:

- a reversed **mapping** is an ordinary mapping, run by `MappingRead`;
- a binding **writes** documents through hexa templates that format values,
  followed by onto stages that restore original spellings and place fragments in
  the document.

As for mappings, no new hexa construct is needed.

### Reversing mappings

`mappingReverse(mapping, fromOntology, toOntology)` is an onto operation, defined
by spec-04's reversal rules and implemented outside the integration. It returns
the reverse mapping `B -> A` and its **lossy** lines, which the report lists.
The integration compiles the reverse like any mapping, with three forms that only
generated reverses contain:

| Form | Produced by | Compiles to |
| --- | --- | --- |
| `Ref <- ref(T, Key)` | A forward line `Key <- Ref.Key`, where `Key` is `{key}` in `T` | `Onto.Ref("<T>", $Key?)`, with the handle from the reverse referential's policy for `T`: derived when the policy derives `T` from that key, source-qualified with the key as source key otherwise |
| `Ref.Attr <- Path` | A forward line with `{reverse}` | An entry of the record's `also`: `{handle: <Ref's handle>, values: {Attr: ...}}`, claimed on that instance |
| `F⁻¹(x)` | A forward call to `F` with `inverse=G` | `G(x)`, a derivation |

- An `@map` whose lines are all `exact` and one-to-one reverses into the `@map`
  with its columns swapped.
- Qualifier conversions reverse with `From` and `To` swapped.
- `$valid` reverses to the scope's `{valid}`.
- Records may carry `also`, a list of claims on other instances, so `ClaimsEmit`
  accepts it in mapping records generally; forward mappings never produce it.

A reverse mapping is normally run with the reverse referential, so that keys
read back give the handles the forward direction started from.

### Writing documents

`HexaBindingOperator.compileWrite(binding, inventory=None, formats=None)` returns a
`BindingWriteProgram`, whose stage `BindingWrite` takes the state of the binding's
ontology and returns the documents.

```text
BindingWrite: DocumentPreviousRetrieve → RecordsPreviousProject → InstancesUnfold
              → <Type>FragmentsProject → OriginalsRestore → DocumentMaterialize
```

| Stage | Input → output | Policy |
| --- | --- | --- |
| `DocumentPreviousRetrieve` | State → state with the previous document | Yields `DocumentPreviousRead({binding, src})`; `null` when there is none |
| `RecordsPreviousProject` | Previous document → records by handle | The reading stages of `BindingRead`, without claims |
| `InstancesUnfold` | State → occurrences per scope line | As for mappings; reach is what the reversible lines read |
| `<Type>FragmentsProject` | Occurrences → fragments | `each(project(Tree, Fragment), Policy.Drop)`; format failures are holes |
| `OriginalsRestore` | Fragments + previous records → fragments | Hand-written, pure |
| `DocumentMaterialize` | Fragments → document | Hand-written, pure |

**Lines.** Each body line reverses as follows; lines that cannot are lossy and
listed in the report:

| Line | Written |
| --- | --- |
| `Attr <- path` | The value at `path` |
| `Attr <- f(path)`, `f` with an inverse | The value formatted through the line's codec (compiled in the reading direction, used to format) |
| `Attr <- trim(path)`, `lower`, `upper` | The value unchanged: these lose only spelling, which originals and formats restore |
| `Attr <- a ?? b` | At `a` |
| `Ref <- ref(T, path)` | The key of the referenced handle, `Onto.HandleKey($Ref?)`, decoded from the handle's encoding |
| `Ref <- ^` | Nothing: it places the record under its parent ([Materializing](#materializing)) |
| `Attr <- a[*]`, `a[*].b` | A list, of values or of `{b: value}` objects; with a `sep:` format, one text |
| `[Facet] {when=path:value}`, `{when}` on a line | `value` at `path` when the facet or line applies, if no reversible line assigns `path` otherwise |
| Literals, other calls, `$` metadata | Lossy |

`id=` expressions are not written: the key fields are written by the lines that
assign them. `@at <- path` writes the run's time from `ClockRead`.

**Fragments.** The template of a scope line is the document fragment of one
record: its paths as nested keys, each leaf a formatted reference
`$Exchange.T.Attr via Codec` (or `?`-optional), so absent values write nothing
and a value that cannot be formatted is a hole, reported with the codec's reason
(`DatePattern.Unformattable`). `null` and `?` values are written only by lines
with a [null policy](spec-04-mapping.md#body-lines): `{null=absent}` writes JSON
`null` for a `null` claim, `{null=unknown}` for a `?` claim; `DocumentMaterialize`
writes them from the occurrence, since templates do not format nulls. Fragments
also carry the record's `handle` and, for a nested scope, its parent's handle.

### Spelling

Each written value is spelled in spec-04's two steps.

**Originals.** `RecordsPreviousProject` reads the previous document with the reading
program, giving each previous record's handle, location and canonical values.
`OriginalsRestore` keeps, for each field of a fragment, the previous raw value at
the previous record's location and the field's path, when the previous record's
canonical value for that line equals the value being written. Reading the
original therefore gives the value to write, as spec-04 requires, and its
spelling survives: padding removed by `trim`, trailing zeros, a time of day,
member order. Raw values never leave the host: they come from the host's own
previous document and go into the new one.

**Formats.** Otherwise the field's codec spells it:

| Field | Codec |
| --- | --- |
| A date or date-time with a chosen pattern | `DatePattern(chosen)`, `Onto.DateTimePattern(chosen)` |
| A line's inverse function | Its compiled codec, after the pattern |
| A number, in a field whose JSON type is `number` | `Onto.DecimalNumber` (JSON numbers keep no trailing zeros, so `decimals:N` does not apply) |
| A number, in a `text` field | `DecimalText`, or `Onto.DecimalPlaces(N)` with `decimals:N` |
| Text with `case:upper` or `case:lower` | `Onto.Case("upper")`, `Onto.Case("lower")` |
| A collection with `sep:<text>` | `Onto.SplitText(<text>)` |
| Anything else | The observations encoding, unchanged |

- A field's JSON type comes from the inventory; without one, from the previous
  document's value at that field; otherwise it is `text`, the observations
  encoding.
- `Onto.DecimalNumber` formats a decimal as a JSON number only when the number
  reads back as the same decimal; otherwise it raises `Onto.DecimalNumber.Inexact`
  and the field is a hole. Precision is never lost silently.
- `padded` cannot be produced without an original and formats as `trim`.

**Learning writing formats.** In a reading run with a formats file,
`DocumentFormatsDiscover` (next to `DocumentFieldsDiscover`) walks each bound
field of each document and classifies its raw values: `decimals:N` for decimal
text, `case:upper` or `case:lower` for text, `trim` or `padded`. It
returns names and counts only. `formatsUpdate` folds them into the formats file
like date patterns, so a field's writing format follows what the system writes.

### Materializing

`DocumentMaterialize` builds the document from the fragments:

- each scope path is created as needed; records of `instruments[*]` become
  elements of `instruments`, in handle order;
- records of a nested scope (`instruments[*].dividends[*]`) are placed under
  the element of the parent their `^` line references, in handle order; a record
  whose parent is not written is a gap, `Binding.ParentMissing`;
- for CSV, each record is a row, columns follow `@columns`, and a column without a
  reversible line is empty;
- fields of the previous document that no line writes are not kept: the binding
  describes the whole document it writes.

The `WriteReport` lists lossy lines, holes, parentless records and, per field,
how many values kept their original and how many were formatted.

### Writing example

Writing `Instrument_US0000000019` back to `instruments.json` with `exchange.bind`,
after reading the spec-04 feed:

```json
{"isin": "US0000000019", "code": "ACM30", "name": " Acme 5.25% 2030 ", "class": "F",
 "issuerId": "C-17", "bond": {"couponRate": 0.0525, "interval": 6, "maturity": 1907712000}}
```

- `name` keeps its padding: the previous record read it as `Acme 5.25% 2030`
  through `trim`, the value being written.
- `couponRate`, `interval` and `maturity` are JSON numbers: the inventory types
  them `number`, and each reads back exactly.
- `issuerId` is the key decoded from `Issuer_C_2D17`.
- The feed spelled the code as `ticker`. `Code <- code ?? ticker` writes `code`,
  as spec-04 specifies, so this record changes shape on writing. A binding that
  must preserve `ticker` needs one scope line per spelling, with `{when}`.

## Deferred

In the order they are expected to be added:

1. **Contextual facets** in mappings: one occurrence per instance and context for
   the lines that target them, with contexts translated through the instance
   correspondence.
2. **Registry-backed identities** (spec-05): minted handles, alternate keys and
   alias lookups, through a host operation `IdentityResolve` in `HandlesResolve`.
3. **Index steps** in paths, which hexa does not support.
