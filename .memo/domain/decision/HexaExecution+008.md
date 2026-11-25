---
identity: "onto:decision:hexa-execution"
created: 2026-11-25T19:44:13.576666+00:00
updated: 2026-11-25T19:44:33.706073+00:00
title: "Bindings and mappings run as hexa programs, through an optional integration"
status: accepted
date: 2026-11-12
code: DEC0008
---
# Bindings and mappings run as hexa programs, through an optional integration

**Status**: accepted. **Date**: 2026-11-12 (spec-06, commit `f259a83`).

**Context**: spec-04 defines what bindings and mappings mean, not how they run.
Running them needs retrieval, effects, a journal with replay, failure policies
and a run ledger, the same in Python and JavaScript.

**Decision**:
- Bindings and mappings compile into hexa shapes, selectors, templates, codecs
  and stages, in an optional integration (`src/py/onto/integrations/hexa/`).
- hexa stays domain-free: onto depends on hexa, never the reverse. What onto
  needed was added to hexa as generic constructs: nested slot namespaces,
  collection captures, evidence and `format(value, original)`, parameterised
  codecs, examples, `transform` declarations, nested derivations, enclosing
  capture blocks, holes, `tolerant`, `gather`, `parsed`, origins.
- A mapping's metadata is a table outside the templates, keyed by tree pointer
  and computed by onto; conflicts fan out through variant projections.
- Deferred then: contextual mappings (implemented on 2026-11-16) and
  registry-backed identities (still open).
- Writing compiles reverse mappings as ordinary mappings, through
  `mappingReverse` in core.

**Alternatives**: not recorded.

**Rationale**, from spec-06: spec-04 says what the formats mean and spec-06
gives one way to execute them; hexa then provides retrieval, effects, the
journal and replay, failure policies and the run ledger, identically in its
Python and JavaScript bindings.

**Consequences**: core never imports hexa, and the integration never patches
it. Where hexa's behaviour did not fit, the integration adapted on its side,
as spec-06 now documents ([domain/component:HexaIntegration],
[domain/antipattern:ProcessWideRegistry],
[domain/decision:IndexStepsAsTuples+017]). The JavaScript runtime came from
the same choice ([domain/component:JsRuntime]).

Sources: `docs/specs/spec-06-hexa.md`, `TODO.md` at `da01e2c` ("hexa
integration (2026-11-12)", "Steps 4–6 progress", "Integration deviation
review")
