/**
 * Module: workers-smoke — the observation store in the Workers runtime: SQLite Durable Objects, one per partition and
 * one per scope for its change feed and indexes, behind the Worker, read through the store's client (spec-08
 * "Implementations").
 *
 * Optional: it needs Miniflare 4 and esbuild, installed outside the repository, on NODE_PATH:
 *
 *	NODE_PATH=/path/to/node_modules make test-workers
 *
 * The Worker's compatibility date is one Miniflare 4's runtime supports.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { storeClient } from "../../src/js/onto/store/client.js";

const require = createRequire(import.meta.url);
const { build } = require("esbuild");
const { Miniflare } = require("miniflare");

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const ADAPTER = join(ROOT, "src/js/onto/store/server/cloudflare.js");
const PARTITION = "Client/Person_U1";

// NOTE: The store bundle and batch of the Python store tests (tests/store.py).
const script = "import json; from tests.store import BUNDLE, EXAMPLE_BATCH; print(json.dumps({'bundle': BUNDLE, 'batch': EXAMPLE_BATCH}))";
const { bundle, batch } = JSON.parse(execFileSync("uv", ["run", "--quiet", "python", "-c", script], { cwd: ROOT, maxBuffer: 1 << 26 }).toString());

const directory = mkdtempSync(join(tmpdir(), "onto-store-workers-"));
let runtime;

/**
 * The store's Worker in Miniflare, its objects persisted in `directory`. With `dropAlarms`, partitions drop their
 * alarms, as Cloudflare does once an alarm's retries run out.
 */
async function start({ dropAlarms = false } = {}) {
	const name = dropAlarms ? "dropping.mjs" : "worker.mjs";
	await build({
		stdin: { contents: `
			import { cloudflareStore } from ${JSON.stringify(ADAPTER)};
			import { Forbidden } from ${JSON.stringify(join(dirname(ADAPTER), "../errors.js"))};
			const store = cloudflareStore({ bundle: ${JSON.stringify(bundle)} });
			export const { ScopeObject } = store;
			export const PartitionObject = ${dropAlarms ? "class extends store.PartitionObject { async alarm() {} }" : "store.PartitionObject"};
			export default store.worker({ authorize: (request) => {
				const principal = request.headers.get("authorization");
				if (!principal) return null;
				if (principal === "user:other") throw new Forbidden("not your client");
				return { scope: "adviser-app", principal };
			}, authorizeServer: (request) => request.headers.get("authorization") === "server:app" ? { scope: "adviser-app", principal: "server:app" } : null });
		`, resolveDir: ROOT },
		outfile: join(directory, name), bundle: true, format: "esm", platform: "browser", external: ["cloudflare:workers"],
	});
	return new Miniflare({
		modules: true, modulesRoot: directory, scriptPath: join(directory, name), compatibilityDate: "2026-06-01",
		durableObjectsPersist: join(directory, "objects"),
		durableObjects: { PARTITIONS: { className: "PartitionObject", useSQLite: true }, SCOPES: { className: "ScopeObject", useSQLite: true } },
	});
}

/** The change feed, once it has `count` entries or after five seconds. */
async function feedOf(server, count) {
	let feed;
	for (let attempt = 0; attempt < 50 && (feed?.entries.length ?? -1) < count; attempt++) {
		await new Promise(resolve => setTimeout(resolve, 100));
		feed = await server.changes();
	}
	return feed;
}

try {
	runtime = await start();
	const client = (principal = "user:adviser") => storeClient({
		base: "https://store.example", fetch: (url, init) => runtime.dispatchFetch(url, init), init: { headers: { authorization: principal } },
	});
	const store = client();
	const appended = await store.append(PARTITION, { requestId: "r1", observations: batch });
	assert.deepEqual([appended.from, appended.head], [1, 8]);
	assert.deepEqual(await store.append(PARTITION, { requestId: "r1", observations: batch }), appended, "a retry is answered as the first append");
	const state = await store.state(PARTITION, { select: [{ population: "checks" }] });
	assert.deepEqual(Object.keys(state.observations.instances).sort(), ["Document_D9", "IdentityCheck_C41", "Person_U1"]);
	const log = await store.log(PARTITION, { after: 7 });
	assert.deepEqual(log.entries.map(entry => entry.seq), [8]);
	const many = await store.stateMany({ reads: [{ partition: PARTITION }, { partition: "Client/Person_U2" }] });
	assert.deepEqual(many.results.map(result => result.status ?? 200), [200, 404], "partitions are separate objects");
	await assert.rejects(store.append(PARTITION, { requestId: "r2", observations: batch, expect: [{ s: "IdentityCheck_C41", p: "Method", version: 0 }] }),
		error => error.status === 409 && error.error === "precondition" && error.details.versions[0].version === 4);
	await assert.rejects(client("user:other").state(PARTITION), error => error.status === 403);
	await assert.rejects(client("").state(PARTITION), error => error.status === 401);
	// NOTE: The partition's alarm reports its change to the scope's object, after the append answered.
	const server = client("server:app");
	const feed = await feedOf(server, 1);
	assert.deepEqual(feed.entries.map(entry => [entry.partition, entry.head]), [[PARTITION, 8]]);
	const found = await server.indexQuery("ClientChecks", { filter: { eq: ["checks.Confirmed", true] } });
	assert.deepEqual(found.partitions, [{ partition: PARTITION, anchor: "Person_U1", state: "active" }]);
	await assert.rejects(store.indexQuery("ClientChecks", { filter: { exists: "checks.Method" } }), error => error.status === 401);
	// A partition whose alarm was dropped reports its change when it is next called: here, read.
	await runtime.dispose();
	runtime = await start({ dropAlarms: true });
	await client().append("Client/Person_U2", { requestId: "r3", observations: JSON.parse(JSON.stringify(batch).replaceAll("Person_U1", "Person_U2")) });
	await new Promise(resolve => setTimeout(resolve, 300));
	assert.deepEqual((await client("server:app").changes()).entries.length, 1, "the dropped alarm reported nothing");
	await runtime.dispose();
	runtime = await start();
	assert.deepEqual((await client("server:app").changes()).entries.length, 1, "nor did restarting the objects");
	await client().state("Client/Person_U2");
	const healed = await feedOf(client("server:app"), 2);
	assert.deepEqual(healed.entries.map(entry => entry.partition).sort(), [PARTITION, "Client/Person_U2"]);
	await client().state(PARTITION);
	await new Promise(resolve => setTimeout(resolve, 300));
	assert.deepEqual((await client("server:app").changes()).entries, healed.entries, "a partition reports nothing it reported already");
	console.log("Workers smoke passed: appends, retries, state, log and batch reads, preconditions, refusals, and the change feed and indexes over SQLite Durable Objects, with dropped reports made again");
} finally {
	await runtime?.dispose();
	rmSync(directory, { recursive: true });
}

// EOF
