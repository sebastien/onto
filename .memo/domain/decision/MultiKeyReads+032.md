---
identity: "onto:decision:multi-key-reads"
created: 2026-11-27T04:07:58.428483+00:00
updated: 2026-11-27T04:07:59.282832+00:00
code: DEC0032
title: A read providing several keys
status: proposed
date: 2026-11-27
---
# A read providing several keys

**Status**: proposed (not decided). **Date**: 2026-11-27.

**Context**: `ViewRead(provides=...)` names one `ViewInput`: a read discovers
one key for later reads (spec-06 "Rooted retrieval"). adviceos-data's mortgage
view (`/mortgage/application/get-view/{id}`) names the application's needs
analysis, its lender deals and its clients. Its catalogue therefore holds three
reads of the same request, one per key, each admitting only the binding scopes
of its own rows and naming its own `via` link (`Mortgage`, `MortgageDeals` and
`MortgageClients` in `recorded.py`). A run sends the request once, since a
response is never requested twice, and each read checks the shared response
for itself.

**Proposal**: `provides` takes several keys, each with its own `via`. Not
designed yet.

**Alternatives**: one read per key, as now. It costs no request, but repeats
the catalogue entry and the response checks.

**Open questions**: whether each provided key keeps its own `via` and admitted
scopes; how plans and reports name a read's several discoveries; whether the
change is worth it while the workaround costs no request.

Related: [domain/decision:Compositions+029] [domain/decision:ReadSelection+024]
[domain/component:HexaIntegration]

Sources: `docs/specs/spec-06-hexa.md#rooted-retrieval`; adviceos-data
`TODO_ONTO.md` at `4035dc3` ("A read provides one key"),
`src/py/adviceos/data/advicelink/recorded.py`
