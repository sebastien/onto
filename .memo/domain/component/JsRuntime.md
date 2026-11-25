---
identity: "onto:component:js-runtime"
created: 2026-11-25T19:44:10.787977+00:00
updated: 2026-11-25T19:44:25.983695+00:00
title: JavaScript runtime component
---
# JavaScript runtime component

**Owns** executing, outside Python, what Python compiles: binding and mapping
programs and rooted views loaded from a bundle (`onto.view-bundle/1`), on hexa's
JavaScript binding, in browsers, Node and Bun.

- *Package*: `src/js/onto/`; spec-06 "Bundles and the JavaScript runtime" lists
  its modules (views, requests, stages, binding, mapping, observations, print,
  vocabulary, functions, types, model, program, values).
- *Interfaces*: `ViewOperator(bundle, {access, implementations, operations})`
  with `plan`, `report`, `retrieve` and `runReads`; `loadBindingProgram` and
  `loadMappingProgram` for single exported programs. Hosts supply library
  function implementations and, in a browser, an `http` operation with the
  user's credentials.
- *Guarantee*: the same claims, gaps, reports and `.obs` text as Python, on the
  same inputs; reads are the same effects, so a journal recorded in either
  language replays in the other.
- *Boundaries*: no parsing or compiling, no writing documents, no re-running
  with approval, no format learning; a binding run omits the inventory `fields`
  and learned writing formats. Logs are not re-validated through text, since
  Python checks the same programs on the same inputs.
- *Verification*: `make test-js` records every run, plan, report and retrieval
  the Python suite makes and replays them here
  ([domain/pattern:SpecExamplesAsTests]). Features the Python tests do not
  exercise in a run are unverified.

Sources: `docs/specs/spec-06-hexa.md#bundles-and-the-javascript-runtime`,
`src/js/onto/`, `tests/conformance.py`, `tests/js/`
