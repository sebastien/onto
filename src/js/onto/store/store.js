/**
 * Module: store/store — an observation store over partitions (spec-08): it authorizes each request with the host's
 * callback, checks what Python checks before a partition is touched, and routes to the partition's own storage.
 *
 * A partition is reached through `partitionFor(scope, id)`, an object with the engine's `append`, `state` and `log`,
 * synchronous or not: a Durable Object's stub in a Worker (`server/cloudflare.js`). Without it, `storageFor(scope, id)`
 * gives each partition's SQLite storage (Cloudflare's shape) for an engine in this process: Bun, Node or tests.
 *
 * A scope's change feed and indexes (spec-08 "Changes", "Indexes") are reached through `scopeFor(scope)` with a remote
 * partition, which reports its changes itself; otherwise they live in this process, in `storageFor(scope, null)`, and
 * the store reports each append's change. Servers read them, as `authorizeServer(request)` allows.
 */

import { Forbidden, StoreError, canonical, invalid } from "./errors.js";
import { PartitionStore } from "./partition.js";
import { ScopeStore } from "./scope.js";
import { BatchValidator } from "./validate.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const RE_HANDLE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const bytes = text => new TextEncoder().encode(text).length;

/** `400 invalid` unless `id` is `<Kind>/<anchor handle>` of a kind the bundle declares, within the handle limit. */
export function checkPartitionId(bundle, id) {
	const slash = typeof id === "string" ? id.indexOf("/") : -1;
	if (slash < 0 || !bundle.kinds.some(kind => kind.kind === id.slice(0, slash)) || !RE_HANDLE.test(id.slice(slash + 1)) || bytes(id) > bundle.limits.handleBytes)
		throw invalid("partition", `Expected a partition ID '<Kind>/<anchor handle>' of a declared kind, not '${id}'`);
}

/** The SHA-256 of a text, in lowercase hexadecimal. */
export async function sha256(text) {
	const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
	return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

export class ObservationStore {
	/**
	 * `authorize(request, partition, access)` answers `{scope, principal}`, null for an unauthenticated request, or
	 * throws `Forbidden`; it may be asynchronous. `authorizeServer(request)` does so for a server's request. `clock()`
	 * gives epoch milliseconds.
	 */
	constructor(bundle, { authorize, authorizeServer = null, storageFor, partitionFor, scopeFor, clock = Date.now }) {
		if (!storageFor === !partitionFor) throw new TypeError("expected storageFor or partitionFor");
		this.bundle = bundle;
		this.authorizeCallback = authorize;
		this.authorizeServerCallback = authorizeServer;
		this.scopeFor = scopeFor;
		this.scopes = new Map();
		this.storageFor = storageFor;
		this.partitionFor = partitionFor;
		this.clock = clock;
		this.validator = new BatchValidator(bundle);
		this.limits = bundle.limits;
		this.partitions = new Map();
	}

	/** The request's scope and principal, or `401` and `403` as the host's callback decides. */
	async authorize(request, partition, access) {
		let grant;
		try {
			grant = await this.authorizeCallback(request, partition, access);
		} catch (error) {
			if (error instanceof Forbidden) throw new StoreError(403, "forbidden", error.message || `${access} denied`);
			throw error;
		}
		if (grant === null || grant === undefined) throw new StoreError(401, "unauthorized", "The request is not authenticated");
		return [grant.scope, grant.principal];
	}

	/** A server request's scope, for the change feed and indexes; `403` without a server callback. */
	async authorizeServer(request) {
		if (!this.authorizeServerCallback) throw new StoreError(403, "forbidden", "The store answers no server requests");
		let grant;
		try {
			grant = await this.authorizeServerCallback(request);
		} catch (error) {
			if (error instanceof Forbidden) throw new StoreError(403, "forbidden", error.message || "servers only");
			throw error;
		}
		if (grant === null || grant === undefined) throw new StoreError(401, "unauthorized", "The request is not authenticated");
		return grant.scope;
	}

	/** A scope's change feed and indexes: its engine in this process, or `scopeFor(scope)`. */
	scope(scope) {
		if (this.scopeFor) return this.scopeFor(scope);
		if (!this.scopes.has(scope)) this.scopes.set(scope, new ScopeStore(this.storageFor(scope, null), { bundle: this.bundle, scope }));
		return this.scopes.get(scope);
	}

	/** A partition by ID, `<Kind>/<anchor handle>` of a declared kind: its engine or its Durable Object. */
	partition(scope, id) {
		checkPartitionId(this.bundle, id);
		if (this.partitionFor) return this.partitionFor(scope, id);
		const key = JSON.stringify([scope, id]);
		if (!this.partitions.has(key))
			this.partitions.set(key, new PartitionStore(this.storageFor(scope, id), { bundle: this.bundle, validator: this.validator, clock: this.clock, scope, id }));
		return this.partitions.get(key);
	}

	/** Append a batch to a partition: whole or not at all (spec-08 "Batches"). */
	async append(request, partitionId, body) {
		const [scope, principal] = await this.authorize(request, partitionId, "append");
		if (body === null || typeof body !== "object" || Array.isArray(body) || typeof body.requestId !== "string" || !body.requestId)
			throw invalid("requestId", "A batch needs a request ID");
		if (bytes(canonical(body)) > this.limits.requestBytes) throw new StoreError(413, "too_large", "The request is larger than the store accepts");
		const partition = this.partition(scope, partitionId);
		const digest = await sha256(canonical({ observations: body.observations ?? null, expect: body.expect ?? [], links: body.links ?? [] }));
		const answer = await partition.append(principal, body, digest);
		// NOTE: A partition in this process reports its change at once; a remote one does, from its own alarm.
		if (!this.partitionFor) await this.scope(scope).record(partition.change());
		return answer;
	}

	/** The scope's change feed after a cursor (spec-08 "Changes"), for servers only. */
	async changes(request, after = 0, epoch = null, limit = null) {
		return await this.scope(await this.authorizeServer(request)).changes(after, epoch, limit);
	}

	/** The partitions an index's rows match a filter, paged (spec-08 "Indexes"), for servers only. */
	async indexQuery(request, name, body) {
		return await this.scope(await this.authorizeServer(request)).indexQuery(name, body);
	}

	/** The reconciled state of a selection of a partition (spec-08 "State"). */
	async state(request, partitionId, body = {}) {
		const [scope, principal] = await this.authorize(request, partitionId, "read");
		return await this.partition(scope, partitionId).state(principal, body);
	}

	/** The statements and records after a `seq`, in order, with their stamps (spec-08 "Log"). */
	async log(request, partitionId, after = 0, limit = null) {
		const [scope, principal] = await this.authorize(request, partitionId, "read");
		return await this.partition(scope, partitionId).log(principal, after, limit);
	}

	/** Selections of several partitions, each authorized and answered on its own (spec-08 "Several partitions"). */
	async stateMany(request, body) {
		const reads = body !== null && typeof body === "object" ? body.reads : undefined;
		if (!Array.isArray(reads) || reads.some(item => item === null || typeof item !== "object" || typeof item.partition !== "string"))
			throw invalid("reads", "A batch read lists partitions with their selections");
		const results = [];
		for (const { partition, ...selection } of reads) {
			try {
				results.push(await this.state(request, partition, selection));
			} catch (error) {
				if (!(error instanceof StoreError)) throw error;
				results.push({ partition, status: error.status, ...error.toJSON() });
			}
		}
		return { results };
	}
}

// EOF
