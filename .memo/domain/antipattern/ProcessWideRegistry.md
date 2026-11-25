---
identity: "onto:antipattern:process-wide-registry"
created: 2026-11-25T19:44:11.931263+00:00
updated: 2026-11-25T19:44:27.208958+00:00
title: Process-wide registries for compiled programs
---
# Process-wide registries for compiled programs

**Approach**: register what a compiled program uses (its functions, stages,
names) in tables shared by the whole process.

**Failure mode**: a program's behaviour depends on what else the process
compiled, and when. In the hexa integration, a mutable dispatch table mapped
each function name to an implementation: two programs compiled with different
implementations of one function both ran the most recently compiled one. The
same function used as a transform and as a codec collided in hexa's registry,
and hexa's process-wide stage and namespace names made two programs with the
same scope types, or a recompile, clash. Tests that compile one program at a
time do not notice.

**Instead**: keep compiled state program-local. Only generic prototypes are
registered; each compiled transform or codec is a program-local copy carrying
its own evaluator and canonical shape, and stages live in a frozen,
program-local `StageNamespace` that names them for traces without registering
them. Compiling the same inputs twice gives programs with equal hexa
encodings. Regressions in `tests/T06-001-hexa-binding-read.py` compile
competing programs and run the older one.

Related: [domain/component:HexaIntegration], [domain/decision:HexaExecution+008]

Sources: `docs/specs/spec-06-hexa.md#binding-and-mapping-operators`,
`src/py/onto/integrations/hexa/vocabulary.py`, `TODO.md` at `da01e2c`
("Integration deviation review")
