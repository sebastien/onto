---
name: onto-modeling
description: Model a domain well in onto. Use when writing, extending or restructuring a `.onto` ontology — choosing between entities, facets, relations, vocabularies and types, naming them, splitting domains, or turning a source system's schema into a conceptual model. For auditing an existing ontology, use onto-review.
---

# Modeling with onto

Build a model that is well decomposed, generic and reusable. The test for every
decision:

> Would this still be right if the data came from a different system, a
> different country, or a different product line?

Syntax and commands are in
[references/onto-cheatsheet.md](references/onto-cheatsheet.md). Read it first if
you have not written onto before.

## Workflow

1. **Read what exists.** `onto ls ontology`, then the files you will touch and
   the namespaces they `@use`. Reuse their types and conventions before adding
   any.
2. **Find the core concepts.** The few things every case shares, each answering
   "what is this in reality?". Not screens, tables or records.
3. **Place each in a domain**, in the lowest one where it makes sense alone.
4. **Declare value types** before using them: qualified scalars, vocabularies,
   structures.
5. **Write entities** with their identity-level attributes only.
6. **Add facets** for roles, variants, domain contributions and judgements.
7. **Add relations**: binary for a plain link, an association when the link has
   roles, state or identity.
8. **Check.** `onto check FILE` after every edit, `onto fmt -w FILE` before you
   finish. Then go through the smells below.

Make the smallest model that answers the need. Do not add attributes "in case".

## What you have, what to write

| You have | Write | Rule |
| --- | --- | --- |
| A thing with identity | `E` | 9.1 |
| A kind of thing, for its whole life | `E < Base` | 4.3 |
| A role, a variant, or a domain's view of a thing | `F of E` | 4.2, 4.3, 8.4 |
| A judgement about a thing, made in a context | `F of E {ctx=C}` | 6.1 |
| A plain link | `S -verb/inverse-> T L:R` | 7.1 |
| A link with roles, a share, a status, or its own identity | `R(Role: T, ...) {kind=state}` | 7.3 |
| Something that happened between things | `R(...) {kind=event}` | 7.3 |
| A closed list of names | `T = A\|B\|C` | 3.3 |
| A list others may extend | `T = A\|B\|...` | 3.3 |
| A list whose members have attributes, or that users add to | An entity, `{layer=Reference}` | 3.5 |
| A taxonomy | `T = {hierarchical}` + tree | 3.1 |
| Someone else's classification | Its own vocabulary and a `@map` | 3.6 |
| A quantity | A type with `cur`, `unit`, `period` or `scale` | 2.1, 2.2 |
| A recurring group of values | A structure `T =` + fields | 2.4 |
| Text with a meaning (code, identifier) | An alias `T = Text` | 2.6 |
| Several values | `* Names T` | 4.1 |
| A value implied by others | `~ Name T <- inputs` | 4.5 |
| A value that may be missing | Cardinality `?`; never an `Unknown` value | 3.2 |
| A state that lasts | `StartDate`, `EndDate`; `IsCurrent` derived | 5.4 |
| A change of status | One `…/StatusChange` concept with `Status` and `At` | 5.3 |
| Who said it, how reliably | Nothing: `src`, `conf` on the observation | 6.2 |
| A source system's field, flag or identifier | Nothing: the binding, mapping or `.ids` | 9.2, 9.5 |

## Smells

Stop and restructure when you are about to write any of these.

- **A vocabulary value in an attribute name**: `HomePhone`, `WorkPhone`;
  `HasPeanutAllergy`; an `Other…` attribute. They are rows, not columns. (4.1)
- **The container, type or unit in a name**: `Order.OrderDate`, `Invoice.Date`,
  `WeightKg`. (1.3, 1.4, 2.1)
- **An optional attribute that applies to some instances only**: it is a facet.
  (4.2)
- **`Customer < Person`**: a role is a facet. (4.3)
- **`Unknown`, `None`, `NotApplicable`** in a vocabulary. (3.2)
- **A vocabulary with two axes**: `ElectricVan`, `LeasedCar`. (3.1)
- **One status mixing lifecycles**, or a date per status. (5.2, 5.3)
- **A stored `IsCurrent` or `IsActive`**, or a state without its start and end.
  (5.4)
- **`Reported…`, `Declared…`, `Verified…`, `…Source`** attributes. (6.2)
- **`Legacy…`, `Source…`, `IsSynced`, `Is…Sent`** attributes. (9.2, 9.5)
- **The same fact on two concepts**, or a stored count, total, age or flag.
  (4.4, 4.5)
- **Parallel concepts that share most attributes.** (4.6)
- **One relation declared against many targets.** (7.2)
- **`relatesTo`, `isAssociatedWith`**, a verb without an inverse, a past tense.
  (7.1, 7.4)
- **A generic concept carrying another domain's attributes**, or a `@use` that
  points from generic to specific. (8.1, 8.4)

## Rules

Each file gives the rule, a DON'T and a DO in onto. Load the one you need.

| File | Rules |
| --- | --- |
| [rules/naming.md](rules/naming.md) | 1.1–1.8 Names, affixes, abbreviations |
| [rules/values.md](rules/values.md) | 2.1–2.7 Units, stocks and flows, composites, scalar types, locale |
| [rules/vocabularies.md](rules/vocabularies.md) | 3.1–3.8 Axes, absence, open and closed, reference entities, maps |
| [rules/decomposition.md](rules/decomposition.md) | 4.1–4.8 Rows not columns, facets, roles, single storage, derivation |
| [rules/time-provenance.md](rules/time-provenance.md) | 5.1–5.4 Workflow, lifecycles, intervals; 6.1–6.4 Judgements, provenance, answers, docs |
| [rules/relations.md](rules/relations.md) | 7.1–7.6 Verbs, supertypes, associations, grammar |
| [rules/domains.md](rules/domains.md) | 8.1–8.6 Dependency direction, placement, layers |
| [rules/source-bias.md](rules/source-bias.md) | 9.1–9.6 Records, system state, workarounds, raw values |

## Known gaps in onto

Two shapes have no direct form yet; the rule files give the workaround.

- No partial date: alias `Text` once, with the format in its doc. (2.4)
- Single inheritance: chain the supertypes, most generic at the root. (7.2)

## When a rule does not fit

The rules are defaults. When you break one, say why in a `{check=token}` on the
element and tell the user, so the choice is visible and can be revisited.
