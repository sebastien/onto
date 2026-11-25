---
identity: "onto:decision:source-qualified-handles"
created: 2026-11-25T19:44:15.552536+00:00
updated: 2026-11-25T19:44:36.063385+00:00
title: Source-qualified handles include the source type
status: accepted
date: 2026-11-17
code: DEC0019
---
# Source-qualified handles include the source type

**Status**: accepted (approved by the user). **Date**: 2026-11-17.

**Context**: without a referential policy, a target handle was `<T>_` followed
by the encoding of `<scope>/<key>`. Two source types mapped to one target type
(a CRM client and a CRM user with the same id) then produced one handle,
merging unrelated records.

**Decision**: the encoded part is `<scope>/<S>/<key>`, with `S` the last
segment of the source type: `Person_Crm_2FClient_2F9` for `Client_9`.

**Alternatives**: the earlier `<scope>/<key>`.

**Rationale**: source-qualified handles exist so that records never merge by
accident; only an identity link may join them.

**Consequences**: specs 04, 05 and 06 and the handle assertions of the mapping
tests were updated. Named scopes later added their name
(`<scope>/@<name>/<S>/<key>`), and records without a key keep source-qualified
handles too (spec-05 "Producing handles", step 4).

Related: [domain/decision:ReferentialIdentities+002],
[domain/decision:TypedCorrespondence+018]

Sources: `docs/specs/spec-04-mapping.md#instances`,
`docs/specs/spec-05-identities.md#handles`, `TODO.md` at `da01e2c`
("Type-directed instance correspondence", "Write-back safety, exclusive lines
and named bindings")
