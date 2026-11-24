/**
 * Module: binding — read documents through a compiled binding into a spec-02 log, as `integrations/hexa/stages.py`.
 *
 * BindingRead: DocumentsRead → ClaimsEmit
 * DocumentsRead: parallel(DocumentRecordsCollect)
 * DocumentRecordsCollect: <Type>RecordsSelect → <Type>RecordsProject, for each scope line
 */

import { Failure } from "hexa/shapes.js";
import { Policy, collect, each, parallel, pipe, project, select, stage } from "hexa/combinators.js";
import { Ledger, report } from "hexa/runtime.js";
import { captureState, copyCaptures } from "hexa/shape.js";
import { FunctionEvaluator } from "./functions.js";
import { Registry } from "./program.js";
import { typed } from "./types.js";
import { BindingCodes, functionCodec, functionTransform, reasonCode } from "./vocabulary.js";
import { isAbsent, jsonEqual, referenceHandles } from "./values.js";

// -----------------------------------------------------------------------------
//
// UTILITIES
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

function itemPolicy(mode) {
	const reason = failure => failure.kind === Failure.Shape ? BindingCodes.TypeMismatch : failure.code;
	return mode === "strict" ? [Policy.Abort, { on: [Failure.Shape], reason }] : [Policy.Drop, { reason }];
}

/** A child occurrence located from the document root, with its enclosing blocks' captures. */
function combine(parent, child) {
	const result = { value: child.value, location: parent.location + child.location };
	let captures = parent.captures;
	if (child.captures) {
		if (!captures) captures = child.captures;
		else {
			captures = copyCaptures(captures);
			const evidence = captureState(captures).evidence, childEvidence = captureState(child.captures).evidence;
			for (const key of Reflect.ownKeys(child.captures)) {
				captures[key] = child.captures[key];
				if (childEvidence.has(key)) evidence.set(key, childEvidence.get(key));
			}
		}
	}
	if (captures) result.captures = captures;
	if (child.origin) result.origin = child.origin;
	return result;
}

function selectStage(scope) {
	const levels = scope.levels.map(select), picks = scope.picks.length ? scope.picks : levels.map(() => null);
	const owner = [];
	owner.push(named(`${scope.name}RecordsSelect`, function* (env, document) {
		let occurrences = [{ value: document, location: "" }];
		for (const [index, level] of levels.entries()) {
			const pick = picks[index], following = [];
			for (const parent of occurrences) {
				let found;
				try { found = yield* level(env, parent.value); }
				catch (failure) {
					if (!(failure instanceof Failure) || failure.kind !== Failure.Gap) throw failure;
					const fields = { source: parent.location + (failure.location ?? "") };
					if (failure.path !== undefined && failure.path !== null) fields.path = failure.path;
					yield report(Ledger.Gap, { target: owner[0], reason: failure.code, ...fields });
					continue;
				}
				// An index step before `[*]` is selected as `*`: keep the element at its position only.
				for (const child of found) if (pick === null || child.location.split("/").at(-1) === String(pick)) following.push(combine(parent, child));
			}
			occurrences = following;
		}
		// spec-04: a null value is not present, so a null record makes no instance and no gap.
		return occurrences.filter(occurrence => occurrence.value !== null);
	}));
	return owner[0];
}

function cleanValue(value, types) {
	if (value && typeof value === "object" && !Array.isArray(value) && Object.hasOwn(value, "ref")) {
		if (Object.hasOwn(value, "type") && !Object.hasOwn(types, value.ref)) types[value.ref] = value.type;
		return { ref: value.ref };
	}
	if (value && typeof value === "object" && !Array.isArray(value) && Object.hasOwn(value, "set")) return { ...value, set: value.set.map(item => cleanValue(item, types)) };
	return value;
}

const handleOf = value => value && typeof value === "object" && Object.hasOwn(value, "ref") ? value.ref : typeof value === "string" ? value : null;

function gapTarget(typePath, path) {
	if (path.length >= 2 && ["values", "links"].includes(path[0])) return `${typePath}.${path[1]}`;
	if (path.length >= 2 && path[0] === "facets") return `${typePath}[${path[1]}]`;
	return typePath;
}

function targetName(target) {
	return typeof target === "string" ? target : target?.name ?? String(target);
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

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

/** Assemble a spec-02 JSON log from records, numbering claims in record order. */
export class ClaimsBuilder {
	constructor(model, ontology, scope, by) {
		this.model = model;
		this.data = { format: "onto.observations/1", obs: { ontology, scope }, sources: {}, instances: {}, claims: [], retractions: [] };
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
		const ctx = handleOf(record.ctx);
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

	finish() {
		for (const [handle, typePath] of Object.entries(this.implicit)) if (!Object.hasOwn(this.data.instances, handle)) this.data.instances[handle] = { type: typePath };
		this.data.instances = Object.fromEntries(Object.entries(this.data.instances).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
		return this.data;
	}
}

/** Report gaps, stale slots (their input produced a gap) and unidentified scope types. */
function documentGaps(records, gaps, scopes, src) {
	const bySource = new Map(records.map(record => [`${record.scope}\u0000${record.source}`, record]));
	const result = [], stale = [], unidentified = [];
	for (const entry of gaps) {
		const target = targetName(entry.target);
		const scope = Object.values(scopes).find(item => [`${item.name}RecordsProject`, `${item.name}RecordsSelect`].includes(target));
		const path = entry.path ?? [];
		const record = scope ? bySource.get(`${scope.name}\u0000${entry.source}`) : undefined;
		const gap = { target: scope ? gapTarget(scope.type, path) : target, reason: reasonCode(entry.reason), src };
		if (Object.hasOwn(entry, "source")) gap.location = entry.source;
		if (record && Object.hasOwn(record, "handle")) gap.handle = record.handle;
		if (record && record.origin && typeof record.origin === "object") gap.origin = record.origin;
		if (path[0] !== "formats") result.push(gap);
		if (!scope) continue;
		if (path[0] === "handle" || !record && target === `${scope.name}RecordsProject`) unidentified.push({ src, type: scope.type });
		else if (record && Object.hasOwn(record, "handle") && path.length >= 2 && ["values", "facets", "links"].includes(path[0])) {
			stale.push({ src, s: record.handle, [{ values: "p", facets: "facet", links: "verb" }[path[0]]]: path[1], reason: gap.reason });
		}
	}
	return [result, stale, unidentified];
}

function documentSummary(document, runTime) {
	const times = document.records.filter(record => typeof record.at === "string").map(record => record.at);
	const result = Object.fromEntries(["src", "replaces"].filter(key => Object.hasOwn(document, key)).map(key => [key, document[key]]));
	return { ...result, at: times[0] ?? runTime, records: document.records.filter(record => Object.hasOwn(record, "handle")).length };
}

/** `ClaimsEmit`: the run's spec-02 log, stale slots and gaps. */
export function emitClaims(program, documents, runTime) {
	const builder = new ClaimsBuilder(program.model, program.ontology, program.scope, program.by);
	const scopes = Object.fromEntries(program.scopes.map(scope => [scope.name, scope]));
	let stale = [], unidentified = [], gaps = [];
	const deleted = [], formats = {};
	for (const document of documents) {
		const alias = builder.alias(document.src);
		for (const record of document.records) {
			for (const [path, name] of Object.entries(record.formats ?? {})) {
				if (typeof name !== "string") continue;
				formats[path] ??= {};
				formats[path][name] = (formats[path][name] ?? 0) + 1;
			}
			if (!Object.hasOwn(record, "handle")) continue;
			const meta = { src: alias, at: typeof record.at === "string" ? record.at : runTime, by: builder.by };
			if (record.deleted === true) {
				deleted.push({ src: document.src, s: record.handle });
				if (document.replaces) meta.of = builder.alias(document.replaces);
			}
			builder.record(record, meta);
		}
		const [documentReport, documentStale, documentUnidentified] = documentGaps(document.records, document.gaps, scopes, document.src);
		gaps = gaps.concat(documentReport);
		stale = stale.concat(documentStale);
		unidentified = unidentified.concat(documentUnidentified);
	}
	return { log: builder.finish(), stale, unidentified, deleted, formats, gaps, documents: documents.map(document => documentSummary(document, runTime)) };
}

function needsClock(documents) {
	return documents.some(document => document.records.some(record => Object.hasOwn(record, "handle") && typeof record.at !== "string"));
}

/**
 * A binding program decoded from its `bindingProgramJson`, with its stages.
 * `implementations` supplies the code of declared library functions, by `Namespace/Name`.
 */
export function loadBindingProgram(data, model, { implementations = {}, registry = new Registry() } = {}) {
	registry.declareSlots(data.slots);
	registerFunctions(registry, data, implementations);
	const scopes = data.scopes.map(scope => ({ ...scope, shape: registry.decode(scope.shape), template: registry.decode(scope.template), outer: scope.outer.map(name => registry.get(name)) }));
	const program = { ...data, model, scopes };
	const [policy, options] = itemPolicy(data.mode);
	const pairs = scopes.map(scope => [selectStage(scope), namedStage(`${scope.name}RecordsProject`, each(project(scope.shape, scope.template, { outer: scope.outer }), policy, options))]);
	const collected = collect(named("scopesRead", function* (env, document) {
		let records = [];
		for (const [selecting, projecting] of pairs) {
			const occurrences = yield* selecting(env, document);
			records = records.concat(yield* projecting(env, occurrences));
		}
		return records;
	}));
	const DocumentRecordsCollect = named("DocumentRecordsCollect", function* (env, item) {
		const result = yield* collected(env, item.document);
		return { src: item.src, records: result.value, gaps: result.ledger, ...(Object.hasOwn(item, "replaces") ? { replaces: item.replaces } : {}) };
	});
	const ClaimsEmit = named("ClaimsEmit", function* (env, documents) {
		const runTime = needsClock(documents) || !documents.some(document => document.records.length) ? yield env.ClockRead() : null;
		return emitClaims(program, documents, runTime);
	});
	const DocumentsRead = namedStage("DocumentsRead", parallel(DocumentRecordsCollect, Policy.Abort));
	program.stages = { DocumentRecordsCollect, DocumentsRead, ClaimsEmit, BindingRead: namedStage("BindingRead", collect(pipe(DocumentsRead, ClaimsEmit))) };
	return program;
}

// EOF
