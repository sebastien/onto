---
identity: "onto:decision:read-gap-detail"
created: 2026-11-25T19:44:15.732435+00:00
updated: 2026-11-25T19:44:36.305918+00:00
title: "A view report's read gap keeps the error's message"
status: accepted
date: 2026-11-25
code: DEC0020
---
# A view report's read gap keeps the error's message

**Status**: accepted. **Date**: 2026-11-25.

**Context**: a view report describes an unavailable read as a gap. The error's
message had been left to the run's journal, because it may quote the source.

**Decision**: the gap is `{step, input, reason, detail}` again, `detail` being
the error's message (a hexa failure's cause, as the journal spells it), absent
when there is none; in Python and JavaScript alike (`readDetail`).

**Alternatives**: the message in the journal only, the previous choice.

**Rationale**: resolving a failure needs the message; the journal is internal,
while the report is for the host that made the read.

**Consequences**: a report may quote the source, so it is for the host that
made the read. The JavaScript conformance replay over HTTP compares reports
without these messages, because a failed request's message names the server
that answered it.

Sources: `docs/specs/spec-06-hexa.md#rooted-retrieval`, `TODO.md` at
`da01e2c` ("Read gaps keep the error's message")
