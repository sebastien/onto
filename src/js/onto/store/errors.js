/** Module: store/errors — a store's error answers (spec-08 "Protocol"), as `store/runtime.py`'s `StoreError`. */

import { compareCodePoints, pyJson } from "../values.js";

/** A store's error answer: an HTTP status, a stable `error` code, a message and details (spec-08 "Protocol"). */
export class StoreError extends Error {
	constructor(status, error, message, details = {}) {
		super(message);
		this.status = status;
		this.error = error;
		this.details = details;
	}

	toJSON() {
		return { error: this.error, message: this.message, ...this.details };
	}
}

/** `400 invalid` for a batch failing `check`, at statement `n` when it can be told. */
export function invalid(check, message, n = null) {
	return new StoreError(400, "invalid", message, { check, ...(n !== null && n !== undefined ? { n } : {}) });
}

/** Raised by an authorization callback to deny a request (`403`). */
export class Forbidden extends Error {}

/** Python's `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`: the store's canonical JSON. */
export function canonical(value) {
	if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
	if (value !== null && typeof value === "object") {
		const keys = Object.keys(value).sort(compareCodePoints);
		return "{" + keys.map(key => pyJson(key, { ascii: false }) + ":" + canonical(value[key])).join(",") + "}";
	}
	return pyJson(value, { ascii: false });
}

// EOF
