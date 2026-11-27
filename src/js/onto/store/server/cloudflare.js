/**
 * Module: store/server/cloudflare — an observation store on Cloudflare (spec-08 "Implementations"): one SQLite-backed
 * Durable Object per partition, routed by scope and partition ID, and a Worker serving the store's protocol.
 *
 * Kept apart from the rest of the store so that browsers never import `cloudflare:workers`. Authorization is the
 * application's: the Worker asks its callback for each request, and never trusts a scope a request names. The scope's
 * own objects (change feed, reference index, erasures, lifecycle alarms) come with the store's administration (O2).
 *
 *	const store = cloudflareStore({ bundle });
 *	export const { PartitionObject } = store;
 *	export default store.worker({ authorize: async (request, partition, access, env) => ({ scope, principal }) });
 *
 * The Worker needs `env.PARTITIONS` bound to `PartitionObject`, with SQLite storage.
 */

import { DurableObject } from "cloudflare:workers";
import { StoreError } from "../errors.js";
import { storeHandler } from "../http.js";
import { PartitionStore } from "../partition.js";
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

		append(identity, principal, body, digest) {
			return outcome(() => this.engine(identity).append(principal, body, digest));
		}

		state(identity, principal, body) {
			return outcome(() => this.engine(identity).state(principal, body));
		}

		log(identity, principal, after, limit) {
			return outcome(() => this.engine(identity).log(principal, after, limit));
		}
	}

	/**
	 * The Worker: `authorize(request, partition, access, env)` answers `{scope, principal}`, null for an
	 * unauthenticated request, or throws `Forbidden`. `origins` lists the browser origins allowed to call it.
	 */
	function worker({ authorize, origins = [] }) {
		return {
			fetch(request, env) {
				const store = new ObservationStore(bundle, {
					authorize: (incoming, partition, access) => authorize(incoming, partition, access, env),
					partitionFor: (scope, id) => remote(env.PARTITIONS.getByName(JSON.stringify([scope, id])), [scope, id]),
				});
				return storeHandler(store, { origins }).fetch(request);
			},
		};
	}

	return { PartitionObject, worker };
}

// EOF
