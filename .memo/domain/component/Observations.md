---
identity: "onto:component:observations"
created: 2026-11-25T19:44:10.072234+00:00
updated: 2026-11-25T19:44:25.213979+00:00
title: Observations component
---
# Observations component

**Owns** the observations format (spec-02): typed loading against an ontology,
reconciliation of claims into a state, the log, state and compact text forms,
JSON interchange, and coverage of views.

- *Package*: `src/py/onto/observations/` (`model.py`, `parser.py`,
  `formatter.py`, `operations.py`), plus `rooted.py` (walks typed view paths
  and collects witnesses from reconciled claims). `coverage.py` at the root
  reports view coverage, and the static coverage rows of bindings and mappings.
- *Interfaces*: `parseObservations`, `resolveObservations`, `loadObservations`,
  `reconcileObservations`, `mergeObservationLogs`, `printObservationsLog`,
  `printObservationsState`, `printObservationsCompact`, `formatObservations`,
  `observationsToJson`, `observationsFromJson`, `observationsCoverage` and
  `Operator` (`ObservationsOperator`, holding the ontology and the mode).
- *Reconciliation*: supersession within a source, conflicts kept between
  sources, producer-scoped withdrawals (`src` and `by`) applied first, then
  identity links, then supersession. It never mutates its input; the log keeps
  the original handles and claims.
- *Modes*: strict rejects any semantic error; lenient keeps failing statements
  as gaps, atomically, with their raw text ([domain/decision:GapsJsonOnly+005]).
  Gaps never count as evidence in coverage.
- *Normal forms*: state replay must give the same state
  ([domain/decision:IdentityLogOrder+004], [domain/decision:CollectionLogOrder+006],
  [domain/decision:TypeOnlyDeclarations+007]), checked by
  [domain/pattern:ReplayAudit].
- *Not implemented*: spec-05 registries (minted handles, alternate keys) and
  implicit-age warnings.

Sources: `docs/specs/spec-02-observations.md`,
`docs/specs/spec-05-identities.md#resolution`, `src/py/onto/observations/`,
`src/py/onto/coverage.py`
