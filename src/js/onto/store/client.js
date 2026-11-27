/**
 * Module: store/client — an observation store's client for browsers and servers (spec-08 "Implementations"), over the
 * store's HTTP protocol with an injected `fetch`: the host's, which adds the user's credentials.
 *
 * Its methods answer as the store's do, and throw `StoreError` with the store's status, code and details. A failure
 * before an answer is the host's (`fetch` rejects): retry an append with the same request ID and payload.
 */

import { StoreError } from "./errors.js";

/**
 * A store client: `base` is the store's URL (`https://store.example/`), `fetch` the host's (default the global one),
 * and `init` extra request options, such as `{credentials: "include"}`.
 */
export function storeClient({ base, fetch = globalThis.fetch, init = {} } = {}) {
	const root = base.replace(/\/+$/, "");
	const partitionPath = (id, action) => `${root}/v1/partitions/${encodeURIComponent(id)}/${action}`;

	async function call(method, url, body) {
		const response = await fetch(url, { ...init, method, headers: { ...init.headers, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
			...(body === undefined ? {} : { body: JSON.stringify(body) }) });
		let data;
		try {
			data = await response.json();
		} catch {
			throw new StoreError(response.status, "server_error", `The store answered ${response.status} without JSON`);
		}
		if (!response.ok) {
			const { error = "server_error", message = "", ...details } = data ?? {};
			throw new StoreError(response.status, error, message, details);
		}
		return data;
	}

	return {
		/** Append a batch (`{requestId, observations, expect?, links?}`) to a partition. */
		append: (partition, body) => call("POST", partitionPath(partition, "statements"), body),
		/** The reconciled state of a selection of a partition (`{select?, include?, asOf?}`). */
		state: (partition, body = {}) => call("POST", partitionPath(partition, "state"), body),
		/** The statements and records after `after`, a page at most `limit` long. */
		log: (partition, { after = 0, limit = null } = {}) =>
			call("GET", partitionPath(partition, "log") + `?after=${after}` + (limit === null ? "" : `&limit=${limit}`)),
		/** Selections of several partitions (`{reads: [{partition, select?, ...}]}`), each answered on its own. */
		stateMany: body => call("POST", `${root}/v1/state`, body),
	};
}

// EOF
