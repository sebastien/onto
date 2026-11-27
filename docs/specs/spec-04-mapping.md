# Bindings and mappings

How data moves between external systems and an [ontology](spec-01-ontology.md).
Every system is described by an ontology of its own (a **source ontology**). A
**binding** reads the system's documents (JSON, CSV) as
[observations](spec-02-observations.md) of that ontology, or writes them back. A
**mapping** turns observations of one ontology into observations of another.
Imports and projections are both mappings; they differ only in direction.

The mapping is data. Only extraction (fetching documents) and a small set of
named functions are code. Functions are specified by signature and examples so
that independent implementations (for example JavaScript and Python) behave
identically. [spec-06](spec-06-hexa.md) defines one execution model, which
compiles bindings and mappings into [hexa](../../../hexa/README.md) programs; this spec stays
authoritative for what they mean.

## Concepts

| Concept | Meaning |
| --- | --- |
| Source ontology | An ontology describing one external system's data as it is, in that system's terms |
| Document | One input or output file of a system: a JSON value or a CSV table |
| Binding | Correspondence between document field paths and a source ontology's elements (`.bind`) |
| Mapping | Correspondence between two ontologies' elements (`.map`) |
| Import | A mapping from a source ontology into a curated ontology |
| Projection | A mapping from a curated ontology (optionally through a view) into an output ontology |
| Scope line | A line selecting the instances to create, with body lines giving their values |
| Expression | The right-hand side of a line: paths, literals, function calls and `??` |
| Function | A named, pure, typed value transformation: built-in, `@fn` or `@map` |
| Function library | A namespace of `@fn` declarations shared by bindings and mappings (`.fn`) |
| Inventory | The list of a document format's field paths, produced by extraction |
| Formats | The value formats learned for each field of a document format, used to read and write it (`.formats`) |
| Referential | The identity policies giving target instances their handles ([spec-05](spec-05-identities.md)) |
| Run | One execution of a binding over a set of documents, or of a mapping over a state |
| Coverage | The derived report of which elements are mapped, how, and which are not |

## Pipeline

```text
documents ──bind──▶ source observations ──map──▶ observations ──reconcile──▶ state
                                                                               │
documents ◀──bind (write)── output observations ◀──map (projection)────────────┘
```

- A binding produces observations in the log form of spec-02, reading one
  document at a time; a [run](#re-running) may read several. Reconciliation (supersession, retraction, conflicts) is spec-02's.
- A mapping reads the **state form** of its input and produces new observations.
  It never resolves conflicts: a conflicting input produces one output claim per
  conflicting value, each keeping its source.
- A mapping with a [referential](spec-05-identities.md) gives its target
  instances managed identities; without one, target handles are qualified by
  their source and never merge by accident.
- A projection is a mapping followed by a binding used for writing.
- Re-running a binding or mapping retracts what its previous run produced and no
  longer does ([Re-running](#re-running)), so removals flow through like changes,
  with safeguards against erasing data on a bad input.

## Example

A stock exchange's data feed publishes `instruments.json`:

```json
{
  "asOf": "2026-11-10",
  "issuers": [{ "id": "C-17", "code": "ACME", "registeredName": "Acme Corporation Ltd" }],
  "instruments": [
    { "isin": "US0000000001", "code": "ACME", "name": "Acme Corp ordinary shares", "class": "E", "issuerId": "C-17",
      "dividends": [{ "exDate": "2026-09-01", "payableDate": "20260915", "amount": 0.42, "currency": "USD", "taxCredit": 0.05 }] },
    { "isin": "US0000000019", "ticker": "ACM30", "name": " Acme 5.25% 2030 ", "class": "F", "issuerId": "C-17",
      "bond": { "couponRate": 0.0525, "interval": 6, "maturity": 1907712000 } }
  ]
}
```

Its source ontology, `Exchange`, describes the feed faithfully, in PascalCase:

```text
@ontology Exchange rev=2026-11-10 src=feed card=? cards=assumed

ClassCode = E|F|O|U|...                         -- Security class codes used by the feed
EpochSeconds = Integer {unit=Second}            -- Seconds since 1970-01-01T00:00:00Z

Dividend
  Amount Amount
  Currency Text
  Instrument Instrument
  PayableDate Date
  TaxCredit Amount

Instrument
  Class ClassCode
  Code Text
  CouponRate Percent {scale=1}
  Isin Text {key}
  Issuer Issuer
  MaturityDate EpochSeconds
  Name Text
  PaymentInterval Integer {unit=Month}

Issuer
  Code Text
  Id Text {key}
  RegisteredName Text
```

The binding, `exchange.bind`, records where each attribute comes from:

```text
@binding Exchange rev=2026-11-10 format=json
@at <- asOf

Dividend <- instruments[*].dividends[*] {id=concat(^.isin, "/", exDate), valid=exDate}
  Amount <- amount
  Currency <- currency
  Instrument <- ^
  PayableDate <- date(payableDate, "YYYYMMDD")
  TaxCredit <- taxCredit

Instrument <- instruments[*] {id=isin}
  Class <- class
  Code <- code ?? ticker
  CouponRate <- bond.couponRate
  Isin <- isin
  Issuer <- ref(Issuer, issuerId)
  MaturityDate <- bond.maturity
  Name <- trim(name)
  PaymentInterval <- bond.interval

Issuer <- issuers[*] {id=id}
  Code <- code
  Id <- id
  RegisteredName <- registeredName
```

Conversions shared by several mappings live in a function library,
`markets.fn`, implemented in code and specified by its examples:

```text
@functions Markets rev=2026-11-10
@use Dimensions as D

@fn FrequencyFromInterval Integer -> D/InterestFrequency {inverse=IntervalFromFrequency} -- Months between payments
  1 => Monthly
  12 => Yearly
  3 => Quarterly
  6 => Biannually

@fn IntervalFromFrequency D/InterestFrequency -> Integer {inverse=FrequencyFromInterval}
  Biannually => 6
  Monthly => 1
  Quarterly => 3
  Yearly => 12
```

Instances of `Finance` get their handles from the referential `market-ids.ref`
([spec-05](spec-05-identities.md#example)): an instrument is identified by its
ISIN, and a company by the exchange's code.

```text
@referential MarketIds rev=2026-11-10
@use Finance as F

F/Company key=Code from=Exchange
F/Instrument key=Isin
```

The import, `exchange-finance.map`, maps `Exchange` into the `Finance` ontology
of [spec-01](spec-01-ontology.md#example):

```text
@mapping Exchange -> Finance from=2026-11-10 to=2026-11-10 referential=MarketIds
@use Dimensions as D
@use Markets as M

@map AssetClassFromCode ClassCode -> D/AssetClass
  E exact Equity
  F exact Bond
  O broader Derivative                          -- Options are one kind of derivative
  U exact Fund

Dividend -> Dividend
  Amount <- Amount {when=Currency:USD}
  Instrument <- Instrument
  PayableDate <- PayableDate
  Payer <- Instrument.Issuer

Instrument -> Instrument
  [Bond] {when=Class:F}
  AssetClass <- AssetClassFromCode(Class)
  Bond.CouponRate <- CouponRate {when=Class:F}
  Bond.InterestFrequency <- M/FrequencyFromInterval(PaymentInterval) {when=Class:F}
  Bond.MaturityDate <- date(MaturityDate) {when=Class:F}
  Code <- Code
  Isin <- Isin
  Name <- Name
  issuedBy <- Issuer

Issuer -> Company
  Code <- Code
  RegisteredName <- RegisteredName

- Dividend.TaxCredit {reason=out-of-scope}      -- Tax credits depend on the investor's jurisdiction
- Issuer.Id {reason=ignore}                     -- Feed identifier; used only for references
```

Binding the document and applying the import, in a run on 2026-11-11, yields,
among others:

```text
@obs Finance at=2026-11-11 by=map:Exchange->Finance
@src f=feed:instruments/2026-11-10
@src f
@scope Finance

Company_ACME:Company
  Code ACME
  RegisteredName Acme Corporation Ltd
Instrument_US0000000019:Instrument[Bond]
  AssetClass Bond
  Bond.CouponRate 5.25
  Bond.InterestFrequency Biannually
  Bond.MaturityDate 2030-06-15
  Code ACM30
  Isin US0000000019
  Name Acme 5.25% 2030
Company_ACME issues Instrument_US0000000019
```

The coupon rate is rescaled from `0..1` to `0..100` by the qualifiers alone.
`Instrument_US0000000019` is the same instance whichever feed or document
mentions it, since its handle derives from its ISIN; `Company_ACME` derives
from the exchange's code. The claims are recorded at the run's time; their
sources stay those of the feed.

A projection then writes a portfolio's trades as a spreadsheet. `Sheet` is the
output ontology:

```text
@ontology Sheet rev=2026-11-10

PositionRow
  AssetClass Text
  Date Date
  Isin Text
  Name Text
  Quantity Number
  Side Text
  Value Number
```

`finance-sheet.map` maps the `PortfolioReview` view into it, and `sheet.bind`
writes the rows as CSV:

```text
@mapping Finance -> Sheet from=2026-11-10 to=2026-11-10 view=PortfolioReview

Trade -> PositionRow
  AssetClass <- Instrument.AssetClass
  Date <- $valid
  Isin <- Instrument.Isin
  Name <- Instrument.Name
  Quantity <- Quantity
  Side <- Side
  Value <- multiply(Price, Quantity)
```

```text
@binding Sheet rev=2026-11-10 format=csv
@columns date, isin, name, "asset class", side, quantity, value

PositionRow <- $[*] {id=concat(date, "/", isin, "/", side)}
  AssetClass <- "asset class"
  Date <- date
  Isin <- isin
  Name <- name
  Quantity <- quantity
  Side <- side
  Value <- value
```

Reading the sheet back recovers each trade's instrument from `Isin`, which
`Finance` declares `{key}` for instruments. `Value`, `Name` and `AssetClass`
cannot be read back into a trade: the projection reports them as lossy
([Reversal](#reversal)). Dates and numbers are written in the formats the
sheet's [formats file](#formats) has learned.

## Lexical rules

The [ontology lexical rules](spec-01-ontology.md#lexical-rules) apply: UTF-8, LF,
two-space bodies of one level, `//` comments, ` -- doc` strings, names and paths.
`<-` separates a line's target from its expression and is surrounded by spaces.
Annotations (`{...}`) follow the expression; their values are tokens or, for
`id`, `valid` and `ctx`, expressions. An expression value extends to the next
`,` or `}` outside parentheses and strings.

## Expressions

Bindings and mappings share one expression language. In a binding, paths address
**document fields**; in a mapping, they address **attributes of the input
ontology**.

```text
expr     := term (" ?? " term)*
term     := path | literal | call | meta
call     := Path "(" [expr (", " expr)*] ")"
literal  := JSON string | number | "true" | "false" | "null" | "?"
meta     := "$valid" | "$at" | "$src" | "$format"
```

| Form | Meaning |
| --- | --- |
| `a.b` | Field or attribute `b` of `a` |
| `"asset class"` in a path | A field name that is not a plain name (bindings only): `row."asset class"` |
| `a[*]` | Each element of a list (bindings only) |
| `a[0]` | One element of a list, from 0 (bindings only) |
| `Attr[Key]` | The element `Key` of a [keyed structure](spec-01-ontology.md#keyed-structures) (mappings): `Phones[Mobile].Number`. Binding and mapping targets name elements the same way |
| `$` | The document root (bindings); alone, the scope instance itself, as a reference (mappings) |
| `^` | The record enclosing the current one: in `a[*].b[*]`, the element of `a`. `^.^` goes one further |
| `Ref.Attr` | Through a reference: the attribute of the referenced instance (mappings) |
| `x ?? y` | `x` when it is present, otherwise `y` |
| `F(x, y)` | A function call |
| `$valid`, `$at`, `$src` | Metadata of the scope instance's existence claim (mappings) |
| `$format` | The format the [formats file](#formats) chose for the field read by the line's first path (bindings) |

- A bare name is a path; a name followed by `(` is a call. A JSON string is a
  literal, except as a path segment after `.` or as the whole expression of a
  binding line, where it is a quoted field name.
- A value is **present** when the field exists and is not JSON `null`, or, in a
  mapping, when the attribute has a claim. `??` falls through absent values only;
  `?` and `null` claims are present.
- A path through a list without `[*]` or an index is an error.
- A path producing several values (through `[*]`, or a multi-valued attribute)
  yields a collection. Assigned to a multi-valued attribute it is claimed as the
  complete collection; assigned to a single-valued attribute it is an error.

### Typing

Every expression has a type, from the input ontology (mappings), from the called
function's signature, or from the target attribute (binding paths). Assigning to
a target checks compatibility:

| From | To | Rule |
| --- | --- | --- |
| A type | The same type or an alias of it | Allowed |
| Number, Integer, Amount, Percent, Duration | Same kind with other qualifiers | Converted by [qualifiers](#qualifier-conversion) or an error |
| Integer | Number | Allowed |
| Number | Integer | Allowed; a non-integral value is a gap |
| Vocabulary value | Text | The value's name |
| Text | Vocabulary | The value of that name; any other text is a gap |
| Vocabulary | Vocabulary | Only when every source value exists in the target vocabulary; otherwise through an `@map` |
| Reference to `S` | Reference to `T` | Through the [instance correspondence](#instances) of `S` |
| Anything else | | Through a function |

In a binding, document scalars are read with the
[observations value encoding](spec-02-observations.md#values) of the target type:
JSON numbers or decimal text for numbers, ISO 8601 text for dates, `true`/`false`
for booleans, names for vocabulary values. Anything else needs a function, such
as `date(payableDate, "YYYYMMDD")`, or `date(payableDate, $format)` to use the
format learned from the documents themselves.

### Qualifier conversion

Measurement qualifiers drive conversions that are exact and need no function:

- `scale`: a Percent with `scale=1` becomes `scale=100` by multiplying by 100, and
  back.
- `unit`: Duration units with fixed ratios convert: `Second`, `Minute`, `Hour`,
  `Day`, `Week`; and `Month`, `Year` (12 months). A day and a month do not convert.
- `cur` and `period` never convert. A fixed `cur` or `period` differing from the
  target's is an error; an unknown (`?`) one is filled by the target's.

### Conditions

The `when` of a binding or mapping line or scope, and a binding scope's
`deleted`, is a **condition**: tests of paths, combined.

```ebnf
condition   := conjunction (" | " conjunction)*
conjunction := operand (" & " operand)*
operand     := test | "(" condition ")"
test        := path [":" value ("|" value)*]
```

- `Class:F` holds when the path's value is `F`, compared as text: as `text()`
  spells it (canonical decimals, `true`/`false`), a reference by its handle.
- `Kind:Home|Investment` holds when the value is one of the values listed.
- A path alone holds when the path has a value, as `present=` reads one: absent,
  `null`, `?`, empty text and empty collections have none, false and zero do.
  `PurchasePrice | NewSecurity:true` holds for a purchase or for new security.
- A test of a collection (a multi-valued attribute, a path through `[*]`)
  holds when one of its members is listed: `Tags:Urgent`.
- `a & b` holds when both hold and `a | b` when either does. `&` binds tighter
  than `|`, and parentheses group: `Kind:Home|Investment & (Offered:true | Replaced:true)`.
- An absent, `null` or `?` value matches no test, so a test of it fails.
- Whitespace surrounds `&` and `|` between tests (as it does `??`), and does
  not surround `|` between values. A value is a token without whitespace, `:`,
  `|`, `&`, parentheses, braces, `,` or `=`, so `A:x|B:y` is an error rather
  than the value `B:y`.
- In a mapping, a conflicting slot read by any test makes the condition a
  conflicting input ([Claims and metadata](#claims-and-metadata)).
  `$` in a mapping test reads the scope instance, compared by its source handle.

## Bindings

```text
@binding <Namespace> {key=value ...}
@use <Namespace> as <Alias>
@at <- <expr>
@valid <- <expr>
@columns <field>, <field>, ...
<Type> <- <path> {id=<expr>, valid=<expr>, ctx=<expr>, deleted=<condition>, optional} [-- doc]
  <Attr> <- <expr> [{annotations}] [-- doc]
  <Facet.Attr> <- <expr> [{annotations}]
  [<Facet>] [{annotations}]
  <verb> <- <expr> [{annotations}]
- <path> {reason=<reason>} [-- doc]
```

`@binding` comes first and names the source ontology. Its keys:

| Key | Meaning | Default |
| --- | --- | --- |
| `rev` | Ontology revision the binding was written against | none |
| `name` | The binding's name, distinguishing bindings of one ontology (a token) | none |
| `format` | `json` or `csv` | `json` |
| `scope` | `@scope` of the produced observations | the namespace |
| `null` | How JSON `null` reads: `absent` or `unknown` ([body lines](#body-lines)) | says nothing |
| `complete` | What a run's documents claim to be complete: `document`, `record` or `none` ([Re-running](#re-running)) | `document` |
| `retract` | The [retraction ceiling](#safeguards), a percentage | `20%` |
| `confirm` | Runs confirming held retractions in lenient mode ([Approval](#approval)) | `1` |

- `@at <- expr` sets the observation time (`at`) of every claim from the
  document, from a document field. Without it, or when its value is absent
  (`a ?? b` falls through a JSON `null`), `at` is the run's time.
- `@valid <- expr` sets when every claim from the document holds (`valid`): a
  date, a date-time or a spec-02 interval, from a document field. A snapshot,
  such as a questionnaire's answers as at its date, says so once. A scope's own
  `valid=` still gives its existence claims theirs, and an absent value dates
  nothing. Mapped claims keep the date, as they keep their inputs' `valid`
  ([Claims and metadata](#claims-and-metadata)), whereas their `at` is the
  mapping's run time. Writing does not write the field back.
- Claims carry `by=bind:<Namespace>`, or `by=bind:<Namespace>/<name>` for a
  named binding, so a re-run withdraws only its own output. Several bindings of
  one ontology reading documents of one `src` (an API's endpoints) must have
  distinct names: otherwise each run retracts the others' output.
- `@columns` lists CSV columns in output order, for writing. Reading ignores it.
- A CSV document is read as a list of objects keyed by the header row, so its
  scope paths are `$[*]`. Cells are text; empty cells are absent.

### Scope lines

`Type <- path` creates one instance of `Type` (an entity or an n-ary relation of
the source ontology) for each value of `path`, evaluated from the document root.
Body lines are evaluated from that value (the **record**).

- `id=expr` is required. Its value, the instance's **key**, determines the
  handle: `<Type>_<key>`, with `Type` the last segment of the type path and every
  character of the key outside `[A-Za-z0-9]` written as `_` followed by the two
  uppercase hexadecimal digits of each of its UTF-8 bytes. `C-17` gives
  `Issuer_C_2D17`. Within one `scope`, equal keys are the same instance, across
  documents.
- `valid=expr` gives the existence claim's `valid`: a date, a date-time or a
  spec-02 interval. `ctx=expr` supplies the default context for contextual facet
  applicability and value claims produced by the body, never for existence or
  non-contextual claims (spec-02).
- `deleted=condition` marks deletions in a feed that reports them: a record
  for which the [condition](#conditions) holds (`deleted=status:Deleted|Merged`)
  produces the retraction `- h` instead of claims. This is how a
  `complete=none` (delta) feed removes instances.
- A path missing from the document is a gap, reported for the record above it,
  since a source that renamed or dropped a field would otherwise lose its
  instances silently. `optional` says some records lack the path: a missing
  path then makes no instance and no gap, as a `null` value does. A list mixing
  kinds of item, such as a timeline of notes and emails, reads each kind with
  an optional scope line: `Record/Comment <- $[*].comment {id=comment.id, optional}`.
- A type may have several scope lines (instances from several places in the
  document); each is applied.

### Body lines

| Line | Claims, per record |
| --- | --- |
| `Attr <- expr` | Attribute value |
| `Facet.Attr <- expr` | Facet attribute value (and the facet's applicability) |
| `[Facet]` | The facet applies |
| `verb <- expr` | Binary relation from this instance to each referenced instance |
| `Role <- expr` | Participant of an n-ary relation instance |

- An absent value produces no claim. `{null=absent}` on a line (or `null=absent`
  in the `@binding` header) makes JSON `null` claim `null` (confirmed absence), and `{null=unknown}`
  claim `?`. Otherwise `null` says nothing.
- `{unset=V}` names the value a source writes for "not given": a value equal to
  `V` says nothing, as an absent one does. `V` is a value of the line's
  attribute, which is single-valued with a text, number, boolean, date or
  vocabulary type, and it compares as one: with `Amount <- cash {unset=0}`, a
  CRM's `0` or `0.00` gives no claim, and `120000` its amount. Writing does not
  restore `V`. Quote text with spaces or delimiters, or empty text (`unset=""`).
- `^` as a whole expression refers to the enclosing record's instance: in the
  example, a dividend's `Instrument`. Its scope line must exist.
- `ref(Type, expr)` refers to the instance of `Type` with that key, whether or
  not the document contains it; until some document does, it is an
  [implicit instance](spec-02-observations.md#implicit-instances).
- `{when=condition}` applies the line only when the [condition](#conditions)
  holds. Writing restores a single `path:value` test on a plain field path;
  other conditions are lossy under writing.

### Exclusions

`- path {reason=ignore|out-of-scope} -- doc` records that a document field is
deliberately not bound, for [coverage](#coverage). `reason` is required.

## Mappings

```text
@mapping <From> -> <To> {key=value ...}
@use <Namespace> as <Alias>
@fn <Name> <Type>[, <Type> ...] -> <Type> [{annotations}] [-- doc]
  <args> => <result>
@map <Name> <From> -> <To> [{annotations}] [-- doc]
  <FromValue> <match> <ToValue> [-- doc]
@lookup <Owner>.<Name> -> <Type> [-- doc]
  <Attr> <- <Attr> [-- doc]
<FromType> -> <ToType> [{name=<Name>, into=<expr>, present=<expr>, when=<condition>, ctx=<expr>, valid=<expr>}] [-- doc]
  <target> <- <expr> [{when=<condition>, src=<path>, as=<Type>, name=<Name>, cur=<expr>, period=<expr>, reverse, candidate}] [-- doc]
  [<Facet>] [{annotations}]
- <From path> {reason=<reason>} [-- doc]
```

`@mapping` comes first. `From` and `To` are ontology namespaces; `@use` aliases
name ontologies and [function libraries](#libraries). Names in expressions
resolve against `From` and targets against `To`, as in spec-01 name resolution;
function names resolve as described in [Functions](#resolution). In a file's
`@map`, `From` resolves against the `From` ontology and `To` against the `To`
ontology.

A mapping may span several files, like an ontology: the files with the same
`@mapping From -> To` header form one mapping, parsed as a whole before it is
resolved. A reference translates through the scope lines of every file, and
coverage counts every file's lines and exclusions. Each file resolves its own
`@use` aliases; the files must agree on header keys and on an alias they share,
and must not declare a local function, map or lookup, or exclude an element,
twice.

| Key | Meaning | Default |
| --- | --- | --- |
| `from`, `to` | Ontology revisions the mapping was written against | none |
| `view` | A view of `From`: lines may only read what it selects | none |
| `scope` | `@scope` of the produced observations | `To` |
| `referential` | The [referential](spec-05-identities.md) giving target handles | none: source-qualified handles |
| `candidates` | `true`: also apply lines marked `candidate` | `false` |
| `retract` | The [retraction ceiling](#safeguards), a percentage | `20%` |
| `confirm` | Runs confirming held retractions in lenient mode ([Approval](#approval)) | `1` |

`@map` has its [spec-01 meaning](spec-01-ontology.md#maps). In a mapping it is
also a function: `AssetClassFromCode(Class)` returns the `To` value of the line
whose `From` value matches; a value with no line is a gap. A **set-valued** map
(spec-01: one that lists a value on several lines, or excludes one with
`- Value`) returns a set: the `To` values of the lines matching its argument,
or every member of a collection, an excluded value adding none. With
`Both narrower Insurance`, `Both narrower Lending` and `- Other`, `Areas(Both)`
is `[Insurance, Lending]` and `Areas(Other)` is `[]`. Its result is a
collection, which only a multi-valued attribute receives; an empty one states
that there are none, which `present=` can skip. Set-valued maps are lossy under
reversal.

### Instances

`S -> T` maps every instance of `S` (and of its specialisations) in the input
state to an instance of `T`. Body lines give `T`'s values.

- The target instance's handle comes from the policy of `T` in the mapping's
  `referential` ([spec-05](spec-05-identities.md#producing-handles)): derived
  from a key the body lines assign, found in the referential's registry, or
  minted. Different sources and mappings producing the same key produce the
  same instance.
- Without a referential, or when `T` has no policy, the handle is
  **source-qualified**: `<T>_` followed by the encoding of `<scope>/<S>/<key>`,
  with `scope` the input's `@scope`, `S` the last segment of the source type, and
  `key` the source handle without its `<S>_` prefix, decoded (or the whole handle,
  when it has no such prefix): `Person_Crm_2FClient_2F9` for `Client_9`. Instances
  from different sources, or of different source types mapped to one target type
  (a CRM's client and user with the same id), then never merge unless an
  [identity link](spec-02-observations.md#identity-links) says so.
- The **instance correspondence** of `S` is the set of these `S → T` pairs. It
  translates references: `issuedBy <- Issuer` links the instrument to the
  `Company` that `Issuer -> Company` produced for it. A reference to an instance
  of a type with no `->` line is a gap.
- A source type may have several `->` lines to different target types: one
  source record describing several things, e.g. a CRM client row that is both a
  person and the practice's relationship with them (`Client -> Person`,
  `Client -> Relationship`). Each line makes its own target instance, and a
  reference translates through the line whose target type the receiving
  attribute, role or verb accepts (that type or one it specialises): `Member <-
  Client`, for a `Party` member, is the client's `Person`. When several lines fit
  the receiver (including two lines to the same type), or none does, the
  reference is an error.
- `{as=T}` on a line chooses the target type its reference translates to, when
  several fit: `concerns <- ref(MortgageApplication, Id) {as=Application}`. `T`
  must be the target of a scope line of the reference's source type, and one the
  receiver accepts. An instance that line's `when` skips has no such target: the
  reference is a gap (`Mapping.ReferenceUnmapped`), never another of its
  targets. An instance known only by reference, whose condition cannot be read,
  takes `T`.
- `ref(S, Key)` reads the source instance of type `S` whose key (its binding
  `id`) is the value of path `Key`: the handle `<S>_<key>` of
  [scope lines](#scope-lines), a reference translated like any other. It is
  for sources that name an instance by type and id, such as a tag row's table
  and id; with exclusive lines, the table chooses the type:

  ```onto
  RecordTag -> Interaction {into=Record}
    concerns <- ref(Client, ForeignId) {when=ForeignTable:ClientId}
    concerns <- ref(Group, ForeignId) {when=ForeignTable:GroupId}
  ```

  `S` resolves against `From`, which must differ from `To`; `Key` is one path to
  a text or number. As a binding's `ref`, it need not name an instance of the
  input state: such an instance is [implicit](spec-02-observations.md#implicit-instances),
  translated through the scope lines of `S`, and its target is implicit too. A
  type with no correspondence is a gap (`Mapping.ReferenceUnmapped`). A line
  whose `when` is false demands nothing, so another table's id is not looked
  up. Source references reverse to the referenced instance's key
  ([Reversal](#reversal)).
- `ref(T, Key)`, with `T` a type of `To`, names the target instance whose key
  under the referential's `key=` policy for `T`
  ([spec-05](spec-05-identities.md#referentials)) is `Key`: a literal or one
  path to a text or number. Its handle is the one the policy derives, whether or
  not the mapping produces the instance, which stays
  [implicit](spec-02-observations.md#implicit-instances) until a source states
  it. Reference data kept apart from a mapping's output, such as a practice's
  reference questions, is named this way:
  `Question <- ref(Questionnaire/Question, "HasWill")`. A type name without
  an alias resolves in `From` first; use a `To` alias when both ontologies
  declare that name. Normal form uses a target alias if one is available.
  A type without such a policy is an error. Lossy under reversal.
- `$` alone reads the scope instance itself, as a reference translated like any
  other: in `Client -> Relationship`, `Client <- $` is the client's `Person`. Its
  claims take the scope instance's existence metadata.
- `{when=condition}` on the scope applies it only to the instances for which the
  [condition](#conditions) holds; `{ctx=expr}` and `{valid=expr}` set the target
  claims' context and validity.
  Without `valid`, the existence claim keeps the source's.
- `{name=ShortGoal}` distinguishes repeated source/target scopes. Repeated
  scopes for the same source and target types must all have distinct names.
  An unnamed scope keeps its existing identity. A named source-qualified
  identity uses `<scope>/@<name>/<S>/<key>` before encoding, so equal text,
  numeric keys or reordered scope declarations do not merge their targets.
  Names are stable identity components, not display labels. Named identity scopes
  currently require source-qualified identities (no target referential policy).
  Incoming references still require a unique type-directed correspondence:
  a receiver accepting several named scopes of the same type is ambiguous,
  not an instruction to choose the first. A line's `{name=N}` chooses: the
  reference translates through the scope line named `N` among those of its
  source type whose target the receiver accepts, e.g. `Item <- $ {name=Wants}`
  for one of the items a row names. As with `{as=T}`, an instance that scope's
  `when` or `present` skips has no such target, and the reference is a gap
  (`Mapping.ReferenceUnmapped`). Lossy under reversal.
- `{into=Application}` assigns the scope's fields, facets or verbs to the
  target already mapped from that source reference, instead of minting another
  target. The selector must be a non-contextual source instance reference. A
  multi-valued one (`into=Clients`) selects its one member: an empty collection
  selects nothing, and several members, or an incomplete collection, are a gap
  (`Mapping.ReferenceAmbiguous`), since collections have no order to take a
  first from;
  correspondence is type-directed against the declared target type. Missing,
  unknown, conflicting, plural, wrong-type or ambiguous destinations never
  choose a handle arbitrarily.
  Identity scopes resolve and emit first, independently of declaration order.
  An `into` destination must have an existence claim emitted by an identity
  scope in this run: an implicit-only, condition-excluded or absent destination
  yields a gap and is not resurrected. Unselected updates (`when`/`present`)
  make no assignments and do not require a destination.
  Updates keep the values' own provenance, confidence and validity; they do not
  replace the destination's existence provenance. Attribute and verb updates
  add no existence header; explicit facet assertions retain spec-02's normal
  same-handle existence encoding, not a new identity.
  They do not contribute instance correspondence, so updates cannot supply one
  another's identities. They reverse into rows of their source type
  ([Reversal](#reversal)).
  A named update may share a source/target pair with an existing unnamed
  identity scope without changing that scope's identity.
- `{present=expr}` emits a scope only for a known, nonempty value. Absent,
  unknown, empty text and empty collections are skipped; **false and zero are
  present**: select a flag with `when=Flag:true`, and declare a source's
  "not given" value in its binding (`{unset=0}`). Use `present=trim(Description)`
  to skip whitespace-only answers while preserving the original description in
  its assignment. Conflicting presence inputs or failed expressions report gaps
  rather than choosing a declaration; a scope its presence does not select
  demands nothing of its lines, which report no gaps. This selection may be
  combined with `when`. Named and presence-selected scopes reverse as
  [Reversal](#reversal) describes.
- Target attributes, facets and relations follow the forms of bindings
  (`Attr`, `Facet.Attr`, `[Facet]`, `verb`, `Role`).
- A target is assigned by one line, or by **exclusive lines**: lines whose
  `when` are tests of values of one single-valued path sharing no value
  (`Kind:Home|Investment` and `Kind:Car`), and at most one line without `when`, the **default**, applied
  when no condition matches (including when the path is absent). At most one of
  them applies to an instance:

  ```onto
  GroupReview -> Review
    StoppedReason <- ReviewStoppedReason
    StoppedReason <- "Other" {when=Status:ClosedOnMigration}
  ```

  Each line keeps its own inputs and provenance; the default also reads the
  conditions' path, so a conflict there is a conflicting input. Other repeated
  assignments, and repeated facet lines, are errors. The default is lossy under
  reversal: its condition cannot be written back.
- A quoted literal assigned to a `Range<T>` attribute is validated and
  canonicalised with the observations range parser. For example,
  `Horizon <- "P1Y..P5Y"` retains a duration band, not an untyped text value.

### Lookups

Sources often describe one thing in rows that do not name each other: a needs
analysis lists each client's personal details and, apart, each client's
address, both naming the client and the analysis. A **lookup** declares the
reference a mapping reads from one row to the other:

```onto
@lookup CnaIndividual.Address -> CnaAddress -- The client's address in the same analysis
  Client <- Client
  Application <- Advice

CnaIndividual -> Residence
  Resident <- Client
  Address.City <- Address.Details.City
  Duration <- YearsMonths(Address.Years ?? 0, Address.Months ?? 0) {when=Address.Years | Address.Months}
```

- `@lookup Owner.Name -> Type` declares `Name`, a single-valued reference from
  each instance of `Owner` to the instance of `Type` (both entity types of
  `From`) whose attributes have the values its lines give. A line `A <- B`
  requires `Type`'s attribute `A` to equal the owner's attribute `B`: both
  single-valued, of one type or references to one type. References compare by
  handle, other values by their text. `Name` is not an attribute of `Owner`,
  and a lookup has at least one line.
- A path of a scope over `Owner` may start with the lookup's name and read
  through it as through a reference (`Address.Details.City`), in an expression,
  a qualifier, a condition or a scope annotation. A scope inherits lookups
  from its source type's ancestors; when several declare the same name, the
  nearest declaration in the lineage wins regardless of file or declaration
  order. Only the scope instance's lookups are read: no path reaches one
  through a reference.
- The lookup finds the instances of `Type` in the input state whose compared
  attributes have known values equal to the owner's. One: the path reads
  through it. None: the path's value is absent, as it is when the owner has no
  value to compare. Unknown (`?`) and confirmed absent (`null`) claims are
  not keys. Several matches, or any compared attribute of the owner with
  conflicting values: a gap, `Mapping.ReferenceAmbiguous`, never the first;
  a condition reading through such a lookup holds for none of them, so its
  line demands nothing.
- Unlike `ref(S, Key)`, a lookup names no implicit instance: it finds only what
  the input holds. A rooted view therefore reads the rows it looks up: a line
  reading through a lookup needs a read supplying both types' compared
  attributes ([spec-06](spec-06-hexa.md#rooted-retrieval)).
- Values read through a lookup keep their own provenance. Lines reading through
  a lookup are lossy under reversal. Coverage counts the compared attributes as
  read by a condition, and each path read through the lookup as the path it
  ends with in `Type`.
- A lookup is declared once in a mapping, in any of its files.

### Claims and metadata

An attribute assignment may supply variable measurement qualifiers from expressions:

```onto
Expense -> Expense
  Amount <- Cost.Value {period=Cost.Period}
```

`cur` and `period` expressions must be single text or vocabulary values.
The receiving attribute must declare that qualifier as variable (`?`), and the
source expression must not already fix it: this feature attaches a missing
measurement basis, never relabels a currency or converts a period. A literal
qualifier is a quoted expression, e.g. `{period="Month"}`.

These reads participate in provenance, validity, confidence, conflicts and
coverage like value-expression reads. Qualifiers appear on the emitted
observation claim, not inside its scalar value. An absent amount emits no claim
and needs no qualifiers. A present amount with an absent, unknown, malformed or
out-of-vocabulary supplied qualifier emits no amount; the line reports
`Mapping.ValueUnmapped` and retains the stale slot. A conflicting qualifier is a
conflicting input. A false line condition does not demand its qualifiers.
Qualifier expressions cannot currently be reversed; reversal reports the line
as lossy rather than dropping its measurement basis.

Each output claim derives from the input claims its expression reads:

- `src`, `valid` and `conf` are those of the input claim. With several inputs,
  `conf` is the lowest and `valid` the intersection.
- `at` is the run's time: the mapping records the claim when it runs. The input
  claims keep their own `at`. A recomputed value (after the mapping or a function
  changed) therefore supersedes the previous one, and a claim produced again
  after a retraction is never hidden by it.
- `src` is the inputs' source when they share one. Otherwise it is the source of
  the input named by the line's `{src=Path}` annotation (one of the paths its
  expression reads), or by default of the first path in the expression. The
  run report lists the other inputs' sources as mixed provenance; the claim does
  not. A single attributed source keeps spec-02 supersession working when one
  input later comes from elsewhere.
- `by` is `map:<From>-><To>`, so mapped claims are distinguishable from the
  claims of their sources.
- A conflicting input slot yields one output claim per conflicting value, when
  it is the input that gives the claim its `src`. A conflict in any other input
  the line reads, or in a `when` path, makes the line a gap for that instance
  (reported as a conflicting input): combining it would attribute several
  outputs to one source, where they would supersede each other and the
  conflict would be lost.
- `?` and `null` inputs give `?` and `null` outputs, except for functions declared
  `{nulls}`. With both kinds of input, `null` takes precedence: any `null` gives
  `null`; otherwise any `?` gives `?`.
- Contextual facet claims keep their context, translated through the instance
  correspondence; `{ctx=expr}` replaces it.

Because outputs are observations, a mapping never overwrites: rerunning it after
the input changes produces new claims, spec-02 supersession applies within each
source, and outputs no longer produced are retracted ([Re-running](#re-running)).
A reference to an instance with no existence claim yet is kept; the instance is
[implicit](spec-02-observations.md#implicit-instances).

### Exclusions and candidates

- `- Path {reason=ignore|out-of-scope} -- doc` records that an element of `From`
  is deliberately not mapped.
- `{candidate}` marks a proposed line: it is reported in coverage and applied
  only when `candidates=true`. Proposals from agents start as candidates.

## Functions

| Kind | Defined | Examples |
| --- | --- | --- |
| Built-in | This spec, in every implementation | `concat`, `date`, `multiply` |
| Declared | `@fn` in a library or a binding/mapping file, implemented in code | `M/FrequencyFromInterval` |
| Value map | `@map` in a mapping file or an ontology | `AssetClassFromCode` |

### Declarations

```text
@fn FrequencyFromInterval Integer -> D/InterestFrequency {inverse=IntervalFromFrequency} -- Months between payments
  1 => Monthly
  6 => Biannually
```

- The signature lists argument types and the result type, resolved like any
  ontology name: built-in types, declared types, vocabularies or references.
  `T*` is a collection argument or result, and `Range<T>` a range of a built-in
  or named type, its examples in the [range encoding](spec-02-observations.md#values)
  (`35-44 => P35Y..P44Y`).
- Declared `@fn` signatures require concrete types. `any` and `any*` are notation
  for the built-in contracts only, not valid types in a declaration. A concrete
  signature fixes how each example is read: bare `p` is text for `Text`, but a
  reference for an entity type. No inference from its spelling is needed.
- Body lines are **examples**: arguments (comma-separated, in the observations
  value encoding) `=>` the result. Every implementation must reproduce them; they
  are the conformance tests shared by implementations. A declared function needs
  at least one example.
  Quote text values containing example delimiters (`,`, `[` or `]`, `=>`, or a
  doc/comment delimiter), in addition to the observations quoting rules.
- Annotations: `inverse=Name` names the function undoing it (used by
  [reversal](#reversal)), in the same library or file; `nulls` makes it receive
  `?` and `null` instead of propagating them.
- `g` is an inverse of `f` when `f(g(y)) = y` for every `y` that `f` produces:
  writing a value back and reading it again gives the same value. It need not
  restore the original spelling (`number("5.50")` is `5.5`, written back as
  `5.50` only through the [formats file](#formats)). A conformance run checks this on
  every example: applying the inverse to the result, then the function, gives
  the result again.

### Libraries

A function library (`.fn`) declares functions shared by several bindings and
mappings:

```text
@functions <Namespace> {key=value ...}
@use <Namespace> as <Alias>
@fn <Name> <Type>[, <Type> ...] -> <Type> [{annotations}] [-- doc]
  <args> => <result>
```

- `@functions` comes first. Its key `rev` is the library's revision. `@use`
  aliases name the ontologies whose types the signatures use.
- A library function's path is `<Namespace>/<Name>`. A library may span several
  files, as an ontology does; duplicate names are errors.
- Bindings and mappings import a library with `@use Markets as M` and call
  `M/FrequencyFromInterval(x)`.
- A local `@fn` in a binding or mapping file suits a one-off conversion. Local
  names must be unique among all the files loaded together; promote a local
  function to a library when a second file needs it.

### Rules

A derived attribute of an ontology may name a library function as its rule:
`~ Level Band <- Score {rule=Rules/Band}`, or `rule=R/Band` with
`@use Rules as R` in the ontology. The function's examples then document and
test the rule. When a library is loaded with its ontologies, each derived
attribute whose `rule` names one of the library's functions is checked:

- the function exists;
- it takes one argument per input, or at least that many when the inputs end
  with `...`; `$Inputs` are not typed;
- each input's type is accepted by its argument (numbers are interchangeable,
  a specialisation stands for its base), and the attribute's type accepts the
  result.

A `rule` token without `/`, or naming a library that is not loaded, is a free
reference, as before. The ontology never depends on the library: the check runs
from the library, which already depends on the ontology's types. Evaluating
derived attributes stays out of scope.

### Resolution

A function name in a call resolves, in order:

1. Built-in functions (reserved lower-case names).
2. The file's own `@fn` and `@map` declarations (by name).
3. Paths whose first segment is a `@use` alias: a library function
   (`M/FrequencyFromInterval`) or an ontology's `@map` (`D/FreqToBasis`).
4. Other paths, relative to the input ontology (`From`, or a binding's
   ontology): an ontology `@map` (`Budget/FreqToBasis`).

An unresolved or ambiguous name is an error.

### Contract for implementations

An implementation registers each library function under its full path
(`Markets/FrequencyFromInterval`) and each local function under its name. A
conformance run executes every example of a library, or of a file's local
functions, and fails on any difference.

- **Pure and deterministic**: no input/output, clock, randomness or state; equal
  arguments give equal results.
- **Values** are passed in the [observations JSON value
  encoding](spec-02-observations.md#json-form): numbers as canonical decimal
  strings, dates as ISO strings, vocabulary values as names, references as
  `{"ref": handle}`, collections as `{"set": [...]}`. Implementations must not
  compute through binary floating point when the result would differ from
  decimal arithmetic.
- **Failure** (a value outside the function's domain) returns a gap with a short
  reason. It never aborts the run: the claim is omitted and the gap reported.
- Unless declared `{nulls}`, functions propagate `null` before `?`: any `null`
  argument gives `null`; otherwise any `?` argument gives `?`.
- A function applied to a collection where it expects a single value is applied
  to each member. When several arguments need this application, it runs on every
  combination of their members (the Cartesian product), not on positional pairs:
  collections are unordered sets. Arguments declared as collections remain whole.

### Built-in functions

| Function | Signature | Inverse | Meaning |
| --- | --- | --- | --- |
| `concat(a, ...)` | `Text, ... -> Text` | | Joins texts; any absent argument makes it absent |
| `split(a, sep)` | `Text, Text -> Text*` | `join` | Splits on a separator; empty parts are dropped |
| `join(a, sep)` | `Text*, Text -> Text` | `split` | Joins members in sorted order |
| `trim(a)` | `Text -> Text` | | Removes leading and trailing whitespace |
| `lower(a)`, `upper(a)` | `Text -> Text` | | Changes case (Unicode default case mapping) |
| `number(a)` | `Text -> Number` | `text` | Parses a decimal number; `.` is the decimal separator |
| `text(a)` | `any -> Text` | | The value's observations encoding |
| `date(a)` | `Integer -> Date` | `epoch` | Seconds since 1970-01-01T00:00:00Z, as a UTC date |
| `date(a, format)` | `Text, Text -> Date` | `format` | Parses with `YYYY`, `MM`, `DD` and literal characters |
| `datetime(a, format)` | `Text, Text -> DateTime` | `format` | As `date`, with `hh`, `mm`, `ss` and `Z` |
| `epoch(a)` | `Date -> Integer` | `date` | Seconds since 1970-01-01T00:00:00Z |
| `format(a, format)` | `Date, Text -> Text` | `date` | Formats a date or date-time |
| `sum(a, ...)`, `multiply(a, ...)` | `Number, ... -> Number` | | Exact decimal arithmetic |
| `subtract(a, b)`, `divide(a, b)` | `Number, Number -> Number` | | `divide` by zero is a gap; results are exact or rounded to 16 significant digits |
| `count(a)` | `any* -> Integer` | | Number of members |
| `ref(Type, key)` | `Text -> Type` | | Bindings only: the instance of `Type` with that key |

`Number` arguments accept any numeric type (Integer, Number, Amount, Percent);
results are `Number`, converted on assignment by the [typing](#typing) rules.
When a numeric result is rounded, ties use round-half-to-even.
`count` and `join` require complete collections. An incomplete collection
(`{"set": [...], "partial": true}`) gives a gap, not a count or join of only the
known members.

Every inverse in the table satisfies the round trip of [Declarations](#declarations)
within these limits, which reversal reports as gaps when they are not met:

- `split` and `join` require a nonempty separator. `join` gives a gap unless
  splitting its result yields the original set of members. This excludes empty
  members, members containing the separator, and separator matches spanning
  member boundaries.
- `format` is an inverse of `date` and `datetime` only with a format holding
  every part they read (`YYYY`, `MM` and `DD`; and `hh`, `mm`, `ss` for
  date-times). Other formats make the line lossy.
- `date(a)` and `epoch(a)` round-trip dates; a time of day in the source is
  restored only by [reusing the original value](#writing).
Built-in names are lower case and reserved; declared functions and maps use
PascalCase names.

## Reversal

A line is **reversible** when its expression can be solved for its input:

- a path within the scope instance (with qualifier conversion), including a
  reference attribute, translated back through the instance correspondence;
- a call to a function with an `inverse`, on a reversible argument;
- an `@map` whose lines are all `exact` and form a one-to-one correspondence.
  Distinct forward maps get distinct local names in the reverse, even when
  their names differ only by qualification.

A path through a reference (`Instrument.Isin`) reads another instance:

- When it ends at an attribute the referenced type declares `{key}` in the
  ontology, it is reversible: it reverses to the reference itself, the handle
  being formed from the key by the policy of the type in the reverse mapping's
  referential ([spec-05](spec-05-identities.md#producing-handles)). In the
  example, a sheet row's `Isin` gives back the trade's `Instrument`. The
  referenced instance need not exist yet: until it does, it is
  [implicit](spec-02-observations.md#implicit-instances), and its handle keeps
  the key for when it arrives.
- Otherwise it is lossy. `{reverse}` on the line makes it reversible by writing
  the value onto the referenced instance; without it, reading data back never
  makes claims about instances other than the scope's own.

`??`, literals, multi-argument functions and `$` metadata (except `$valid`, which
reverses to the scope's `valid`) are not reversible. A `when` condition whose
tested paths are all assigned by reversible lines translates into the reverse;
it keeps its values, alternatives and combination.

Scopes and lines reverse as follows
([spec-10](spec-10-operations.md#reversal)):

- **Source-side conditions.** A scope condition testing source paths that no
  reversible line assigns, such as `{when=Deleted:false}`, held for every
  instance the scope produced.
  - The reverse scope applies to all of its target instances, without a
    condition.
  - It asserts the tested value on the source instance when the condition tests
    one value of one path; alternatives and combinations assert nothing.
- **Literal lines** (`Type <- "FileNote"`) write nothing back. They become
  conditions of the reverse scope: only target instances with that value
  reverse through it.
- **Named scopes** reverse onto the source instance each target instance was
  produced from, which a named source-qualified handle names
  (`<scope>/@<name>/<S>/<key>`).
- **Presence-selected scopes** reverse as their lines do. Retracting one of
  their target instances clears the source paths their `present` expression
  reads, when reversible lines of the scope assign them.
- **Update scopes** (`into=`) reverse into rows: a slot they assign is written
  as an instance of the scope's source type, whose selector names the
  destination's source instance. Retracting the slot retracts the row.
- **Source references** `ref(S, Key)` reverse when the referenced target
  instance comes from an instance of `S`: `Key` takes its key. Among exclusive
  lines, the line whose `S` matches applies, and its `when` test value is
  asserted.

A **derived** value is never projected back (A -> B -> A): a value the source
computes, or one a rule derives, is not an input anyone writes. A line is lossy,
reported as "derived target, not written back", when its target is a derived
attribute (`~`) of the output ontology, or when its reverse would assign a
derived attribute of the input ontology. For a binding, a line whose target is
a derived attribute of the source ontology (`CanEdit <- canEdit`, for
`~ CanEdit Boolean`, a value the API computes on read) is read, never written.

The **reverse** of a mapping `A -> B` is the mapping `B -> A` made of the
reverses of its reversible lines. Tools report the others as **lossy**; the
reverse of `exchange-finance.map` loses `AssetClass` (`O broader Derivative` is
not one-to-one), the bond attributes whose condition reads `Class`, and the
dividend's `Payer`; that of `finance-sheet.map` keeps the instrument (through
`Isin`) and loses `Value`, `Name` and `AssetClass`. A projection does not have
to be reversible; reporting what it loses is what matters.

Operations should be reversible wherever they can be: a lossy line is reported,
and a line that loses only spelling (formatting, case, order, whitespace) is
not lossy, since [writing](#writing) restores spelling.

### Writing

A binding is used for writing by reversing its lines: values are written at
their paths, creating objects and list elements as needed, and `a ?? b` writes
`a`. Instances are written in handle order; CSV columns follow `@columns`, and a
column without a reversible line is left empty.

Each value is spelled in two steps:

1. **Original value.** When the field had a value in the previous version of the
   document being written (read by a binding run, or written by a previous
   one), and reading that value gives the value to write, it is written
   unchanged. Unchanged values thus round-trip exactly, including what the
   line's functions drop: whitespace removed by `trim`, trailing zeros, a time
   of day, member order.
   - Originals may also come from another document, read by another binding,
     such as the response an operation reads before writing its request
     ([spec-10](spec-10-operations.md#running-an-update)).
   - They are then matched by instance and source slot rather than by field
     path, since the two documents differ.
2. **Format.** Otherwise the value is encoded with the format the field's
   [formats](#formats) entry chose, then by the line's inverse functions;
   without an entry, in its observations encoding.

### Formats

A formats file records, for each field of a document format, the formats its
values were seen in, so that new values are written as the system writes them.
It lives next to the binding, named after it (`exchange.bind` →
`exchange.formats`), because it changes with the documents read, not with the
binding.

```text
path	format	seen	pin
instruments[*].dividends[*].amount	decimals:2	decimals:2 951	pin
instruments[*].dividends[*].payableDate	YYYYMMDD	YYYYMMDD 412; YYYY-MM-DD 3
instruments[*].name	trim	trim 380; padded 35
```

- After the header line, one tab-separated line per field, sorted by path: the
  chosen `format`, the formats `seen` with their counts (most frequent first,
  then by name), and, optionally, `pin` for a format chosen by a person.
  Field paths use binding syntax from the document root, including wildcards
  and fixed indexes (e.g. `rows[*][0].date`).
  Write a format name containing `; `, a tab, or a line break as a JSON string
  so it cannot be confused with the row or `seen` delimiters.
- Formats are date and date-time patterns (as in `date(a, format)`),
  `decimals:N` (fixed decimal places), `case:upper` or `case:lower`, `trim` or
  `padded`, and `sep:<text>` for a collection written in one field. How a format
  is detected is up to implementations; the formats file is the shared contract:
  given the same file, two implementations read and write alike.
- Each binding run counts the formats of the values it reads. A field whose
  values come in several formats is reported. The chosen format is the most
  frequent one, unless pinned; when that changes, the run asks for approval in
  strict mode and switches with a warning in lenient mode
  ([Run modes](#run-modes)).
- `$format` in a binding line reads with the chosen format, then with the other
  formats seen; a value matching none is a gap.

## Re-running

Observations accumulate, so a run must withdraw what it previously claimed and
no longer claims; otherwise a removed field or a delisted instrument would
survive in the state forever.

- A run reads a **set of documents** (a binding) or a state (a mapping) and is
  compared with the **previous output** of the same binding or mapping for the
  same source: the claims with that `src` and the binding's or mapping's `by`.
  A feed paginated over several documents is one run.
- Every slot (subject, attribute path or facet or relation, and context) present
  in the previous output's state and absent from the new output gets a
  retraction, with the same `src` and `by`: `- h.Attr`, `- h[F]`, `- s verb o`,
  or `- h` for an instance no longer produced. Since a retraction with `by`
  withdraws only claims with that `src` and `by` (spec-02), other sources, and
  other processes reporting for the same source, are unaffected.
- Changed values need no retraction: the new claim supersedes the old one within
  the source.
- When successive snapshots of a feed use different `src` tokens (one per
  date), the run is told which token it replaces. Its retractions then carry
  `{of=<previous token>}` and the new `src`.
- A run whose input is unchanged produces nothing new.

Retractions are written to the run's output like its claims, at the run's time,
so the log form records when each fact stopped being reported, not just when it
started.

### Removals and gaps

A slot is absent from a run's output for one of two reasons, which are treated
differently:

- **Its input is absent**: the field, attribute or instance is no longer in the
  input. The source stopped saying it, so the slot is retracted.
- **It produced a gap**: a function failed, a value did not convert, an `@map`
  had no line for the value, or an input was in conflict. The source still says
  something the run could not translate, so the previous claim is **kept**. The
  run report lists it as stale, with the gap's reason.

### Completeness

A mapping reads a state, which is complete by construction. A binding's
documents may not be: the `complete` header key says what a run's documents
claim.

| `complete` | Absent from the run | Use |
| --- | --- | --- |
| `document` | Instances and slots are retracted | Full snapshots |
| `record` | Slots of instances present are retracted; absent instances are kept | Feeds of changed records, each complete |
| `none` | Nothing is retracted | Additive or delta feeds |

Whatever `complete` says, a scope line's `deleted=path:value` retracts the
instances the feed reports as deleted. For a replacement snapshot, these
explicit retractions also carry `{of=<previous token>}`.

### Safeguards

A bad input (a truncated download, an empty page, a feed in a new format) must
not erase what is known:

- **Retraction ceiling.** When a run would retract more than its `retract`
  percentage (default `20%`) of the slots in its previous output, the
  retractions are **held**: not written, and listed in the run report until
  [approved](#approval). In strict mode the whole run waits for that approval.
- **Empty input.** A `complete=document` run without any record is an error in
  strict mode; in lenient mode it writes nothing and warns.
- **Older snapshots.** A binding run whose `at` is earlier than the previous
  run's for the same source is an error in strict mode. In lenient mode it adds
  only the claims the log does not have yet, retracts nothing, and warns.

## Run modes

Runs are **strict** (the default; offline and batch processing) or **lenient**
(online processing), the two modes of
[spec-02 validation](spec-02-observations.md#validation).

| Condition | Strict | Lenient |
| --- | --- | --- |
| Retraction ceiling exceeded | Waits for approval | Writes claims, holds retractions until approved or confirmed, warns |
| Empty input under `complete=document` | Error | Warns; no retractions |
| Older snapshot | Error | Adds new claims only; warns |
| A field's chosen format changes | Waits for approval | Switches; warns |
| Identity conflict ([spec-05](spec-05-identities.md#resolution)) | Waits for approval | Keeps the instances apart; warns |
| Unknown element in an input | Error | Gap; warns |

A strict run is all or nothing: when anything waits for approval, nothing from
the run is written until it is approved, so an offline batch is never half
applied. Gaps, mixed provenance, lossy lines and
[implicit instances](spec-05-identities.md#implicit-instances) older than their
age (default `P7D`, a run setting) are reported in both modes, as warnings.

### Approval

What waits for approval (held retractions; in strict mode, a whole run) is
**pending** until approved or superseded:

- **By a person.** A curator approves or rejects the pending items of a run, in
  either mode. Strict runs are approved only this way.
- **By confirmation** (lenient mode, held retractions only). When the next
  `confirm` runs (default `1`) of the same binding or mapping, for the same
  source, would make the same retractions again, they are approved: a
  truncated download is transient, a real removal persists. Only the
  retractions every confirming run repeats are approved.
- **Superseded.** Each run recomputes its retractions from its own comparison.
  A run's pending retractions that the next run does not repeat lapse; those it
  repeats carry over, counting towards `confirm`.

Approved retractions are written as they were computed, with the run's `src`,
`by` and `at`, so that they never withdraw claims made after the run, plus
`approved=<token>`: the approver's token, or `confirm:<n>` for `n` confirming
runs. The log thus records who allowed each held erasure.

## Coverage

Coverage is computed, not authored. For a mapping, every attribute, facet, role
and relation of `From` (restricted to `view` when set) gets one status:

| Status | When |
| --- | --- |
| `direct` | Read by a line whose expression is a path, with at most qualifier conversion |
| `transformed` | Read through a function, an `@map` or `??` |
| `condition` | Read only in `when`, `deleted`, `id`, `ctx` or `valid` |
| `ambiguous` | Read only by `candidate` lines |
| `ignore`, `out-of-scope` | Excluded with that reason |
| `unmapped` | None of the above |

The report also lists, for `To`, the elements no line assigns.

A binding has two sides, both reported:

- **Ontology side**: every attribute, facet, role and relation of the source
  ontology that no binding line assigns. This needs no data.
- **Document side**: every field of the document format, with the statuses
  above, measured against its **inventory**.

### Inventories

An inventory lists the field paths a document format can contain, one per line,
tab-separated from the field's JSON type (`text`, `number`, `boolean`, `object`,
`list`), sorted by path:

```text
asOf	text
instruments[*]	object
instruments[*].bond.couponRate	number
instruments[*].bond.interval	number
instruments[*].dividends[*].taxCredit	number
instruments[*].isin	text
```

Paths use the binding path syntax. Extraction produces the inventory from the
best evidence available: an OpenAPI or JSON Schema description, a CSV header,
or, failing those, sample documents (and then says so in its provenance, since
fields absent from the samples are invisible). Fields observed in documents but
missing from the inventory are reported when a binding runs.

### Default bindings

Since extraction already derives the source ontology from the same evidence, it
can also derive a **default binding**: one scope line per list of objects, and
one body line per field, assigning the attribute named by the field in
PascalCase (`couponRate` → `CouponRate <- bond.couponRate`). Colliding names
are disambiguated by path and, if needed, a numeric suffix. A scope with no
addressable scalar key candidate is left for the author to add. People then
edit the exceptions: `id=`, `??`, `date(...)`, references and exclusions. The
default binding is regenerated, and compared with the edited one, when the
source format changes.

The **coverage table** lists the coverage, sorted by source path:

```text
source	target	status	note
Dividend.Amount	Dividend.Amount	direct
Dividend.Currency		condition
Dividend.TaxCredit		out-of-scope	Tax credits depend on the investor's jurisdiction
Instrument.Class	Instrument.AssetClass	transformed
Instrument.CouponRate	Instrument.Bond.CouponRate	direct
```

`note` is the line's or exclusion's doc.

## Validation

Errors (nothing is produced):

- unknown ontology, type, attribute, facet, role, verb, view or function;
- a target assigned twice for the same scope;
- an incompatible type assignment, or a fixed qualifier contradiction;
- a reference to a type with several `->` lines, none or several of which the
  receiving attribute, role or verb accepts;
- a scope line without `id` (bindings);
- an unknown `referential`, or a scope line whose target type has a `key`
  policy but assigns none of its keys;
- a `complete`, `retract` or `confirm` value outside its domain;
- a `@fn` without examples, an `inverse` whose signature is not the reverse, or
  an example that does not round-trip through its inverse;
- a derived attribute whose `rule` names a function of a loaded library that
  does not exist or does not match its inputs and type ([rules](#rules));
- an unresolved or ambiguous function name, or a local function name declared
  by two loaded files;
- `{src=Path}` naming a path the line's expression does not read;
- `{reverse}` on a line that does not read through a reference;
- a line reading outside the mapping's `view`.

Warnings:

- a `from`, `to` or `rev` differing from the loaded ontology's or library's
  revision;
- an `@fn` example failing in an implementation (an error for conformance runs);
- inventory fields absent from the binding without an exclusion, and document
  fields absent from the inventory;
- mixed provenance, gaps, stale slots, held retractions, implicit instances and
  lossy lines (in the run report);
- fields whose values come in several formats, and chosen format changes;
- the conditions of [Run modes](#run-modes), which are errors or wait for
  approval in strict mode.

## Normal form

1. The header line (`@binding`, `@mapping` or `@functions`), then `@use` sorted
   by alias, then `@at`, `@valid` and `@columns` (bindings).
2. `@fn` declarations sorted by name, examples sorted by encoded arguments.
3. `@map` declarations sorted by name, lines as in spec-01.
4. `@lookup` declarations sorted by owner type path, then name; lines sorted
   by attribute.
5. Scope lines sorted by source type path, then target type path (or path, for
   bindings); body lines sorted by target (`[Facet]` lines first).
6. Exclusions sorted by path.

Annotations follow the order `id`, `name`, `into`, `present`, `when`, `src`, `as`, `ctx`, `valid`, `deleted`,
`null`, `unset`, `cur`, `period`, `reverse`, `candidate`, `reason`. Header keys follow the order of their
tables. Spacing, docs and comments follow
spec-01; a declaration with a body is surrounded by blank lines.

## JSON form

The interchange form for implementations that should not parse the text: one
schema, [`mapping.schema.json`](../../src/json/mapping.schema.json), covers the
three file kinds, with `format` `onto.binding/1`, `onto.mapping/1` or
`onto.functions/1`. Text and JSON convert losslessly (comments excepted).

```json
{
  "format": "onto.mapping/1",
  "from": "Exchange",
  "to": "Finance",
  "header": { "from": "2026-11-10", "to": "2026-11-10", "referential": "MarketIds" },
  "uses": { "D": "Dimensions", "M": "Markets" },
  "scopes": [
    { "source": "Exchange/Instrument", "target": "Finance/Instrument",
      "lines": [
        { "facet": "Bond", "when": { "path": ["Class"], "value": "F" } },
        { "target": "AssetClass", "expr": { "call": "AssetClassFromCode", "args": [{ "path": ["Class"] }] } },
        { "target": "Bond.CouponRate", "expr": { "path": ["CouponRate"] }, "when": { "path": ["Class"], "value": "F" } },
        { "target": "Bond.InterestFrequency", "expr": { "call": "Markets/FrequencyFromInterval", "args": [{ "path": ["PaymentInterval"] }] },
          "when": { "path": ["Class"], "value": "F" } },
        { "verb": "issuedBy", "expr": { "path": ["Issuer"] } }
      ] }
  ],
  "exclusions": [{ "path": "Exchange/Dividend.TaxCredit", "reason": "out-of-scope", "doc": "Tax credits depend on the investor's jurisdiction" }]
}
```

A function library:

```json
{
  "format": "onto.functions/1",
  "namespace": "Markets",
  "header": { "rev": "2026-11-10" },
  "uses": { "D": "Dimensions" },
  "functions": [
    { "name": "FrequencyFromInterval", "args": [{ "builtin": "Integer" }], "result": { "path": "Dimensions/InterestFrequency" },
      "ann": { "inverse": "IntervalFromFrequency" }, "doc": "Months between payments",
      "examples": [{ "args": ["6"], "result": "Biannually" }] }
  ]
}
```

- Type and scope paths are fully qualified; calls to library functions and
  ontology maps use full paths, local functions their names. Local `@fn`
  declarations of a binding or mapping go under `functions`, and `@map`
  declarations use the spec-01 JSON `map` declaration form, under `maps`.
- Lines carry `src` (a path, as a string) and `reverse`, `candidate` flags.
  Attribute lines may also carry `qualifiers`, an object from `cur` or `period`
  to expression objects (e.g. `{"period": {"path": ["Cost", "Period"]}}`).
- Mapping scopes may carry `name` (an identifier), `present` and `into` (expressions).
  Structure/entity exclusions cover their descendant fields; explicit leaf
  exclusions are more specific, and actual reads still take precedence.
- A mapping line's `{name=N}` is its `name`. `@lookup` declarations go under
  `lookups`, each `{"owner", "name", "type", "lines": [{"attr", "from", "doc"?}],
  "doc"?}`, with fully qualified type paths.
- Expressions: `{"path": [step, ...]}`, where a step is a field or attribute
  name (any string), `{"each": true}` (`[*]`), `{"index": n}`, `{"up": n}` (`^`)
  or `{"root": true}` (`$`); `{"text": "..."}`, `{"number": "5.25"}`,
  `{"boolean": true}`, `{"null": true}` and `{"unknown": true}` literals;
  `{"call": name, "args": [...]}`; `{"coalesce": [...]}`; `{"meta": "valid"}`.
- Conditions: a test is `{"path": [step, ...], "value": "F"}`,
  `{"path": [...], "values": ["Home", "Investment"]}` for two values or more, or
  `{"path": [...]}` alone for having a value; `{"all": [...]}` and
  `{"any": [...]}` combine two conditions or more, never directly nesting their
  own kind.
- Bindings use `"ontology"` instead of `from`/`to`, scopes with `"type"` and a
  `"path"` expression, `"id"`, `"valid"` and `"ctx"` expressions, an optional
  `"deleted"` condition (the form of `when`), `"optional": true` for an
  optional scope line, and an optional document `"at"`,
  `"valid"` and `"columns"`. Attribute lines may carry `"unset"`, a string. `{"meta": "format"}`
  is `$format`.
- Header keys are strings, except `candidates` (a boolean) and `confirm` (an
  integer); `retract` is written as in the text (`"20%"`).
- Absent optional members are omitted, never `null`.
