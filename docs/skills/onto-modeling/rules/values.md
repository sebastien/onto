# 2. Values and units

## 2.1 A quantity carries its unit

A number without a unit is not a value. In onto the unit is a **measurement
qualifier** (`cur`, `unit`, `period`, `scale`) on the type, never part of the
attribute name and never a second attribute. `?` leaves the qualifier to each
observed value (`12 {cur=EUR}`).

DON'T

```onto
Parcel
  PriceUsd Number
  Price Number
  PriceCurrency Text
  WeightKg Number
```

DO

```onto
Money = Amount {cur=?}
Mass = Number {unit=?}

Parcel
  Price Money
  Weight Mass
```

Fix the qualifier on the type only when every value shares it
(`Years = Duration {unit=Year}`).

## 2.2 Distinguish stocks from flows

An amount and an amount per period are different types. The `period` qualifier
makes the difference.

DON'T

```onto
Money = Amount {cur=?}

Subscription
  Fee Money
  FeeFrequency Text

Account
  Balance Money
```

DO

```onto
Money = Amount {cur=?}
MoneyFlow = Amount {cur=?, period=?}

Subscription
  Fee MoneyFlow

Account
  Balance Money
```

## 2.3 Reuse composites; do not rebuild them

Two attributes that together equal an existing type are a duplicate type.

DON'T

```onto
Money = Amount {cur=?}

Salary
  Amount Money
  Period Week|Month|Year
```

DO

```onto
MoneyFlow = Amount {cur=?, period=?}

Salary
  Amount MoneyFlow
```

## 2.4 Give ranges, partial dates and taxed amounts their own type

Recurring shapes get one definition, as a structure.

DON'T

```onto
Money = Amount {cur=?}

Listing
  AgeBand Text                                  -- "35-44"
  BuiltMonth Text                               -- "2019-03"
  PriceHigh Money
  PriceLow Money

Invoice
  Amount Money
  Tax Money
```

DO

```onto
Money = Amount {cur=?}
Years = Duration {unit=Year}
PartialDate = Text                              -- ISO 8601 date, year or year and month

Money/Range =
  High Money
  Low Money

Years/Range =
  High Years
  Low Years

TaxedAmount =
  Net Money
  Tax Money

Listing
  Age Years/Range
  Built PartialDate
  Price Money/Range

Invoice
  Amount TaxedAmount
```

Workarounds, until onto has them: there is no generic `Range<T>`, so declare one
`T/Range` structure per element type; there is no partial date, so alias `Text`
once and say so in its doc. Both are registered in `TODO.md` ("Modeling gaps").

## 2.5 One encoding per fact

Do not carry the same information twice in one value.

DON'T: the sign and the direction can disagree.

```onto
Money = Amount {cur=?}

Transaction
  Amount Money                                  -- Signed
  Direction Credit|Debit
```

DO

```onto
Money = Amount {cur=?}

Transaction
  Amount Money                                  -- Always positive
  Direction Credit|Debit
```

## 2.6 Use semantic scalar types, not a catch-all string

Identifiers, codes and names are different types even when all are text. An
alias costs one line and carries the meaning.

DON'T

```onto
Name = Text

Book
  ExternalKey Name
  Isbn Name
  Shelf Name
```

DO

```onto
Identifier = Text
Isbn = Text
ShelfCode = Text

Book
  ExternalKey Identifier
  Isbn Isbn {key}
  Shelf ShelfCode
```

## 2.7 Keep locale out of core types

Core value types are universal. A national list or a default currency belongs
to a locale-specific namespace. `{default=}` on a core attribute is a locale
leaking in.

DON'T

```onto
@ontology Core

Currency = Text
Region = Bavaria|Saxony|...

Price
  Currency Currency {default=EUR}
```

DO

```onto
@ontology Germany
@use Core as C

C/Currency = Text
C/Subdivision = Text                            -- ISO 3166-2 code
State = Bavaria|Saxony|...
```

When a country has values a generic open vocabulary lacks, the country domain
adds them with `{extends=}` instead of renaming them into generic words or
listing them in comments. The values stay the country's; the vocabulary stays
generic.

```onto
@ontology Tax layering=declared
@domain Core
@domain Germany

Core/TaxKind = Income|Sales|...                 -- Kinds of tax, any country
Germany/TaxKind = ChurchTax|SolidaritySurcharge {extends=Core/TaxKind} -- German taxes with no generic name
```
