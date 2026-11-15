# 1. Naming

## 1.1 One name per thing, one thing per name

The same name means the same thing, with the same type, wherever it appears.
Different things have different names.

DON'T: `Address` is a postal address in one place and an email in another;
`Carrier` and `Courier` name the same thing.

```onto
PostalAddress =
EmailAddress = Text

Customer
  Address PostalAddress

Message
  Address EmailAddress

Shipment
  Carrier Text

Return
  Courier Text
```

DO

```onto
PostalAddress =
EmailAddress = Text

Customer
  Address PostalAddress

Message
  Email EmailAddress

Shipment
  Carrier Text

Return
  Carrier Text
```

## 1.2 Names are identifiers, not phrases

The grammar enforces identifiers. Use PascalCase for everything except relation
verbs, which are lowerCamel.

```text
DON'T   proof_of_delivery, proofOfDelivery, PROOF_OF_DELIVERY
DO      ProofOfDelivery
```

## 1.3 Do not repeat the context

A name is read with its container: the owner for an attribute, the namespace for
a path.

```text
DON'T                         DO
OrderLine                     Order/Line
Order.OrderDate               Order.PlacedDate
Person.Name.FirstName         Person.Name.Given
Shop/ShopOrderStatus          Shop/Order/Status
```

A namespace path does not create a relation: `Order/Line` is only a name. Link
it explicitly (`Order -hasLine/isLineOf-> Order/Line 1:*`).

## 1.4 Name the meaning, not the type or the encoding

```text
DON'T                         DO
Invoice.Date                  Invoice.IssueDate
Document.Text                 Document.Content
File.Sha256                   File.Digest
Loan.TermMonths               Loan.Term        (the unit is a qualifier, see 2.1)
```

## 1.5 Use affixes consistently

| Kind | Convention | Example |
| --- | --- | --- |
| Boolean | `Is…`, `Has…` | `IsActive`, `HasWarranty` |
| Date | `…Date` | `IssueDate` |
| DateTime | `…At` | `SentAt` |
| Multi-valued (`*`, `+`) | plural | `Tags`, `Lines` |
| Count | `…Count` | `SeatCount` |
| Unresolved name | `…Label` | `SupplierLabel` |

## 1.6 Use one word for "kind"

`Type`, `Kind`, `Category` and `Class` are synonyms to a reader. Choose `Type`
for the classification of a concept and nest it the same way everywhere.

```text
DON'T   Vehicle/Type, Product/Kind, Expense/Category, VehicleFuelType
DO      Vehicle/Type, Product/Type, Expense/Type, Vehicle/Fuel/Type
```

## 1.7 Expand abbreviations unless they are the name

Keep abbreviations that are the thing's actual name in its field (`Iban`,
`Isbn`, `Vat`), written as words (`Isbn`, not `ISBN`). Expand everything else.

```text
DON'T   Order.PoNbr, Customer.Cna, Item.Qty
DO      Order.PurchaseOrderNumber, Customer.NeedsAnalysis, Item.Quantity
```

## 1.8 Relation verbs

Verbs are lowerCamel, present tense, with the inverse given: see
[7.4](relations.md#74-one-consistent-grammar).
