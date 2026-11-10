# Identities

When records from different sources, documents or mappings are the same
underlying entity, and which handle names it. [Observation](spec-02-observations.md)
handles are transport identities; a **referential** turns them into managed
identities. Identity is always explicit: two handles are the same instance only
when they are spelled the same or an identity link says so, and every link is an
observation, with a source, a time and a possible retraction.

## Concepts

| Concept | Meaning |
| --- | --- |
| Referential | Identity policies for the types of an ontology (`.ref`), plus its registry |
| Policy | How a type's canonical handles are formed: derived from a key, or minted |
| Key | An attribute declared `{key}` in the ontology and named by the policy |
| Primary key | The first key of a `key` policy: its value derives the handle |
| Alternate key | Any other key: resolved through the registry |
| Canonical handle | The one handle a group of same-instance handles is reported under |
| Source-qualified handle | A handle that names its source scope, so it never merges by accident |
| Identity link | An observation that two handles are the same instance (`=`) or not (`!=`) |
| Group | The handles joined by applied `=` links |
| Registry | The correspondences a referential cannot recompute from the data (`.reg`) |
| Implicit instance | A handle that is referenced but has no existence claim yet |

## Example

`market-ids.ref` gives identity policies for the `Finance` ontology of
[spec-01](spec-01-ontology.md#example):

```text
@referential MarketIds rev=2026-11-10
@use Finance as F

F/Account key=Number                            -- Account numbers are global
F/Company key=Code from=Exchange implicit=P45D  -- Only the exchange's codes are canonical
F/Instrument key=Isin implicit=P2D              -- The instrument feed is daily
F/Party implicit=never                          -- Counterparties are referenced, never fed
F/Person minted key=Email                       -- No shared identifier; e-mail helps matching
```

The `Exchange -> Finance` import of [spec-04](spec-04-mapping.md#example) uses it
(`@mapping Exchange -> Finance referential=MarketIds`). An instrument with ISIN
`US0000000019` is `Instrument_US0000000019` whichever feed reports it. A broker
statement, mapped with the same referential, reports a company by a code of its
own: not being the exchange, its company is source-qualified,
`Company_Broker_2FACM`, until a curator links it:

```text
@obs Finance at=2026-11-12 by=curator:review
@src cu=curator:review/14
@src cu

Company_ACME:Company = Company_Broker_2FACM:Company
```

From then on, claims about `Company_Broker_2FACM` are reported on `Company_ACME`.
People have no shared identifier, so the referential mints their handles and
records which source record each one came from. Its registry, `market-ids.reg`:

```text
Finance/Person	Person_1	alias	Person_Broker_2F884
Finance/Person	Person_1	alias	Person_Crm_2Fc_2D21
Finance/Person	Person_1	key:Email	jo@example.org
```

The broker's client 884 and the CRM's contact `c-21` share an e-mail address, so
they are the same person, `Person_1`. The registry is an index of the
referential's own links (`Person_1 = Person_Broker_2F884 {by=ref:MarketIds}`)
and of the keys claimed on its canonical handles, so the log alone can rebuild
it.

## Lexical rules

The [ontology lexical rules](spec-01-ontology.md#lexical-rules) apply to `.ref`
files. The registry is tab-separated text, one entry per line, LF line endings.

## Referentials

```text
@referential <Namespace> {key=value ...}
@use <Namespace> as <Alias>
<Type> key=<Attr>[,<Attr> ...] [from=<Namespace>] [implicit=<age>] [-- doc]
<Type> minted [key=<Attr>[,<Attr> ...]] [implicit=<age>] [-- doc]
<Type> implicit=<age> [-- doc]
```

`@referential` comes first; its key `rev` is the referential's revision. `@use`
aliases name the ontologies whose types it covers. A referential may span several
files, as an ontology does; a type with two policies is an error.

| Policy | Canonical handle | Registry entries |
| --- | --- | --- |
| `key=A` | Derived from the value of `A` | None |
| `key=A,B` | Derived from `A`; `B` is an alternate key | Each `B` value seen with an `A` value |
| `key=A from=Ns` | Derived from `A` when the input comes from `Ns`; source-qualified otherwise | None |
| `minted` | Generated when first seen, never changed | Each source record it was generated for |
| `minted key=B` | As `minted`; `B` is an alternate key | As `minted`, plus each `B` value |

- Every named key must be an attribute of the type (or of its base) declared
  `{key}`. `from` names the source ontology of the mapping (its `From`), so that
  only the system of record's identifiers become canonical.
- A type without a policy (including one with only `implicit`), or a mapping
  without a referential, produces source-qualified handles only.
- `implicit=<age>` sets how long an instance of the type may stay
  [implicit](#implicit-instances) before a warning: an ISO 8601 duration
  (`P2D`), or `never`. It applies to the type and its specialisations.
- A specialisation shares its base's identity (spec-01); its policy is the base's.
  A policy on a specialisation of a type that already has one is an error.

## Handles

A handle is `<Type>_<encoded>`, with `Type` the last segment of the type path and
the encoding of [spec-04 bindings](spec-04-mapping.md#scope-lines): every
character outside `[A-Za-z0-9]` becomes `_` followed by the two uppercase
hexadecimal digits of each of its UTF-8 bytes. The encoding is reversible, so a
handle keeps the key it was derived from.

| Form | Encoded part | Example |
| --- | --- | --- |
| Derived | The primary key's value, in its observations encoding | `Instrument_US0000000019` |
| Source-qualified | `<scope>/<key>`: the source `@scope` and the source record's key | `Company_Broker_2FACM` |
| Minted | A positive integer, the next unused one for the type in the registry | `Person_1` |

A type's policy fixes which forms its handles take. Changing a policy re-keys
existing instances; that is a migration, outside this spec.

## Identity links

Spec-02 has two identity statements:

| Form | Claims |
| --- | --- |
| `a = b` | `a` and `b` are the same instance; `a` is the canonical handle |
| `a != b` | `a` and `b` are different instances, whatever other links say |

- Both handles must have compatible types (one a specialisation of the other, or
  the same). Links carry metadata like any claim (`src`, `at`, `by`, `conf`) and
  are withdrawn by retraction: `- a = b`.
- `a = b` is symmetric for sameness; its order only chooses the canonical handle
  when it joins two groups ([Resolution](#resolution)).
- Links are made by curators, by agents (with a `conf` and, typically, review),
  and by referentials themselves (`by=ref:<Namespace>`).

## Resolution

Resolution applies the links of a state to its handles:

1. Applied `=` links join handles into **groups**. A handle without links is a
   group of its own, and its own canonical handle.
2. Links apply in log order. When `a = b` joins two groups, the canonical
   handle of `a`'s group stays canonical; that of `b`'s group, and every member
   of it, become **aliases**. Canonical handles therefore never change, except
   by becoming aliases.
3. Claims on every member, and references to every member, are reported on the
   canonical handle. Their slots then supersede and conflict as spec-02
   describes; the log keeps the original handles.

An **identity conflict** is:

- an `a != b` between handles that `=` links would join;
- two links joining the same pair of groups with opposite canonical choices;
- an alternate key value already registered for another canonical handle.

Identity conflicts are reported. What happens next depends on the
[run mode](spec-04-mapping.md#run-modes):

| | Strict | Lenient |
| --- | --- | --- |
| Identity conflict | The run waits for approval; nothing is written | The conflicting link or pairing is not applied: `!=` wins, and an earlier link or registration stands. A warning is reported |

### Producing handles

A mapping with a referential forms each target instance's handle from the policy
of its target type, in this order:

1. The **primary key** assigned by the scope line, when the policy derives from
   it (and, with `from`, the mapping's `From` is that source): the derived handle.
2. A registered **alternate key** value: its canonical handle.
3. The **source record**, when the registry has an `alias` entry for its
   source-qualified handle: that entry's canonical handle.
4. Otherwise, for `minted`: a new minted handle, registered with the source
   record's source-qualified handle as an alias. For `key`: the source-qualified
   handle.

When a scope line assigns both a primary key and an alternate key, the pair is
registered. When an instance found at step 2 or 3 also has a derived handle that
differs (an ISIN change, a wrong pairing), that is an identity conflict.

Every `alias` registration is also emitted as a link by the referential
(`Person_1 = Person_Broker_2F884 {by=ref:MarketIds}`), with the run's `at`; an
alternate key pairing is the key's claim on the canonical handle.

### Implicit instances

A reference may arrive before the instance it names: a trade can mention an
instrument the instrument feed has not delivered yet. Such a handle is an
**implicit instance**:

- It is referenced (a reference value, a relation participant, a `ctx`), but no
  existence claim from any source survives in the state.
- It is valid. The state form marks it ([spec-02](spec-02-observations.md#implicit-instances));
  the mark disappears when an existence claim arrives.
- A derived or source-qualified implicit handle keeps its key, so the referential
  matches it to the instance when that instance arrives.
- Run reports count implicit instances per type. One that is still implicit
  longer than its type's age after it was first referenced is a warning, in
  both run modes: nothing is lost, but a feed may be missing or a key
  misspelt.
- Age is measured on the data, never the clock: from the `at` of the earliest
  surviving claim referencing the instance to the run's `at`, so replaying a
  log reports the same warnings.
- The age is the type's `implicit` in the referential (its nearest base's, for a
  specialisation without one), or else the run's setting, `P7D` by default.
  `never` turns the warning off, for types that are referenced but never fed.

## Registry

The registry lives next to the referential, named after it (`market-ids.ref` →
`market-ids.reg`). It lists, per type, the correspondences that cannot be
recomputed from data: tab-separated `type`, `canonical`, `kind`, `value`, sorted
by the four columns.

| Kind | Value | Meaning |
| --- | --- | --- |
| `alias` | A handle | The handle is a member of the canonical handle's group |
| `key:<Attr>` | A key value, in its observations encoding | The alternate key value identifies the canonical handle |

- Derived handles need no entries: their key gives them back. Minted handles
  always have at least one `alias` (the record they were minted for).
- Each `alias` entry indexes a link `canonical = alias`, emitted with
  `by=ref:<Namespace>`; retracting the link removes the entry. Each `key:` entry
  indexes the alternate key value claimed on the canonical handle. Rebuilding
  the registry from the log gives the same file.
- The next minted handle of a type is the largest registered minted integer plus
  one; minted integers are never reused.

## Validation

Errors:

- unknown ontology, type or attribute; a key that is not declared `{key}`;
- two policies for one type, or a policy on a specialisation of a typed base
  (an `implicit`-only line is not a policy);
- an `implicit` value that is neither an ISO 8601 duration nor `never`;
- `from` naming an unknown ontology;
- an identity link between incompatible types, or a link from a handle to itself;
- a registry entry for a type without a policy, or a malformed entry.

Warnings:

- a `rev` differing from the loaded ontology's;
- identity conflicts (errors in strict mode, until approved);
- implicit instances older than their type's age.

## Normal form

1. `@referential`, then `@use` sorted by alias.
2. Policy lines sorted by type path. Keys keep their order: the first is the
   primary key. Keys follow the order `key` (or `minted`, then `key`), `from`,
   `implicit`.
3. Spacing, docs and comments follow spec-01.

## JSON form

[`referential.schema.json`](../../src/json/referential.schema.json),
`format` `onto.referential/1`. Text and JSON convert losslessly (comments
excepted).

```json
{
  "format": "onto.referential/1",
  "namespace": "MarketIds",
  "header": { "rev": "2026-11-10" },
  "uses": { "F": "Finance" },
  "policies": [
    { "type": "Finance/Company", "keys": ["Code"], "from": "Exchange", "implicit": "P45D", "doc": "Only the exchange's codes are canonical" },
    { "type": "Finance/Instrument", "keys": ["Isin"], "implicit": "P2D", "doc": "The instrument feed is daily" },
    { "type": "Finance/Party", "implicit": "never", "doc": "Counterparties are referenced, never fed" },
    { "type": "Finance/Person", "minted": true, "keys": ["Email"], "doc": "No shared identifier; e-mail helps matching" }
  ]
}
```

- A `key` policy has a non-empty `keys`; a `minted` policy has `"minted": true`
  and optional `keys`; a line with neither has only `implicit`. Absent optional
  members are omitted, never `null`.
- Identity links use the spec-02 JSON claim forms `"same"` and `"distinct"`.
