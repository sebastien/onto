# 3. Vocabularies

## 3.1 One axis per vocabulary

Each vocabulary answers exactly one question. If a value contains "And", or two
values can both be true, there are two axes.

DON'T

```onto
Vehicle/Type = Car|ElectricCar|ElectricVan|LeasedCar|Van
```

DO

```onto
Vehicle/Body = Car|Truck|Van
Vehicle/Fuel = Diesel|Electric|Petrol
Vehicle/Tenure = Leased|Owned
```

A `{hierarchical}` vocabulary is still one axis: its levels refine one question
(`Food/Fruit/Apple`). Do not use the tree to combine two axes (`Electric/Car`).

## 3.2 Absence is not a value

`Unknown`, `NotStated`, `None` and `NotApplicable` encode a missing value as
data. Use cardinality `?` and let observations say what is missing: an omitted
attribute says nothing, `?` says not known, `null` says there is none. Keep such
a value only when it is a real, distinct answer (`PreferNotToSay`).

DON'T

```onto
Gender = Female|Male|NotStated|Other|Unknown
```

DO

```onto
Gender = Female|Male|Other

Person
  ? Gender Gender
```

## 3.3 Closed or open, not both

A vocabulary is closed (`A|B`, with `Other` as the explicit remainder if needed)
or open (`A|B|...`). `Other` in an open vocabulary is contradictory.

DON'T

```onto
Channel = Email|Other|Phone|...
```

DO

```onto
Channel = Email|Other|Phone
Carrier = Acme|Globex|...
```

## 3.4 Do not hide a quantity in a value

DON'T

```onto
Review/Type = Annual|Month2|Month4|Month8
```

DO

```onto
Months = Duration {unit=Month}

Review
  Interval Months
  Type Onboarding|Periodic
```

Use `{ordered}` for bands that have an order but no measure
(`Low|Medium|High {ordered}`).

## 3.5 Closed sets are vocabularies; open sets are reference entities

If users or providers can add members, or members have attributes of their own,
it is an entity with instances, not a list of names.

DON'T

```onto
Insurer = Acme|Globex|Initech|...
```

DO

```onto
Organisation {layer=Reference}
  Name Text
  RegistrationNumber Text {key}
```

## 3.6 Keep your vocabulary separate from external classifications

Do not adopt a regulator's or a standard's list as your own. Model yours, model
theirs, and relate them with `@map`.

```onto
Product/Type = Laptop|Phone|Tablet
Customs/TariffCode = T847130|T851713|...        -- External: never extended here

@map ProductToTariff Product/Type -> Customs/TariffCode
  Laptop exact T847130
  Phone narrower T851713
```

## 3.7 Do not mirror a subtype hierarchy with a vocabulary

Two ways to say what something is will disagree. The same holds for a
vocabulary that mirrors a set of facets.

DON'T

```onto
Contact
  Type Call|Email|Meeting

Call < Contact
Email < Contact
Meeting < Contact
```

DO

```onto
Contact
Call < Contact
Email < Contact
Meeting < Contact
```

## 3.8 Inline or named

Write a vocabulary inline (`Side Buy|Sell`) when one attribute uses it. Declare
a named type as soon as a second attribute needs it, or it needs an annotation
or a map. Two inline copies of the same list break 1.1.
