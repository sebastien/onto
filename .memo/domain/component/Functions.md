---
identity: "onto:component:functions"
created: 2026-11-25T19:44:10.261787+00:00
updated: 2026-11-25T19:44:25.406554+00:00
title: Functions component
---
# Functions component

**Owns** function libraries (`.fn`, spec-04 Functions): their declarations,
the built-in functions, pure execution with exact decimals, and conformance
runs of every example and inverse.

- *Package*: `src/py/onto/functions/` (`model.py`, `parser.py`,
  `formatter.py`, `operations.py`) and `runtime.py` (application, built-ins,
  conformance).
- *Interfaces*: `parseFunctions`, `resolveFunctions`, `loadFunctions`,
  `printFunctions`, `formatFunctions`, `functionsToJson`, `functionsFromJson`,
  `FunctionEvaluator`, `FunctionResult` and `Operator` (`FunctionsOperator`,
  holding the ontologies the signatures use), with `.evaluator(...)` and
  `.conformance(library, implementations)`. The CLI runs conformance as
  `onto fn test`.
- *Declarations*: signatures resolve against loaded ontologies and use
  concrete types ([domain/decision:ConcreteSignatures+009]); examples are read
  with the observations value encoding.
- *Execution*: libraries register implementations by full path, local
  functions by name. `evaluate` returns one `FunctionResult` per application
  (one per Cartesian combination over collection arguments), failures
  included ([domain/decision:FunctionSemantics+010]). A domain exception, an
  invalid result or a missing map entry is a gap with a reason; an unresolved
  name, a wrong arity or a missing implementation is a configuration error.
- *Boundaries*: loading a library never executes implementation code.
  `evaluate` does not assemble claims or merge fan-out: that belongs to the
  binding and mapping executors ([domain/component:HexaIntegration]). `ref`
  returns a gap here, since it needs a binding's context. Arithmetic follows
  [domain/pattern:ExactValues].

Sources: `docs/specs/spec-04-mapping.md#functions`, `src/py/onto/functions/`,
`TODO.md` at `da01e2c` ("Spec-04 implementation progress")
