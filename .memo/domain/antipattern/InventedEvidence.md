---
identity: "onto:antipattern:invented-evidence"
created: 2026-11-25T19:44:12.135081+00:00
updated: 2026-11-25T19:44:27.398684+00:00
title: Invented evidence
---
# Invented evidence

**Approach**: fill a hole in the data with a claim nobody made, to make a
result complete or printable: `[]` when the last member of a collection is
withdrawn, an existence or facet claim to carry a type, an aggregate claim
merging a slot, a "missing" coverage row for a deleted or aliased handle, a
target instance for a reference that has no correspondence.

**Failure mode**: observations are evidence with provenance. An invented claim
asserts what no source said: `[]` claims confirmed absence and can contradict a
`+` cardinality; a synthetic existence claim makes an implicit instance look
delivered. Downstream it cannot be told from real evidence, and it outlives
the reason it was made.

**Instead**: keep the claims that were made, and put the rest in reports, not
in data. Withdrawing the last member withdraws its claim, so an earlier
producer's evidence can show again; types without claims go in the registry
(`@type`); order-sensitive slots keep each claim rather than an aggregate;
unmapped references are gaps; implicit instances stay implicit until a source
states them; coverage reports what is missing without adding claims.

Related: [domain/decision:TypeOnlyDeclarations+007],
[domain/decision:CollectionLogOrder+006]

Sources: `docs/specs/spec-02-observations.md#normal-forms`, `TODO.md` at
`da01e2c` ("View coverage implemented", "Conformance audit", "Contextual
mappings implemented")
