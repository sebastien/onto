/**
 * Module: workers-smoke — the observation store in the Workers runtime: SQLite Durable Objects, one per partition,
 * behind the Worker, read through the store's client (spec-08 "Implementations").
 *
 * Optional: it needs miniflare and esbuild, installed outside the repository, on NODE_PATH:
 *
 *	NODE_PATH=../../AdviceLink/advicelink-mcp/node_modules node tests/js/workers-smoke.mjs   # miniflare 4
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
try {
	await build({
		stdin: { contents: `
			import { cloudflareStore } from ${JSON.stringify(ADAPTER)};
			import { Forbidden } from ${JSON.stringify(join(dirname(ADAPTER), "../errors.js"))};
			const store = cloudflareStore({ bundle: ${JSON.stringify(bundle)} });
			export const { PartitionObject } = store;
			export default store.worker({ authorize: (request) => {
				const principal = request.headers.get("authorization");
				if (!principal) return null;
				if (principal === "user:other") throw new Forbidden("not your client");
				return { scope: "adviser-app", principal };
			} });
		`, resolveDir: ROOT },
		outfile: join(directory, "worker.mjs"), bundle: true, format: "esm", platform: "browser", external: ["cloudflare:workers"],
	});
	runtime = new Miniflare({
		modules: true, modulesRoot: directory, scriptPath: join(directory, "worker.mjs"), compatibilityDate: "2026-06-01",
		durableObjects: { PARTITIONS: { className: "PartitionObject", useSQLite: true } },
	});
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
	console.log("Workers smoke passed: appends, retries, state, log and batch reads, preconditions and refusals over SQLite Durable Objects");
} finally {
	await runtime?.dispose();
	rmSync(directory, { recursive: true });
}

// EOF
