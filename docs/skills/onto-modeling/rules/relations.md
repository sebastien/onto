# 7. Relations

## 7.1 Use precise verbs

`concerns`, `relatesTo` and `isAssociatedWith` say that a link exists, not what
it means. Use them only for a deliberately generic link (7.2).

DON'T

```onto
Invoice
Order
Invoice -relatesTo/isRelatedTo-> Order
```

DO

```onto
Invoice
Order
Invoice -bills/isBilledBy-> Order *:1
```

## 7.2 Do not enumerate the targets of a generic relation

If a relation is repeated for every concept in the model, the targets share a
supertype. Declare it once.

DON'T

```onto
Customer
Order
Shipment
Note
Task
Note -concerns/isConcernOf-> Customer
Note -concerns/isConcernOf-> Order
Note -concerns/isConcernOf-> Shipment
Task -concerns/isConcernOf-> Customer
Task -concerns/isConcernOf-> Order
```

DO

```onto
Subject                                         -- Anything that can be discussed
Customer < Subject
Order < Subject
Shipment < Subject
Note
Task
Note -concerns/isConcernOf-> Subject
Task -concerns/isConcernOf-> Subject
```

Workaround, until onto has more: specialisation is single, so two unrelated
supertypes cannot both be bases. Put the most generic one at the root of the
chain (`Car < Asset`, `Asset < Subject`). When no chain fits, keep the generic
relation on the root and leave the gap as `{check=supertype}`. Registered in
`TODO.md` ("Modeling gaps").

## 7.3 A relation with attributes is an association

A binary relation may carry a few attributes of the link. When the link has
named roles, a share, a status, or can exist twice between the same
participants, declare an association: it has its own identity and can take
facets.

DON'T

```onto
Person

House
  OwnerShare Percent {scale=100}
  OwnershipStartDate Date

Person -owns/isOwnedBy-> House
```

DO

```onto
Person
House

Ownership(Asset: House, Owner: Person) {kind=state}
  EndDate Date
  Share Percent {scale=100}
  StartDate Date
```

Keep the readable verb as a view of the association when it helps:

```onto
Person
House

Ownership(Asset: House, Owner: Person) {kind=state}
  EndDate Date
  Share Percent {scale=100}
  StartDate Date

Person -owns/isOwnedBy-> House {context=Ownership, subjectRole=Owner, objectRole=Asset}
```

## 7.4 One consistent grammar

Present tense, the inverse always given, the same verb for the same meaning.
Passive inverses are `is…By`, `is…Of`.

DON'T

```onto
Person
File
Task
Case
Person -downloaded/wasDownloadedBy-> File
Task -isAssignedTo/isAssigneeOf-> Person
Case -hasOwner/owns-> Person
```

DO

```onto
Person
File
Task
Case
Person -downloads/isDownloadedBy-> File
Task -isAssignedTo/isAssigneeOf-> Person *:?
Case -isAssignedTo/isAssigneeOf-> Person *:?
```

A verb may be shared by relations from different subjects, or to unrelated
object types. State the counts (`L:R`) when known: `1:*` reads "each object has
one subject, each subject has many objects".

## 7.5 Do not duplicate a relation as an attribute or a role list

DON'T

```onto
Person

Company
  HasDirectors Boolean

Group/Membership(Company, Member: Person)
  Role Director|Trustee

Company -hasDirector/isDirectorOf-> Person
```

DO

```onto
Person
Company
Company -hasDirector/isDirectorOf-> Person
```

## 7.6 A reference attribute or a relation

An attribute typed by an entity is a reference (`Shelf Location`). Use it for a
single, one-way, attribute-like link that nobody reads from the other end. Use a
relation as soon as the link is navigated both ways, is many-to-many, or carries
anything. Never declare both for the same link.

## 7.7 Mark a composition as a part

A part goes with its whole, as an arm with its body: an application with the
needs analysis it is made on, a loan split with its structure. Declare the
relation from the whole, mark it `{part}` and give each part one whole (`1:*`
or `?:*`). What a part carries is not part of the whole, nor is a thing that
relates to several of them: a person is a client of many analyses without
belonging to any. Rooted views reach the parts and wholes of what they reach,
and follow other links only where they say so.

DON'T

```onto
Engagement
Application
Party
Application -isPartOf-> Engagement
Engagement -hasClient/isClientIn-> Party ?:* {part}
```

DO

```onto
Engagement
Application
Party
Engagement -resultsIn/resultsFromEngagement-> Application ?:* {part}
Engagement -hasClient/isClientIn-> Party
```
