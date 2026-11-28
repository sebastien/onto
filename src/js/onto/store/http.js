/**
 * Module: store/http — an observation store's HTTP protocol (spec-08 "Protocol"): JSON over HTTPS, as Storelight's
 * server answers it. It runs wherever `fetch` handlers do: a Worker, Bun or Node.
 *
 * The store authorizes every request with its callback, which receives the HTTP request; the handler grants nothing
 * itself. Cross-origin callers need their origin listed; same-origin callers need no CORS.
 */

import { StoreError } from "./errors.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const RE_PARTITION = /^\/v1\/partitions\/([^/]+)\/(statements|state|log)$/;
const RE_INDEX = /^\/v1\/indexes\/([^/]+)\/query$/;
const RE_CURSOR = /^(0|[1-9][0-9]*)$/;
const LOCAL = ["localhost", "127.0.0.1", "[::1]"];

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

function fail(status, error, message, details = {}) {
	throw new StoreError(status, error, message, details);
}

/** A JSON answer, never cached. */
function answer(body, status, headers) {
	return new Response(JSON.stringify(body), { status, headers: { ...headers, "Content-Type": "application/json", "Cache-Control": "no-store" } });
}

/** A request's JSON body, refused beyond `limit` bytes before it is parsed. */
async function readJson(request, limit) {
	if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json")
		fail(400, "invalid", "Expected application/json", { check: "request" });
	const declared = Number(request.headers.get("content-length") ?? NaN);
	if (declared > limit) fail(413, "too_large", "The request is larger than the store accepts");
	const bytes = new Uint8Array(await request.arrayBuffer());
	if (bytes.length > limit) fail(413, "too_large", "The request is larger than the store accepts");
	try {
		return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
	} catch {
		fail(400, "invalid", "The request body is not JSON", { check: "request" });
	}
}

/** One integer query parameter, or `fallback` when absent. */
function integer(url, name, fallback) {
	const values = url.searchParams.getAll(name);
	if (!values.length) return fallback;
	if (values.length > 1 || !RE_CURSOR.test(values[0])) fail(400, "invalid", `Expected one integer ${name}`, { check: "cursor" });
	return Number(values[0]);
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

/**
 * A `fetch` handler serving `store` (an `ObservationStore`): appends, state and log reads, and batch reads. `origins`
 * lists the origins allowed to call it from a browser; `prefix` is the path it serves the protocol under, as
 * `/api/store` for `/api/store/v1/state`.
 */
export function storeHandler(store, { origins = [], prefix = "" } = {}) {
	const allowed = new Set(origins), limit = store.bundle.limits.requestBytes, root = prefix.replace(/\/+$/, "");
	return {
		async fetch(request) {
			let headers = {};
			try {
				const url = new URL(request.url);
				if (url.protocol !== "https:" && !(url.protocol === "http:" && LOCAL.includes(url.hostname))) fail(400, "https_required", "HTTPS is required");
				const origin = request.headers.get("origin");
				if (origin && origin !== url.origin) {
					if (!allowed.has(origin)) fail(403, "origin_forbidden", "Origin is not allowed");
					headers = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true", Vary: "Origin" };
				}
				const path = url.pathname.startsWith(`${root}/`) ? url.pathname.slice(root.length) : null;
				const match = path && RE_PARTITION.exec(path), many = path === "/v1/state", changes = path === "/v1/changes", index = path && RE_INDEX.exec(path);
				if (!match && !many && !changes && !index) fail(404, "not_found", "Unknown endpoint");
				if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...headers,
					"Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization", "Cache-Control": "no-store" } });
				const expected = match?.[2] === "log" || changes ? "GET" : "POST";
				if (request.method !== expected) fail(405, "method_not_allowed", "Method is not supported");
				if (many) return answer(await store.stateMany(request, await readJson(request, limit)), 200, headers);
				// NOTE: The change feed and indexes are for servers: the store asks the host's server callback.
				if (changes) return answer(await store.changes(request, integer(url, "after", 0), url.searchParams.get("epoch"), integer(url, "limit", null)), 200, headers);
				if (index) {
					let name;
					try { name = decodeURIComponent(index[1]); } catch { fail(400, "invalid", "Malformed index name encoding", { check: "index" }); }
					return answer(await store.indexQuery(request, name, await readJson(request, limit)), 200, headers);
				}
				let partition;
				try { partition = decodeURIComponent(match[1]); } catch { fail(400, "invalid", "Malformed partition ID encoding", { check: "partition" }); }
				if (match[2] === "log") return answer(await store.log(request, partition, integer(url, "after", 0), integer(url, "limit", null)), 200, headers);
				const body = await readJson(request, limit);
				return answer(await (match[2] === "statements" ? store.append(request, partition, body) : store.state(request, partition, body)), 200, headers);
			} catch (error) {
				if (error instanceof StoreError) return answer(error.toJSON(), error.status, headers);
				console.error(JSON.stringify({ error: "store_failure", message: String(error) }));
				return answer({ error: "server_error", message: "Server failure; retry the same request ID and payload" }, 500, headers);
			}
		},
	};
}

// EOF
