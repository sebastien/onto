# 5. State, time and workflow

Model time explicitly. If the model captures when something started, ended or
changed, declare it as an attribute: only what the ontology declares can be
stored, mapped, transformed and selected in a view.

Observation metadata does not replace it. `valid=` and `at=` qualify one claim
(when it holds, when it was recorded); they are evidence about the data, and a
consumer may keep or drop them. `{kind=state}` and `{kind=event}` say how to
read a relation in time, and go together with its date attributes.

## 5.1 The thing and the process about the thing are separate

A contract, an asset or a person is not the case file that handles it. Workflow
state belongs to the process.

DON'T

```onto
Person

Policy
  AssignedClerk Person
  IsSentToClient Boolean
  Status InForce|Lapsed
  UnderwritingStage Text
```

DO

```onto
Person

Policy
  Status InForce|Lapsed

Application
  Stage Assessed|Decided|Received {ordered}

Application -isAssignedTo/isAssigneeOf-> Person *:?
Application -proposes/isProposedBy-> Policy
```

## 5.2 One vocabulary per lifecycle

A status that mixes progress, outcome and the state of a different thing cannot
be reasoned about.

DON'T

```onto
Order/Status = Cancelled|Delivered|Draft|OnHold|Packed|Paid|Placed|Refunded|Shipped
```

DO

```onto
Order/Status = Draft|Placed|Fulfilled|Cancelled {ordered}
Payment/Status = Pending|Paid|Refunded {ordered}
Shipment/Status = Packed|Shipped|Delivered {ordered}
```

## 5.3 Record transitions once, not one date per status

DON'T

```onto
Order/Status = Cancelled|Draft|Placed

Order
  CancelledDate Date
  IsCancelled Boolean
  PaidDate Date
  PlacedDate Date
  Status Order/Status
  StatusWhenCancelled Order/Status
```

DO: the current status on the thing, and one concept for every transition.

```onto
Order/Status = Draft|Placed|Fulfilled|Cancelled {ordered}

Order
  Status Order/Status

Order/StatusChange
  At DateTime
  Status Order/Status

Order -hasChange/isChangeOf-> Order/StatusChange 1:*
```

"Status when X happened" is then a query, not an attribute. A new status adds a
value, not an attribute. When a transition has an actor or a reason, they are
attributes or relations of the change.

## 5.4 Use intervals for things that last

A state has a start and an end: declare both. `IsCurrent` is derived from them.

DON'T

```onto
Person
Organisation

Employment(Employee: Person, Employer: Organisation)
  IsCurrent Boolean
```

DO

```onto
Person
Organisation

Employment(Employee: Person, Employer: Organisation) {kind=state}
  EndDate Date
  ~ IsCurrent Boolean <- $AsOf, EndDate, StartDate
  StartDate Date
```

Use the same pair of names (`StartDate`, `EndDate`) for every interval in the
model (1.1). An open interval has no `EndDate`: absent, not a far-future date
(3.2).

# 6. Facts, judgements and provenance

## 6.1 A fact and a judgement about it are different things

What is true of a thing, and how someone treats it for a purpose, do not share a
concept. A judgement is a **contextual facet**: `{ctx=C}` scopes its values to
one instance of `C`, so two assessments can disagree without conflict.

DON'T

```onto
Money = Amount {cur=?}

Income
  AcceptedAmount Money
  Amount Money
  IsIncludedInAssessment Boolean
```

DO

```onto
Money = Amount {cur=?}

Income
  Amount Money

Assessment

Treatment of Income {ctx=Assessment}
  AcceptedAmount Money
  IsIncluded Boolean
```

## 6.2 Provenance is metadata, not an attribute

Who said it, when, how reliably and from which document applies to every value.
Observations carry it (`src`, `at`, `by`, `conf`); the ontology does not.

DON'T

```onto
Money = Amount {cur=?}

Person
  DeclaredIncome Money
  IncomeSource Declared|Documented
  IsIncomeVerified Boolean
  ReportedAge Integer
```

DO

```onto
MoneyFlow = Amount {cur=?, period=?}

Person
  BirthDate Date
  Income MoneyFlow
```

```text
@src declared=form:intake/7
@src payslip=document:payslip/2026-10

p1.Income 82000 {cur=EUR, period=Year, src=declared}
p1.Income 84500 {cur=EUR, period=Year, src=payslip, conf=0.95}
```

Two sources that differ are a reported conflict, not two attributes. Corollary:
a doc that says "not proof of…" on every attribute is stating a provenance rule.
State it once for the model.

## 6.3 A fact and an answer are different things

A question may acquire a fact (a birth date) or capture an opinion (a
preference). Facts are attributes of the concept they describe. Opinions,
intentions and free narrative stay as answers to questions.

DON'T

```onto
Customer
  BirthDate Date
  SatisfactionComment Text
  WantsEcoPackaging Boolean
```

DO

```onto
Customer
  BirthDate Date

Question
  Wording Text

Answer(Question, Respondent: Customer) {kind=event}
  Value Text
```

When a question populates an attribute, link it to the ontology through the
`Meta` domain (`onto meta`) rather than copying the attribute's path as text.

## 6.4 Doc strings define; they do not defend

One line that says what the thing is and what distinguishes it from its nearest
neighbour. A doc cannot span lines.

DON'T

```onto
Document
  IssueDate Date                                -- Date; the system may set this to upload date, so do not treat as proof
```

DO

```onto
Document
  IssueDate Date                                -- When the issuer issued the document; not when it was received
```
