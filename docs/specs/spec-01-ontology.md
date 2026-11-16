# Ontology format

A compact text format for a conceptual model ("the Ontology"): types, entities,
facets, relations and views. It is designed to be communicated to agents in few
tokens, to diff cleanly, and to be generated from other schema sources. It
describes concepts, not storage, executable rules or validation logic.

Instance data uses the [observations format](spec-02-observations.md). Curated
facet assignments for imports use the [overlay format](spec-03-overlay.md).
Data moves between systems and ontologies through
[bindings and mappings](spec-04-mapping.md).

## Concepts

| Concept | Meaning |
| --- | --- |
| Domain | A declared top-level namespace segment grouping elements (Investing, Planning, ...). |
| Type | A named value type: scalar, vocabulary, structure or alias. Values have no identity. |
| Entity | A kind of identifiable thing. Instances are referenced by identity. |
| Specialisation | A subtype sharing its base's identity and inheriting its attributes and facets. |
| Facet | A perspective a domain contributes to an entity or association: a named group of attributes that applies to some instances, possibly only within a context. |
| Relation | An association between participants. Each instance has its own identity and may carry attributes (state). |
| Map | How the values of one vocabulary correspond to another's. |
| View | A selection of entities, facets, attributes and relations for a context (a profile). |
| Attribute | A property of an entity, facet, relation or structure: observed or derived. |

## Example

```text
@ontology Finance rev=2026-11-10 src=import card=? cards=assumed
@use Dimensions as D

// Types
D/AssetClass = Bond|Cash|Derivative|Equity|Fund|... -- Open: values are examples
D/InterestFrequency = Monthly|Quarterly|Biannually|Yearly {ordered}
D/Money/USD = Amount {cur=USD}

D/PersonName =
  FullName Text
  GivenNames Text
  Surname Text

D/RiskTolerance = Low|Medium|High {ordered}
Years = Duration {unit=Year}

// Entities and their facets
Account
  Number Text {key}
  Type Brokerage|Retirement|Savings

Company < Organisation                          -- An issuer of listed instruments
  Code Text {key}
  RegisteredName Text
  SuspensionStatus Active|Halted|Suspended

Household

Instrument                                      -- A tradable security
  AssetClass D/AssetClass
  Code Text
  Isin Text {key}
  Name Text

Bond of Instrument                              -- Fixed-income terms
  CouponRate Percent {scale=100}
  InterestFrequency D/InterestFrequency
  MaturityDate Date

Organisation < Party
Party

Person < Party                                  -- A natural person
  ~ Age Years <- $AsOf, DateOfBirth {rule=?}
  DateOfBirth Date
  Email Text {key}
  Name D/PersonName

Investing/Investor of Person                    -- Contributed by the Investing domain
  Horizon Years
  RiskTolerance D/RiskTolerance

// Relations
Company -issues/issuedBy-> Instrument 1:*

Directorship(Company, Director: Person) {kind=state}
  Type Executive|Independent|NonExecutive

Dividend(Instrument, Payer: Company) {kind=event}
  Amount D/Money/USD
  PayableDate Date

Household -hasMember/memberOf-> Person 1:*
  Role Adult|Dependant

Ownership(Account, Owner: Party) {kind=state}
  SharePercent Percent {scale=100}

Trade(Account, Counterparty: * Party, Instrument, Trader: + Person) {kind=event}
  Price D/Money/USD
  Quantity Number
  Side Buy|Sell

// Views
@view PortfolioReview                           -- What a portfolio review needs
  Household.hasMember
  Instrument[Bond]
  Ownership
  Person[Investor]
  Trade
```

## Lexical rules

- UTF-8, LF line endings. Trailing whitespace is insignificant; blank lines separate
  nothing and are ignored.
- Declarations start in column 0. Body lines are indented by exactly two spaces.
  Bodies have one level, except hierarchical vocabulary trees, whose indentation
  increases by two spaces per level.
- `//` to end of line is a comment and is discarded. A comment must be the whole
  line or be preceded by whitespace.
- ` -- text` at the end of a declaration or body line is a doc string attached to
  that element. Docs are kept in normal form and may be stripped when slicing.
  A doc ends at the end of the line; it cannot contain line breaks.
- **Names** match `[A-Za-z_][A-Za-z0-9_]*`. Types, entities, facets, relations,
  roles and attributes use PascalCase. Relation verbs use lowerCamel, so a verb
  never collides with an attribute or role. Naming policy beyond the grammar is
  out of scope.
- **Paths** are `/`-separated names: `Investing/Investor`. The final segment names
  the element; preceding segments are its namespace. Namespaces imply neither
  inheritance nor grouping of vocabularies.

## Directives

```text
@ontology <Namespace> {key=value ...}
@use <Namespace> as <Alias>
@domain <Name> [-- doc]
@map <Name> <From> -> <To> [{annotations}] [-- doc]
@view <Name> [-- doc]
```

`@ontology` is required and comes first. Its arguments are `key=value` pairs
(without braces) that set file defaults:

| Key | Meaning | Default |
| --- | --- | --- |
| `rev` | Revision token of the ontology | none |
| `src` | Default provenance for declarations | none |
| `card` | Default attribute cardinality | `?` |
| `cards` | Evidence status of cardinalities: `stated`, `inferred`, `assumed` | `stated` |
| `rel` | Default binary relation counts (`L:R`) | `*:*` |

An ontology may span several files with the same `@ontology` namespace and `rev`.
Their declarations are combined; duplicate declarations are errors. This keeps
large vocabularies or domain contributions in separate files.

`@use Namespace as Alias` lets `Alias/...` stand for `Namespace/...` in this file.
Aliases are file-local.

`@domain Name` declares a domain `Namespace/Name`. `Name` is a single name (no
`/`); the directive has no body. An element whose first path segment (relative to
its namespace) is a declared domain belongs to that domain.

### Name resolution

A name in type, subject, base or participant position resolves, in order:

1. Built-in type names (reserved; cannot be declared).
2. Paths whose first segment is a `@use` alias: `D/Money/USD` means
   `Dimensions/Money/USD`.
3. Otherwise, paths relative to the `@ontology` namespace: `Person` means
   `Finance/Person`, `Investing/Investor` means `Finance/Investing/Investor`.

Declarations use the same rule. To refer to another namespace, declare a `@use`
alias for it (`@use Dimensions as Dimensions` is valid). There is no search
through other namespaces; an unresolved name is an error.

## Declarations

| Form | Declares |
| --- | --- |
| `T = Builtin {qualifiers}` | Scalar type |
| `T = OtherType {qualifiers}` | Alias: same values, its own meaning; qualifiers inherited |
| `T = Entity` | Reference type: a reference to an instance, not a copy |
| `T = A\|B\|C` | Closed vocabulary |
| `T = A\|B\|...` | Open vocabulary: values are examples, others are allowed |
| `T = A/B\|A/C {hierarchical}` | Hierarchical vocabulary; also accepts an indented tree body |
| `T = ...` | Categorical with unknown vocabulary |
| `T =` + body | Structure: named fields, no identity of its own |
| `T =` (no body) | Type with unspecified detail |
| `E` / `E < Base` + optional body | Entity / specialisation |
| `F of E` + optional body | Facet `F` of entity or association `E` |
| `R(Role: [card] Type, ...)` + optional body | Relation |
| `S -verb[/inverse]-> T [L:R]` + optional body | Binary relation (shorthand) |
| `@domain D` | Domain |
| `@map M From -> To` + body | Value map between two vocabularies |
| `@view V` + body | View |

Any declaration line may end with `{annotations}` and then ` -- doc`.

Every declared path is unique across domains, types, entities, facets, relations,
maps and views.
Cycles in aliases or specialisation are errors.

### Built-in types

`Text`, `Integer`, `Number`, `Boolean`, `Date`, `DateTime`, `Duration`, `Amount`,
`Percent`.

- `Amount` is a monetary amount; its currency is a qualifier.
- `Percent` is numeric; its scale (`1` for `0..1`, `100` for `0..100`) is a qualifier.
- `Duration` is an elapsed length; its unit is a qualifier.
- `Years`, `Months`, `Days` are not built in; declare them, e.g. `Years = Duration {unit=Year}`.

### Vocabularies

- Values are names, or value paths with `{hierarchical}` (see below).
  `A|B` is exhaustive; a trailing `|...` makes it open.
- A single-value vocabulary starts with `|` (`|TrialPeriod`), so it is not read
  as a type name. Spaces around `|` are allowed when parsing; normal form has none.
- Values are sorted in normal form unless the type is annotated `{ordered}`
  (e.g. bands), in which case declaration order is meaningful and kept.
- A vocabulary may be declared inline as an attribute type
  (`Side Buy|Sell`). It then has no path of its own; declare a
  named type when it is shared or needs annotations.

#### Hierarchical vocabularies (taxonomies)

`{hierarchical}` gives vocabulary values a parent–child hierarchy. It does not
change the namespace meaning of declaration paths. These declarations are
equivalent:

```text
Category = Food/Fruit/Apple|Food/Fruit/Pear|Food/Vegetables|Clothing/Shirts {hierarchical}
```

```text
Category = {hierarchical}
  Food
    Fruit
      Apple
      Pear
    Vegetables
  Clothing
    Shirts
```

- A value is a `/`-separated sequence of names. Its full path identifies it
  within the vocabulary; `Food/Fruit/Apple` is not a reference to a declaration.
  Empty segments, leading or trailing `/` and non-name segments are invalid.
  Without `{hierarchical}`, vocabulary values remain single names.
- Each proper path prefix is an ancestor and an allowed value. Compact paths
  infer missing ancestors: `Food/Fruit/Apple` also declares `Food` and
  `Food/Fruit`. Intermediate nodes can be selected just like leaves.
- A tree body starts at two spaces. Each line contains one name; each deeper
  level adds exactly two spaces and appends that name to its parent's path.
  Indentation may not skip a level. Duplicate full paths in the tree are errors;
  the same name under different parents is allowed.
- A declaration uses either compact values or a tree body, never both. A body
  requires an explicit `{hierarchical}` flag and at least one node. This
  distinguishes it from a structure. Multiline vocabularies are named types;
  inline attribute vocabularies may use compact paths with `{hierarchical}`.
  A compact single-value vocabulary keeps the leading `|` rule:
  `Category = |Food/Fruit/Apple {hierarchical}`.
- A trailing `|...` makes the compact form open. In a tree, a final `...` line
  at two spaces does the same; it is not a node and cannot occur deeper.
  Open vocabularies accept other well-formed value paths, including new roots;
  observing one does not extend the declared vocabulary.
- Each node has at most one parent. Multiple roots are allowed; multiple
  parents require an explicit entity-and-relation model instead.
- Values match exactly. The hierarchy describes ancestry, not automatic
  ancestor observations, descendant matching or aggregation.
- Aliases retain the vocabulary's hierarchy, openness and ordering.

### Structures

```text
D/PersonName =
  FullName Text
  GivenNames Text
  Surname Text
```

Fields use attribute syntax. Namespace children are not fields: `D/PersonName/X`
is a separate type, unrelated to the structure.

### Entities and specialisations

`E < Base` declares a subtype that shares the base's identity: an instance of `E`
is an instance of `Base`. It inherits attributes and facets and may add its own.
It must not redeclare an inherited attribute name. Single inheritance only.

An entity's own body should hold its core, identity-level attributes. Contextual
attributes belong in facets.

### Facets

`F of E` declares a facet: a group of attributes that a domain contributes to
entity or association `E`, applicable to some of its instances. A facet:

- shares its subject's identity; it is not a separate instance;
- has exactly one subject (v1): an entity, and then it applies to its
  specialisations, or an association (an n-ary relation). Binary relations have
  no facets;
- may live in any namespace, which records the contributing domain;
- is addressed on its subject by the last segment of its path. That segment must
  be unique among the subject's facets (including inherited ones) and must not
  equal one of the subject's attribute names (or, for an association, its roles).

Facet attributes are always addressed through the facet:
`Person.Investor.RiskTolerance`, `Income.IncomeTreatment.IsIncluded`. Two
facets may therefore declare attributes with the same name.

#### Contextual facets

```text
Income(Payer: Party, Recipient: + Person)
  Amount D/Money/USD

Planning/Scenario                               -- A what-if projection of a household's finances
  Name Text

Planning/IncomeTreatment of Income {ctx=Planning/Scenario}
  IsIncluded Boolean
  ShadingPercent Percent {scale=100}
```

`{ctx=C}` on a facet makes it **contextual**: its applicability and attribute
values hold only within an instance of `C`, not of the subject as a whole. A
salary is counted in a household's base scenario and may be excluded in an
early-retirement scenario. `C` resolves like any name and must denote an entity or an
association. Every observation of the facet (applicability or attribute value)
names the context instance ([spec-02](spec-02-observations.md#contexts)).

A contextual facet models a judgement about its subject made in a context; it is
not a link to the context. Its attributes follow the same rules as other facet
attributes.

### Relations

```text
Trade(Account, Counterparty: * Party, Instrument, Trader: + Person) {kind=event}
  Price D/Money/USD
```

- Participants are `Role: [card] Type`. The role is optional and defaults to the
  type's last segment; roles must be unique within the relation. `Type` is an
  entity or another n-ary relation (an **association**: it has identity, so it
  can be a participant, a binary relation's subject or object, or an attribute
  type). Binary relations cannot be participants.
- Participant cardinality (`1`, `?`, `+`, `*`; default `1`) counts participants
  **per relation instance**: a trade on a joint account may have several traders.
- A relation needs at least two participant slots.
- Relation instances have **their own identity**: two trades of the same
  instrument by the same traders are two instances, each with its own attributes.
  Evidence for an instance (contract notes, statements) is linked through
  participants or reference attributes.
- Roles and relation attributes share one namespace and must not collide.
- `{kind=event}`: an instance happens at a point in time. `{kind=state}`: an
  instance holds over an interval. When an instance happens or holds is carried
  by observations (`valid=`), not by an implicit attribute. Without `kind`, the
  temporal reading is unspecified.
- Participation counts (how many instances a given participant may be in) are not
  expressed for n-ary relations in this version; record them with `check=`.

### Binary shorthand

```text
Household -hasMember/memberOf-> Person 1:*
  Role Adult|Dependant
```

- Declares a binary relation identified by its subject, verb and object, with path
  `Household.hasMember.Person` (`S.verb.T`). Its roles are the participants' type
  names; when both participants have the same type, they are `Subject` and `Object`.
- A verb may be shared by several relations from the same subject when their
  object types differ (`Party -holds-> Account`, `Party -holds-> Instrument`). Reading
  a verb from an entity (forward from `S`, or `inverse` from `T`) must identify one
  relation for any compatible object type: two relations with the same verb clash
  when both their source types and their target types are related by
  specialisation. Inherited relations count.
- `S -verb/verb-> S` (same verb, inverse and type) declares a **symmetric**
  relation: `a verb b` and `b verb a` are the same association.
- `L:R` gives participation counts: `L` is how many `S` each `T` relates to, `R`
  is how many `T` each `S` relates to. Each side is `?`, `1`, `*` or `+`. The
  example says a person is in at most one household, a household has many members.
  Omitted, `@ontology rel=` applies.
- Annotations go after `L:R`: `S -verb-> T 1:* {kind=state}`.
- `{context=R}` names an n-ary relation (the association) whose instances carry
  the link's state and other roles. It resolves like any name and must denote an
  n-ary relation. `subjectRole` and `objectRole` select the context's roles that
  hold the subject and the object:
  `Person -directs/directedBy-> Company {context=Directorship, subjectRole=Director, objectRole=Company}`.
  Selectors name roles of the context, compatible with each endpoint through
  specialisation. When both select the same role, it must have cardinality `+`
  or `*`.

### Maps

```text
@map Budget/FreqToBasis D/Freq -> D/Basis {rule=x26} -- Pay frequency to budget basis
  Fortnightly broader Monthly                   -- approximate
  Monthly exact Monthly
```

- `From` and `To` are declared vocabulary types (directly or through aliases).
- Body lines are `FromValue match ToValue [-- doc]`, with `match` one of `exact`
  (equivalent), `broader`, `narrower`, `related` (SKOS), read "To is *match*
  than From". Values must be listed in their vocabularies (open ones included).
  A `(From, To)` pair appears once.
  For hierarchical vocabularies, use full value paths; inferred ancestors count
  as declared values. Map lines do not implicitly apply to descendants.
- Annotations: `rule` (e.g. a scalar conversion token), `status`, `src`, `check`.
- In [mappings](spec-04-mapping.md#mappings), a map is also a function from
  `From` values to `To` values.

## Attributes

Body lines of entities, facets, relations and structures:

```text
[card] [~] Name [Type] [<- dependencies] [{annotations}] [-- doc]
```

| Cardinality | Meaning (values per owner instance) |
| --- | --- |
| `1` | Exactly one |
| `?` | Zero or one |
| `+` | One or more |
| `*` | Zero or more |

- Cardinality is written only when it differs from `@ontology card=`.
- `Type` is a built-in, declared type, inline vocabulary, entity or association
  (a reference), or `Owner.Attr` / `Owner.Facet.Attr` (reuse that attribute's type, not a link).
  An omitted type is unspecified.
- `~` marks a derived attribute. It requires `<-` followed by inputs:
  `<- A, B` (exhaustive), `<- A, ...` (incomplete), `<- ...` (unknown). Inputs are
  local attribute names, `Owner.Attr` paths or `$Input` context inputs supplied at
  evaluation time. Dependencies never imply a formula.
- Attributes are unique by name within their owner; in a facet, within the facet.

## Annotations

`{key=value, flag, ...}`. Values are unquoted tokens (no whitespace, `{}`, `,`,
`=`), numbers or `?` (unknown). A bare token is a flag. Free text goes in docs.
Keys, in normal-form order:

| Key | Applies to | Meaning |
| --- | --- | --- |
| `key` | attribute | Used for entity resolution (matching records to an instance). Not uniqueness, not requiredness. |
| `id` | attribute | How far a value identifies its subject: `key`, `narrow`, `broad`, `none`. `key` is the flag's meaning |
| `privacy` | attribute | Who may see values: audience names joined by `+` (e.g. `Owner+Household`). The audiences are not fixed by the format; normal form sorts them |
| `default` | attribute | The value assumed when none is observed (e.g. `Currency Currency {default=NZD}`). On a closed vocabulary it must be one of its values. Not allowed on derived attributes |
| `kind` | relation | `event` or `state` |
| `layer` | entity, relation | A name classifying the element across domains (e.g. `Party`, `Holding`, `Evidence`). The layers are not fixed by the format |
| `context` | binary relation | The n-ary relation carrying the link's state; written shortest, stored as a full path |
| `subjectRole`, `objectRole` | context-backed binary relation | Role names on the context selecting the subject and object |
| `ctx` | facet | Entity or association whose instances the facet's values hold within ([contextual facets](#contextual-facets)); written shortest, stored as a full path |
| `ordered` | vocabulary | Value order is meaningful |
| `hierarchical` | vocabulary | Values are taxonomy paths; prefixes are ancestors |
| `cur` | type, attribute | Currency code, or `?` |
| `unit` | type, attribute | Unit, or `?` |
| `period` | type, attribute | Reporting/payment basis (`Month`, `Year`, ...), or `?` |
| `scale` | type, attribute | Percent scale `1` or `100`, or `?` |
| `status` | any | `stated`, `inferred`, `assumed` |
| `cards` | attribute | Evidence status of this attribute's cardinality, overriding `@ontology cards=` |
| `deps` | derived attribute | `candidate`: dependencies are proposed, not confirmed |
| `rule` | derived attribute | Rule reference token, or `?` |
| `src` | any | Provenance; overrides the inherited value |
| `check` | any | Token naming an open question |
| `elided` | vocabulary | A slice omitted this many values |

**Measurement qualifiers** (`cur`, `unit`, `period`, `scale`) belong on type
declarations and are inherited through aliases and uses. A use may fill a `?` but
must not contradict a fixed value. Qualifiers do not cascade into structure fields.

**Provenance** `src` inherits ontology → declaration → attribute. `cards`
defaults to `@ontology cards=`. Other annotations are local.

`card` always means a cardinality (`@ontology card=`); the evidence for a
cardinality is `cards`, in the header and on attributes alike.

## Views

```text
@view IssuerProfile                             -- What an issuer summary needs
  Company.Code
  Company.issues
  Directorship
  Dividend
  Instrument[Bond]
```

Body lines select:

| Line | Selects |
| --- | --- |
| `E` | Entity `E` and its own attributes |
| `E[F1, F2]` | Entity `E`, its own attributes and the listed facets |
| `E[*]` | Entity `E` with all facets |
| `E.Attr` / `E.F.Attr` | A single attribute (and its owner, without other attributes) |
| `R` | A relation, its participants' entities (identity only) and its attributes |
| `R[F]` / `R.F.Attr` | An association with the listed facets / one facet attribute |
| `S.verb` / `S.verb.T` | All binary relations from `S` with that verb / the one to `T` |
| `V` (another view) | Everything that view selects |

Types used by selected elements, and the `ctx` of selected facets, are included
implicitly. Views are used to slice
the ontology for agents, to check whether observations cover a profile, and to
express extraction requests.

## Normal form

The formatter produces one canonical text per ontology; formatting it again
changes nothing. Diffs compare normal forms.

1. `@ontology`, then `@use` lines sorted by alias.
2. Domains.
3. Types.
4. Entities; each followed by its facets.
5. Relations (binary shorthand sorts by its `S.verb.T` path); each association
   followed by its facets.
6. Maps (lines sorted by `From` value, then `To` value).
7. Views.

Within declarations:

- Sorting uses fully resolved paths (`Dimensions/...` before `Finance/Years`),
  while names are written in their shortest form: relative to `@ontology` when
  possible, otherwise through a `@use` alias, otherwise fully qualified.
- Attributes and view lines are sorted by name. Flat vocabulary values are sorted
  unless `{ordered}` (on the type, or on the attribute for an inline vocabulary).
  Dependencies are sorted as written, `$Inputs` first and `...` last. Relation
  association participants sort by role name (their order is non-semantic);
  binary endpoints keep subject/object order.
- Cardinality equal to the default is omitted. Annotation keys follow the table
  order above; flags follow the same order.
- Tokens are separated by single spaces. A doc's ` -- ` starts at column 48
  (counting from 0, indentation included), padding the code with spaces, or one
  space after code that reaches column 47. Sections are separated by one blank line.
  Within a section, a declaration with a body is surrounded by one blank line;
  consecutive bodiless declarations are adjacent.
- Comments are dropped; docs are kept.
- A type is written as declared (inline vocabularies stay inline).
- Named hierarchical vocabularies are always written as indented trees, with
  every inferred ancestor explicit. Roots and siblings are sorted by name,
  unless `{ordered}`, then their first-appearance order is kept. In compact
  input, ancestors first appear with their first descendant. Parents precede
  their children (depth-first traversal). An open tree ends with `...` at two
  spaces. Inline hierarchical vocabularies remain compact, with every ancestor
  explicit in the same traversal order.

The [example](#example) is in normal form, except for its comments.

## Identity sidecar

`<Namespace>.ids` is a tab-separated file mapping normal-form paths to stable
source identifiers (for example, record IDs in the system the ontology was
imported from), sorted by path:

```text
Dimensions/RiskTolerance	...
Dimensions/RiskTolerance:Low	...
Finance/Bond	(overlay)
Finance/Household.hasMember.Finance/Person	0190f...
Finance/Instrument	019d2783-...
Finance/Instrument.Bond.CouponRate	019d2783-...
```

| Element | Path |
| --- | --- |
| Type, entity, facet, n-ary relation, view | Its path |
| Binary relation | `S.verb.T` with full paths |
| Entity/relation/structure attribute | `Owner.Attr` |
| Facet attribute | `Subject.Facet.Attr` |
| Relation role | `Relation.Role` |
| Vocabulary value | `Type:Value` |

For a hierarchical value, `Value` is the full path, for example
`Dimensions/Category:Food/Fruit/Apple`. Ancestors may have their own identifiers.

The sidecar is not part of the agent-facing text. Paths without a source
identifier are omitted or marked `(overlay)`/`(authored)` for elements that do not
exist in the source.

## JSON form

The interchange form for tools that should not parse the text. Text and JSON
convert losslessly (comments excepted); the structure is defined by
[`ontology.schema.json`](../../src/json/ontology.schema.json). An excerpt of the
[example](#example):

```json
{
  "format": "onto.ontology/1",
  "namespace": "Finance",
  "header": { "rev": "2026-11-10", "src": "import", "card": "?", "cards": "assumed" },
  "uses": { "D": "Dimensions" },
  "decls": [
    { "kind": "type", "path": "Dimensions/Money/USD", "def": { "builtin": "Amount" }, "ann": { "cur": "USD" } },
    { "kind": "type", "path": "Dimensions/PersonName", "fields": [{ "name": "Surname", "card": "?", "type": { "builtin": "Text" } }] },
    { "kind": "type", "path": "Dimensions/RiskTolerance", "def": { "values": ["Low", "Medium", "High"], "open": false }, "ann": { "ordered": true } },
    { "kind": "entity", "path": "Finance/Person", "base": "Finance/Party", "doc": "A natural person",
      "attrs": [
        { "name": "Age", "card": "?", "derived": true, "type": { "path": "Finance/Years" },
          "deps": [{ "input": "AsOf" }, { "local": "DateOfBirth" }], "ann": { "rule": "?" } },
        { "name": "Email", "card": "?", "type": { "builtin": "Text" }, "ann": { "key": true } }
      ] },
    { "kind": "facet", "path": "Finance/Investing/Investor", "subject": "Finance/Person", "doc": "Contributed by the Investing domain",
      "attrs": [{ "name": "RiskTolerance", "card": "?", "type": { "path": "Dimensions/RiskTolerance" } }] },
    { "kind": "relation", "path": "Finance/Household.hasMember.Finance/Person",
      "participants": [{ "role": "Household", "card": "1", "type": "Finance/Household" }, { "role": "Person", "card": "1", "type": "Finance/Person" }],
      "arrow": { "verb": "hasMember", "inverse": "memberOf", "counts": "1:*" },
      "attrs": [{ "name": "Role", "card": "?", "type": { "values": ["Adult", "Dependant"], "open": false } }] },
    { "kind": "relation", "path": "Finance/Trade",
      "participants": [
        { "role": "Account", "card": "1", "type": "Finance/Account" },
        { "role": "Counterparty", "card": "*", "type": "Finance/Party" },
        { "role": "Instrument", "card": "1", "type": "Finance/Instrument" },
        { "role": "Trader", "card": "+", "type": "Finance/Person" }
      ],
      "attrs": [{ "name": "Side", "card": "?", "type": { "values": ["Buy", "Sell"], "open": false } }],
      "ann": { "kind": "event" } },
    { "kind": "view", "path": "Finance/PortfolioReview", "doc": "What a portfolio review needs",
      "lines": [{ "path": "Finance/Household", "member": "hasMember" }, { "path": "Finance/Person", "facets": ["Investor"] }] }
  ],
  "ids": { "Finance/Instrument": "019d2783-..." }
}
```

- `decls` are in normal-form order. Every path is fully qualified (aliases are
  resolved); `uses` only records the aliases used to print the text form.
- Defaults are **explicit**: every attribute has `card` (the `@ontology card=`
  default applied), every participant has `card` (`1` by default) and every
  binary `arrow` has `counts` (`@ontology rel=` applied). `header` keeps the
  defaults so the text form can omit them again.
- Absent optional members are omitted, never `null`: no `type` means unspecified,
  no `attrs` means none, no `base`/`doc`/`ann`/`inverse`.
- Type expressions: `{"builtin": "Text"}`; `{"path": P}` for a declared type or an
  entity (a reference); `{"path": P, "attr": "A.B"}` reuses an attribute's type;
  `{"values": [...], "open": bool}` for a vocabulary; `{"unknown": true}` for `...`.
- Hierarchical vocabularies use the same flat `values` array with full value
  paths and `"hierarchical": true` in the declaration's `ann` (or the attribute's
  `ann` for an inline vocabulary). Every ancestor is explicit; values follow
  the tree's normal-form traversal order. JSON input may omit ancestors, which
  are inferred as in compact text. No nested JSON tree is needed. For example:

  ```json
  {
    "kind": "type",
    "path": "Finance/Category",
    "def": {
      "values": ["Food", "Food/Fruit", "Food/Fruit/Apple"],
      "open": false
    },
    "ann": { "hierarchical": true }
  }
  ```

- Dependencies: `{"local": "A"}`, `{"input": "AsOf"}` (`$AsOf`),
  `{"path": P, "attr": "A"}`, `{"ellipsis": true}` (`...`), in normal-form order.
- Annotations are an object in normal-form key order; values are tokens (strings)
  and flags are `true`.
- A binary relation's `path` is `S.verb.T` and its roles are derived as in the text
  form; both are written out so consumers need not derive them.
- `{"kind": "domain", "path", "doc"?}`; `{"kind": "map", "path", "from", "to",
  "lines": [{"from", "match", "to", "doc"?}], "ann"?, "doc"?}` (`from`/`to` are
  full type paths; line values are names, or full value paths for hierarchical
  vocabularies).
- `ann.context` and `ann.ctx` are full paths.
- `ids` optionally carries the identity sidecar (same paths and identifiers).

Reading JSON prints its normal-form text and parses that, so every rule of this
spec applies; JSON that does not survive the round trip (invalid names, tokens,
or a `path`/role inconsistent with the participants) is rejected. The schema is
structural only: references, collisions and cycles are checked by loading.

## Meta domain

Data sometimes refers to the ontology itself: a questionnaire question to the
attribute its answer populates, a rule to the vocabulary it ranges over. The
`Meta` domain describes an ontology as instances of itself, so that such
references are relations to instances rather than paths copied as text.

```text
Meta/Concept {layer=Reference}
  1 Path Meta/Path {id=key}
  1 Kind Meta/Concept/Kind
  ? Description Text
Meta/Attribute {layer=Reference}
  1 Path Meta/Path {id=key}
  1 IsRequired Boolean
  1 IsMultiple Boolean
  ? Description Text
Meta/Dimension {layer=Reference}
  1 Path Meta/Path {id=key}
  ? Kind Meta/Dimension/Kind
  * Values Text
  ? IsOpen Boolean
  ? IsOrdered Boolean
  ? Description Text
Meta/Concept -hasAttribute/isAttributeOf-> Meta/Attribute 1:*
Meta/Attribute -hasDimension/isDimensionOf-> Meta/Dimension *:?
Meta/Dimension -isBasedOn/isBaseOf-> Meta/Dimension *:?
```

Neither the declarations nor the instances are written by hand.
`onto meta --decl` prints the declarations as a file of the ontology (same
namespace and header); `onto meta` prints the instances as
[observations](spec-02-observations.md):

| Instance | One per | Notes |
| --- | --- | --- |
| `Meta/Concept` | Entity, facet, n-ary relation, binary relation with attributes | `Kind` is `Entity`, `Facet` or `Relation` |
| `Meta/Attribute` | Attribute, on the concept that declares it | `IsRequired` for `1` and `+`, `IsMultiple` for `*` and `+`; roles are not attributes |
| `Meta/Dimension` | Built-in type in use, type declaration, vocabulary written in an attribute | `Kind` is `Builtin`, `Vocabulary`, `Value` (a named scalar) or `Structure`; an alias takes the kind and values of what it names |

- `Path` is relative to the ontology namespace: `Person`, `Person.Email`,
  `D/AssetClass`, `Household.hasMember.Person.Role`. A built-in's path is its
  name. A vocabulary written in an attribute has the attribute's path.
- The handle of an instance is its path with `/` written `_` and `.` written
  `__` (`D_AssetClass`, `Person__Email`); a vocabulary written in an attribute
  adds `__Values`. The document declares `@scope onto:<Namespace>`, so the
  handles are stable and other documents of that scope can refer to them.
- `hasDimension` links an attribute to the dimension of its type; attribute
  reuse (`Owner.Attr`) takes the reused attribute's dimension. An attribute that
  refers to a concept has none.
- `isBasedOn` links a named type to the type it is defined as
  (`D/Money/USD = Amount`).
- `Description` is the element's doc string.
- Inherited attributes are not repeated on specialisations, structure fields
  are not described, and the `Meta` domain describes itself as any other domain.

## Changes

`onto diff` (`ontologyDiff` in Python) compares two normal forms (and their sidecars) and writes one
change per line, sorted by path:

```text
~ D/AssetClass +Fund -MutualFund
~ Household.hasMember.Person counts *:* => 1:*
~ Instrument doc
> Instrument.BondCouponRate => Instrument.Bond.CouponRate
> Instrument.ISIN => Instrument.Isin
- Instrument.Ticker
~ Person.Age type Number => Years
~ Person.Email card ? => 1
~ Person.Email ann +key
+ Person.Name D/PersonName
```

| Marker | Meaning |
| --- | --- |
| `+` | Added element (with its normal-form line) |
| `-` | Removed element |
| `>` | Renamed or moved; matched by sidecar identifier |
| `~` | Changed: `type`, `card`, `counts`, `ann`, `base`, `kind`, vocabulary values, participants, `doc` |

Without sidecar identifiers, renames appear as `-` and `+`.

[`onto snap`](spec-07-cli.md#onto-snap-file---format-jsononto) creates a normalized
JSON or text snapshot from an explicit set of ontology files. `onto diff`
compares two such sets or snapshots as combined models: moving declarations
between source files is not a model change. Its JSON output carries structured
before/after values; the text above is a change report, not ontology source.
