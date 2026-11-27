/**
 * Module: store/origins — an instance's origin from its handle, and the slots a store holds for it, read from a store
 * bundle, as `store/origins.py` (spec-09 "Origins", spec-08 "Held slots").
 */

import { decodeKey } from "../values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

export const ORIGIN_STORE = "@store";
export const ORIGIN_SHARED = "@shared";
const RE_ELEMENT_KEY = /\[[^\]]*\]/g;
const RE_QUALIFIED_KEY = /\[(?:[^\]/]*\/)*([^\]/]*)\]/g;

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** `type` and its bases, from the bundle's model facts. */
export function lineage(bundle, type) {
	const types = bundle.model.types, result = [];
	while (type && !result.includes(type)) {
		result.push(type);
		type = types[type]?.base ?? "";
	}
	return result;
}

export const isA = (bundle, type, ancestor) => lineage(bundle, type).includes(ancestor);
export const related = (bundle, left, right) => isA(bundle, left, right) || isA(bundle, right, left);

/** An attribute path with its element keys as their last segment: `Phones[Core/PhoneType/Mobile]` is `Phones[Mobile]`. */
export const elementPath = path => path.replace(RE_QUALIFIED_KEY, "[$1]");

/** An attribute path without its element keys. */
export const unkeyedPath = path => path.replace(RE_ELEMENT_KEY, "");

/** A statement's slot kind and name, keyed elements included; null for identity links, which no instance holds. */
export function slotOf(claim) {
	if (Object.hasOwn(claim, "same") || Object.hasOwn(claim, "distinct")) return null;
	if (Object.hasOwn(claim, "rel")) return ["rel", claim.rel];
	if (Object.hasOwn(claim, "facet")) return ["facet", claim.facet];
	if (Object.hasOwn(claim, "p")) return ["attr", elementPath(claim.p)];
	return ["exists", ""];
}

/** The decoded part of a handle of `typePath`, or null when the handle is not of that type's form. */
export function handleKey(handle, typePath) {
	const prefix = typePath.slice(typePath.lastIndexOf("/") + 1) + "_";
	return handle.startsWith(prefix) ? decodeKey(handle.slice(prefix.length)) : null;
}

/** A source-qualified handle's `<scope>/<S>/<key>`, or null when `key` has not that form. */
export function sourceParts(key) {
	const first = key.indexOf("/");
	if (first < 0) return null;
	const scope = key.slice(0, first), rest = key.slice(first + 1), second = rest.indexOf("/");
	if (second < 0) return null;
	const sourceType = rest.slice(0, second), value = rest.slice(second + 1);
	return scope && sourceType && value ? [scope, sourceType, value] : null;
}

/** Whether `system`'s mapping fills the slot on `type` or a type compatible with it; keyed elements are distinct slots. */
function fills(system, bundle, type, kind, name) {
	for (const [target, filled] of Object.entries(system.types)) {
		if (kind === "rel" && filled.relations.includes(name)) return true;
		if (!related(bundle, type, target)) continue;
		if (kind === "attr" && filled.attrs.some(item => elementPath(item) === name) || kind === "facet" && filled.facets.includes(name)) return true;
	}
	return false;
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

/**
 * The system an instance of `type` comes from: a system's name, `ORIGIN_STORE`, `ORIGIN_SHARED`, or null when its handle
 * tells none. `scope` is the store's scope, which its source-qualified handles carry.
 */
export function originOf(bundle, handle, type, scope) {
	const entry = bundle.origins[type];
	if (entry === undefined) return ORIGIN_STORE;
	for (const prefix of lineage(bundle, type)) {
		const key = handleKey(handle, prefix);
		if (key === null) continue;
		const parts = sourceParts(key);
		if (parts) {
			if (parts[0] === scope) return ORIGIN_STORE;
			const system = bundle.systems.find(item => item.scope === parts[0]);
			if (system) return system.name;
		}
		if (entry.policy) return entry.policy.from ?? ORIGIN_SHARED;
	}
	return null;
}

/** Whether the store holds the slot `claim` states about a subject of `type` and `origin`. */
export function holds(bundle, origin, type, claim) {
	const slot = slotOf(claim);
	if (slot === null) return true;
	const [kind, name] = slot;
	if (origin !== ORIGIN_STORE) {
		// NOTE: A system holds the existence of its instances, so the store never states it.
		if (kind === "exists") return false;
		const producers = origin === ORIGIN_SHARED ? bundle.origins[type]?.systems ?? [] : [origin];
		if (bundle.systems.some(system => producers.includes(system.name) && fills(system, bundle, type, kind, name))) return false;
	}
	// NOTE: Exclusions name attributes without keys, so they exclude every element.
	const unkeyed = unkeyedPath(name);
	return !(kind === "attr" && bundle.exclusions.some(item => item.path === unkeyed && isA(bundle, type, item.type)));
}

// EOF
