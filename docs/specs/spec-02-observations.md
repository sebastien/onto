# Observations format

A compact text format for instance data about an [ontology](spec-01-ontology.md):
entities, facets, attribute values and relation instances, expressed as
**observations** — claims about identified subjects, with provenance and time.

Observations accumulate. They are never silently merged: conflicting claims are
kept and reported, and withdrawn claims are expressed by explicit retraction.
Observations are produced from external documents and translated between
ontologies by [bindings and mappings](spec-04-mapping.md); mapped claims keep
their source and record the mapping in `by`.

## Example

```text
@obs Finance rev=2026-11-10 at=2026-11-10
@src st=broker:statement/2026-10 ex=exchange:announcement/411075 d7=upload:document/123
@src st

p1:Person[Investor]
  DateOfBirth 1990-06-15
  Name.Surname Ng
  Investor.RiskTolerance Medium
h1:Household
h1 hasMember p1
r1: h1 hasMember p2:Person
r1.Role Adult

c1:Company
  Code ACME
i1:Instrument[Bond]
  Isin US0000000001
  Bond.CouponRate 5.25
c1 issues i1
a1:Account
o1:Ownership {valid=2024-03-01..}
  Account a1
  Owner p1
  SharePercent 100
t1:Trade {valid=2024-03-01}
  Account a1
  Counterparty ?
  Instrument i1
  Trader [p1, p2]
  Price 98.5
  Quantity 100
  Side Buy

@src ex
dr1:Directorship {valid=2021-07-01..}
  Company c1
  Director p1
dr1 {valid=2021-07-01..2026-06-30}

@src d7
p1.DateOfBirth 1990-06-16 {at=2026-10-01}
- p1.DateOfBirth 1990-06-16 {at=2026-11-02}
```

The exchange announcement records `p1` as a director of `c1` from July 2021,
then that the directorship ended in June 2026. The uploaded document claimed a
different date of birth and later withdrew it.

## Lexical rules

The [ontology lexical rules](spec-01-ontology.md#lexical-rules) apply: UTF-8, LF,
two-space indentation with one level, `//` comments, name and path grammar.
Doc strings (`--`) are not used in observations.

## Directives

```text
@obs <Namespace> {key=value ...}
@src <alias>=<token> [<alias>=<token> ...]
@src <alias>
@at <date-or-datetime>
@ctx <handle> | @ctx none
@scope <token>
@type <handle> <Type-or-S.verb.T>
@implicit <handle> [<handle> ...]
```

- `@obs` is required and comes first. It names the ontology namespace and sets
  defaults for statement metadata (`rev`, `src`, `at`, `by`, `conf`). `rev`
  identifies the ontology revision the data was written against.
- `@src a=token` declares source aliases: short names for provenance references.
  `@src a` (no `=`) sets the default source for subsequent statements.
- `@at` sets the default observation time for subsequent statements.
- `@ctx h` sets the default context for subsequent claims on contextual facets
  ([Contexts](#contexts)); `@ctx none` clears it. It does not apply to other claims.
- `@scope token` declares that handles are stable within that scope (e.g. one
  source system). Without it, handles are local to the document.
- `@type h T` records the type of a handle without making an observation claim
  ([type-only declarations](#type-only-declarations)).
- `@implicit` lists [implicit instances](#implicit-instances). The state form
  writes it; it is ignored on input (recomputed).

Defaults set by directives apply until the next directive of the same kind.

## Handles

- A handle names an entity or relation instance: `[A-Za-z_][A-Za-z0-9_]*`.
- A handle is typed once, at its first typed mention, with the most specific known
  type: `p1:Person`. Later mentions are bare. A typed mention may appear in any
  handle position: record headers, value statement subjects (`p1:Person.Email x`),
  relation participants and reference values. A named binary relation instance
  (`r1: s verb o`) is typed by its relation and is never written `r1:Type`.
- A reference through a base type uses the same handle. Retyping a handle to an
  incompatible type is an error; retyping to a specialisation refines it.
- Handles are transport identities, not business keys. Matching instances across
  documents requires a shared `@scope`. Within a scope, [identity
  links](#identity-links) and the referentials of
  [spec-05](spec-05-identities.md) decide which handles are the same instance.
- A handle may be referenced before any existence claim names it: it is then an
  [implicit instance](#implicit-instances), not an error.

### Type-only declarations

```text
@type p Person
@type scenario Planning/Scenario
@type r Household.hasMember.Person
```

`@type` populates the instance type registry. It asserts neither existence nor
facets nor relation endpoints, carries no statement metadata, changes no metadata
defaults, and consumes no statement ordinal. It takes exactly a handle and an
instance type: an entity, an association, or a binary relation's canonical
`S.verb.T` path. Names and both binary endpoints resolve using the ontology
namespace and aliases, just as ordinary typed mentions do.

Declarations may appear after `@obs` anywhere outside record bodies; they are
available throughout the document. Compatible specialisation refines a type.
Invalid declarations—unknown or incompatible types, or malformed syntax—are
errors in both modes. A later ordinary statement can assert existence, but the
declaration itself does not. Retractions withdraw claims, not registry types.

Normal forms emit `@type` only when ordinary typed mentions or defining named
links cannot preserve the registry: for unused handles, context-only handles and
named binary handles without a defining link. This retains type information after
retraction without inventing existence. `@implicit` remains a separate,
recomputed display marker; declaring a type does not itself make a handle implicit.

## Statements

| Form | Claims |
| --- | --- |
| `h:Type` / `h` | Instance `h` exists (bare form for an already-typed handle, e.g. to give `valid`) |
| `h:Type[F1, F2]` / `h[F1]` | Facets `F1`, `F2` apply to `h` (an entity or association instance) |
| `h.Attr Value` / `h:Type.Attr Value` | Attribute value (optionally typing the handle) |
| `h.Attr.Field Value` | Field of a structured attribute value |
| `h.Attr[Key].Field Value` | Field of the element `Key` of a [keyed structure](spec-01-ontology.md#keyed-structures) |
| `h.Facet.Attr Value` | Facet attribute value; implies the facet applies |
| `[r:] s verb o` | Binary relation instance `r` (inverse verbs accepted) |
| `r.Attr Value` / `r.Role h` | Relation attribute / participant |
| `a = b` / `a != b` | Identity link: same instance, `a` canonical / different instances ([below](#identity-links)) |
| `- statement` | Retraction (see below) |

### Record form

A typed mention followed by indented body lines is shorthand for the same
statements with `h.` prefixed:

```text
p1:Person[Investor]
  DateOfBirth 1990-06-15
  Investor.RiskTolerance Medium
```

is equivalent to

```text
p1:Person[Investor]
p1.DateOfBirth 1990-06-15
p1.Investor.RiskTolerance Medium
```

Metadata on the header line applies to the header claim only, not the body lines.

### Relations

- Binary relations declared with the shorthand use line form: `h1 hasMember p1`.
  An inverse verb is accepted and normalised to the forward direction:
  `p1 memberOf h1` is the same claim. When a verb is shared by several relations,
  the object's type selects one; an unknown object (`?`) must then be unambiguous.
- Symmetric relations order their participants by handle: `p2 partnerOf p1` and
  `p1 partnerOf p2` are the same claim.
- `r: s verb o` names the instance so attributes can be given (`r.Role Adult`).
  Without a handle, the instance is anonymous and identified by its participants
  within the document.
- n-ary relations use record form. Role lines and attribute lines look alike; the
  ontology distinguishes them. Multi-participant roles take a collection.
- Each relation handle is a distinct instance: two trades are two handles even
  with identical participants.
- A participant may be `?` (unknown). Facet subjects and statement subjects must
  be handles.

## Values

Interpretation follows the ontology type, not the spelling.

| Kind | Encoding |
| --- | --- |
| Text | Bare text to end of line (or to ` {`). Use a JSON string `"..."` when the text has leading/trailing spaces, contains ` {`, a line break or `,`/`]` inside a collection, or would read as `?`, `null`, `[` or `"`. |
| Category | A vocabulary value. Closed vocabularies are enforced; open ones accept other names. Hierarchical vocabularies use full value paths, e.g. `Food/Fruit/Apple`. |
| Integer, Number, Amount, Percent | Decimal number, optionally signed, optional exponent, no grouping separators |
| Boolean | `true` / `false` |
| Date / DateTime | ISO 8601 (`2026-11-10`, `2026-11-10T09:30:00+13:00`) |
| Duration | Number in the type's unit; ISO 8601 duration (`P2Y6M`) when the unit is unknown |
| Range | `low..high`, `low..`, `..high`, or one value `v` (read `v..v`); each bound in the encoding of the range's type, inclusive, `low <= high`. Stored as `low..high` with canonical bounds |
| Reference | A handle (`p1`) or typed mention (`p2:Person`) |
| Structure | Field paths `Attr.Field Value`, one line each; on a multi-valued keyed structure, per element: `Attr[Key].Field Value` |
| Collection | `[a, b]` complete set; `[a, b, ...]` incomplete; `[]` known empty |
| Unknown | `?` |
| Absent | `null`: confirmed absence of a single value |

- A local measurement qualifier may follow the value: `92000 {cur=USD}`. It may
  fill an unknown qualifier, never contradict a fixed one, and must be a value
  of the qualifier's vocabulary when the type declares one (`{cur=?:Currency}`).
  No conversion is implied.
- For [hierarchical vocabularies](spec-01-ontology.md#hierarchical-vocabularies-taxonomies),
  any declared node (including an inferred ancestor) is a valid category.
  Values are full paths, never ambiguous leaf names: `Food/Fruit/Apple`, not
  `Apple`. A value does not assert additional values for its ancestors, and
  collections do not expand to include ancestors. JSON encodes the full path
  as a string.
- On a multi-valued attribute, a bare value claims **one member**. A bracketed
  collection claims the **membership**: complete, or incomplete with `...`.
- Collections are unordered, duplicate-free and do not nest.
- A value for a derived attribute is an observed value; it is not recomputed or
  verified unless its rule and inputs are known.
- An omitted attribute says nothing. `?` says the value is not known. `null` says
  there is none. `[]` says the collection is empty.

## Metadata

Any statement may end with `{key=value, ...}`. Values are tokens, as in ontology
annotations; dates and intervals are tokens.

| Key | Meaning |
| --- | --- |
| `src` | Who made the claim: a source alias or token |
| `at` | When the claim was recorded or observed |
| `valid` | When the fact holds: `d`, `d1..d2`, `d1..` (open end), `..d2` (open start) |
| `ctx` | Context instance (a handle) of a claim on a contextual facet |
| `conf` | Confidence, `0..1` |
| `by` | Agent or process that produced the claim |
| `of` | Source whose claims a retraction withdraws |
| `approved` | Who approved a held retraction: a person or process token, or `confirm:<n>` ([spec-04](spec-04-mapping.md#approval)) |
| `cur`, `unit`, `period`, `scale` | Local measurement qualifiers on the value |
| `conflict` | Flag written by the state form; ignored on input (recomputed) |

Defaults come from `@obs` and the latest `@src`/`@at`/`@ctx` directives.

- `at` is transaction/observation time; `valid` is when the fact is true in the
  world. Neither implies the other.
- For `kind=event` relations, `valid` is a point; for `kind=state` relations, an
  interval. A new claim on the instance with a closed interval (e.g.
  `dr1 {valid=2021-07-01..2026-06-30}`) states the state ended. It is not a
  retraction.

## Contexts

A [contextual facet](spec-01-ontology.md#contextual-facets) (`F of E {ctx=C}`)
holds only within an instance of `C`. Its claims name that instance with `ctx`:

```text
@obs Finance at=2026-11-10
@src plan=planner:file/88
@src plan

o1:Organisation
p1:Person
i1:Income
  Payer o1
  Recipient [p1]
s1:Planning/Scenario
  Name Base
s2:Planning/Scenario
  Name EarlyRetirement

@ctx s1
i1[IncomeTreatment]
i1.IncomeTreatment.IsIncluded true
i1.IncomeTreatment.IsIncluded false {ctx=s2}
@ctx none
```

The salary is counted in the base scenario and excluded from the early-retirement
scenario: two slots, no conflict, even though the same source made both claims.

- A claim on a contextual facet — applicability `h[F]` or a value
  `h.F.Attr ...`, and their retractions — **requires** `ctx`, explicitly or from
  `@ctx`. The handle must be typed in the document as an instance of the facet's
  `ctx` type (or a specialisation; an association exactly).
- `ctx` on any other claim is an error. On a header line (`h:T[F, G] {ctx=a1}`)
  it applies to the contextual facets only, not to the existence claim; at least
  one must be contextual.
- `none` is reserved: it is not a valid context handle.

## Supersession and conflicts

A **slot** is a subject plus attribute path (or facet applicability, or relation
existence), plus the context for contextual claims. Claims in different contexts
are in different slots: they never supersede or conflict with each other.

- **Within one source**, for a single-valued slot, the claim with the latest `at`
  supersedes earlier claims. Equal `at`: the later statement in the log wins.
- For multi-valued slots, member claims accumulate; a complete collection claim
  from a source replaces that source's earlier members.
- **Across sources**, differing claims on a single-valued slot are a **conflict**.
  Conflicts are reported and all claims are kept; resolution is the consumer's
  decision, possibly expressed as a new claim by a curating source.
- Claims with different `valid` intervals do not conflict unless the intervals
  overlap.

## Retraction

`- statement` withdraws earlier claims. A retraction is itself an observation with
its own `src` and `at`.

| Form | Withdraws |
| --- | --- |
| `- h.Attr Value` | The claim of that value |
| `- h.Attr` | All claims on that slot; for a keyed structure, every element |
| `- h.Attr[Key]` | The element `Key` of a keyed structure: all its fields |
| `- s verb o` / `- r` | The relation instance and its attributes |
| `- h[F]` | Applicability of facet `F` and its attribute claims |
| `- h` | Instance `h` and every claim about it |

- A retraction with `ctx` withdraws claims in that context only; one on a
  contextual facet requires it. `- h` also withdraws claims whose context is `h`.
- By default a retraction withdraws claims made by the **same source** with `at`
  at or before the retraction's `at`. When the retraction carries `by`, it
  withdraws only claims with the same `by` as well: a re-run binding or mapping
  withdraws its own output, never what another process reported for the same
  source. `{of=d7}` withdraws another source's claims; this is for curators and
  correcting agents, and keeps the retracting `src`.
- A retraction means "this claim should not have been made". It does not mean the
  value is false, absent or ended:
  - fact stopped being true → claim with `valid=..end`;
  - confirmed absence → `null` / `[]`;
  - corrected value → a new claim (which supersedes within the same source).
- Retracting a claim that does not exist is a warning, not an error.

Each element of a keyed structure is its own slots (`h.Phones[Mobile].Number`,
`h.Phones[Home].Number`): sources supersede, conflict and are withdrawn element
by element. A key must be a value of the key field's vocabulary; a field path of
a keyed attribute without a key (`h.Phones.Number`), a key on an attribute that
has none, or a statement of the key field itself (`h.Phones[Mobile].Use`) is an
error (`key`).

## Identity links

`a = b` claims that handles `a` and `b` name the same instance, `a` being the
canonical handle; `a != b` that they name different instances. Links are claims:
they carry metadata, accumulate and are withdrawn by retraction (`- a = b`).
Their resolution (groups, canonical handles, identity conflicts) is defined by
[spec-05](spec-05-identities.md#resolution). Both handles are typed, as anywhere
else (`c1:Company = c9:Company` when first mentioned), with compatible types; a
link from a handle to itself is an error.

## Implicit instances

A handle that is referenced (a reference value, a relation participant or a
`ctx`) but has no surviving existence claim, from any source, is **implicit**:
the data mentions it before, or without, describing it. It is valid. The state
form lists implicit handles in `@implicit`; the mark is recomputed, never read,
and disappears once an existence claim arrives.

## Validation

Against the ontology (and optionally a view):

- Types exist; facets belong to the subject's type; attributes, roles and verbs
  exist on their owners; references and participants have compatible types.
- Values match their types; closed vocabularies are enforced; `null` only on
  single values; `[]` contradicts `1`/`+`.
- Required cardinalities are unverified, not violated, when values are omitted or
  collections incomplete.
- Unknown elements are errors. In lenient mode they are kept as **gaps** with
  their raw text, for review and ontology evolution.

Every processor has two modes. **Strict** (the default; offline processing)
turns anything doubtful into an error or a request for approval and writes
nothing until it is resolved. **Lenient** (online processing) keeps going,
reports warnings and holds back only what could erase data. The
[run modes](spec-04-mapping.md#run-modes) of bindings and mappings and the
identity conflicts of [spec-05](spec-05-identities.md#resolution) use the same
two modes.
- With a view: report which selected attributes, facets and relations are
  supplied, unknown, absent or missing (coverage).

Lenient observation loading retains semantically invalid statements as **gaps**,
with their raw source, location, effective metadata defaults and diagnostics.
A statement is atomic: none of a gap's expanded claims or retractions is applied.
Other valid statements continue to be processed. Syntax, header and directive
errors remain fatal, rather than guessing how they affect subsequent statements.
Gaps are review material, not evidence of a value, absence or removal.
Gap-bearing results use the JSON form for interchange. Text normal-form printers
must not silently discard gaps or emit them as active statements: printing fails
until the gaps have been reviewed and removed or explicitly reprocessed.

## Normal forms

**Log form** (audit, replay): all statements including retractions and superseded
claims, one per line (no record form); ordered by `at`, then document order. Each
handle is typed at its first occurrence. `@src`/`@at`/`@ctx` directives are
emitted when the source, time or context (of contextual claims) changes; metadata
equal to the current defaults is omitted.

**State form** (comparison, diff): retractions applied, superseded claims
removed, conflicts kept and marked `{conflict}`, identity links applied (claims
on and references to aliases reported on the canonical handle), implicit
instances listed.

1. `@obs`, then `@src` alias declarations sorted by alias, then `@scope`, then
   necessary `@type` declarations sorted by handle, then `@implicit` with its
   handles sorted. Log form uses the same registry-only type prelude.
2. Entity records in record form, sorted by `(type path, handle)`. Facets in the
   header sorted. Body lines sorted by attribute path, then context, then value.
   Order-sensitive multi-valued slots use rule 9 instead of value order.
3. Binary relation lines sorted by `(subject handle, verb, object handle)`, always
   in the forward direction. Named instances keep their handles; their attribute
   lines follow, sorted.
4. n-ary relation records sorted by `(relation path, handle)`, body as entities.
   Then identity links in log order (`at`, then statement ordinal), preserving
   their original endpoints and metadata. Do not sort links by operator or handles:
   their order determines canonical handles (spec-05). A `!=` link puts the
   smaller handle first; this does not change the link's position.
5. Collections are sorted by encoded value.
6. Metadata keys follow the table order. The formatter sets `@src` and `@at` to
   the most frequent source and time among the claims; claims with other values
   carry them explicitly.
7. A record header carries the existence claim's metadata. Additional existence
   claims print as bare `h {...}` lines, and facet claims whose metadata differs
   from the header as `h[F] {...}` lines, after the record body.
8. `ctx` is always explicit (`IncomeTreatment.IsIncluded true {ctx=s1}`, one line
    per context; contextual facets as `h[F] {ctx=a1}` lines); there is no `@ctx`.
9. When a multi-valued slot retains a source's complete collection and later
   claims (members, incomplete collections or unknowns), keep all claims on that
   slot in log order (`at`, then statement ordinal). Value-sorting could put later additions
   before the complete collection and discard them on replay. Keep each claim's
   metadata; do not invent an aggregate claim. Other slots retain value order,
   and members inside each collection remain sorted by encoded value.

## JSON form

The interchange form; text and JSON convert losslessly (comments excepted). The
structure is defined by
[`observations.schema.json`](../../src/json/observations.schema.json). An
excerpt of the [example](#example):

```json
{
  "format": "onto.observations/1",
  "obs": { "ontology": "Finance", "rev": "2026-11-10", "at": "2026-11-10", "scope": null },
  "sources": { "d7": "upload:document/123", "ex": "exchange:announcement/411075", "st": "broker:statement/2026-10" },
  "instances": {
    "dr1": { "type": "Finance/Directorship" },
    "p1": { "type": "Finance/Person" },
    "r1": { "type": "Finance/Household.hasMember.Finance/Person" },
    "t1": { "type": "Finance/Trade" }
  },
  "claims": [
    { "n": 1, "s": "p1", "exists": true, "src": "st", "at": "2026-11-10" },
    { "n": 1, "s": "p1", "facet": "Investor", "src": "st", "at": "2026-11-10" },
    { "n": 2, "s": "p1", "p": "DateOfBirth", "v": "1990-06-15", "src": "st", "at": "2026-11-10" },
    { "n": 7, "s": "r1", "rel": "Finance/Household.hasMember.Finance/Person", "roles": { "Household": "h1", "Person": "p2" }, "src": "st", "at": "2026-11-10" },
    { "n": 22, "s": "t1", "p": "Counterparty", "v": { "unknown": true }, "src": "st", "at": "2026-11-10" },
    { "n": 24, "s": "t1", "p": "Trader", "v": { "set": [{ "ref": "p1" }, { "ref": "p2" }] }, "src": "st", "at": "2026-11-10" },
    { "n": 25, "s": "t1", "p": "Price", "v": "98.5", "src": "st", "at": "2026-11-10" },
    { "n": 31, "s": "dr1", "exists": true, "valid": "2021-07-01..2026-06-30", "src": "ex", "at": "2026-11-10" },
    { "n": 32, "s": "p1", "p": "DateOfBirth", "v": "1990-06-16", "src": "d7", "at": "2026-10-01" }
  ],
  "retractions": [
    { "n": 33, "s": "p1", "p": "DateOfBirth", "v": "1990-06-16", "src": "d7", "at": "2026-11-02" }
  ]
}
```

- `obs` holds the `@obs` arguments (strings) plus `ontology` and `scope` (`null`
  when handles are document-local). `sources` maps aliases to provenance tokens.
  `instances` maps each handle to its most specific known type, plus
  `"implicit": true` for [implicit instances](#implicit-instances) in the state
  form (ignored on input).
  Type-only declarations use this existing registry; they introduce no JSON
  claim or additional member. The text round trip preserves even unused types.
- Values (`v`), read through the ontology type:

  | Value | JSON |
  | --- | --- |
  | Text, vocabulary value, Date, DateTime, ISO Duration | string |
  | Integer, Number, Amount, Percent, numeric Duration | **canonical decimal string**: no `+`, no leading or trailing zeros, `-0` is `0` (`"850000"`, `"7.5"`, `"1.25e3"`) |
  | Boolean | `true` / `false` |
  | Reference | `{"ref": "h"}` |
  | Collection | `{"set": [...]}`, plus `"partial": true` when incomplete; `[]` is `{"set": []}` |
  | Unknown `?` / absent `null` | `{"unknown": true}` / `null` |

  Numbers are strings so that no precision is lost to binary floating point and
  equal values compare equal as strings. Omitting `v` is only valid on a
  retraction (it withdraws the whole slot).
- Claim kinds: existence `"exists": true`; facet applicability `"facet"`; attribute
  value `"p"` (attribute path, as in the text form) and `"v"`; relation `"rel"` and
  `"roles"` (role → handle, `"?"` for an unknown participant), with `"s"` only for
  named instances; identity links `"same": [a, b]` (`a = b`) and
  `"distinct": [a, b]` (`a != b`), without `"s"`. Types and relation paths are
  fully qualified.
- Metadata members are those of [Metadata](#metadata), already resolved against
  the `@obs`/`@src`/`@at`/`@ctx` defaults: `src`, `at`, `valid`, `ctx` (a handle),
  `by`, `of`, `approved`, the qualifiers (strings) and `conf` (a JSON number in `0..1`).
- An optional `gaps` array retains unapplied statements from lenient loading;
  it is omitted when empty. Each gap has `n`, `raw` (the original physical line),
  `text` (line-form statement without metadata, with a record-body subject expanded),
  `loc: {file, line}`, `meta` (effective metadata as text tokens), and
  `diagnostics: [{code, message}]`. An optional `ctx` records the active `@ctx`
  default separately from any explicit `meta.ctx`. Gap-bearing JSON requires
  lenient loading; gap statements are revalidated but never promoted silently to
  claims. The raw source and original locations remain available for review.
- `n` is the 1-based ordinal of the statement in the document. Each line-form
  statement, record header and record body line counts once; directives,
  comments and blank lines do not. `n` orders claims with equal `at`. Claims
  from one statement (a record header with facets, a typed mention) share `n`.
- **Log form** (`obs --form json-log`): every claim and retraction. **State form**
  (`obs --form json`): `retractions` is empty, superseded claims are removed and
  conflicting claims have `"conflict": true`. Both validate against the schema and
  both are accepted as input.

Reading JSON prints its log-form text and parses that, so every rule of this spec
applies, including typing against the ontology; JSON that does not survive the
round trip is rejected.
