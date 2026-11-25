---
identity: "onto:decision:gaps-json-only"
created: 2026-11-25T19:44:13.041358+00:00
updated: 2026-11-25T19:44:33.054412+00:00
title: "Gap-bearing results travel as JSON, never as text"
status: accepted
date: 2026-11-11
code: DEC0005
---
# Gap-bearing results travel as JSON, never as text

**Status**: accepted (specified in spec-02). **Date**: 2026-11-11 (commit
`066d68d`).

**Context**: lenient loading keeps semantically invalid statements as *gaps*,
with their raw source, location, effective defaults and diagnostics; none of a
gap's claims or retractions is applied.

**Decision**: the public text printers (log and state) refuse a result that
has gaps; JSON is the gap-preserving interchange form. The JSON reader
revalidates each gap and rejects one that has become valid, rather than
promoting it to a claim.

**Alternatives**: printing gaps as ordinary statements, or silently dropping
them; both ruled out.

**Rationale**: a raw statement printed into a text normal form could become
active under a later ontology, so presenting it as inert is unsafe; dropping it
loses review material.

**Consequences**: a host reviews gaps (removes or reprocesses them) before it
prints text. Gaps never count as evidence in coverage.

Related: [domain/component:Observations]

Sources: `docs/specs/spec-02-observations.md#validation`, `TODO.md` at
`da01e2c` ("Lenient semantic gaps implemented")
