/**
 * Module: sessions — page views over a system's reads and an observation store, and changes routed to each slot's
 * holder (spec-09 Sessions), as `integrations/hexa/sessions.py`, from a session bundle (`onto.view-bundle/3`).
 *
 * A `SessionViewOperator` plans a view as `ViewOperator` does for its system, then gives the obligations on slots the
 * store holds to store reads of the partition kinds that reach them. A `Session` keeps the state of the view it opened
 * and routes a change set: the store's slots to their home partitions, the system's to its operations (read-only here).
 *
 * The host adds two functions to a view host's: `storeRead(body)`, a batch read of partitions, and
 * `storeAppend(partition, body)`, an append, such as a store client's `stateMany` and `append`. A refusal is a
 * `StoreError`; any other failure is an append without an answer.
 */

import { claimSlot } from "./observations.js";
import { StoreError } from "./store/errors.js";
import { ORIGIN_SHARED, ORIGIN_STORE, elementPath, holds, isA, originOf, related, unkeyedPath } from "./store/origins.js";
import { encodeKey, referenceHandles, valueKey } from "./values.js";
import { Evidence, SESSION_BUNDLE_FORMAT, ViewOperator, readWaves } from "./views.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const SLOT_KEYS = ["s", "p", "facet", "exists", "rel", "roles", "ctx"];
const pick = (item, keys) => Object.fromEntries(keys.filter(key => Object.hasOwn(item, key)).map(key => [key, item[key]]));
/** A slot's identity: subject, member and context (spec-02). */
const slotKey = item => claimSlot(pick(item, SLOT_KEYS));

/** A UUID of version 7: its first 48 bits the time in milliseconds, the rest random (RFC 9562). */
export function uuid7(now = Date.now()) {
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	for (let index = 0; index < 6; index++) bytes[index] = Math.floor(now / 2 ** (8 * (5 - index))) % 256;
	bytes[6] = (bytes[6] & 0x0f) | 0x70;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = [...bytes].map(byte => byte.toString(16).padStart(2, "0")).join("");
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** Plan and retrieve page views over one system's reads and a store (spec-09 "Page views"). */
export class SessionViewOperator extends ViewOperator {
	/** `bundle` is a session bundle; `scope` the store's scope, which its own handles carry. */
	constructor(bundle, { scope, ...options }) {
		if (bundle.format !== SESSION_BUNDLE_FORMAT) throw new Error(`expected ${SESSION_BUNDLE_FORMAT}`);
		super(bundle, options);
		this.store = bundle.store;
		this.scope = scope;
		this.system = bundle.source.namespace;
		this.storeName = this.store.store;
		this.kinds = Object.fromEntries(this.store.kinds.map(kind => [kind.kind, kind]));
	}

	// -- Holders -----------------------------------------------------------------

	/** The origin of the instances of `type` a view reaches: the system when it produces the type, else the store. */
	typeOrigin(type) {
		return (this.store.origins[type]?.systems ?? []).includes(this.system) ? this.system : ORIGIN_STORE;
	}

	/** Who holds a field of instances of `subjectType` (spec-09 "Holders"). */
	fieldHolder(subjectType, field) {
		const claim = field.relation ? { rel: field.relation } : { p: field.member };
		return holds(this.store, this.typeOrigin(subjectType), subjectType, claim) ? this.storeName : this.system;
	}

	/** The keyed elements of a field the system fills for its instances, when the store holds its others (spec-09 "Keyed elements"). */
	keyedHolders(subjectType, field) {
		if (field.relation || this.typeOrigin(subjectType) !== this.system) return {};
		const found = {};
		for (const system of this.store.systems) {
			if (system.name !== this.system) continue;
			for (const [target, filled] of Object.entries(system.types)) {
				if (!related(this.store, subjectType, target)) continue;
				for (const path of filled.attrs.map(elementPath)) if (path.includes("[") && unkeyedPath(path) === field.member) found[path] = this.system;
			}
		}
		return Object.fromEntries(Object.entries(found).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
	}

	/** Who holds the slot a claim states, by its subject's origin; null when the subject has no origin. */
	claimHolder(claim, instances) {
		const subject = this.subjectOf(claim), type = instances[subject]?.type;
		const origin = type ? originOf(this.store, subject, type, this.scope) : null;
		if (origin === null) return null;
		if (holds(this.store, origin, type, claim)) return this.storeName;
		return origin === ORIGIN_SHARED || origin === this.system ? this.system : origin;
	}

	/** A statement's subject: its `s`, a binary relation's first participant, an identity link's first handle. */
	subjectOf(claim) {
		if (Object.hasOwn(claim, "s")) return claim.s;
		if (Object.hasOwn(claim, "rel")) return claim.roles[this.targetModel.get(claim.rel).participants[0].role];
		return (claim.same ?? claim.distinct)[0];
	}

	// -- Planning ----------------------------------------------------------------

	/** The view's populations a store's partitions hold: alias -> [kind, the kind's population, the anchor's alias]. */
	matched(rooted) {
		const found = {};
		for (const [alias, population] of Object.entries(rooted.populations)) {
			const kind = this.store.kinds.find(item => isA(this.store, population.type, item.root.type));
			if (kind) found[alias] = [kind.kind, kind.root.name, alias];
		}
		let changed = true;
		while (changed) {
			changed = false;
			for (const [alias, path] of Object.entries(rooted.paths)) {
				const hop = path.find(item => item.population === alias && item.test === undefined);
				if (Object.hasOwn(found, alias) || !hop || !Object.hasOwn(found, hop.parent)) continue;
				const [kindName, parentName, anchor] = found[hop.parent], type = rooted.populations[alias].type;
				for (const population of this.kinds[kindName].populations) {
					const link = population.link;
					const follows = hop.field.relation ? link.rel === hop.field.relation : link.slot === hop.field.member && link.on === (hop.reverse ? "member" : "parent");
					if (population.parent === parentName && follows && (isA(this.store, type, population.type) || isA(this.store, population.type, type))) {
						found[alias] = [kindName, population.name, anchor];
						changed = true;
						break;
					}
				}
			}
		}
		return found;
	}

	/** Give the store the obligations on slots it holds: store reads, holders and writability (spec-09 "Results"). */
	storePlan(view, fields, result) {
		const rooted = this.views[view], matched = this.matched(rooted), pages = rooted.pages ?? {};
		const providers = new Map(result.steps.map(step => [step.step, step.requires[0] ?? null]));
		const later = Math.max(-1, ...readWaves([...providers.keys()], providers).values()) + 1;
		const steps = new Map(), selections = new Map(), populations = new Map();
		const storeStep = alias => {
			const [kindName, populationName, anchor] = matched[alias];
			const name = anchor === rooted.root ? `store:${kindName}` : `store:${kindName}:${anchor}`;
			if (!steps.has(name)) steps.set(name, { step: name, kind: "store", partitionKind: kindName, anchor, wave: anchor === rooted.root ? 0 : later });
			if (!populations.has(name)) populations.set(name, {});
			populations.get(name)[populationName] = alias;
			return name;
		};
		const select = (alias, member) => {
			if (!Object.hasOwn(matched, alias)) return null;
			const name = storeStep(alias), key = valueKey([name, matched[alias][1]]);
			if (!selections.has(key)) selections.set(key, [name, matched[alias][1], new Set()]);
			selections.get(key)[2].add(member);
			return name;
		};
		const wanted = this.select(view, fields);
		const holders = {}, writable = {}, unhomed = new Set(), keyedHolders = {};
		for (const [spelling, key] of Object.entries(wanted)) {
			const { population: alias, field } = rooted.selections[key];
			const holder = holders[spelling] = this.fieldHolder(rooted.populations[alias].type, field);
			const attr = field.relation ? undefined : this.targetModel.lookup(field.owner, field.member);
			writable[spelling] = holder === this.storeName && !attr?.derived;
			if (holder !== this.storeName) continue;
			const keyed = this.keyedHolders(rooted.populations[alias].type, field);
			if (Object.keys(keyed).length) keyedHolders[spelling] = keyed;
			const supplier = select(alias, field.member);
			const path = result.paths[spelling];
			rooted.paths[path.objectPopulation ?? alias].forEach((hop, index) => {
				const route = path.hops[index];
				if (route.supplier !== null || hop.test !== undefined) return;
				// NOTE: A member's own link is selected with it; a parent's link, with the parent.
				const owner = hop.reverse ? hop.population : hop.parent;
				if (this.fieldHolder(rooted.populations[owner].type, hop.field) === this.storeName) {
					route.supplier = select(owner, hop.field.relation ? hop.field.relation : hop.field.member);
					if (Object.hasOwn(matched, hop.population)) select(hop.population, "exists");
				}
			});
			// NOTE: A field whose keyed elements a system fills keeps that system's supplier beside the store's.
			const systemSupplier = Object.hasOwn(keyedHolders, spelling) ? result.fields[spelling] : null;
			result.fields[spelling] = systemSupplier ? (supplier ? [systemSupplier, supplier] : systemSupplier) : supplier;
			if (supplier === null) unhomed.add(spelling);
		}
		const stored = new Set(Object.entries(holders).filter(([spelling, holder]) => holder === this.storeName && !Object.hasOwn(keyedHolders, spelling)).map(([spelling]) => spelling));
		result.gaps = [...result.gaps.filter(gap => !stored.has(gap.field)),
			...[...unhomed].sort().map(spelling => ({ field: spelling, reason: "Store.Unhomed", stoppedAt: rooted.selections[wanted[spelling]].field.path }))];
		for (const [name, populationName, members] of selections.values()) {
			const step = steps.get(name), alias = populations.get(name)[populationName], kind = this.kinds[step.partitionKind];
			const slots = [...members].filter(member => member !== "exists").sort();
			const entry = populationName === kind.root.name ? { s: "{anchor}", slots }
				: { population: populationName, slots, ...(Object.hasOwn(pages, alias) ? { page: { size: pages[alias] } } : {}) };
			(step.select ??= []).push(entry);
		}
		result.storeSteps = [...steps.values()];
		result.holders = holders;
		result.writable = writable;
		result.keyedHolders = keyedHolders;
		return result;
	}

	/** Plan a view's system reads and store reads, with each field's holder and writability. */
	async plan(view, seed, fields = null) {
		const result = this.storePlan(view, fields, await super.plan(view, seed, fields));
		result.steps = [...result.steps, ...result.storeSteps];
		delete result.storeSteps;
		return result;
	}

	// -- Retrieval ---------------------------------------------------------------

	/** One wave's store reads, one per partition of each step's anchors, with the step and anchor of each. */
	static storeRequests(steps, anchorsOf) {
		const reads = [], owners = [];
		for (const step of steps) for (const anchor of anchorsOf(step)) {
			reads.push({ partition: `${step.partitionKind}/${anchor}`, select: step.select.map(entry => entry.s === "{anchor}" ? { ...entry, s: anchor } : entry) });
			owners.push([step, anchor]);
		}
		return [reads, owners];
	}

	/** Run the store reads of the first wave, the system's reads, then the later store reads, and keep each claim from its slot's holder. */
	async runReads(view, seed, fields = null, options = {}) {
		const rooted = this.views[view];
		const planned = await super.plan(view, seed, fields);
		// NOTE: When `rootHandle` gives the root's handle from the seed, the root's store read needs no system read.
		const early = planned.root.handle;
		const first = early ? this.storePlan(view, fields, structuredClone(planned)).storeSteps.filter(step => step.wave === 0) : [];
		let [reads, owners] = SessionViewOperator.storeRequests(first, () => [early]);
		const answers = reads.length ? [...(await this.access.storeRead({ reads })).results] : [];
		let [result, state, outcomes] = await super.runReads(view, seed, fields, { ...options, planned });
		result = this.storePlan(view, fields, result);
		const root = result.root.handle;
		let graph = null;
		const anchorsOf = step => {
			if (step.anchor === rooted.root) return root ? [root] : [];
			graph ??= new Evidence(this.targetModel, state);
			const [reached] = graph.walk(rooted, step.anchor, root, () => null);
			return [...new Set(reached.map(([bindings]) => bindings[step.anchor]))];
		};
		const done = new Set(first.map(step => step.step));
		const [later, laterOwners] = SessionViewOperator.storeRequests(result.storeSteps.filter(step => !done.has(step.step)), anchorsOf);
		if (later.length) answers.push(...(await this.access.storeRead({ reads: later })).results);
		reads = [...reads, ...later];
		owners = [...owners, ...laterOwners];
		const kept = holder => holder === this.system || holder === null;
		const claims = state.claims.filter(claim => kept(this.claimHolder(claim, state.instances)));
		const offAuthority = state.claims.filter(claim => !kept(this.claimHolder(claim, state.instances)));
		const instances = { ...state.instances };
		let ordinal = Math.max(0, ...state.claims.map(claim => claim.n));
		const versions = new Map(), homes = {}, pages = {}, matched = this.matched(rooted);
		const outcome = (name, item) => {
			if (!outcomes.has(name)) outcomes.set(name, []);
			outcomes.get(name).push(item);
		};
		owners.forEach(([step, anchor], index) => {
			const read = reads[index], answer = answers[index], call = { step: step.step, partition: read.partition };
			if (Object.hasOwn(answer, "error")) {
				const status = answer.status === 404 ? "empty" : "unavailable";
				outcome(step.step, { handles: new Set([anchor]), status, emptyTypes: [] });
				result.calls.push({ ...call, status });
				if (status === "unavailable") result.gaps.push({ ...call, reason: `Store.${answer.error}` });
				return;
			}
			outcome(step.step, { handles: new Set([anchor]), status: "ok", emptyTypes: [] });
			result.calls.push({ ...call, status: "ok", head: answer.head });
			const data = answer.observations;
			for (const [handle, item] of Object.entries(data.instances)) if (!Object.hasOwn(instances, handle)) instances[handle] = { type: item.type };
			for (const given of data.claims) {
				ordinal += 1;
				const claim = { ...given, n: ordinal };
				homes[this.subjectOf(claim)] = read.partition;
				(this.claimHolder(claim, instances) === this.storeName ? claims : offAuthority).push(claim);
			}
			for (const slot of answer.versions) versions.set(slotKey(slot), slot.version);
			for (const [population, cursor] of Object.entries(answer.pages ?? {})) {
				const [alias] = Object.entries(matched).find(([, [kind, name]]) => kind === step.partitionKind && name === population);
				(pages[alias] ??= {})[step.step] = cursor;
			}
		});
		result.steps = [...result.steps, ...result.storeSteps];
		delete result.storeSteps;
		result.store = { versions, homes };
		result.pages = pages;
		result.offAuthority = offAuthority;
		return [result, { ...state, instances, claims, retractions: [] }, outcomes];
	}

	/** A view's report, with each fact's holder, partition and version, and the state it was projected from. */
	async open(view, seed, fields = null, options = {}) {
		const [result, state, outcomes] = await this.runReads(view, seed, fields, options);
		result.format = "onto.view-report/1";
		[result.facts, result.coverage] = this.project(state, result, outcomes);
		const rooted = this.views[view], store = result.store;
		delete result.store;
		for (const fact of result.facts) {
			const { field } = rooted.selections[this.select(view, [fact.field])[fact.field]];
			const member = fact.member ?? field.member;
			// NOTE: A fact's holder is its own slot's: a keyed field's elements may have different holders.
			fact.holder = field.relation ? result.holders[fact.field] : this.claimHolder({ s: fact.subject, p: member }, state.instances) ?? result.holders[fact.field];
			fact.writable = fact.holder === this.storeName && result.writable[fact.field];
			if (fact.holder === this.storeName) {
				const slot = { s: fact.subject, p: member, ...(Object.hasOwn(fact, "ctx") ? { ctx: fact.ctx } : {}) };
				fact.partition = store.homes[fact.subject] ?? null;
				fact.version = store.versions.get(slotKey(slot)) ?? 0;
			}
		}
		return [result, state];
	}

	/** Explain the reads and facts of a view, each fact with its holder, and the store's with partition and version. */
	async report(view, seed, fields = null, options = {}) {
		return (await this.open(view, seed, fields, options))[0];
	}
}

/** A client's session: the state of the view it opened, and changes routed to each slot's holder (spec-09 "Changes"). */
export class Session {
	/** `newId()` gives request IDs and new handles' keys; UUIDs of version 7 by default. */
	constructor(operator, { newId = () => uuid7() } = {}) {
		this.operator = operator;
		this.newId = newId;
		this.report = null;
		this.state = null;
		this.opened = null;
	}

	/** A handle for a new instance of `type`, source-qualified in the store's scope, so that its origin is the store (spec-09 "Origins"). */
	newHandle(type) {
		const short = type.slice(type.lastIndexOf("/") + 1);
		return `${short}_${encodeKey(`${this.operator.scope}/${short}/${this.newId()}`)}`;
	}

	/** Read a view and keep its state. */
	async open(view, seed, fields = null, options = {}) {
		this.opened = [view, seed, fields, options];
		[this.report, this.state] = await this.operator.open(view, seed, fields, options);
		return this.report;
	}

	/** Each handle's home partition and population, and the home links a system holds that each partition needs (spec-08 "Homes"). */
	homes(statements, types) {
		const { operator } = this, bundle = operator.store, homes = {};
		for (const [handle, type] of Object.entries(types)) {
			const kind = bundle.kinds.find(item => isA(bundle, type, item.root.type));
			if (kind) homes[handle] = [`${kind.kind}/${handle}`, kind.root.name];
		}
		const claims = [...statements.filter(item => !item.retract).map(item => [item, false]), ...(this.state?.claims ?? []).map(item => [item, true])];
		const links = {}, typed = Object.fromEntries(Object.entries(types).map(([handle, type]) => [handle, { type }]));
		let changed = true;
		while (changed) {
			changed = false;
			for (const [handle, type] of Object.entries(types)) {
				if (Object.hasOwn(homes, handle)) continue;
				search: for (const kind of bundle.kinds) for (const population of kind.populations) {
					if (!isA(bundle, type, population.type)) continue;
					for (const [claim, fromState] of claims) {
						const parent = Session.linkParent(claim, handle, population);
						if (parent === null || !Object.hasOwn(homes, parent) || homes[parent][1] !== population.parent || !homes[parent][0].startsWith(kind.kind + "/")) continue;
						homes[handle] = [homes[parent][0], population.name];
						if (fromState && operator.claimHolder(claim, typed) !== operator.storeName) (links[homes[handle][0]] ??= []).push(pick(claim, ["s", "p", "v", "rel", "roles"]));
						changed = true;
						break search;
					}
				}
			}
		}
		return [homes, links];
	}

	/** The parent a claim links `handle` to along `population`'s link, if it states that link. */
	static linkParent(claim, handle, population) {
		const link = population.link;
		if (Object.hasOwn(link, "rel")) {
			const roles = claim.roles ?? {};
			return claim.rel === link.rel && roles[link.memberRole] === handle ? roles[link.parentRole] ?? null : null;
		}
		if (claim.p !== link.slot) return null;
		const targets = referenceHandles(claim.v);
		if (link.on === "member") return claim.s === handle && targets.length ? targets[0] : null;
		return targets.includes(handle) ? claim.s ?? null : null;
	}

	/** An append of statements with the store file's edit source, their slots' versions and the home links. */
	batch(statements, types, links) {
		const { operator } = this, claims = [], retractions = [], expect = [], mentioned = new Set();
		const mentions = item => [item.s, ...Object.values(item.roles ?? {}), ...referenceHandles(item.v)].filter(Boolean);
		statements.forEach((statement, index) => {
			const entry = Object.fromEntries(Object.entries(statement).filter(([key]) => !["version", "was", "retract"].includes(key)));
			if (Object.hasOwn(statement, "version")) expect.push({ ...pick(entry, SLOT_KEYS), version: statement.version });
			(statement.retract ? retractions : claims).push({ ...entry, n: index + 1, src: "e" });
			for (const handle of mentions(entry)) mentioned.add(handle);
		});
		for (const link of links) for (const handle of mentions(link)) mentioned.add(handle);
		const instances = Object.fromEntries([...mentioned].sort().filter(handle => Object.hasOwn(types, handle)).map(handle => [handle, { type: types[handle] }]));
		return { requestId: this.newId(), expect, ...(links.length ? { links } : {}),
			observations: { format: "onto.observations/1", obs: { ontology: operator.targetModel.namespace, scope: operator.scope },
				sources: { e: operator.store.edit }, instances, claims, retractions } };
	}

	/** Append a batch; an append without an answer is retried once with the same request ID (spec-08 "Retries"), and is `uncertain` if that fails too. */
	async append(partition, body) {
		const { access } = this.operator;
		for (let attempt = 0; attempt < 2; attempt++) {
			try {
				await access.storeAppend(partition, body);
				return { result: "applied", partition };
			} catch (error) {
				if (error instanceof StoreError) throw error;
			}
		}
		return { result: "uncertain", partition, requestId: body.requestId };
	}

	/** The slots that moved since a batch was prepared, each with its current version and value (spec-09 "Atomic per partition"). */
	async moved(partition, expect, versions) {
		const moved = versions.filter((current, index) => expect[index].version !== current.version), subjects = new Map();
		for (const slot of moved) {
			const subject = this.operator.subjectOf(slot);
			if (!subjects.has(subject)) subjects.set(subject, new Set());
			subjects.get(subject).add(slot.p || slot.rel || (Object.hasOwn(slot, "facet") ? `[${slot.facet}]` : "exists"));
		}
		const { results: [answer] } = await this.operator.access.storeRead({ reads: [{ partition,
			select: [...subjects].map(([subject, slots]) => ({ s: subject, slots: [...slots].sort() })) }] });
		const values = new Map((answer.observations?.claims ?? []).filter(claim => Object.hasOwn(claim, "v")).map(claim => [slotKey(claim), claim.v]));
		return moved.map(slot => values.has(slotKey(slot)) ? { ...slot, v: values.get(slotKey(slot)) } : slot);
	}

	/**
	 * Route a change set (spec-09 "Changes"): store-held statements to their home partitions, one batch per partition;
	 * system-held ones are read-only until the system declares operations (spec-10). After applying, the session reads
	 * its view again.
	 */
	async change(changes) {
		const { operator } = this, bundle = operator.store;
		const types = { ...Object.fromEntries(Object.entries(this.state?.instances ?? {}).map(([handle, item]) => [handle, item.type])),
			...Object.fromEntries(Object.entries(changes.instances ?? {}).map(([handle, item]) => [handle, item.type])) };
		const statements = [...(changes.claims ?? []).map(item => ({ ...item })), ...(changes.retractions ?? []).map(item => ({ ...item, retract: true }))];
		const [homes, links] = this.homes(statements, types);
		const results = statements.map(() => ({})), groups = new Map();
		statements.forEach((statement, index) => {
			const subject = operator.subjectOf(statement), type = types[subject];
			const origin = type ? originOf(bundle, subject, type, operator.scope) : null;
			if (origin === null) results[index] = { result: "rejected", reason: type ? "origin.unknown" : "type" };
			else if (!holds(bundle, origin, type, statement)) results[index] = { result: "readonly" };
			else if (!Object.hasOwn(homes, subject)) results[index] = { result: "unhomed" };
			else {
				const partition = homes[subject][0];
				if (!groups.has(partition)) groups.set(partition, []);
				groups.get(partition).push(index);
			}
		});
		for (const [partition, indexes] of groups) {
			const body = this.batch(indexes.map(index => statements[index]), types, links[partition] ?? []);
			let outcome;
			try {
				outcome = await this.append(partition, body);
			} catch (error) {
				if (!(error instanceof StoreError)) throw error;
				outcome = error.error === "precondition" ? { result: "conflict", partition, moved: await this.moved(partition, body.expect, error.details.versions) }
					: { result: "rejected", partition, reason: error.details.check ?? error.error };
			}
			for (const index of indexes) results[index] = outcome;
		}
		if (this.opened && results.some(result => result.result === "applied")) {
			const [view, seed, fields, options] = this.opened;
			await this.open(view, seed, fields, options);
		}
		return { statements: statements.map((statement, index) => ({ ...pick(statement, SLOT_KEYS), ...results[index] })) };
	}
}

// EOF
