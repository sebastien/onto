---
identity: "onto:component:hexa-integration"
created: 2026-11-25T19:44:10.612619+00:00
updated: 2026-11-27T17:40:14.445263+00:00
title: hexa integration component
---
# hexa integration component

**Owns** execution: compiling bindings and mappings into hexa programs and
running them (reading documents, learning formats, re-running with
safeguards, unfolding mappings, writing documents), rooted views over a host's
read catalogue, and bundles for the JavaScript runtime.

- *Package*: `src/py/onto/integrations/hexa/`; spec-06 "Layout" lists its
  modules (compiler, vocabulary, stages, unfold, runs, writing, catalogue,
  views,
  requests, bundle, operations, model).
- *Interfaces*: `HexaBindingOperator` (`compile`, `result`, `formatsUpdate`,
  `approve`, `compileWrite`), `HexaMappingOperator`, `HexaViewOperator` (`plan`,
  `report`, `retrieve`, `runReads`), their functional forms, `viewBundle`,
  `vocabularyConformance` and `IntegrationUnavailable`.
- *Host hooks*: the host persists outcomes and supplies previous output
  (`OutputPreviousRead`, `RetractionsPendingRead`); views take an `access`
  adapter (`rootHandle`, `fetch`, optional `check`, `describe`, `discover`) and
  hexa operations such as `RequestSend`. Registry identities would come through
  an `IdentityResolve` operation (deferred).
- *Boundaries*: imported lazily, never by core; reads parsed models, never
  text; uses hexa's public API only and never patches it
  ([domain/decision:HexaExecution+008]). Its output is validated through
  `observationsFromJson`: an invalid log is a defect of the integration, never
  a data error. Compiled state is program-local
  ([domain/antipattern:ProcessWideRegistry]).
- *Adaptations to hexa*, all documented in spec-06: positions are
  `either(Null, tolerant(P))` so a failed codec keeps its own reason; nested
  selectors run one level at a time so one missing path loses only its own
  children; transforms leave a key out with an absence marker that
  `ClaimsEmit` drops; Integer attributes read through `Onto.IntegerText`;
  transform gap codes are reported as `Binding.*` or `Mapping.*`; index steps
  use tuples ([domain/decision:IndexStepsAsTuples+017]).
- *Gaps*: hexa ships no runner for vocabulary examples, so
  `vocabularyConformance()` runs every `Onto` codec and transform example.
  Tests (`tests/T06-*`) are skipped without hexa.

Sources: `docs/specs/spec-06-hexa.md`, `src/py/onto/integrations/hexa/`,
`TODO.md` at `da01e2c` ("Steps 4–6 progress", "Integration deviation review")
