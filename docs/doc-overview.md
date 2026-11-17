# Onto overview

An executive summary of what *onto* is, the problem it addresses, the concepts it
is built on and the tools that implement them. It introduces each term once and
links to the specs for the detail.

## What onto is

*onto* is a family of compact text formats (each with a lossless JSON form) and
a Python toolkit for:

- **describing** what data means: a conceptual model, or **ontology**;
- **recording** what is known about the world: **observations**, claims with
  provenance and time;
- **moving** data between systems and models: **bindings** and **mappings**;
- **identifying** the same thing across systems: **referentials**.

Everything is a plain file, reviewed in version control, readable by people and
cheap for agents to read and write.

## The problem

Organisations hold the same things (people, accounts, instruments, policies) in
many systems, each with its own schema, codes, formats and identifiers.
Integrating them usually means:

- a shared model that exists only implicitly, spread across code, tables and
  heads;
- point-to-point transformation code that hides what maps to what, and what is
  silently dropped;
- data merged destructively, losing where each value came from and when;
- identity matching done ad hoc, with no record of why two records were joined;
- removals that never propagate, or bad feeds that erase good data.

onto makes each of these explicit, declarative and inspectable.

## Approach

- **Concepts, not storage.** An ontology says what things are, not how they are
  stored or validated. Systems' own schemas are described as ontologies too.
- **Data as claims.** Observations accumulate; they are never silently merged.
  Conflicts are kept and reported, withdrawals are explicit retractions.
- **Mappings are data.** Correspondences are declared line by line; only a small
  set of named, typed, example-specified functions is code.
- **Identity is explicit.** Two handles are the same instance only when their
  spelling or a recorded identity link says so.
- **Compact and diffable.** Few tokens, a canonical layout (`onto fmt`), and
  semantic diffs, so that agents and reviewers can work on the files directly.
- **Static analysis first.** Checking, coverage, reversal and diffs need no data
  and no running system.

## Key concepts

### Modeling: the ontology (`.onto`)

| Concept | Meaning |
| --- | --- |
| Namespace | The name of an ontology (`Finance`); files refer to each other by namespace (`@use Finance as F`) |
| Domain | A top-level grouping within a namespace (`Investing`, `Planning`), optionally layered from generic to specific |
| Type | A value without identity: scalar (with qualifiers like unit or currency), vocabulary, structure, range or alias |
| Vocabulary | A closed or open set of values, possibly ordered or hierarchical (a taxonomy) |
| Entity | A kind of identifiable thing (`Person`, `Instrument`); a specialisation (`Person < Party`) shares its base's identity |
| Attribute | A property of an entity, facet, relation or structure: observed, or derived by a rule |
| Facet | A group of attributes a domain contributes to some instances of an entity (`Investor of Person`); may be **conditional** (applies when a value holds) or **contextual** (holds only within a context, such as a scenario) |
| Relation | A **binary** link (`Company -issues-> Instrument`) or an **association** with roles, its own identity and attributes (`Trade(Account, Instrument, ...)`) |
| Map | How the values of one vocabulary correspond to another's |
| View | A named slice of the ontology for a purpose: an agent's context, a profile to cover, an extraction request |

```text
@ontology Finance rev=2026-11-10
@use Dimensions as D

D/AssetClass = Bond|Cash|Derivative|Equity|Fund|... -- Open vocabulary: values are examples
D/InterestFrequency = Monthly|Quarterly|Biannually|Yearly {ordered}

Account
  Number Text {key}

Company                                         -- An issuer of listed instruments
  Code Text {key}
  RegisteredName Text

Instrument                                      -- A tradable security
  AssetClass D/AssetClass
  Isin Text {key}
  Name Text

Bond of Instrument                              -- Facet: fixed-income terms
  CouponRate Percent {scale=100}
  InterestFrequency D/InterestFrequency
  MaturityDate Date

Person
  DateOfBirth Date
  Email Text {key}

Company -issues/issuedBy-> Instrument 1:*       -- Binary relation

Trade(Account, Instrument, Trader: + Person) {kind=event}
  Quantity Number
  Side Buy|Sell

@view PortfolioReview                           -- What a portfolio review needs
  Instrument[Bond]
  Trade
```

Supporting features: `{history}` attributes generate change records, the
generated `Meta` domain lets data refer to the ontology's own elements, and
an identity sidecar (`.ids`) tracks renames so that `onto diff` reports them.
An **overlay** (spec-03) curates an ontology imported from a schema, adding
types and facets without editing the generated file.

### Data: observations (`.obs`)

| Concept | Meaning |
| --- | --- |
| Observation | A claim about a subject: existence, attribute value, facet applicability, relation |
| Handle | The name of an instance in a document (`p1`, `Instrument_US0000000019`) |
| Source | Where a claim comes from (`src`), with its time (`at`), validity (`valid`) and producer (`by`) |
| Slot | A subject plus attribute (or facet, relation), plus context: the unit of comparison |
| Supersession | Within one source, a later claim on a slot replaces an earlier one |
| Conflict | Different sources disagreeing on a slot: kept and reported, never resolved silently |
| Retraction | An explicit withdrawal of earlier claims (`- p1.DateOfBirth`) |
| Log form / state form | All statements in order (audit, replay) / the reconciled current picture |

A broker statement and an uploaded document make claims about the same person;
the upload's date of birth conflicts with the broker's, and is later withdrawn:

```text
@obs Finance rev=2026-11-10 at=2026-11-10
@src st=broker:statement/2026-10 d7=upload:document/123
@src st

p1:Person
  DateOfBirth 1990-06-15
  Email jo@example.org
i1:Instrument[Bond]
  Isin US0000000001
  Bond.CouponRate 5.25

@src d7
p1.DateOfBirth 1990-06-16 {at=2026-10-01}
- p1.DateOfBirth 1990-06-16 {at=2026-11-02}
```

### Integration: bindings and mappings (`.bind`, `.map`, `.fn`)

| Concept | Meaning |
| --- | --- |
| Source ontology | An ontology describing one system's data as it is, in its own terms |
| Document | One file exchanged with an external system: read by a binding (an export, an API response, a feed page) or written by one (a report, an upload). Either a JSON value or a CSV table, whose rows are read as objects |
| Binding | Reads documents as observations of a source ontology, or writes them back |
| Mapping | Turns observations of one ontology into observations of another |
| Import / projection | A mapping into a curated ontology / out of it (optionally through a view) |
| Function library | Named, pure, typed conversions, specified by examples so implementations agree |
| Coverage | The computed status of every element: `direct`, `transformed`, `condition`, excluded, `unmapped` |
| Inventory / formats | The field paths of a document format / the value spellings learned for each field |
| Run | One execution of a binding or mapping; re-running retracts what is no longer produced, with safeguards and approval against bad inputs |
| Reversal | Deriving the opposite mapping, reporting the lines that lose information |

An exchange publishes a JSON document:

```json
{
  "asOf": "2026-11-10",
  "issuers": [{ "id": "C-17", "code": "ACME", "registeredName": "Acme Corporation Ltd" }],
  "instruments": [
    { "isin": "US0000000019", "ticker": "ACM30", "name": " Acme 5.25% 2030 ", "class": "F",
      "issuerId": "C-17", "bond": { "couponRate": 0.0525, "interval": 6 } }
  ]
}
```

The binding reads it as observations of `Exchange`, the source ontology that
describes the feed as it is. Each line says where an attribute comes from:

```text
@binding Exchange rev=2026-11-10 format=json
@at <- asOf

Instrument <- instruments[*] {id=isin}
  Class <- class
  Code <- code ?? ticker
  CouponRate <- bond.couponRate
  Isin <- isin
  Issuer <- ref(Issuer, issuerId)
  Name <- trim(name)
  PaymentInterval <- bond.interval

Issuer <- issuers[*] {id=id}
  Code <- code
  Id <- id
  RegisteredName <- registeredName
```

A function library holds conversions shared by mappings, specified by examples:

```text
@functions Markets rev=2026-11-10
@use Dimensions as D

@fn FrequencyFromInterval Integer -> D/InterestFrequency -- Months between payments
  1 => Monthly
  3 => Quarterly
  6 => Biannually
  12 => Yearly
```

The import maps `Exchange` into `Finance`: a vocabulary map for class codes, a
conditional facet for bonds, and explicit exclusions so that coverage is
complete. The coupon rate is rescaled from `0..1` to `0..100` by the attributes'
qualifiers alone.

```text
@mapping Exchange -> Finance from=2026-11-10 to=2026-11-10 referential=MarketIds
@use Dimensions as D
@use Markets as M

@map AssetClassFromCode ClassCode -> D/AssetClass
  E exact Equity
  F exact Bond
  O broader Derivative                          -- Options are one kind of derivative

Instrument -> Instrument
  [Bond] {when=Class:F}
  AssetClass <- AssetClassFromCode(Class)
  Bond.CouponRate <- CouponRate {when=Class:F}
  Bond.InterestFrequency <- M/FrequencyFromInterval(PaymentInterval) {when=Class:F}
  Isin <- Isin
  Name <- Name
  issuedBy <- Issuer

Issuer -> Company
  Code <- Code
  RegisteredName <- RegisteredName

- Instrument.Code {reason=out-of-scope}         -- Tickers are specific to the exchange
- Issuer.Id {reason=ignore}                     -- Feed identifier; used only for references
```

### Identity: referentials (`.ref`)

| Concept | Meaning |
| --- | --- |
| Referential | Identity policies for an ontology's types |
| Policy | How canonical handles are formed: derived from a key (`key=Isin`), or minted |
| Source-qualified handle | A handle that names its source, so records never merge by accident |
| Identity link | An observation that two handles are (`=`) or are not (`!=`) the same instance |
| Registry | The correspondences a referential cannot recompute from data (`.reg`) |
| Implicit instance | A handle referenced before anything states that it exists |

The referential named by the import gives `Finance` instances their handles:

```text
@referential MarketIds rev=2026-11-10
@use Finance as F

F/Company key=Code from=Exchange                -- Only the exchange's codes are canonical
F/Instrument key=Isin                           -- Same handle whichever feed reports it
F/Person minted key=Email                       -- No shared identifier: minted, matched by e-mail
```

The import thus produces `Instrument_US0000000019` and `Company_ACME`. A
broker's own company code stays source-qualified until a curator links it:

```text
@obs Finance at=2026-11-12
@src cu=curator:review/14
@src cu
@scope Finance

Company_ACME:Company = Company_Broker_2FCompany_2FACM:Company
```

## How it fits together

```text
             source ontology                      curated ontology               output ontology
                   │                                     │                              │
documents ──bind──▶ source observations ──map (import)──▶ observations ──reconcile──▶ state
                                              ▲                                         │
                                         referential                            map (projection)
                                                                                        │
documents ◀──────────────────────bind (write)──────────────────── output observations ◀─┘
```

A system is described by a source ontology; a binding reads its documents; an
import maps them into the curated ontology, where a referential gives instances
stable identities; observations from all sources reconcile into a state; a
projection and a writing binding produce documents for another system.

## Components

| Component | What it provides |
| --- | --- |
| Formats | `.onto`, `.obs`, `.bind`, `.map`, `.fn`, `.ref` (text and JSON), plus `.inv`, `.formats`, `.ids`, `.reg` sidecars; JSON schemas in `src/json/` |
| Python library (`onto`) | Parse, validate, format and convert each format; reconcile observations; diff ontologies; coverage; mapping reversal; function execution. Standard library only, Python ≥ 3.14 |
| CLI (`onto`) | Workspace-aware commands (below); human or `--json` output, diagnostics as `file:line:` |
| hexa integration | Optional (`onto.integrations.hexa`): compiles bindings and mappings into [hexa](../../hexa/README.md) programs to execute runs, learn formats, re-run and write documents |
| Agent skills | `onto-modeling` and `onto-review` in `docs/skills/`: how to build and audit a good model |

CLI commands, by task:

- **Files**: `check` (validate with all dependencies), `fmt` (canonical layout),
  `json` / `text` (convert), `ls` (index the workspace), `snap` / `diff`
  (snapshot and compare ontologies), `meta` (the ontology as observations).
- **Observations**: `state` (reconciled), `log` (audit form).
- **Mappings**: `coverage`, `reverse`, `inventory` (from sample documents).
- **Functions**: `fn test` (run a library's examples against an implementation),
  `fn ls`.

The **workspace** is the set of onto files under the project root (plus `-I` and
`ONTO_PATH`), indexed by header, so a command finds every file a model needs.

## Use cases

**Describe a domain for people and agents.** A team writes the `Finance`
ontology with domains, facets and views. `onto check` and the `onto-review`
skill keep it sound; a view such as `PortfolioReview` gives an agent exactly the
concepts it needs, in a few hundred tokens.

**Integrate a feed.** An exchange publishes `instruments.json`. Its `Exchange`
source ontology and binding describe the feed as it is; an import maps class
codes to asset classes and rescales coupon rates; the `MarketIds` referential
makes an instrument `Instrument_US0000000019` whichever feed mentions it.
`onto coverage` shows what is mapped, transformed, excluded or missing before
any data flows.

**Keep provenance and resolve disagreements.** A broker statement, the exchange
and an uploaded document all make claims about the same person and company.
The state keeps each claim's source, reports the conflicting date of birth, and
records a curator's identity link joining the broker's company code to the
exchange's.

**Track removals safely.** A delisted instrument disappears from the next
snapshot: the re-run retracts it. A truncated download that would retract half
the data is held for approval instead.

**Produce outputs.** A projection maps the `PortfolioReview` view into a
`Sheet` ontology and a CSV binding writes it, using the date and number formats
learned from earlier sheets. `onto reverse` reports which columns cannot be read
back.

**Evolve the model.** `onto snap` stores a baseline; `onto diff` reports added,
removed, renamed and changed elements between versions, independent of file
layout.

## Status

Ontologies, observations, bindings, mappings, functions, referential policies,
the CLI and the hexa integration are implemented in Python. Overlays (spec-03)
and registry-backed identities (minted handles, alternate keys) are specified
but not yet implemented. A JavaScript implementation is planned.

## Where to go next

- [README](../README.md): install and a first session.
- Specs: [ontology](specs/spec-01-ontology.md),
  [observations](specs/spec-02-observations.md),
  [overlay](specs/spec-03-overlay.md),
  [bindings and mappings](specs/spec-04-mapping.md),
  [identities](specs/spec-05-identities.md), [hexa](specs/spec-06-hexa.md),
  [CLI](specs/spec-07-cli.md).
- [Cheatsheet](ref/ref-onto-cheatsheet.md) for syntax at a glance.
