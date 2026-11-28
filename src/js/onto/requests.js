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
const RE_PLACEHOLDER = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;
const ABSENT = Symbol("absent");

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

/**
 * A list read's template part with its parameters' values (spec-09 "List reads"): `"{name}"` is the value, `{name}` in
 * a longer string its text; a part whose placeholders are all absent is left out (`ABSENT`), or null.
 */
function templateFillMany(item, values, absent = "omit") {
	if (typeof item === "string") {
		const names = [...item.matchAll(RE_PLACEHOLDER)].map(match => match[1]);
		if (names.length && !names.some(name => Object.hasOwn(values, name))) return absent === "null" ? null : ABSENT;
		if (names.length === 1 && item === `{${names[0]}}`) return values[names[0]];
		return item.replace(RE_PLACEHOLDER, (match, name) => Object.hasOwn(values, name) ? valueText(values[name]) : match);
	}
	if (Array.isArray(item)) {
		const kept = item.map(entry => templateFillMany(entry, values, absent)).filter(entry => entry !== ABSENT);
		return item.length && !kept.length ? ABSENT : kept;
	}
	if (item && typeof item === "object") {
		const kept = Object.entries(item).map(([key, entry]) => [key, templateFillMany(entry, values, absent)]).filter(([, entry]) => entry !== ABSENT);
		return Object.keys(item).length && !kept.length ? ABSENT : Object.fromEntries(kept);
	}
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

/** A list read's `RequestSend` request for its parameters' values, leaving out what no value fills. */
export function listRequestFor(read, values) {
	const request = {};
	for (const [key, item] of Object.entries(requestTemplate(read))) {
		const filled = ["method", "path", "api"].includes(key) ? item : templateFillMany(item, values, read.list?.absent);
		if (filled !== ABSENT) request[key] = filled;
	}
	return request;
}

/** A response's provenance token: the read's `source` template, else the request's API and path. */
export function requestSource(read, request, value) {
	if (read.source !== undefined) return read.source.split(`{${read.input.name}}`).join(valueText(value));
	return (request.api !== undefined ? request.api + ":" : "") + request.path;
}

// EOF
