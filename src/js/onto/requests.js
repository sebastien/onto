/**
 * Module: requests — fill a view read's request template into a hexa `RequestSend` request, as `integrations/hexa/requests.py`.
 *
 * A read's `request` is `{method?, path, api?, query?, headers?, body?}`. In `path`, `{name}` (the input's name)
 * is the input value as one encoded path segment; elsewhere a string `"{name}"` is the value itself, and `{name}`
 * within a longer string its text. A read's `source` spells the response's provenance token the same way.
 * Only path substitutions are encoded here; the host sending the request must handle its other fields safely.
 */

import { p } from "hexa/runtime.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

export const REQUEST_KEYS = ["method", "path", "api", "query", "headers", "body"];

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** A key value as text (`String`). */
const valueText = value => String(value);

/** A request template part with the input value: `"{name}"` is the value, `{name}` in a longer string its text. */
function templateFill(item, name, value) {
	const token = `{${name}}`;
	if (typeof item === "string") return item === token ? value : item.split(token).join(valueText(value));
	if (Array.isArray(item)) return item.map(entry => templateFill(entry, name, value));
	if (item && typeof item === "object") return Object.fromEntries(Object.entries(item).map(([key, entry]) => [key, templateFill(entry, name, value)]));
	return item;
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

/** A read's request template in its canonical member order, the method spelled out. */
export function requestTemplate(read) {
	return { method: read.request.method ?? "GET", ...Object.fromEntries(REQUEST_KEYS.slice(1).filter(key => Object.hasOwn(read.request, key)).map(key => [key, read.request[key]])) };
}

/** A read's `RequestSend` request for `value`; hexa's `p` encodes each path substitution as a segment. */
export function requestFor(read, value) {
	const literals = read.request.path.split(`{${read.input.name}}`);
	const path = p(Object.assign([...literals], { raw: [...literals] }), ...literals.slice(1).map(() => value));
	return Object.fromEntries(Object.entries(requestTemplate(read)).map(([key, item]) =>
		[key, key === "path" ? path : ["method", "api"].includes(key) ? item : templateFill(item, read.input.name, value)]));
}

/** A response's provenance token: the read's `source` template, else the request's API and path. */
export function requestSource(read, request, value) {
	if (read.source !== undefined) return read.source.split(`{${read.input.name}}`).join(valueText(value));
	return (request.api !== undefined ? request.api + ":" : "") + request.path;
}

// EOF
