/**
 * Module: views — plan and retrieve rooted views over a host read catalogue, as `integrations/hexa/views.py`.
 *
 * The operator runs a bundle (`onto.view-bundle/1`) produced by Python's `viewBundle`. The host supplies
 * `access`, the only part that knows the source system:
 *
 * - `rootHandle(input, value, targetType)` translates a source identity into a target handle;
 * - `describe(step, value)` describes a read without performing it;
 * - `fetch(step, value)` performs it and resolves to `{document, source, emptyTypes?, emptyInputs?}`;
 *   a `ViewReadError` is reported with its reason;
 * - `discover(state, provides)` validates the bound response and returns the keys for the next read.
 *
 * `fetch` is needed only for reads without a request template; `describe` and `discover` have defaults, and an
 * optional `check(step, value, response)` checks a request's response, returning the document as `fetch` does.
 * Bundles and host operations are trusted inputs; the constructor checks the bundle format, not its full schema.
 *
 * A retrieval is one hexa run. A read with a request template is a `RequestSend` effect (an HTTP request, see
 * `hexa/http.js`); any other read is a `DocumentFetch` effect answered by `fetch`. Effects are journaled and
 * replayable, and the reads whose input is known run concurrently.
 */

import { Failure, SelectionRequest, codes, profile } from "hexa/shapes.js";
import { REGISTRY, member } from "hexa/core.js";
import { parallel, pipe, plan, validate } from "hexa/combinators.js";
import { run } from "hexa/runtime.js";
import { loadBindingProgram } from "./binding.js";
import { loadMappingProgram } from "./mapping.js";
import { Model, unkeyed } from "./model.js";
import { observationsFromJson, reconcileObservations, sourceState, sourceToken } from "./observations.js";
import { requestFor, requestSource, requestTemplate } from "./requests.js";
import { RE_NAME, RE_PATH, activeHandles, jsonEqual, observationStatus, pyJson, referenceHandles, valueKey } from "./values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

export const BUNDLE_FORMAT = "onto.view-bundle/1";
const RE_REASON = /^[A-Za-z][A-Za-z0-9]*$/;
const PROFILES = new Map();
// A read the host reports unavailable with reason `R` fails with the code `ViewRead.R`, declared on first use.
codes("ViewRead", "UnreadableResponse");

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

const hopKey = hop => hop.population + (hop.test !== undefined ? "?" : "");
const unwrap = raw => raw && raw.ledger && Object.hasOwn(raw, "value") ? raw.value : raw;

/** The code of a read unavailable for `reason`: `ViewRead.<reason>`, or `ViewRead.UnreadableResponse`. */
function readCode(reason) {
	const name = `ViewRead.${typeof reason === "string" && RE_REASON.test(reason) ? reason : "UnreadableResponse"}`;
	return REGISTRY.get(name) ?? member(name);
}

/**
 * How a report names a failed read: a `ViewReadError` or `ViewRead` code by its reason, another hexa code (a failed
 * request, say) by its qualified name, anything else as `UnreadableResponse`.
 */
function readReason(error) {
	if (error instanceof ViewReadError) return typeof error.reason === "string" && RE_REASON.test(error.reason) ? error.reason : "UnreadableResponse";
	if (!(error instanceof Failure) || ![Failure.Effect, Failure.Contract].includes(error.kind)) return "UnreadableResponse";
	const code = error.code.description.replace(/^member:/, "");
	return code.startsWith("ViewRead.") ? code.slice("ViewRead.".length) : code;
}

/**
 * The message of a failed read, as a report gives it to help resolve the failure: a hexa failure's host cause (spelled
 * as its journal records it), or the error itself; none when there is no message.
 */
function readDetail(error) {
	const cause = error instanceof Failure ? error.cause : error;
	return cause === undefined || cause === null ? {} : { detail: cause instanceof Error ? cause.message || cause.name : String(cause) };
}

/** `FailureClassify` for reads: a `ViewReadError` fails with its reason's code, any other error as unreadable. */
function readClassify(error) {
	return { code: readCode(error instanceof ViewReadError ? error.reason : null), transient: error?.transient === true };
}

const documentData = response => ({ document: response.document, source: response.source, emptyTypes: [...(response.emptyTypes ?? [])], emptyInputs: [...(response.emptyInputs ?? [])] });

/** The `DocumentFetch` operation over a host `fetch`; what it throws is classified by `readClassify`. */
function documentFetch(fetch) {
	return async (step, value) => documentData(await fetch(step, value));
}

/** Convert finite numeric text to a JSON number for numeric keys; otherwise retain the value. */
function keyValue(value, builtin) {
	if (typeof value !== "string" || !["Integer", "Number"].includes(builtin)) return value;
	const number = Number(value);
	return Number.isFinite(number) ? number : value;
}

/** Each planned read's provider: the earlier read that discovers its key; none for the seed's reads. */
function readProviders(steps, reads, seedKey) {
	const providers = new Map();
	for (const [index, name] of steps.entries()) {
		const key = reads[name].input.key;
		providers.set(name, key === seedKey ? null : steps.slice(0, index).find(other => reads[other].provides?.key === key) ?? null);
	}
	return providers;
}

/** Each planned read's wave: 0 without a provider, one more than its provider's otherwise. */
function readWaves(steps, providers) {
	const waves = new Map();
	for (const name of steps) {
		const provider = providers.get(name);
		waves.set(name, provider ? waves.get(provider) + 1 : 0);
	}
	return waves;
}

const ancestorOf = hop => typeof hop.test === "string" && hop.test.startsWith("@") ? hop.test.slice(1) : null;

function memberMatches(member, asked) {
	member = unkeyed(member);
	return member === asked || member.startsWith(asked + ".");
}

/** Render a planned traversal or filter for the diagnostic path. */
export function describeHop(hop) {
	if (hop.test !== undefined) return { on: hop.population, where: hop.field.path, equals: hop.test };
	return { from: hop.parent, bind: hop.population, via: hop.field.path, reverse: Boolean(hop.reverse), ...(hop.proves ? { proves: hop.proves } : {}) };
}

function describeWitness(state, witness) {
	const hop = witness.hop, data = { from: witness.subject, source: sourceToken(state, witness.claim) ?? null };
	if (hop.test !== undefined) return { ...data, where: hop.field.path, value: witness.value };
	return { ...data, via: hop.field.path, to: witness.value, ...(hop.reverse ? { reverse: true } : {}), ...(hop.proves ? { proves: hop.proves } : {}) };
}

/** `datetime.now(timezone.utc).isoformat(timespec="seconds")`. */
export function clockNow(date = new Date()) {
	return date.toISOString().slice(0, 19) + "+00:00";
}

/** A short stable name for request options (FNV-1a), as Python names its profiles by digest. */
function digest(text) {
	let hash = 0x811c9dc5;
	for (let index = 0; index < text.length; index++) hash = Math.imul(hash ^ text.charCodeAt(index), 0x01000193) >>> 0;
	return hash.toString(16).padStart(8, "0");
}

function selectionProfile(options) {
	const name = "OntoView" + digest(pyJson(options));
	if (!PROFILES.has(name)) PROFILES.set(name, profile(name, { requests: new Map([[SelectionRequest, options]]) }));
	return PROFILES.get(name);
}

/** A read failure the host attributes to the source; its `reason` is reported. */
export class ViewReadError extends Error {
	constructor(message, reason = "UnreadableResponse") {
		super(message);
		this.reason = reason;
	}
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** A per-run index of the reconciled claims usable in a rooted view. */
class Evidence {
	constructor(model, state) {
		Object.assign(this, { model, state, index: new Map() });
	}

	rows(field) {
		const key = valueKey(field);
		if (!this.index.has(key)) {
			const rows = [];
			const symmetric = field.relation && this.model.relations[field.relation]?.symmetric;
			for (const claim of this.state.claims) {
				if (claim.ctx !== undefined && claim.ctx !== null) continue; // These views request unqualified facts.
				if (field.relation && claim.rel === field.relation) {
					const [subject, other] = field.roles.map(role => claim.roles[role]);
					if (this.isA(subject, field.owner) && (other === "?" || this.isA(other, field.other))) rows.push([subject, other === "?" ? { unknown: true } : { ref: other }, claim]);
					if (subject !== other && symmetric && this.isA(other, field.owner)) rows.push([other, { ref: subject }, claim]);
				} else if (!field.relation && Object.hasOwn(claim, "p") && memberMatches(claim.p, field.member) && this.isA(claim.s, field.owner)) rows.push([claim.s, claim.v, claim]);
			}
			this.index.set(key, rows);
		}
		return this.index.get(key);
	}

	isA(handle, kind) {
		return this.model.isA(this.state.instances[handle]?.type ?? "", kind);
	}

	/** Retain every matching filter claim, or explain why none proves the filter. */
	test(hop, bindings) {
		const subject = bindings[hop.population];
		const checks = this.rows(hop.field).filter(([handle]) => handle === subject).map(([, value, claim]) => [value, claim]);
		if (checks.some(([, claim]) => claim.conflict)) return [[], "conflict"];
		const ancestor = ancestorOf(hop), witnesses = [];
		for (const [value, claim] of checks) {
			if (ancestor ? referenceHandles(value).includes(bindings[ancestor]) : jsonEqual(value, hop.test)) witnesses.push({ claim, hop, subject, value });
		}
		const states = new Set(checks.map(([value]) => observationStatus(value)));
		const status = states.has("unknown") ? "unknown" : states.size === 1 && states.has("absent") ? "absent" : states.size === 1 && states.has("supplied") ? "notMatched" : "missing";
		return [witnesses, status];
	}

	/** Reached bindings and first stops; `blocked` can rule out a hop before inspection. */
	walk(view, population, root, blocked) {
		let paths = [[{ [view.root]: root }, []]];
		const stops = [], chain = view.paths[population];
		for (const [index, hop] of chain.entries()) {
			if (hop.test !== undefined) continue; // Applied with the edge that bound its candidate.
			const guard = index + 1 < chain.length && chain[index + 1].test !== undefined ? chain[index + 1] : null;
			const reached = [];
			for (const [bindings, trail] of paths) {
				const handle = bindings[hop.parent];
				const why = blocked(hop, bindings);
				if (why) {
					stops.push({ subject: handle, stoppedAt: hop.field.path, statuses: [why], path: trail });
					continue;
				}
				let status = "missing";
				const branches = [], rejected = [];
				for (const [subject, value, claim] of this.rows(hop.field)) {
					const found = observationStatus(value);
					if (!hop.reverse && subject === handle && found !== "supplied") {
						status = claim.conflict ? "conflict" : found;
						continue;
					}
					for (const other of referenceHandles(value)) {
						const [start, end] = hop.reverse ? [other, subject] : [subject, other];
						if (start !== handle || !this.isA(end, view.populations[hop.population].type)) continue;
						if (claim.conflict) { status = "conflict"; continue; }
						const bound = { ...bindings, [hop.population]: end }, witness = { claim, hop, subject: handle, value: end };
						if (guard) {
							let reason = blocked(guard, bound), proofs = [];
							if (!reason) [proofs, reason] = this.test(guard, bound);
							if (!proofs.length) {
								rejected.push({ subject: end, stoppedAt: guard.field.path, statuses: [reason], path: [...trail, witness] });
								continue;
							}
							for (const proof of proofs) branches.push([bound, [...trail, witness, proof]]);
						} else branches.push([bound, [...trail, witness]]);
					}
				}
				reached.push(...branches);
				stops.push(...rejected.filter(item => !branches.length || valueKey(item.statuses) !== valueKey(["notMatched"])));
				if (!branches.length && !rejected.length) stops.push({ subject: handle, stoppedAt: hop.field.path, statuses: [status], path: trail });
			}
			paths = reached;
			if (!paths.length) break;
		}
		return [paths, stops];
	}
}

/** Plan, read, map and project the rooted views of a bundle. */
export class ViewOperator {
	/**
	 * `implementations`: the code of declared library functions, by `Namespace/Name`. `operations`: hexa host
	 * operations for every run, `RequestSend` for reads with a request template (e.g. from `hexa/http.js`) and
	 * optionally `FailureClassify`.
	 */
	constructor(bundle, { access, implementations = {}, operations = {} }) {
		if (bundle.format !== BUNDLE_FORMAT) throw new Error(`expected ${BUNDLE_FORMAT}`);
		this.bundle = bundle;
		this.access = access;
		this.operations = operations;
		this.sourceModel = new Model(bundle.source);
		this.targetModel = new Model(bundle.target);
		this.views = Object.fromEntries(Object.entries(bundle.views).map(([name, view]) => [name, {
			...view, guarded: new Map(view.guardedLinks.map(([parent, relation, roles, alias]) => [valueKey([parent, relation, roles]), alias])),
		}]));
		this.reads = bundle.reads;
		this.keyTypes = bundle.keyTypes;
		this.programs = {};
		for (const [key, program] of Object.entries(bundle.bindings)) this.programs[key] = loadBindingProgram(program, this.sourceModel, { implementations });
		this.mapping = loadMappingProgram(bundle.mapping, this.sourceModel, this.targetModel, { implementations });
	}

	/** The catalogue reachable from the seed, in prerequisite order with ties in catalogue order. */
	readSteps(seedKey) {
		const providers = new Map([[seedKey, null]]), steps = {};
		for (;;) {
			const ready = Object.entries(this.reads).filter(([step, read]) => !Object.hasOwn(steps, step) && providers.has(read.input.key));
			if (!ready.length) break;
			for (const [name, read] of ready) {
				const parent = providers.get(read.input.key);
				steps[name] = { requires: parent ? [parent] : [], capability: name };
				const key = read.provides?.key;
				if (key && key !== seedKey) {
					if (providers.has(key)) throw new Error(`ambiguous providers of ${key}: ${providers.get(key)}, ${name}`);
					providers.set(key, name);
				}
			}
		}
		return steps;
	}

	/** Resolve selectors to declared projections, preferring exact population names. */
	select(view, fields) {
		const rooted = this.views[view];
		if (fields === null || fields === undefined) return { ...rooted.defaults };
		if (!fields.length) throw new Error("select at least one field declared by this view");
		const result = {};
		for (const spelling of fields) {
			if (Object.hasOwn(rooted.selections, spelling)) { result[spelling] = spelling; continue; }
			const keys = rooted.typeSelections[spelling] ?? [];
			if (!keys.length) throw new Error(`unknown view field '${spelling}'`);
			if (keys.length > 1) throw new Error(`ambiguous view field '${spelling}'; select one of ${keys.join(", ")}`);
			result[spelling] = keys[0];
		}
		return result;
	}

	/** Check the concrete JSON argument against its declared source key before using it for a read. */
	checkValue(input, value) {
		const t = this.keyTypes[input.key];
		let ok;
		if (t.builtin === "Integer") ok = Number.isSafeInteger(value);
		else if (t.builtin === "Number") ok = typeof value === "number" && Number.isFinite(value);
		else if (t.kind === "vocab") ok = typeof value === "string" && (t.hierarchical ? RE_PATH : RE_NAME).test(value) && (t.open || t.values.includes(value));
		else ok = typeof value === "string";
		if (!ok) throw new Error(`${input.name} requires ${t.builtin || t.path || "a vocabulary value"} for ${input.key}`);
	}

	/** Plan the required reads for a view without fetching documents (`onto.view-plan/1`). */
	async plan(view, seed, fields = null) {
		const rooted = this.views[view];
		if (!rooted) throw new Error(`unknown rooted view ${view}`);
		const param = rooted.input;
		if (valueKey(Object.keys(seed)) !== valueKey([param.name])) throw new Error(`${view} requires ${param.name}: ${param.key}`);
		const value = seed[param.name];
		this.checkValue(param, value);
		const kind = rooted.populations[rooted.root].type;
		const handle = this.access.rootHandle(param, value, rooted.rootTarget);
		const wanted = this.select(view, fields), steps = this.readSteps(param.key), matches = rooted.matches;
		const supplier = Object.fromEntries(Object.entries(matches).map(([key, entries]) => [key, entries.length ? entries[0].supplier : null]));
		const dependents = new Map(), paths = {}, outputs = {};
		for (const [spelling, key] of Object.entries(wanted)) {
			const [alias, field] = rooted.selections[key];
			const child = rooted.guarded.get(valueKey([alias, field.relation ?? "", field.roles ?? []]));
			const chain = rooted.paths[child ?? alias];
			paths[spelling] = { population: alias, hops: chain.map(hop => ({ ...describeHop(hop), supplier: supplier[hopKey(hop)] ?? null })), leaf: field.path, ...(child ? { objectPopulation: child } : {}) };
			outputs[spelling] = supplier[key] ?? null;
			// Onto orders the proof. Hexa schedules each obligation up to and including the first static gap.
			for (const [obligation, at] of [...chain.map(hop => [hopKey(hop), hop.field.path]), [key, field.path]]) {
				if (!dependents.has(obligation)) dependents.set(obligation, []);
				dependents.get(obligation).push([spelling, at]);
				if (!supplier[obligation]) break;
			}
		}
		const obligations = [...dependents.keys()];
		const attributes = Object.fromEntries(Object.entries(matches).map(([key, entries]) => [key, { correspondences: entries }]));
		const options = { versions: [1], entitySets: { Proof: Object.keys(attributes) }, relations: [], maxSelections: 1, maxRelations: 0 };
		const env = { policy: { profile: selectionProfile(options), allow: Object.keys(steps) }, vocabulary: { SelectionRequest: { steps, entitySets: { Proof: { type: kind, attributes } } } } };
		const compiled = await run(env, pipe(validate(SelectionRequest), plan(SelectionRequest)), { version: 1, selections: { Proof: { from: "Proof", attributes: obligations } } });
		const reads = compiled.steps.map(({ step: name }) => {
			const read = this.reads[name];
			return { step: name, input: read.input.name, requires: steps[name].requires, bindings: read.bindingNames,
				...this.describeRead(name, read.input.key === param.key ? value : `{${read.input.name}}`) };
		});
		const gaps = [];
		for (const gap of compiled.gaps) {
			for (const [spelling, at] of dependents.get(obligations[gap.path.at(-1)])) {
				gaps.push({ field: spelling, reason: gap.code, stoppedAt: at });
				outputs[spelling] = null;
			}
		}
		return { format: "onto.view-plan/1", view, seed: { ...seed }, root: { role: rooted.root, type: kind.slice(this.targetModel.namespace.length + 1), handle },
			fields: outputs, paths, steps: reads, gaps };
	}

	/**
	 * The plan and receipts, the reconciled target state and the read outcomes, before projection.
	 *
	 * One hexa run reads, binds and maps. A read with a request template is a `RequestSend` effect; another read is
	 * a `DocumentFetch(step, value)` effect answered by `fetch` (default `access.fetch`). Reads run in waves: a
	 * wave's effects are performed concurrently (`parallel`), each distinct request once, then its reads are
	 * checked, bound and accounted for in plan order. `now` fixes the clock; `operations` add to the operator's;
	 * `record` (a journal sink), `replay`, `signal` and `policy` (retry, concurrency) go to the run. A failed read
	 * is reported by reason and message; its outcome keeps the failure, and the journal a failed effect's details.
	 */
	async runReads(view, seed, fields = null, { now = clockNow(), fetch = (step, value) => this.access.fetch(step, value), operations = {}, record, replay, signal, policy = {} } = {}) {
		const result = await this.plan(view, seed, fields);
		const param = this.views[view].input, steps = result.steps.map(item => item.step);
		const providers = readProviders(steps, this.reads, param.key), waves = readWaves(steps, providers);
		// A replayed journal may name host reasons this process has not declared yet.
		for (const entry of replay ?? []) if (typeof entry?.failure?.code === "string" && entry.failure.code.startsWith("ViewRead.")) readCode(entry.failure.code.slice("ViewRead.".length));
		const env = { FailureClassify: readClassify, ...this.operations, ...operations, ClockRead: () => now, DocumentFetch: documentFetch(fetch),
			policy: { maxNodes: 500000, ...policy }, ...(record ? { record } : {}), ...(replay ? { replay } : {}), ...(signal ? { signal } : {}) };
		const operator = this;
		const send = parallel(function* ReadSend(env, [operation, ...args]) {
			try { return { status: "ok", result: yield env[operation](...args) }; }
			catch (error) {
				if (error instanceof Failure && error.kind === Failure.Defect) throw error;
				return { status: "unavailable", reason: readReason(error), failure: error };
			}
		});
		function* ViewRetrieve(env) {
			const values = new Map(), outputs = new Map(), sent = new Map();
			for (let wave = 0; wave <= Math.max(-1, ...waves.values()); wave++) {
				const names = steps.filter(name => waves.get(name) === wave), items = [], effects = new Map();
				for (const name of names) {
					values.set(name, operator.readValues(name, providers.get(name), param, seed, outputs));
					for (const value of values.get(name)) {
						const item = operator.readEffect(name, value);
						items.push([name, value, item]);
						if (item.key !== undefined && !sent.has(item.key) && !effects.has(item.key)) effects.set(item.key, item.effect);
					}
				}
				const results = effects.size ? yield* send(env, [...effects.values()]) : [];
				[...effects.keys()].forEach((key, index) => sent.set(key, results[index]));
				for (const name of names) outputs.set(name, []);
				for (const [name, value, item] of items) outputs.get(name).push(yield* operator.readProcess(env, name, value, item, sent.get(item.key)));
			}
			const logs = steps.flatMap(name => outputs.get(name).flatMap(output => output.status === "ok" ? output.logs : []));
			return { values, outputs, mapped: logs.length ? unwrap(yield* operator.mapping.stages.MappingRead(env, sourceState(operator.sourceModel, logs))) : null };
		}
		const { values, outputs, mapped } = await run(env, ViewRetrieve);
		const emptyInputs = new Set(), calls = [], outcomes = new Map();
		const outcome = (name, item) => { if (!outcomes.has(name)) outcomes.set(name, []); outcomes.get(name).push(item); };
		for (const name of steps) {
			const read = this.reads[name];
			if (!values.get(name).length) {
				outcome(name, { handles: new Set(), status: emptyInputs.has(read.input.key) ? "empty" : "unavailable", emptyTypes: [] });
				if (!emptyInputs.has(read.input.key)) result.gaps.push({ step: name, reason: "MissingInput", input: read.input.name });
			}
			values.get(name).forEach((value, index) => {
				const output = outputs.get(name)[index], ok = output.status === "ok";
				const receipt = { step: name, input: { [read.input.name]: value }, ...this.describeRead(name, value), status: output.status };
				calls.push(receipt);
				result.gaps.push(...output.gaps);
				if (ok) {
					for (const key of output.emptyInputs) emptyInputs.add(key);
					if (read.provides) receipt.discovered = { [read.provides.name]: output.discovered };
				} else result.gaps.push({ step: name, input: receipt.input, reason: output.reason, ...readDetail(output.failure) });
				const handles = new Set(this.bundle.inputTargets[read.input.key].map(kind => this.access.rootHandle(read.input, value, kind)));
				outcome(name, { handles, status: output.status, emptyTypes: ok ? output.emptyTypes : [], ...(ok ? {} : { failure: output.failure }) });
			});
		}
		let state = { format: "onto.observations/1", obs: { ontology: this.targetModel.namespace, scope: null }, sources: {}, instances: {}, claims: [], retractions: [] };
		if (mapped) {
			result.gaps.push(...mapped.gaps.map(gap => ({ target: gap.target, reason: gap.reason, src: gap.src ?? null, location: gap.location ?? null, handle: gap.handle ?? null, origin: gap.origin ?? null })));
			const { warnings, ...reconciled } = reconcileObservations(this.targetModel, observationsFromJson(mapped.log));
			state = reconciled;
		}
		result.calls = calls;
		return [result, state, outcomes];
	}

	/** The host's description of a read, else its request (its template while the value is the placeholder `{name}`). */
	describeRead(name, value) {
		if (typeof this.access?.describe === "function") return this.access.describe(name, value);
		const read = this.reads[name];
		if (!read.request) return {};
		return value === `{${read.input.name}}` ? requestTemplate(read) : requestFor(read, value);
	}

	/** A read's input values: the seed, or what its `provider` (an earlier wave) discovered, in order. */
	readValues(name, provider, param, seed, outputs) {
		if (this.reads[name].input.key === param.key) return [seed[param.name]];
		return [...new Set((provider ? outputs.get(provider) : []).flatMap(output => output.status === "ok" ? output.discovered : []))];
	}

	/** The effect a read needs, `[operation, ...arguments]`, keyed so that equal requests are sent once. */
	readEffect(name, value) {
		const read = this.reads[name];
		let effect;
		try { effect = read.request ? ["RequestSend", requestFor(read, value)] : ["DocumentFetch", name, value]; }
		catch (error) {
			if (error instanceof Failure) return { failure: error };
			throw error;
		}
		return { effect, key: valueKey(effect) };
	}

	/** The document of a read from its effect's result: a request's response, checked by the host's `check`. */
	readDocument(name, value, effect, result) {
		if (effect[0] === "DocumentFetch") return result;
		const read = this.reads[name], request = effect[1], source = requestSource(read, request, value);
		if (typeof this.access?.check !== "function") return { document: result.data, source, emptyTypes: [], emptyInputs: [] };
		// Reads sharing a request share its response; each checks a copy of its own.
		return documentData(this.access.check(name, value, { request, status: result.status, data: structuredClone(result.data), source }));
	}

	/** Without a host `discover`: the provided key's values on the bound instances of its type, in claim order. */
	discoverKeys(state, provides) {
		if (!provides) return [];
		const builtin = this.keyTypes[provides.key]?.builtin, found = [];
		for (const claim of state.claims) {
			const instance = state.instances[claim.s], value = claim.v;
			if (claim.p === provides.attr && !claim.conflict && instance && this.sourceModel.isA(instance.type, provides.path)
				&& ["string", "number"].includes(typeof value)) found.push(keyValue(value, builtin));
		}
		return [...new Set(found)];
	}

	/** One read after its effect: the document, its bindings and discovered keys. A failure makes it unavailable, with a reason. */
	*readProcess(env, name, value, item, sent) {
		const read = this.reads[name], gaps = [], logs = [];
		if (item.failure) return { status: "unavailable", gaps: [], reason: readReason(item.failure), failure: item.failure };
		if (sent.status !== "ok") return { status: "unavailable", gaps: [], reason: sent.reason, failure: sent.failure };
		try {
			const response = this.readDocument(name, value, item.effect, sent.result);
			for (const key of read.bindings) {
				const bound = unwrap(yield* this.programs[key].stages.BindingRead(env, [{ src: response.source, document: response.document }]));
				logs.push(bound.log);
				gaps.push(...bound.gaps.map(gap => ({ step: name, target: gap.target, reason: gap.reason, src: gap.src ?? null, location: gap.location ?? null, handle: gap.handle ?? null, origin: gap.origin ?? null })));
			}
			const state = sourceState(this.sourceModel, logs);
			const discovered = typeof this.access?.discover === "function" ? [...this.access.discover(state, read.provides ?? null)] : this.discoverKeys(state, read.provides);
			if (read.provides) for (const key of discovered) this.checkValue(read.provides, key);
			return { status: "ok", logs, gaps, discovered, emptyTypes: response.emptyTypes, emptyInputs: response.emptyInputs };
		} catch (error) {
			if (error instanceof Failure && error.kind === Failure.Defect) throw error;
			return { status: "unavailable", gaps, reason: readReason(error), failure: error };
		}
	}

	/** Only the leaves reached from this seed, with the claims that established each path. */
	project(state, result, outcomes, selected = null) {
		const facts = [], coverage = [], view = this.views[result.view];
		const graph = new Evidence(this.targetModel, state), root = result.root.handle;
		const gaps = Object.fromEntries(result.gaps.filter(gap => Object.hasOwn(gap, "field")).map(gap => [gap.field, gap.reason]));
		for (const [spelling, key] of Object.entries(this.select(result.view, Object.keys(result.fields)))) {
			const [alias, field] = view.selections[key];
			const supplier = result.fields[spelling], path = result.paths[spelling], child = path.objectPopulation;
			const chain = view.paths[child ?? alias];
			const hopSuppliers = new Map(chain.map((hop, index) => [hopKey(hop), path.hops[index].supplier]));
			const blocked = (step, population, bindings, other = "") => {
				if (!step) return gaps[spelling] === "SelectionRequest.NotSupplied" ? "notSupplied" : "unmapped";
				let cases = outcomes.get(step) ?? [];
				for (const handle of Object.values(bindings).reverse()) {
					const scoped = cases.filter(item => item.handles.has(handle));
					if (scoped.length) { cases = scoped; break; }
				}
				if (cases.length && cases.every(item => item.status === "unavailable")) return "unavailable";
				if (cases.length && cases.every(item => item.status === "empty" || item.emptyTypes.includes(view.populations[population].type) || item.emptyTypes.includes(other))) return "empty";
				return null;
			};
			const [reached, stops] = graph.walk(view, child ?? alias, root, (hop, bound) => blocked(hopSuppliers.get(hopKey(hop)), hop.population, bound));
			if (selected === null) coverage.push(...stops.map(stop => ({ field: spelling, population: alias, ...stop, path: stop.path.map(witness => describeWitness(state, witness)) })));
			const incoming = view.paths[alias].find(hop => hop.population === alias && hop.test === undefined);
			const returnsToParent = field.relation && incoming && incoming.field.relation === field.relation
				&& valueKey(field.roles) === valueKey(incoming.reverse ? incoming.field.roles : [...incoming.field.roles].reverse());
			for (const [bindings, trail] of reached) {
				const handle = bindings[alias], seen = new Set();
				const reason = blocked(supplier, alias, bindings, field.other ?? "");
				for (const [subject, value, claim] of reason === null ? graph.rows(field) : []) {
					if (subject !== handle) continue;
					if (returnsToParent && value?.ref !== bindings[incoming.parent]) continue; // Returning a filing/review link back to the root must preserve that root.
					if (child) {
						const edge = trail.at(-2).claim; // The last witness is the object filter, immediately after its incoming edge.
						if (value?.ref !== bindings[child] || Object.hasOwn(edge, "rel") && edge !== claim) continue;
					}
					if (selected !== null) {
						selected.add(claim);
						for (const witness of trail) selected.add(witness.claim);
						continue;
					}
					const member = claim.p ?? field.member;
					facts.push({ field: spelling, population: alias, subject: handle, value, source: sourceToken(state, claim) ?? null,
						path: trail.map(witness => describeWitness(state, witness)), ...(member !== field.member ? { member } : {}),
						...Object.fromEntries(["cur", "unit", "period", "scale", "valid", "at", "ctx", "conflict"].filter(name => Object.hasOwn(claim, name)).map(name => [name, claim[name]])) });
					seen.add(claim.conflict ? "conflict" : value && typeof value === "object" && value.partial ? "partial" : observationStatus(value));
				}
				if (selected === null) {
					coverage.push({ field: spelling, population: alias, subject: handle, statuses: [...(seen.size ? seen : new Set([reason ?? "missing"]))].sort(),
						...(seen.has("supplied") ? {} : { stoppedAt: field.path, path: trail.map(witness => describeWitness(state, witness)) }) });
				}
			}
		}
		return [facts, coverage];
	}

	/** Explain the reads, proven answers and missing links (`onto.view-report/1`). */
	async report(view, seed, fields = null, options = {}) {
		const [result, state, outcomes] = await this.runReads(view, seed, fields, options);
		result.format = "onto.view-report/1";
		[result.facts, result.coverage] = this.project(state, result, outcomes);
		return result;
	}

	/** Native observations: the selected claims and the evidence that connects them to the seed. */
	async retrieve(view, seed, fields = null, options = {}) {
		const [result, state, outcomes] = await this.runReads(view, seed, fields, options);
		return this.retrieved(state, result, outcomes);
	}

	retrieved(state, result, outcomes) {
		const selected = new Set();
		this.project(state, result, outcomes, selected);
		const claims = state.claims.filter(claim => selected.has(claim));
		const handles = activeHandles(claims), sources = new Set(claims.map(claim => claim.src));
		const header = Object.fromEntries(Object.entries(state.obs).filter(([key]) => ["ontology", "rev", "scope"].includes(key)));
		for (const key of ["at", "by", "src", "conf"]) if (claims.length && Object.hasOwn(claims[0], key) && claims.every(claim => claim[key] === claims[0][key])) header[key] = String(claims[0][key]);
		return { format: "onto.observations/1", obs: header, sources: Object.fromEntries(Object.entries(state.sources).filter(([key]) => sources.has(key))),
			instances: Object.fromEntries(Object.entries(state.instances).filter(([handle]) => handles.has(handle)).map(([handle, item]) => [handle, { type: item.type }])),
			claims, retractions: [] };
	}
}

// EOF
