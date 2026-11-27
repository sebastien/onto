---
identity: "onto:decision:fact-history"
created: 2026-11-27T17:20:29.552144+00:00
updated: 2026-11-27T17:37:56.387608+00:00
code: DEC0036
title: "Sessions read who changed the facts a view shows, from each slot's holder"
status: accepted
date: 2026-11-28
---
# Sessions read who changed the facts a view shows, from each slot's holder

**Status**: accepted. **Date**: 2026-11-28.

**Context**: the AdviceOS UX prototype (claude.ai artifact
`9ovFfefAsBDmZJyDfh4L1P`, version of 2026-11-07) shows:
- on each record, who last changed it and when ("Updated 21 Jul 2026 by Mere
  Tipoki"), and the oldest such date on a page;
- a list of changes, each with the values before and after, who made it, and
  its source.

AdviceOS keeps no copy of CRM data, so these come from each fact's holder:
- the store stamps each statement with `recorded` and `principal`, and its log
  keeps superseded claims (spec-08);
- the AdviceLink CRM's audit log records each update with its actor and the
  record's JSON before and after (`DomainedEvent.updateEvent`). A new CRM read
  returns them as the user (adviceos-crm `docs/spec/spec-001-design.md`, C12).

**Decision**: histories, in `docs/specs/spec-09-sessions.md` (History).

- **Per holder.** Each slot's holder supplies its history:
  - the store, from a newest-first log read of the view's partitions and
    slots, each statement with `was`, the value it replaced (spec-08 Log);
  - a system, from its declared history read.
- **History reads.** A catalogue role, `history`: records and a page in;
  changes newest first out, each with its time, its actor, and the record's
  rows before and after.
- **Compared after mapping.** The session binds and maps both rows of a
  system's change, and compares the two states slot by slot.
- **One order.** The store orders history by `recorded` and then `seq`, not
  append order, so it remains in time order after merges. An opaque cursor
  continues the initial selection without skipping the head. The session
  merges ordered streams and retains entries that did not fit on a page.
- **Latest.** `{latest: true}` answers each instance's newest change, for
  "updated … by …", without reading whole histories.
- **On request.** A page's retrieval makes no history reads.

**Alternatives**:
- **Provenance in every report:** every page would pay a history read per
  record, though few pages show it.
- **Observation metadata from bindings (`at`, `by`):** mappings rewrite both
  (spec-04 Claims and metadata), and a CRM record read names no author.
- **Field-level changes from the CRM:** the CRM would have to know AdviceOS's
  slots. Comparing mapped rows keeps the mapping the only translation.
- **`updated_at` and `updated_by` columns in the CRM:** they give the latest
  change only, and the database does not know the application's user.

**Rationale**:
- Holders already decide where each fact lives; the same rule tells where its
  history lives.
- Bindings and mappings already turn a system's rows into facts, so a history
  read only has to return rows.

**Consequences**:
- spec-08 gains newest-first log reads with `was`, and spec-09 gains History,
  both written with this decision.
- spec-06's catalogue gains the `history` role with the implementation.
- The implementation is open work in `TODO.md`, after the read path's first
  milestone (adviceos-crm `docs/plan/plan-001-read-path.md`).
- `{history}` ([domain/decision:HistoryConcept+013]) is unrelated: it models a
  domain's own changes as facts.
- Deferred: histories of list views, and reasons for changes beyond `src` and
  `ctx`.

**Approval**: accepted by the user on 2026-11-28, in the adviceos-crm design
session, after the review of the UX prototype.

Related: [domain/decision:Sessions+028] [domain/decision:ObservationStore+026]
[domain/decision:HistoryConcept+013]

Sources: `docs/specs/spec-09-sessions.md`, `docs/specs/spec-08-store.md`,
adviceos-crm `docs/spec/spec-001-design.md`
