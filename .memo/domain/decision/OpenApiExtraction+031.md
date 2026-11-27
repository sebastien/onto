---
identity: "onto:decision:openapi-extraction"
created: 2026-11-27T04:07:57.038951+00:00
updated: 2026-11-27T04:07:57.865202+00:00
code: DEC0031
title: Extraction from OpenAPI descriptions
status: proposed
date: 2026-11-27
---
# Extraction from OpenAPI descriptions

**Status**: proposed (not decided). **Date**: 2026-11-27.

**Context**: spec-04 expects extraction to derive a source ontology, an
inventory and a default binding from the best evidence available, an OpenAPI
or JSON Schema description first ("Inventories", "Default bindings"), but
`onto inventory` reads sample documents only. adviceos-data derives its
`AdviceLink` source ontology from the CRM's two OpenAPI descriptions with a job
of its own (`jobs/advicelink-api-review-projection.py`). The job also writes the
identity sidecar (`AdviceLink.ids`) from each schema's own identifiers (the
Java class), so that `onto diff` reports a renamed element as a rename
(`Snippet/com_advicelink_crm_snippet_model_Snippet_SnippetKey` to
`Snippet/SnippetKey`), not a removal and an addition. Another job derives each
binding's inventory (`jobs/advicelink-bindings-author.py refresh-inventories`).

**Proposal**: extraction in onto from an OpenAPI or JSON Schema description: a
source ontology, an inventory per response schema, and the `.ids` sidecar from
the schema's identifiers. Not designed yet.

**Alternatives**: extraction in host jobs, as now.

**Open questions**: adviceos-data deferred this (2026-11-18) until a second
OpenAPI source appears: with one source, generic rules would be that API's
rules relabelled. Which naming and identifier rules generalise; how a curated
ontology and a regenerated projection coexist (adviceos-data stages the
projection and applies its diff by review, so that hand annotations survive).

Related: [domain/component:Cli] [domain/component:Declarations]

Sources: `docs/specs/spec-04-mapping.md#inventories`,
`docs/specs/spec-04-mapping.md#default-bindings`; adviceos-data `TODO_ONTO.md`
at `4035dc3` ("No extraction from OpenAPI"),
`jobs/advicelink-api-review-projection.py`
