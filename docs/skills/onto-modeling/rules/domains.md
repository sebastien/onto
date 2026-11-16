# 8. Domains and dependencies

onto has two levels of grouping. An **ontology** is a namespace (`@ontology
Sales`), usually one file or a few; it reaches another with `@use`. A **domain**
(`@domain Lending`) is a top-level path segment inside one ontology. The rules
apply to both; "domain" below means either.

## 8.1 Dependencies point one way: specific to generic

Order the domains from most generic to most specific. A domain may reference
those before it, never those after, and never in a cycle.

```text
Core  <-  Party  <-  Asset, Account  <-  Sales, Lending  <-  Operations
```

DON'T: `Party` reaches up into `Sales`.

```onto
@ontology Party
@use Sales as S

Person

S/Order

Buyer of Person {ctx=S/Order}
  IsGiftRecipient Boolean
```

DO: `Sales` contributes its own facet to `Party/Person`.

```onto
@ontology Sales
@use Party as P

P/Person

Order

Buyer of P/Person {ctx=Order}
  IsGiftRecipient Boolean
```

When two domains at the same level each need the other's type, move the shared
type down to the lower domain both already use. The `@use` lines of a file are
its dependency list: read them to check the direction.

Within one ontology, declare the domains in that order, all in one file, and
set `@ontology <Name> layering=declared` on every file: `onto check` then reports
any reference to a later domain. A binary relation belongs to the later of its
ends (and its `context`), so the later domain declares it.

## 8.2 A concept lives where it is generic

Put a concept in the lowest domain where it makes sense on its own. Height is a
fact about a person, not about the insurance that asked for it.

DON'T

```onto
@ontology Insurance
@use Party as P

Length = Number {unit=?}
P/Person

Applicant of P/Person
  Height Length
```

DO

```onto
@ontology Party
@use Core as C

C/Length = Number {unit=?}

Person

Physique of Person
  Height C/Length
```

## 8.3 Domain names are specific; domain contents are cohesive

A domain name that could mean anything will attract everything. Split a domain
when it holds two subjects that can be understood independently.

```text
DON'T   Practice, Common, Misc, General
DO      DentalPractice;  Finance -> Finance (accounts, liabilities) + Lending + Investment
```

## 8.4 Generic concepts carry no domain-specific attributes

When a specific domain needs to say something about a generic concept, it adds a
facet in its own namespace. The facet's path records who contributed it.

DON'T

```onto
@ontology Clinic

Appointment
  IsXrayDiscussed Boolean
  Purpose Text
  XrayOutcome Text
```

DO

```onto
@ontology Clinic
@domain Radiology

Appointment
  Purpose Text

Radiology/Discussion of Appointment
  Outcome Text
```

## 8.5 Jurisdiction and product specifics are a layer

Keep national schemes, regulators and branded products out of generic concepts.

DON'T

```onto
@ontology Finance

Savings
  Is401kEligible Boolean
```

DO

```onto
@ontology UnitedStates
@use Finance as F

F/Account

Retirement401k of F/Account
  IsEligible Boolean
```

## 8.6 `layer` is not a domain

`{layer=…}` classifies an element across domains by what kind of thing it is
(`Party`, `Holding`, `Evidence`, `Reference`). Use one small, fixed set of
layers for the whole model, and do not use it to record ownership: the namespace
does that.
