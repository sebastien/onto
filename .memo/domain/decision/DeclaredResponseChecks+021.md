---
identity: "onto:decision:declared-response-checks"
created: 2026-11-25T19:44:15.920173+00:00
updated: 2026-11-25T19:44:36.546429+00:00
title: Declared response checks for view reads
status: proposed
date: 2026-11-25
code: DEC0021
---
# Declared response checks for view reads

**Status**: proposed (not decided). **Date**: 2026-11-25.

**Context**: a view read with a request template is a `RequestSend` effect,
deduplicated within the run. The host's optional
`check(step, value, response)` verifies a response: that it is the record
asked for, the rows the view admits, the collections and keys it shows empty.
adviceos-data implements the same checks twice, in Python (`recorded.py`) and
JavaScript (`advicelink.js`); its recorded next step was to move its catalogue
to request templates and its checks to `check`.

**Proposal**: declare the common checks (the record is the one asked for,
deleted rows, empty collections), so that hosts need no code but their
credentials.

**Alternatives**: keep checks in host code, as now.

**Open questions**: the form and place of the declarations; not designed yet.
`rootHandle` stays a host hook regardless: a target handle may depend on more
than the source key.

Related: [domain/component:HexaIntegration], [domain/component:JsRuntime]

Sources: `docs/specs/spec-06-hexa.md#rooted-retrieval`, `TODO.md` at
`da01e2c` ("Later work", Views; "Conditions, unset values and set-valued
maps", open items)
