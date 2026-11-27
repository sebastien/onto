---
identity: "onto:decision:sessions"
created: 2026-11-26T01:58:40.153369+00:00
updated: 2026-11-27T17:19:34.007251+00:00
title: "Sessions combine a store's systems into one state, and route changes to each slot's holder"
status: accepted
date: 2026-11-27
code: DEC0028
---
# Sessions combine a store's systems into one state, and route changes to each slot's holder

**Status**: accepted. **Date**: 2026-11-27.

**Context**: an application built on onto reads several systems of record: a
CRM through bindings and a mapping, and its own observation store (spec-08)
for the facts only it holds. AdviceOS, on adviceos-data, reads the AdviceLink
CRM as the user from the browser and keeps no copy of CRM data. Its pages
therefore need, client-side:
- one view over both;
- for each fact, which system holds it;
- lists filtered on facts either system holds;
- refreshes when either changes;
- changes routed to the right system.

adviceos-crm `docs/spec/spec-001-design.md` asks for these as D1 (authority)
and D3 (sessions over several sources).

**Decision**: the sessions of `docs/specs/spec-09-sessions.md`.

- **Systems.** A store file's systems: its `@system` mappings' sources, and the
  store.
- **Holders.** Each slot of an instance has a holder, decided by the
  instance's origin, read from its handle form:
  - `from=` policies and source-qualified scopes give a system;
  - the store's scope gives the store;
  - key-derived handles without `from` are shared.
- **Planning.** Spec-06's planner gains store reads as suppliers of
  store-held obligations, in waves, batched per wave.
- **List views.** Rooted views with a `*` parameter, retrieved by key queries
  compiled to a system's declared list read, composed with store indexes
  through include and exclude key sets. Queries using an index run on the
  server.
- **Limits and pages.** Views hint page sizes and the largest page; list
  views and populations are read a page at a time.
- **Notices.** They drop the outputs of the reads they concern, and the
  session reruns what used them.
- **Changes.** Spec-02 fragments with slot versions, appended per home
  partition. System-held slots stay read-only until operations are specified.

**Alternatives**:
- **Holders per type** (spec-08 as accepted): AdviceOS-only instances of a
  type the CRM maps, such as a dependant or a prospect recorded only in
  AdviceOS, could never hold their own names.
- **Holders by declaration only:** every slot of a large ontology would need a
  line; deriving holders from the `@system` mappings keeps the store file
  short.
- **Origin from the store's existence claims instead of handles:** the store
  could not tell a CRM client from a new instance claiming the same handle.
- **Resolving cross-system conflicts in reconciliation:** spec-02 reports
  conflicts across sources; off-authority claims are reported beside the
  state instead, so nothing is silently resolved.
- **List views as a separate view kind:** a list view is a rooted view per
  row, so it reuses rooted views' planning, with a key query as the seed.
- **Index answers in the browser:** they name partitions the user may not see;
  key queries using indexes run on the server.

**Rationale**:
- Holders follow what each system's mapping actually fills, so the CRM stays
  authoritative for its data while AdviceOS-only instances hold all their own
  slots.
- Sessions reuse rooted retrieval, the store's protocol and reversal; the new
  machinery is store reads, list reads and notices.

**Consequences**:
- Written into the specs on acceptance:
  - spec-01: `*` parameters, and the `page` and `max` hints;
  - spec-06: holders, store steps, list reads and page parameters;
  - Sessions use `onto.view-bundle/3`. Rooted views already use `/2` for
    per-view read plans; separate versions distinguish the two contracts;
  - spec-08: held slots by origin, `@system` scopes, `origin.unknown` and
    population pages.
- The implementation is open work in `TODO.md`.
- The JavaScript runtime gains `Session`, which adviceos-data's own session
  (`src/js/adviceos/views.js`) can then use.
- Tests follow `T09`.

**Review answers** (2026-11-26):

- **Holders per record.** Agreed, amending spec-08's per-type held slots.
- **`*` for list views.** Agreed, since `*` is spec-01's cardinality for zero
  or more: many keys.
- **Limits.** Views hint them, and pagination is supported. List views take
  `page` and `max`, and population lines take `page`. Reads that cannot page
  are read whole, and the session pages them. The store pages population
  selections, the most recently added first.

**Approval**: accepted by the user on 2026-11-27, after the review above, in
the adviceos-crm design session.

Related: [domain/decision:ObservationStore+026]
[domain/decision:ReadSelection+024] [domain/decision:ReferentialIdentities+002]
[domain/component:JsRuntime] [domain/component:HexaIntegration]

Sources: `docs/specs/spec-09-sessions.md`, adviceos-crm
`docs/spec/spec-001-design.md`


