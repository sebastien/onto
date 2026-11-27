/** Module: store-http — an observation store served over HTTP (spec-08 "Protocol") and read through its client. */

import { beforeAll, expect, test } from "bun:test";
import { storeClient } from "../../src/js/onto/store/client.js";
import { Forbidden, StoreError } from "../../src/js/onto/store/errors.js";
import { storeHandler } from "../../src/js/onto/store/http.js";
import { ObservationStore } from "../../src/js/onto/store/store.js";
import { sqlite } from "./sqlite.js";

const PARTITION = "Client/Person_U1";
let BUNDLE, BATCH;

beforeAll(() => {
	// NOTE: The store bundle and batch of the Python store tests (tests/store.py).
	const script = "import json; from tests.store import BUNDLE, EXAMPLE_BATCH; print(json.dumps({'bundle': BUNDLE, 'batch': EXAMPLE_BATCH}))";
	const run = Bun.spawnSync(["uv", "run", "--quiet", "python", "-c", script], { stderr: "pipe" });
	if (run.exitCode !== 0) throw new Error(run.stderr.toString());
	({ bundle: BUNDLE, batch: BATCH } = JSON.parse(run.stdout.toString()));
});

/** A store authorizing `Bearer <principal>` in its scope, denying `user:other`, and its client over its handler. */
function served({ origins = [], prefix, base = "http://localhost/", headers = { Authorization: "Bearer user:adviser" } } = {}) {
	const store = new ObservationStore(BUNDLE, {
		storageFor: () => sqlite(),
		clock: () => Date.parse("2026-11-26T09:30:00Z"),
		authorize: request => {
			const principal = request.headers.get("authorization")?.replace(/^Bearer /, "");
			if (!principal) return null;
			if (principal === "user:other") throw new Forbidden("not your client");
			return { scope: "adviser-app", principal };
		},
	});
	const handler = storeHandler(store, { origins, prefix });
	const fetch = (url, init) => handler.fetch(new Request(url, init));
	return { handler, client: storeClient({ base, fetch, init: { headers } }) };
}

const append = (client, requestId = "r1", extra = {}) => client.append(PARTITION, { requestId, observations: BATCH, ...extra });

test("a batch appended over HTTP is read back as state, log and batch reads", async () => {
	const { client } = served();
	const appended = await append(client);
	expect(appended).toMatchObject({ partition: PARTITION, from: 1, head: 8, recorded: "2026-11-26T09:30:00.000Z" });
	const state = await client.state(PARTITION, { select: [{ s: "IdentityCheck_C41", slots: ["Confirmed"] }] });
	expect(state.observations.claims.map(claim => [claim.p ?? "exists", claim.v ?? null])).toEqual([["exists", null], ["Confirmed", true]]);
	const log = await client.log(PARTITION, { after: 6 });
	expect([log.through, log.hasMore, log.entries.map(entry => entry.seq)]).toEqual([8, false, [7, 8]]);
	const many = await client.stateMany({ reads: [{ partition: PARTITION, select: [{ population: "checks" }] }, { partition: "Client/Person_U2" }] });
	expect(many.results.map(result => result.status ?? 200)).toEqual([200, 404]);
});

test("a retried append is answered once, and a request ID reused for another batch is refused", async () => {
	const { client } = served();
	const first = await append(client);
	expect(await append(client)).toEqual(first);
	await expect(append(client, "r1", { expect: [{ s: "IdentityCheck_C41", exists: true, version: 0 }] })).rejects.toMatchObject({ status: 409, error: "request_reused" });
});

test("refusals keep their status, code and details", async () => {
	const { client } = served();
	await append(client);
	const moved = await append(client, "r2", { expect: [{ s: "IdentityCheck_C41", p: "Method", version: 0 }] }).catch(error => error);
	expect(moved).toBeInstanceOf(StoreError);
	expect([moved.status, moved.error, moved.details.versions]).toEqual([409, "precondition", [{ s: "IdentityCheck_C41", p: "Method", version: 4 }]]);
	const wrong = structuredClone(BATCH);
	wrong.claims[3].v = "Telepathy";
	await expect(client.append(PARTITION, { requestId: "r3", observations: wrong })).rejects.toMatchObject({ status: 400, error: "invalid", details: { check: "value", n: 4 } });
	await expect(client.state("Nowhere/X")).rejects.toMatchObject({ status: 400, details: { check: "partition" } });
	await expect(served({ headers: {} }).client.state(PARTITION)).rejects.toMatchObject({ status: 401, error: "unauthorized" });
	await expect(served({ headers: { Authorization: "Bearer user:other" } }).client.state(PARTITION)).rejects.toMatchObject({ status: 403, error: "forbidden" });
});

test("the handler refuses what is not its protocol", async () => {
	const { handler } = served();
	const status = async (url, init = {}) => {
		const response = await handler.fetch(new Request(url, init));
		return [response.status, (await response.json()).error];
	};
	expect(await status("http://store.example/v1/state", { method: "POST" })).toEqual([400, "https_required"]);
	expect(await status("http://localhost/v1/elsewhere")).toEqual([404, "not_found"]);
	expect(await status(`http://localhost/v1/partitions/${encodeURIComponent(PARTITION)}/log`, { method: "POST" })).toEqual([405, "method_not_allowed"]);
	expect(await status(`http://localhost/v1/partitions/${encodeURIComponent(PARTITION)}/state`, { method: "POST", body: "{", headers: { "Content-Type": "application/json" } }))
		.toEqual([400, "invalid"]);
	expect(await status(`http://localhost/v1/partitions/${encodeURIComponent(PARTITION)}/log?after=x`)).toEqual([400, "invalid"]);
	const large = "x".repeat(BUNDLE.limits.requestBytes + 1);
	expect(await status("http://localhost/v1/state", { method: "POST", body: large, headers: { "Content-Type": "application/json" } })).toEqual([413, "too_large"]);
});

test("a store served under a path prefix answers there, and only there", async () => {
	const { handler, client } = served({ prefix: "/api/store/", base: "http://localhost/api/store" });
	expect(await append(client)).toMatchObject({ partition: PARTITION, from: 1 });
	expect((await client.log(PARTITION)).entries).toHaveLength(8);
	const status = async url => (await handler.fetch(new Request(url, { method: "POST" }))).status;
	expect([await status("http://localhost/v1/state"), await status("http://localhost/api/storev1/state")]).toEqual([404, 404]);
});

test("browsers of listed origins may call it, others may not", async () => {
	const { handler } = served({ origins: ["https://app.example"] });
	const preflight = await handler.fetch(new Request("http://localhost/v1/state", { method: "OPTIONS", headers: { Origin: "https://app.example" } }));
	expect([preflight.status, preflight.headers.get("access-control-allow-origin")]).toEqual([204, "https://app.example"]);
	const other = await handler.fetch(new Request("http://localhost/v1/state", { method: "OPTIONS", headers: { Origin: "https://evil.example" } }));
	expect([other.status, (await other.json()).error]).toEqual([403, "origin_forbidden"]);
});

// EOF
