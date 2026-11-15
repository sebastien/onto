# 9. Source-system bias

A model derived from an existing system inherits its tables, screens and
workarounds. onto gives the source its own place, so the ontology does not have
to hold it:

| What the source has | Where it goes |
| --- | --- |
| Its fields and record shapes | A binding (`.bind`) and a mapping (`.map`), spec-04 |
| Its record identifiers | The `.ids` sidecar and referentials (`.ref`), spec-05 |
| Its code lists | A vocabulary in the source's own ontology, related with `@map` |
| Values that cannot be interpreted | The observation or the mapping, never the model |

## 9.1 Model the world, not the records

Ask "what is this in reality?" of every concept. A screen, a table, an import
batch or a "deal" is rarely a real thing.

```text
DON'T   CrmDeal, ClientRecord, ImportRow, ClientGroup ("a grouping in the system")
DO      Application, Household, Organisation
```

## 9.2 System state is not domain data

Flags that drive the application's behaviour, UI or integrations do not describe
the domain.

DON'T

```onto
Customer
  IsShownOnWebsite Boolean
  IsWelcomeEmailSent Boolean
  LastSyncedAt DateTime
  LegacyType Text
```

DO: leave them in the system; record the event if it matters.

```onto
Customer

Message
  Subject Text

Message -isSentTo/receives-> Customer {kind=event}
```

## 9.3 Do not copy a workaround

If the source has two near-identical structures because of how it grew, model
the one concept they both approximate and map both onto it.

DON'T

```onto
Case
ProviderCase
Application
Submission
```

DO

```onto
Application
Submission
Application -isSubmittedAs/submits-> Submission 1:*
```

Product-line differences are then facets of `Application` (4.2).

## 9.4 Stage names of a workflow tool are not a vocabulary

Values named after screens, forms or queue names belong to the tool.

DON'T

```onto
Task/Type = PostSettlementTask|ShortFormWebLeadTask|StageThreeFollowup
```

DO: the subject says the rest.

```onto
Task/Type = FollowUp|InformationRequest|Review

Subject
Task

Task -concerns/isConcernOf-> Subject
```

## 9.5 Preserve what you cannot interpret, outside the model

When a source value cannot be mapped, keep the raw value with the observation or
in the mapping layer. Do not add a `Source…` or `Legacy…` twin to the model.

```text
DON'T   Product.Type, Product.SourceType, Product.LegacyCategory
DO      Product.Type          # the mapping reports the values it could not map
```

## 9.6 Evidence annotations say how sure the model is

When the model is inferred from a source rather than stated by someone who
knows, say so with the header (`src=import cards=assumed`), `{status=inferred}`
and `{check=…}` on what is uncertain. Do not encode the doubt in a name or a
doc.
