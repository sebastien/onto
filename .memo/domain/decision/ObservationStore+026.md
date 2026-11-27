---
identity: "onto:decision:observation-store"
created: 2026-11-26T00:41:27.639357+00:00
updated: 2026-11-26T01:16:44.484303+00:00
title: "An observation store keeps observations online, in partitions around key entities"
status: accepted
date: 2026-11-26
code: DEC0026
---
# An observation store keeps observations online, in partitions around key entities

**Status**: accepted. **Date**: 2026-11-26.

**Context**: onto describes, exchanges and maps observations, but keeping them
in an online system is left to hosts (spec-07 defers re-running against a host
store). The AdviceOS application, built on adviceos-data, must store the facts
only it holds beside the AdviceLink CRM: identity checks, questionnaire
answers, attributes of CRM entities the CRM does not model. Its browser
combines them with CRM reads made as the user. It must manage access,
retention, redaction and erasure per client, and attribute every append and
read.

**Decision**: the observation store of `docs/specs/spec-08-store.md`.

- Store files (`.store`) declare what a store holds and how: partitions around
  key entities, the systems that hold other slots, lifecycle policies and
  indexes.
- A store keeps spec-02 statements per partition, with:
  - preconditions per slot;
  - lifecycle states at three levels;
  - redaction, purges, merges and erasure;
  - minimal indexes for servers.
- It is implemented in JavaScript and in Python.

**Alternatives**:

- **Storelight documents.** Mutable JSON trees, with conflicts per document and
  a journal compacted after 100 entries. Observations need provenance per
  claim, lasting history and conflicts per slot, so the store takes
  Storelight's server design but not its data model.
- **One document per instance, or per CRM record.** The former is too fine for
  authorization and erasure, the latter shaped by the source system. A key
  entity matches the unit people are authorized for and erased as.
- **A server-side copy of CRM data.** Rejected by the application: the CRM must
  log reads under the user, and AdviceOS keeps no copy of CRM data.
- **`@partition` in ontology files.** Rejected in review: a partition is a
  storage view of what is stored and how, so it belongs in a file of its own,
  as a referential does.
- **Naming partitions by the anchor's key.** It would require a key-derived
  identity policy for every key entity; handles work with any spec-05 policy.
- **Calling the isolation boundary a namespace.** In onto, a namespace names an
  ontology, so the boundary is a scope, as `@scope` already defines.
- **Registering every anchor**, so that an index covers instances without a
  partition. Deferred: hosts compose negative lists with the system of
  record's own lists instead.

**Rationale**:

- One partition is one unit for authorization, isolation, retention and
  erasure.
- Reconciliation stays spec-02's, with log order as statement order.
- Preconditions per slot keep writers of different facts from colliding.
- Redaction destroys values, for privacy, while a retraction keeps them, for
  audit.
- Lifecycle states flag data rather than drop it, at the level people act on.

**Consequences**:

- spec-07 gains the `.store` kind and `onto store bundle`; the ontology
  formats are unchanged.
- The JavaScript runtime gains statement validation against model facts.
- Tests follow `T08`, and the implementation is open work in `TODO.md`.

**Approval**: reviewed and accepted by the user on 2026-11-26, in the session
that drafted it for adviceos-crm. The review settled:

- store files rather than ontology files;
- lifecycle at three levels, with:
  - an effective state, the most advanced that applies;
  - shared members active while one parent is;
  - default policies `never`, `never` and `P30D`;
  - anchor-level states covering the anchor's own statements;
  - partition-level changes leaving slot versions alone;
- an eventually consistent reference index for erasure;
- a minimal index (`eq`, `in`, `exists`, `and`) for servers.

Related: [domain/component:Observations] [domain/component:JsRuntime]
[domain/decision:RunSemantics+001] [domain/decision:ReferentialIdentities+002]

Sources: `docs/specs/spec-08-store.md`, `docs/specs/spec-07-cli.md`,
adviceos-crm `docs/spec/spec-001-design.md`
