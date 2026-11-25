---
identity: "onto:guide:conventions"
created: 2026-11-25T19:44:03.123780+00:00
updated: 2026-11-25T19:44:03.493103+00:00
title: Conventions of this knowledge base
---
# Conventions of this knowledge base

This store documents the onto implementation: what it is made of, the patterns
it follows and why it was designed as it is. It follows the
`memo-documentation` skill's conventions, as the sibling `memo` project's own
store does.

## Namespaces

| Namespace | Holds | Kinds |
|---|---|---|
| `domain/` | the implementation and its design history | `architecture`, `component`, `pattern`, `antipattern`, `decision`, `collection` |
| `usage/` | how to use this store | `guide` |
| `project/` | the project agent's memory (agent store, `.agents/memo/`) | `agent`, `observations`, `learning` |

## Rules

- The specifications in `docs/specs/` are authoritative for the formats and
  their meaning, and `docs/doc-overview.md` introduces the vocabulary. Entries
  here link them and add what they do not say: structure, rationale,
  alternatives, approval and evidence. There are no `concept` entries.
- One concern per entry, short enough to read alone.
- Link with `[REF]`; never copy a specification passage. Write onto syntax,
  file paths and anything else with square brackets in backticks, so that it
  is not read as a reference.
- Every entry ends with `Sources:` naming the canonical files, in backticks.
  History migrated from `TODO.md` cites it at commit `da01e2c`, the last
  version holding the implementation notes.
- Identities are readable and stable: `onto:KIND:name`.
- Decisions are members of [domain/collection:Decisions] with `DEC` codes, a
  `status` and a `date`; see that entry for how dates are chosen.
- Open work stays in `TODO.md`. An open proposal there links its `proposed`
  decision here, which holds the design.
- Working rules for agents are learnings of the project agent
  (`memo agent wake`), not documentation.
- Edit through Memo (`memo edit`, `memo meta set`), then run `memo ref check`.

Sources: `TODO.md`, `docs/doc-overview.md`
