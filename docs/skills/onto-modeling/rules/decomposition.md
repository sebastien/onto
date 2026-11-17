# 4. Decomposition

## 4.1 Never put a vocabulary value in an attribute name

The most common modeling error. When several attributes differ only by a word
that could be a value, they are rows, not columns. The model must not change
when a new value appears.

DON'T

```onto
PhoneNumber = Text

Person
  HomePhone PhoneNumber
  MobilePhone PhoneNumber
  WorkPhone PhoneNumber

Patient
  HasLatexAllergy Boolean
  HasPeanutAllergy Boolean
  OtherAllergies Text

Consent
  IsMarketingAccepted Boolean
  IsPrivacyAccepted Boolean
  IsTermsAccepted Boolean
```

DO

```onto
PhoneNumber = Text

ContactPoint =                                  -- Keyed by its use: Phones[Mobile].Number
  1 Number PhoneNumber
  1 Use Home|Mobile|Work {key}

Person
  * Phones ContactPoint

Patient
Substance {layer=Reference}

Allergy(Patient, Substance) {kind=state}
  EndDate Date
  Severity Mild|Moderate|Severe {ordered}
  StartDate Date

Consent
  GivenAt DateTime
  Subject Marketing|Privacy|Terms
```

Tell-tale signs: an `Other…` attribute, a number in the name
(`HasTwoYearsHistory`), or a set of attributes sharing a prefix or suffix.

## 4.2 Core concepts first, specifics as facets

Identify the few concepts every case shares. What is specific to a variant is a
facet of the core concept, never an optional attribute on it.

DON'T

```onto
Vehicle
  BatteryCapacity Number                        -- Electric only
  ChargePort Text                               -- Electric only
  Make Text
  PayloadLimit Number                           -- Trucks only
```

DO

```onto
Energy = Number {unit=KilowattHour}
Mass = Number {unit=?}

Vehicle
  Make Text

Electric of Vehicle
  BatteryCapacity Energy
  ChargePort Text

Freight of Vehicle
  PayloadLimit Mass
```

## 4.3 A role is a facet, not a subtype

A thing does not change identity when it takes on a role, and it can hold
several roles at once. `<` is for what a thing **is** for its whole life; `of`
is for what it is **as**.

DON'T

```onto
Person
Organisation
Customer < Person
Employee < Person
Supplier < Organisation
```

DO

```onto
Person
Organisation

Customer of Person
Employee of Person
Supplier of Organisation
```

## 4.4 Store each fact once

A fact belongs to exactly one concept: the one it is true of.

DON'T

```onto
Order
  IsGift Boolean

Order/Line
  IsGift Boolean

Shipment
  IsGiftOrder Boolean

Booking
  IsStudent Boolean
```

DO

```onto
Order
  IsGift Boolean

Order/Line
Shipment

Person
  IsStudent Boolean                             -- True of the person, not the booking

Booking
```

## 4.5 Do not store what can be derived

Counts, totals, ages and flags implied by other data are derivations. Mark them
`~` with their inputs, or leave them out.

DON'T

```onto
Team
  MemberCount Integer

Person
  Age Integer
  BirthDate Date

Loan
  ClosedDate Date
  IsClosed Boolean
```

DO

```onto
Years = Duration {unit=Year}

Team
  ~ MemberCount Integer <- ...

Person
  ~ Age Years <- $AsOf, BirthDate
  BirthDate Date

Loan
  ClosedDate Date

Team -hasMember/isMemberOf-> Person
```

`$AsOf` is an input supplied at evaluation time; `<- ...` says the inputs are
not attributes (here, the `hasMember` links).

## 4.6 One pattern for one shape

When the same structure appears for different things, model it once. Parallel
near-identical concepts are the sign of a missing abstraction.

DON'T

```onto
Person
Car
House
Boat

CarOwnership(Car, Person) {kind=state}
  Share Percent {scale=100}

HouseOwnership(House, Person) {kind=state}
  Share Percent {scale=100}

Person -isBoatOwnerOf/hasBoatOwner-> Boat
```

DO

```onto
Person
Asset
Boat < Asset
Car < Asset
House < Asset

Ownership(Asset, Owner: Person) {kind=state}
  Arrangement Joint|Sole
  EndDate Date
  Share Percent {scale=100}
  StartDate Date
```

Specialisation is single: see [7.2](relations.md#72-do-not-enumerate-the-targets-of-a-generic-relation)
when a concept needs two unrelated supertypes.

## 4.7 An attribute with attributes is a concept

When you need to say something about a value (when, by whom, how much), promote
it to an entity or an association.

DON'T

```onto
Money = Amount {cur=?}

Policy
  CoverAmount Money
  CoverExclusions Text
  CoverStartDate Date
  CoverType Text
```

DO

```onto
Money = Amount {cur=?}

Policy

Cover
  Amount Money
  * Exclusions Text
  Risk Death|Disability|Illness
  StartDate Date                                -- Contractual start: a term of the cover

Policy -hasCover/isCoverOf-> Cover 1:*
```

## 4.8 Keep the unresolved wording beside the resolved link

Source data often names a thing before it can be identified. Keep the wording as
a `…Label` attribute and the link as a relation; never mark the label `{key}`.

```onto
Organisation

Invoice
  SupplierLabel Text                            -- As written; may be unresolved

Invoice -isIssuedBy/issues-> Organisation *:?
```
