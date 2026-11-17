# onto cheat sheet

The `.onto` syntax and the command loop on one page. The authority is
[spec-01](../specs/spec-01-ontology.md) (ontologies),
[spec-02](../specs/spec-02-observations.md) (observations) and
[spec-07](../specs/spec-07-cli.md) (command line).

## A file

```onto
@ontology Shop rev=2026-11-16
@use Core as C
@domain Sales                                   -- Selling to customers

// Types: values without identity
C/Money = Amount {cur=?}                        -- Scalar with a qualifier
C/Years = Duration {unit=Year}
C/Email = Text                                  -- Alias: same values, its own meaning
Channel = Email|Phone|Post                      -- Closed vocabulary
Carrier = Acme|Globex|...                       -- Open vocabulary: values are examples
Size = Small|Medium|Large {ordered}

Category = {hierarchical}
  Food
    Fruit
  Clothing

C/PersonName =
  Given Text
  Family Text

// Entities: things with identity
Party

Person < Party                                  -- Specialisation: shares its base's identity
  1 Name C/PersonName
  ~ Age C/Years <- $AsOf, BirthDate
  BirthDate Date
  Email C/Email {key}
  * Channels Channel

Product
  Category Category
  Price C/Money
  Size Size
  Sku Text {key}

Sales/Customer of Person                        -- Facet: attributes in a role
  Since Date

Basket

Sales/Discount of Product {ctx=Basket}          -- Contextual facet: holds within one Basket
  Rate Percent {scale=100}

// Relations
Person -places/isPlacedBy-> Basket 1:*

Basket -contains/isContainedIn-> Product *:*
  Quantity Integer

Review(Author: Person, Product) {kind=event}    -- Association: a link with identity
  Rating Integer

Subscription(Product, Subscriber: + Person) {kind=state}
  EndDate Date
  Fee C/Money {period=Month}
  StartDate Date

Customs/Code = C6109|C0808|...

@map CategoryToCustoms Category -> Customs/Code -- Value correspondence
  Clothing narrower C6109
  Food/Fruit narrower C0808

@view Catalogue                                 -- A slice for one use
  Person[Customer]
  Product
  Review
```

## Declarations

| Form | Declares |
| --- | --- |
| `T = Builtin {qualifiers}` | Scalar type |
| `T = Other` | Alias |
| `T = A\|B\|C` | Closed vocabulary |
| `T = A\|B\|...` | Open vocabulary |
| `T = {hierarchical}` + tree | Taxonomy |
| `D/T = A\|B {extends=T}` | Values a later domain adds to open vocabulary `T` |
| `T =` + body | Structure: fields, no identity |
| `E` / `E < Base` + body | Entity / specialisation (single inheritance) |
| `F of E` + body | Facet of an entity or an association |
| `F of E {ctx=C}` | Contextual facet: values hold within an instance of `C` |
| `F of E {when=A:V}` | Conditional facet: applies only to subjects whose `A` is `V` |
| `S -verb/inverse-> T L:R` + body | Binary relation |
| `R(Role: [card] Type, ...)` + body | Association (n-ary relation) |
| `@map M From -> To` + body | Value map: `exact`, `broader`, `narrower`, `related` |
| `@view V` + body | View |
| `@domain D` | Domain: a top-level namespace segment |
| `~ A T <- X {rule=Lib/Fn}` | Derived attribute whose rule is a `.fn` library function, checked when the library loads |
| `A T {one=G}` | Exclusive group: attributes or fields sharing `G` hold at most one value |
| `Attr T {history}` | Dated history: generates `Owner/AttrChange` and `Owner -hasChange-> Owner/AttrChange` |
| `@ontology N layering=declared` | Domains declared in dependency order; `onto check` reports references to later ones |

Built-in types: `Text`, `Integer`, `Number`, `Boolean`, `Date`, `DateTime`,
`Duration`, `Amount`, `Percent`. `Range<T>` is a band of an orderable `T` (number,
amount, percent, date, duration, `{ordered}` vocabulary), observed `low..high`,
`low..`, `..high` or `v` (`v..v`); bounds inclusive, `low <= high`.
`{cur=?:V}` (also `unit`, `period`) takes each value's qualifier from vocabulary `V`.

## Attributes

```text
[card] [~] Name [Type] [<- dependencies] [{annotations}] [-- doc]
```

- Cardinality: `1` exactly one, `?` zero or one (the default), `+` one or more,
  `*` zero or more.
- `~` marks a derived attribute; `<-` lists its inputs: local names,
  `Owner.Attr` paths, `$Input`, or `...` when unknown.
- A type is a built-in, a declared type, an inline vocabulary (`Side Buy|Sell`),
  an entity or association (a reference), or `Owner.Attr` (reuse that type).
- A single-value inline vocabulary starts with `|`: `Kind |Trial`.

## Annotations

| Key | On | Meaning |
| --- | --- | --- |
| `key` | attribute | Used to match records to an instance |
| `default` | attribute | Value assumed when none is observed |
| `privacy` | attribute | Audiences, joined by `+` |
| `kind` | relation | `event` (a point in time) or `state` (an interval) |
| `layer` | entity, relation | Classification across domains |
| `context`, `subjectRole`, `objectRole` | binary relation | Association carrying the link's state |
| `ctx` | facet | Context the facet's values hold within |
| `ordered`, `hierarchical` | vocabulary | Order is meaningful / values are paths |
| `extends` | named vocabulary | Open vocabulary this one adds its values to |
| `cur`, `unit`, `period`, `scale` | type, attribute | Measurement qualifiers; `?` is filled per value |
| `status` | any | `stated`, `inferred`, `assumed` |
| `src`, `check` | any | Provenance / an open question |

## Names and layout

- Names match `[A-Za-z_][A-Za-z0-9_]*`. Everything is PascalCase except relation
  verbs, which are lowerCamel.
- Paths are `/`-separated: `Sales/Customer`. The last segment names the element.
  A path resolves relative to the `@ontology` namespace, or through a `@use`
  alias. Namespaces imply neither inheritance nor grouping.
- Declarations start in column 0; body lines are indented by two spaces.
- `// comment` is dropped; ` -- doc` is kept and belongs to its element.
- Facet attributes are addressed through the facet: `Person.Customer.Since`.

## Observations

Instance data is not written in the ontology. Each claim carries its evidence:
who made it, when, and when it holds. This metadata does not replace attributes:
declare the dates the model captures.

```text
@obs Shop at=2026-11-16
@src crm=crm:export/12

p1:Person[Customer]
  BirthDate 1990-06-15 {src=crm, conf=0.9}
  Customer.Since 2021-03-01
s1:Subscription {valid=2024-01-01..2025-12-31}
  Fee 12 {cur=EUR}
```

| Metadata | Meaning |
| --- | --- |
| `src`, `by` | Who made the claim / what produced it |
| `at` | When the claim was recorded |
| `valid` | When the fact holds: `d`, `d1..d2`, `d1..`, `..d2` |
| `ctx` | Context instance of a contextual facet claim |
| `conf` | Confidence, `0..1` |

An omitted attribute says nothing; `?` says not known; `null` says there is
none; `[]` says the collection is empty.

## Command loop

```sh
onto ls ontology          # what the workspace holds
onto check file.onto      # parse and validate, with the files it uses
onto fmt -w file.onto     # fix layout (doc alignment, whitespace)
onto json file.onto       # JSON form; `onto text` prints the normal form back
```

Run `onto check` after every edit. From a checkout of onto, the command is
`./bin/onto`.
