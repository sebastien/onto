/**
 * Module: store/server/cloudflare — an observation store on Cloudflare (spec-08 "Implementations"): one SQLite-backed
 * Durable Object per partition, routed by scope and partition ID, and a Worker serving the store's protocol.
 *
 * Kept apart from the rest of the store so that browsers never import `cloudflare:workers`. Authorization is the
 * application's: the Worker asks its callback for each request, and never trusts a scope a request names.
 *
 * Each scope has an object for its change feed and indexes (spec-08 "Changes", "Indexes"): after an append, a
 * partition's alarm reports its change to it, again until the report succeeds, so that the scope learns of every
 * change at least once. The reference index, erasures and lifecycle alarms come with the store's administration (O2).
 *
 *	const store = cloudflareStore({ bundle });
 *	export const { PartitionObject, ScopeObject } = store;
 *	export default store.worker({ authorize: async (request, partition, access, env) => ({ scope, principal }),
 *		authorizeServer: async (request, env) => ({ scope, principal }) });
 *
 * The Worker needs `env.PARTITIONS` bound to `PartitionObject` and `env.SCOPES` to `ScopeObject`, both with SQLite
 * storage.
 */

import { DurableObject } from "cloudflare:workers";
import { StoreError } from "../errors.js";
import { storeHandler } from "../http.js";
import { PartitionStore } from "../partition.js";
import { ScopeStore } from "../scope.js";
import { ObservationStore } from "../store.js";
import { BatchValidator } from "../validate.js";

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** An operation's outcome as data: RPC carries a store's refusals as answers rather than as exceptions. */
function outcome(action) {
	try {
		return { status: 200, body: action() };
	} catch (error) {
		if (error instanceof StoreError) return { status: error.status, body: error.toJSON() };
		throw error;
	}
}

/** A scope's Durable Object as the store reaches its feed and indexes: `record`, `changes` and `indexQuery`, refusals thrown. */
function remoteScope(stub, scope) {
	const call = async (method, ...args) => {
		const { status, body } = await stub[method](scope, ...args);
		if (status !== 200) {
			const { error, message, ...details } = body;
			throw new StoreError(status, error, message, details);
		}
		return body;
	};
	return {
		record: change => call("record", change),
		changes: (after, epoch, limit) => call("changes", after, epoch, limit),
		indexQuery: (name, body) => call("indexQuery", name, body),
	};
}

/** A partition's Durable Object as the store reaches its partitions: `append`, `state` and `log`, refusals thrown. */
function remote(stub, identity) {
	const call = async (method, ...args) => {
		const { status, body } = await stub[method](identity, ...args);
		if (status !== 200) {
			const { error, message, ...details } = body;
			throw new StoreError(status, error, message, details);
		}
		return body;
	};
	return {
		append: (principal, body, digest) => call("append", principal, body, digest),
		state: (principal, body) => call("state", principal, body),
		log: (principal, after, limit) => call("log", principal, after, limit),
	};
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

/** The Durable Object class and the Worker factory of a store bundle. */
export function cloudflareStore({ bundle }) {
	const validator = new BatchValidator(bundle);

	/** One partition: its statements, members, versions, retry records and audit in the object's SQLite storage. */
	class PartitionObject extends DurableObject {
		/** The partition's engine; the storage keeps the identity of its first request and refuses any other. */
		engine([scope, id]) {
			this.partition ??= new PartitionStore(this.ctx.storage, { bundle, validator, clock: Date.now, scope, id });
			if (this.partition.scope !== scope || this.partition.id !== id) throw new StoreError(409, "identity_conflict", "The object holds another partition");
			return this.partition;
		}

		async append(identity, principal, body, digest) {
			const result = outcome(() => this.engine(identity).append(principal, body, digest));
			// NOTE: The alarm reports the partition's change to its scope, and runs again until the report succeeds.
			if (result.status === 200) await this.ctx.storage.setAlarm(Date.now());
			return result;
		}

		/** Report the partition's change to its scope's object; a failure throws, and Cloudflare retries the alarm. */
		async alarm() {
			const [row] = this.ctx.storage.sql.exec("SELECT scope, partition FROM partition WHERE id = 1").toArray();
			if (!row) return;
			const change = this.engine([row.scope, row.partition]).change();
			const { status, body } = await this.env.SCOPES.getByName(row.scope).record(row.scope, change);
			if (status !== 200) throw new Error(`the scope refused the change of ${row.partition}: ${body?.error}`);
		}

		state(identity, principal, body) {
			return outcome(() => this.engine(identity).state(principal, body));
		}

		log(identity, principal, after, limit) {
			return outcome(() => this.engine(identity).log(principal, after, limit));
		}
	}

	/** A scope's change feed and index rows, which its partitions report their changes to. */
	class ScopeObject extends DurableObject {
		engine(scope) {
			this.scope ??= new ScopeStore(this.ctx.storage, { bundle, scope });
			if (this.scope.scope !== scope) throw new StoreError(409, "identity_conflict", "The object holds another scope");
			return this.scope;
		}

		record(scope, change) {
			return outcome(() => this.engine(scope).record(change));
		}

		changes(scope, after, epoch, limit) {
			return outcome(() => this.engine(scope).changes(after, epoch, limit));
		}

		indexQuery(scope, name, body) {
			return outcome(() => this.engine(scope).indexQuery(name, body));
		}
	}

	/**
	 * The store as a Worker reaches it: a remote object per partition and per scope (`store.js`).
	 * @param {object} env
	 * @param {{authorize: Function, authorizeServer?: Function | null}} options
	 */
	function storeFor(env, { authorize, authorizeServer = null }) {
		return new ObservationStore(bundle, {
			authorize: (incoming, partition, access) => authorize(incoming, partition, access, env),
			authorizeServer: authorizeServer && (incoming => authorizeServer(incoming, env)),
			partitionFor: (scope, id) => remote(env.PARTITIONS.getByName(JSON.stringify([scope, id])), [scope, id]),
			scopeFor: scope => remoteScope(env.SCOPES.getByName(scope), scope),
		});
	}

	/**
	 * The Worker: `authorize(request, partition, access, env)` answers `{scope, principal}`, null for an
	 * unauthenticated request, or throws `Forbidden`; `authorizeServer(request, env)` does so for the change feed and
	 * indexes, and without it they refuse. `origins` lists the browser origins allowed to call it, and `prefix` the
	 * path it serves the protocol under.
	 * @param {{authorize: Function, authorizeServer?: Function | null, origins?: string[], prefix?: string}} options
	 */
	function worker({ authorize, authorizeServer = null, origins = [], prefix = "" }) {
		return {
			fetch(request, env) {
				return storeHandler(storeFor(env, { authorize, authorizeServer }), { origins, prefix }).fetch(request);
			},
		};
	}

	return { PartitionObject, ScopeObject, storeFor, worker };
}

// EOF
