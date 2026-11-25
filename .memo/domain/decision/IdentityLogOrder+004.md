---
identity: "onto:decision:identity-log-order"
created: 2026-11-25T19:44:12.867882+00:00
updated: 2026-11-25T19:44:32.779560+00:00
title: The state form keeps identity links in log order
status: accepted
date: 2026-11-11
code: DEC0004
---
# The state form keeps identity links in log order

**Status**: accepted (approved by the user during the spec-02 alignment of
phase 2). **Date**: 2026-11-11 (commit `066d68d`).

**Context**: the state form sorts most statements, but identity links cannot be
sorted freely: when `a = b` joins two groups, the link's order chooses which
canonical handle survives (spec-05 Resolution).

**Decision**: the state form prints identity links after the records, in log
order (`at`, then statement ordinal), with their original endpoints and
metadata. Only the endpoints of a `!=` link are sorted, which does not move
the link.

**Alternatives**:
- Sorting links by operator or handles: changes canonical handles on replay.
- A temporary guard rejecting states whose links would not replay
  (`identity-order`), used until the decision and then removed.

**Rationale**: replaying the state must give the same canonical handles and
keep each link's provenance. With `a=b`, `c=d` then `b=d`, log order keeps `a`
canonical; sorted by handles (`a=b`, `b=d`, `c=d`), the links make `c`
canonical instead.

**Consequences**: specs 02 and 05 agree; canonicalised links, if ever needed,
are a separate derived representation, never a replacement for the claims. A
later replay review found repeated `=` evidence from one source superseding
itself, which changed the canonical handle for `c = a`, `b = a`, `c = a`;
identity links now accumulate, as spec-02 requires
([domain/pattern:ReplayAudit]).

Sources: `docs/specs/spec-02-observations.md#normal-forms` (rule 4),
`docs/specs/spec-05-identities.md#resolution`, `TODO.md` at `da01e2c`
("Updated spec-02 alignment", "Conformance audit: fixes and review outcome")
