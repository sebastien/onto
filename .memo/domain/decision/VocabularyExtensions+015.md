---
identity: "onto:decision:vocabulary-extensions"
created: 2026-11-25T19:44:14.832737+00:00
updated: 2026-11-25T19:44:35.172109+00:00
title: Vocabulary extensions are vocabularies of the contributing domain
status: accepted
date: 2026-11-16
code: DEC0015
---
# Vocabulary extensions are vocabularies of the contributing domain

**Status**: accepted. **Date**: 2026-11-16 (modeling gap 5; commit `94c90aa`).

**Context**: a later domain could not add values to an earlier domain's
vocabulary (rule 2.7). Workarounds renamed generic values, put country names
in comments, or mapped a country vocabulary onto the generic one.

**Decision**: the values are declared as a vocabulary of the contributing
domain, naming the one it extends:
`Nz/IncomeMeasure = Paye|Esct {extends=Finance/Income/Measure}`. Only open
vocabularies can be extended; the extension is closed and not itself
extended; its values must be new; children may go under existing values,
repeating their ancestors; `{ordered}` vocabularies append. Text and JSON keep
the extension as written; the merge is a reading of the ontology.

**Alternatives**: the proposed `Finance/Income/Measure += Paye|Esct`, written
in a later domain's file.

**Rationale**: `+=` had no place to record the contributing domain, since
files are not tied to domains. A vocabulary of its own belongs to its domain,
and `extends` is a reference that layering checks.

**Consequences**: `onto meta` adds `Meta/Dimension -extends->` links.

Sources: `docs/specs/spec-01-ontology.md#extensions`, `TODO.md` at `da01e2c`
("Modeling gaps", 5)
