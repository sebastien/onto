/**
 * Module: stages — building blocks shared by the binding and mapping runs: named stages, program functions
 * and claim emission, as `integrations/hexa/stages.py` provides them to `unfold.py`.
 */

import { stage } from "hexa/combinators.js";
import { FunctionEvaluator } from "./functions.js";
import { OBSERVATIONS_FORMAT } from "./observations.js";
import { typed } from "./types.js";
import { functionCodec, functionTransform } from "./vocabulary.js";
import { isAbsent, isRef, isSet, jsonEqual, referenceHandles } from "./values.js";

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** The handle a record's reference names: a `{ref}` value or a plain handle. */
const refHandle = value => isRef(value) ? value.ref : typeof value === "string" ? value : null;

/** Strip the integration's reference types, recording them in `types` for implicit instances. */
export function cleanValue(value, types) {
	if (isRef(value)) {
		if (Object.hasOwn(value, "type") && !Object.hasOwn(types, value.ref)) types[value.ref] = value.type;
		return { ref: value.ref };
	}
	if (isSet(value)) return { ...value, set: value.set.map(item => cleanValue(item, types)) };
	return value;
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** A stage carrying `name` in traces and ledger targets, without process-wide registration. */
export function namedStage(name, inner) {
	const run = function* (env, ...inputs) { return yield* inner(env, ...inputs); };
	return named(name, run);
}

/** Name a generator for traces; `stage(fn)` takes the function's name without registering it. */
export function named(name, fn) {
	Object.defineProperty(fn, "name", { value: name });
	return stage(fn);
}

/** Declare a program's function transforms and codecs in its registry, bound to one evaluator. */
export function registerFunctions(registry, data, implementations) {
	const evaluator = new FunctionEvaluator({ functions: data.functions ?? {}, maps: data.maps ?? {}, implementations, typed });
	for (const name of [...Object.keys(data.functions ?? {}), ...Object.keys(data.maps ?? {})]) {
		const transform = functionTransform(name, evaluator);
		registry.set(transform.name, transform);
	}
	for (const [name, item] of Object.entries(data.codecs ?? {})) registry.set(name, functionCodec(item.function, item.inverse, registry.decode(item.canonical), evaluator));
	return evaluator;
}

/** Assemble a spec-02 JSON log; facets share an existence claim's number when their metadata matches. */
export class ClaimsBuilder {
	constructor(model, ontology, scope, by) {
		this.model = model;
		this.data = { format: OBSERVATIONS_FORMAT, obs: { ontology, scope }, sources: {}, instances: {}, claims: [], retractions: [] };
		Object.assign(this, { by, aliases: new Map(), implicit: {}, headers: new Map(), n: 0 });
	}

	alias(token) {
		if (!this.aliases.has(token)) {
			this.aliases.set(token, `d${this.aliases.size + 1}`);
			this.data.sources[this.aliases.get(token)] = token;
		}
		return this.aliases.get(token);
	}

	instance(handle, typePath) {
		const existing = this.data.instances[handle];
		if (!existing || this.model.isA(typePath, existing.type) && typePath !== existing.type) this.data.instances[handle] = { type: typePath };
	}

	add(claim, retraction = false) {
		this.n += 1;
		const result = { n: this.n, ...claim };
		this.data[retraction ? "retractions" : "claims"].push(result);
		return result;
	}

	exists(handle, meta) {
		const claim = this.add({ s: handle, exists: true, ...meta });
		this.headers.set(handle, [claim.n, meta]);
		return claim;
	}

	facet(handle, name, meta, ctx) {
		const strip = item => Object.fromEntries(Object.entries(item).filter(([key]) => !["valid", "ctx"].includes(key)));
		meta = strip(meta);
		const header = this.headers.get(handle);
		let n;
		if (header && jsonEqual(strip(header[1]), meta)) n = header[0];
		else {
			n = this.n += 1;
			this.data.claims.push({ n, s: handle, exists: true, ...meta });
		}
		this.data.claims.push({ n, s: handle, facet: name, ...meta, ...(ctx ? { ctx } : {}) });
	}

	contextual(typePath, member, isFacet) {
		const facet = this.model.facets(typePath).get(isFacet ? member : member.split(".")[0]);
		return Boolean(facet && (isFacet || this.model.facetOf(typePath, member) === facet) && facet.ctx);
	}

	/** Existence, values, facets and links of one identified record (or `- h` when deleted). */
	record(record, meta) {
		const { handle, type: typePath } = record;
		this.instance(handle, typePath);
		if (record.deleted === true) {
			this.add({ s: handle, exists: true, ...meta }, true);
			return;
		}
		const valid = record.valid;
		this.exists(handle, { ...meta, ...(typeof valid === "string" ? { valid } : {}) });
		const ctx = refHandle(record.ctx);
		const relation = this.model.get(typePath);
		for (const [name, value] of Object.entries(record.facets ?? {})) {
			if (value === true) this.facet(handle, name, meta, ctx && this.contextual(typePath, name, true) ? ctx : null);
		}
		for (const [name, value] of Object.entries(record.values ?? {})) {
			if (isAbsent(value)) continue;
			const claim = { s: handle, p: name, ...meta, v: cleanValue(value, this.implicit) };
			if (ctx && this.contextual(typePath, name, false)) claim.ctx = ctx;
			this.add(claim);
		}
		for (const [verb, value] of Object.entries(record.links ?? {})) {
			if (isAbsent(value)) continue;
			cleanValue(value, this.implicit);
			const found = !relation || relation.kind === "entity" ? this.model.verbs(typePath, verb) : [];
			if (!found.length) continue;
			const [decl, inverse] = found[0];
			const [first, second] = decl.participants.map(item => item.role);
			for (const other of referenceHandles(value)) this.add({ rel: decl.path, roles: inverse ? { [first]: other, [second]: handle } : { [first]: handle, [second]: other }, ...meta });
		}
	}

	/** Add missing implicit instances, sort instances by handle, and return the mutable log. */
	finish() {
		for (const [handle, typePath] of Object.entries(this.implicit)) if (!Object.hasOwn(this.data.instances, handle)) this.data.instances[handle] = { type: typePath };
		this.data.instances = Object.fromEntries(Object.entries(this.data.instances).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
		return this.data;
	}
}

// EOF
