---
identity: "onto:decision:operations"
created: 2026-11-27T03:29:30.047552+00:00
updated: 2026-11-27T04:06:17.522586+00:00
code: DEC0030
title: Operations write system-held slots back through reversed mappings and request bindings
status: accepted
date: 2026-11-27
---
# Operations write system-held slots back through reversed mappings and request bindings

**Status**: accepted. **Date**: 2026-11-27.

**Context**: sessions (spec-09) read a system of record and route changes to
each slot's holder, but left writing system-held slots to a later proposal.
- **Operations.** Onto had no representation of a system's operations
  (adviceos-data `TODO_ONTO.md`, "Operations").
- **Reversal.** It lost most of the AdviceLink to AdviceOS mapping: 600 lossy
  lines.
  - 368 come from scope conditions such as `{when=Deleted:false}`
    (`mapping/reversal.py`, condition).
  - 206 come from named, presence-selected and `into` scopes, which were
    refused outright.
- **JavaScript.** The runtime could not write.

adviceos-crm `docs/spec/spec-001-design.md` asks for these as D4 to D7. The
AdviceLink CRM's updates are full-record, guarded by record versions (its own
spec, C3).

**Decision**: the operations of `docs/specs/spec-10-operations.md`.

- **Reversal widened.**
  - Source-side conditions reverse and assert single values.
  - Literal lines become reverse conditions.
  - Named, presence-selected and update scopes, and source references,
    reverse.
- **Operations.** Declared beside reads, with:
  - an effect, a subject source type and body bindings, used for writing;
  - a request template, a preparatory read and arguments;
  - a response binding and a client-minted key for creates;
  - a conflict status.
- **Checks.** Full-record safety: an update's body slots come from the change
  or the read (`operation.unread`).
- **Sessions.**
  - Reverse a change set's before and after states, and plan the fewest
    operations in dependency order.
  - Read afresh, check seen values (`was`), write with the read's response as
    originals, send as the principal and confirm by reading again.
  - Results: `applied`, `conflict`, `rejected`, `uncertain`, `unconfirmed`,
    `readonly` and `ambiguous`.
- **JavaScript.** Runs reverse mappings, writing bindings and operations, with
  conformance against Python.

**Alternatives**:
- **Partial updates of changed fields only.** Rejected for the AdviceLink CRM,
  which keeps full-record updates guarded by versions. Body bindings still
  allow narrow endpoints, whose bodies write only the changed slots and need
  no read.
- **Writing from the session's cached state.** A record changed since the
  page loaded would be overwritten silently. A fresh read keeps the race to
  the time between that read and the request, which the system's version check
  closes.
- **Resending uncertain updates.** They may have been saved. Following the MCP's
  write rules, only keyed creates are resent, and other uncertain writes are
  resolved by reading.
- **Originals by document path only** (spec-04 as is). A request body and the
  read's response are different documents, so originals are matched by
  subject and source slot.
- **Reads and operations in a file format of their own.** Rejected in review:
  it would bring workspace checks without host code, and diffs and drafts by
  tooling, but hosts get both already. Compiling the bundle checks the
  catalogue, the bundle is its language-neutral form, and a host can keep its
  catalogue as generated JSON. A format would add a grammar, normal and JSON
  forms, a parser and CLI support for JSON-shaped request templates. Revisit
  if a second host needs the same catalogue.

**Rationale**:
- Writing reuses what onto has, instead of hand-written request builders:
  reversal, writing bindings, originals and formats, request templates and
  Hexa effects.
- Full-record writes are safe only when every field comes from a fresh read,
  which a static check enforces.

**Consequences**:
- Written into the specs on acceptance:
  - spec-04: the reversal forms, and originals from another document;
  - spec-06: the generated reversal forms, request bodies, operations in the
    catalogue and bundle, and writing in JavaScript;
  - spec-09: writability by operations, and `was` with its routes and results.
- The implementation is open work in `TODO.md`.
- Tests follow `T10`.
- adviceos-data drafts operations from its projection's `write`, `key` and
  `arg` rows.

**Review answers** (2026-11-27):
- **No file format** for reads and operations (above); hosts may keep them as
  data.
- **New instances.** A new instance's source type is decided by the operation
  the change set names for it. Otherwise its reverse conditions (literals,
  source-side conditions, value maps) must single one out, else its statements
  are `ambiguous`. A new `FileNote` interaction becomes a CRM comment, while a
  new person needs its operation named, since clients and users both map to
  persons.
- **Confirming reads** after every write are accepted.

**Approval**: accepted by the user on 2026-11-27, after the review above, in
the adviceos-crm design session.

Related: [domain/decision:Sessions+028] [domain/decision:ObservationStore+026]
[domain/decision:RunSemantics+001] [domain/component:HexaIntegration]
[domain/component:JsRuntime]

Sources: `docs/specs/spec-10-operations.md`, `src/py/onto/mapping/reversal.py`,
adviceos-crm `docs/spec/spec-001-design.md`


