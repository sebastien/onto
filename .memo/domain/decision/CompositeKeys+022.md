---
identity: "onto:decision:composite-keys"
created: 2026-11-25T19:44:16.099091+00:00
updated: 2026-11-25T19:44:36.748491+00:00
title: "Composite keys: handles derived from several attributes"
status: proposed
date: 2026-11-25
code: DEC0022
---
# Composite keys: handles derived from several attributes

**Status**: proposed (not decided). **Date**: 2026-11-25.

**Context**: in spec-05, `key=A,B` is a primary key `A` with an alternate key
`B`; no policy derives a handle from several attributes together, and spec-06
lists composite keys as deferred. adviceos-data needs one for numbers unique
only within a scope: a company number within its country's register, a policy
or loan number within its provider (`AdviceOSIds`).

**Proposal**: not designed yet. A key read through a reference (the provider)
also meets `Mapping.KeyReference`, so the design must say how a referenced
instance's key enters a handle.

**Open questions**, noted while migrating these notes (2026-11-26): the policy
syntax, since `key=A,B` already means an alternate key; the handle encoding;
how composite keys interact with alternate keys and the registry.

Related: [domain/decision:ReferentialIdentities+002]

Sources: `docs/specs/spec-05-identities.md#referentials`,
`docs/specs/spec-06-hexa.md#deferred`, `TODO.md` at `da01e2c` ("Conditions,
unset values and set-valued maps", open items)
