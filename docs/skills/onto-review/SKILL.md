---
name: onto-review
description: Review an onto ontology against the modeling rules. Use when asked to review, audit or critique `.onto` files or a change to them, to find modeling problems (naming, vocabularies, decomposition, time, provenance, relations, domains, source-system bias), or to produce a backlog of model fixes. For writing or restructuring a model, use onto-modeling.
---

# Reviewing an onto model

Find where a model departs from the modeling rules and say what to do about it.
The rules are in [rules/](rules/), numbered 1.1 to 9.6; syntax is in
[references/onto-cheatsheet.md](references/onto-cheatsheet.md). A review reports;
it does not edit the model unless asked.

The test behind every finding:

> Would this still be right if the data came from a different system, a
> different country, or a different product line?

## Procedure

1. **Scope.** `onto ls ontology` for the whole model, or the changed files for a
   change (`git diff --name-only -- '*.onto'`). For a change, review what it
   adds and what it touches, not the whole file.
2. **Validate.** `onto check FILE...`. Report errors first: a model that does
   not load cannot be reviewed further.
3. **Read the dependencies.** List each file's `@ontology` and `@use` lines and
   draw the direction. Cycles and generic-to-specific uses are 8.1 findings.
4. **Sweep** with the searches below. Each hit is a candidate, not a finding:
   read it in context.
5. **Read** each file once in full for what searches cannot see: concepts that
   are records (9.1), parallel shapes (4.6), facts on the wrong concept (4.4,
   8.2), mixed lifecycles (5.2).
6. **Report** in the format below.

## Sweep

Run from the directory holding the `.onto` files. The comment gives the rule and
what the search looks for.

```sh
# Naming
rg -n '^\s+(Date|Text|Type|Value|Number|Name) '          # 1.4 names that state a type
rg -n ' Boolean' | rg -v ' (Is|Has)[A-Z]'                # 1.5 booleans without Is/Has
rg -n '(Kind|Category|Class)\b'                          # 1.6 more than one word for "type"

# Values
rg -n '(Kg|Usd|Eur|Months|Years|Days|Pct)\b.* (Number|Integer)'   # 2.1 unit in the name
rg -n ' (Amount|Duration|Percent)( |$)'                  # 2.1 built-in without a qualified type
rg -n '(Frequency|Period|Per[A-Z])'                      # 2.2 a flow split in two attributes
rg -n '(Low|High|Min|Max|From|To)\b'                     # 2.4 a range as two attributes
rg -c ' Text( |$)'                                       # 2.6 catch-all text, per file
rg -n 'default='                                         # 2.7 locale in a generic type

# Vocabularies
rg -n '[a-z]And[A-Z]'                                    # 3.1 two axes in one value
rg -n '\b(Unknown|NotStated|None|NotApplicable|Unspecified)\b'    # 3.2 absence as a value
rg -n 'Other.*\.\.\.'                                    # 3.3 closed and open at once
rg -n '=.*[A-Za-z][0-9]+(\||$)'                          # 3.4 a quantity in a value
rg -n '=.*\|\.\.\.'                                     # 3.5 open sets: reference entities?

# Decomposition
rg -n '^\s+Other[A-Z]'                                   # 4.1 values in names
rg -n '(Count|Total|Age|Sum)\b' | rg -v '~'              # 4.5 stored derivations

# Time and provenance
rg -n '(Status|Stage)[A-Za-z]*(Date|At) '                # 5.3 a date per status
rg -n '(IsCurrent|IsActive|IsExpired|IsClosed)' | rg -v '~'         # 5.4 stored flag instead of an interval
rg -n 'kind=state'                                       # 5.4 states: do they declare start and end?
rg -n '(Reported|Declared|Verified|Stated|Estimated|Source)'       # 6.2 provenance in names
rg -n -- ' -- .{100,}'                                   # 6.4 docs that defend

# Relations
rg -n -- '-(concerns|relatesTo|isAssociatedWith|has|is)[/-]'       # 7.1 vague verbs
rg -oIN -- ' -[a-z][A-Za-z]*' | sort | uniq -c | sort -rn | head   # 7.2 a verb repeated per target
rg -n -- ' -[a-z][A-Za-z]*->'                            # 7.4 missing inverse
rg -n -- ' -[a-z]+ed[/-]'                                # 7.4 past tense

# Domains and bias
rg -n '^@(ontology|use)'                                 # 8.1 dependency direction
rg -n '(Legacy|Sync|Import|Crm|Screen|Sent|Shown)'       # 9.2 system state
```

Searches cannot find these; read for them: the owner's name repeated in an
attribute (1.3), attributes sharing a prefix or suffix (4.1), and everything in
step 5.

`onto json FILE` gives the model as data when a question needs counting
(attributes per entity, facets per subject, uses of a type).

## Judging a candidate

- A finding needs the rule, the place and the consequence: what goes wrong when
  a new value, source, country or product line arrives.
- Check the rule's DO form is expressible. For ranges, partial dates and
  multiple supertypes onto has only a workaround (see `rules/values.md` 2.4 and
  `rules/relations.md` 7.2): report the workaround, not the ideal.
- An element with `{check=…}` or `{status=assumed}` is already flagged by its
  author: report it as an open decision, not a defect.
- Do not report style that `onto fmt` fixes, or what `onto check` rejects.
- Many instances of one rule are one finding with a list, not many findings.

## Report

Order sections by rule number and keep the rule numbers: they are stable
references. Omit rules without findings.

```markdown
# Review of `<scope>` against the modeling rules

<Scope: files and revision. Result of `onto check`.>

## Summary

<Three to six sentences: the main structural problems, most important first.>

| Rule | Findings | Severity |
| --- | --- | --- |
| 4.1 Vocabulary value in an attribute name | 12 | High |

## 4. Decomposition

### 4.1 Vocabulary value in an attribute name

| Where | Problem | Proposed |
| --- | --- | --- |
| `Person.HomePhone`, `.WorkPhone`, `.MobilePhone` | Three attributes differ by a value | `* Phones ContactPoint` with `Use Home\|Mobile\|Work` |

## Backlog

<Ordered list of changes, each naming the findings it closes. Structural
changes first, renames last: a rename is wasted on a concept about to be
removed.>

## Open decisions

<Questions only the model's owner can answer, each with the options and what
each one implies.>
```

Severity:

- **High**: the model must change when data changes (4.1, 3.1), or two places
  can disagree (4.4, 2.5, 3.7, 7.5, 5.4).
- **Medium**: wrong placement or coupling (5.1, 6.1, 6.2, 8.x, 9.x).
- **Low**: naming and docs (1.x, 6.4).

Give paths as onto writes them (`Owner.Attr`, `Subject.Facet.Attr`,
`S.verb.T`, `Type:Value`) and write proposals in onto syntax. State what you did
not review.
