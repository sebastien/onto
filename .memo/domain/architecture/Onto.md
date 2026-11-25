---
identity: "onto:architecture"
created: 2026-11-25T19:44:09.710488+00:00
updated: 2026-11-25T19:44:24.829295+00:00
title: onto architecture
---
# onto architecture

onto is a family of text formats, each with a lossless JSON form, and a Python
library that parses, checks, prints, converts and analyses them. A CLI sits on
top; execution is an optional integration with hexa, and a JavaScript runtime
executes what Python compiles. The specifications define the formats; the
library implements them feature by feature.

## Structure

- *Core* (`src/py/onto/`): one package per format, each following
  [domain/pattern:FeaturePackage], and shared modules at the root: `text.py`
  (lexical rules, `Source`, `Diagnostic`, `FormatError`), `expressions.py`,
  `conditions.py`, `coverage.py` and `meta.py`. Standard library only, Python
  3.14 or later. Components: [domain/component:Ontology],
  [domain/component:Observations], [domain/component:Functions] and
  [domain/component:Declarations].
- *Integrations* (`src/py/onto/integrations/`): optional, each importing its
  library only when it is itself imported. The only one is
  [domain/component:HexaIntegration], which executes bindings, mappings and
  rooted views as hexa programs ([domain/decision:HexaExecution+008]).
- *CLI* ([domain/component:Cli]): indexes the workspace and runs one command per
  task; it adds no format semantics of its own.
- *JavaScript runtime* ([domain/component:JsRuntime]): executes bundles that
  Python compiles; it neither parses nor compiles.
- *Schemas* (`src/json/`): the contracts of the JSON forms, checked by the tests.

## Dependency direction

- Core never imports an integration: `import onto` works without hexa.
- The hexa integration uses hexa's public API only. hexa knows nothing of onto
  and is never patched; what onto needed from it was added as generic
  constructs, or adapted on onto's side ([domain/decision:IndexStepsAsTuples+017]).
- Executors read parsed models (or their JSON); they never parse text.
- Loading declarations never runs implementation code: libraries, bindings and
  mappings are checked statically, and execution is a separate, explicit step.
- An ontology never depends on a function library: rule checks run from the
  library, which already depends on the ontology's types.

## Flows

- *Formats*: text or JSON → parse → resolve and validate against the
  ontologies in context → model → canonical text or JSON. Every format has a
  normal form, and text and JSON convert losslessly.
- *Data*: documents → binding run → source observations → import mapping
  (a referential gives handles) → observations of the curated ontology →
  reconciliation → state → projection mapping → binding write → documents.
  Re-running retracts what is no longer produced, behind safeguards
  ([domain/decision:RunSemantics+001]).
- *Views*: a rooted view plans the reads that can prove its facts, performs
  them as one hexa run and returns observations
  ([domain/component:HexaIntegration]).
- *Static analysis*: checking, coverage, reversal and semantic diff need no
  data and no running system.

## Related projects

- hexa (`../hexa`): the shape-pipeline engine the integration compiles to.
- adviceos-data: the main consumer; most features recorded from 2026-11-16
  onwards were found mapping its CRM data to the AdviceOS ontology.
- Read-only sources: the original reference implementation and a
  stock-exchange model used as domain inspiration. Examples stay generic.

Sources: `docs/doc-overview.md`, `docs/specs/spec-06-hexa.md#integration`,
`docs/specs/spec-07-cli.md#implementation`, `TODO.md` at `da01e2c`
