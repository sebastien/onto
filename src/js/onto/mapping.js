/**
 * Module: mapping — map a reconciled state through a compiled mapping, as `integrations/hexa/unfold.py`.
 *
 * MappingRead: HandlesResolve → InstancesUnfold → MappingRecordsCollect → ClaimsEmit
 *
 * A state is a graph and hexa projects trees: each scope instance is unfolded into a tree holding
 * what the scope reads, with a metadata table from tree pointers to the claims each value came from.
 */

import { Location } from "hexa/shapes.js";
import { Policy, collect, each, lift, pipe, project } from "hexa/combinators.js";
import { Registry } from "./program.js";
import { ClaimsBuilder, cleanValue, named, namedStage, registerFunctions } from "./stages.js";
import { conditionHolds, isPresent, reasonCode, textOf } from "./vocabulary.js";
import { clone, compareCodePoints, compareTimestamps, handleOf, intersectIntervals as intersect, isAbsent, isSet, isUnknown, valueKey } from "./values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const InputConflicting = "Mapping.InputConflicting", ReferenceUnmapped = "Mapping.ReferenceUnmapped", ValueUnmapped = "Mapping.ValueUnmapped";
const RE_TOKEN = /^[^\s{},=]+$/u;

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);
const escape = key => key.replaceAll("~", "~0").replaceAll("/", "~1");
const sortCodePoints = items => [...items].sort(compareCodePoints);

function metaOf(claim, sources) {
	const result = { src: Object.hasOwn(sources, claim.src ?? "") ? sources[claim.src] : claim.src ?? null, at: claim.at ?? null };
	for (const key of ["valid", "conf"]) if (Object.hasOwn(claim, key)) result[key] = claim[key];
	return result;
}

/** Follow `keys` through references' `of` subtrees; return null when a step is missing. */
function valueAt(tree, keys) {
	let node = tree;
	for (const [index, key] of keys.entries()) {
		if (!isObject(node) || !Object.hasOwn(node, key)) return null;
		node = node[key];
		if (index + 1 < keys.length) node = isObject(node) ? node.of ?? null : null;
	}
	return node ?? null;
}

function setAt(tree, pointer, value) {
	const result = clone(tree), parts = pointer.split("/").slice(1).map(part => part.replaceAll("~1", "/").replaceAll("~0", "~"));
	let node = result;
	for (const part of parts.slice(0, -1)) {
		if (Array.isArray(node)) node = node[Number(part)];
		else { node[part] ??= {}; node = node[part]; }
	}
	node[parts.at(-1)] = value;
	return result;
}

/** The tree pointers of the claims along a path, through references and their `of` subtrees. */
function pointersOf(tree, steps) {
	const result = [];
	let frontier = [["", tree]];
	for (const [index, key] of steps.entries()) {
		const following = [];
		for (const [base, node] of frontier) {
			const pointer = `${base}/${escape(key)}`;
			result.push(pointer);
			const value = isObject(node) ? node[key] : undefined;
			if (index + 1 === steps.length || !isObject(value)) continue;
			if (Object.hasOwn(value, "set")) value.set.forEach((item, position) => { if (isObject(item) && Object.hasOwn(item, "of")) following.push([`${pointer}/set/${position}/of`, item.of]); });
			else if (Object.hasOwn(value, "of")) following.push([`${pointer}/of`, value.of]);
		}
		frontier = following;
	}
	return result;
}

const lineRecord = info => info.slot || info.key;
const sourcePath = (info, paths) => 0 <= info.source && info.source < paths.length ? paths[info.source] : [];
const activeLines = (plan, occurrence) => plan.lines.filter(info => info.contextual === (occurrence.context !== null && occurrence.context !== undefined));

/** The values at segment `keys`, through references' `of` subtrees and the members of collections. */
function valuesAt(tree, keys) {
	let nodes = [tree];
	for (const [index, key] of keys.entries()) {
		const found = [];
		for (const node of nodes) {
			if (!isObject(node) || !Object.hasOwn(node, key)) continue;
			const value = node[key];
			if (index + 1 === keys.length) found.push(value);
			else if (isSet(value)) for (const item of value.set) { if (isObject(item) && Object.hasOwn(item, "of")) found.push(item.of); }
			else if (isObject(value) && Object.hasOwn(value, "of")) found.push(value.of);
		}
		nodes = found;
	}
	return nodes;
}

/** The tests of a condition, in order. */
const conditionTests = condition => condition.all ?? condition.any ? (condition.all ?? condition.any).flatMap(conditionTests) : [condition];
const conditionReader = (plan, occurrence) => path => valuesAt(occurrence.value, plan.segmentKeys.get(valueKey(path)));

/** Whether a slot any test of `condition` reads holds conflicting claims. */
function conditionConflicts(plan, occurrence, condition) {
	if (!condition) return false;
	const conflicts = occurrence.conflicts ?? {};
	return conditionTests(condition).some(test => pointersOf(occurrence.value, plan.segmentKeys.get(valueKey(test.path))).some(pointer => Object.hasOwn(conflicts, pointer)));
}

function lineApplies(plan, occurrence, info) {
	if (info.when) return conditionHolds(info.when, conditionReader(plan, occurrence));
	if (info.unless) return !conditionHolds(info.unless, conditionReader(plan, occurrence));
	return true;
}

function scopeSelected(plan, occurrence) {
	if (!plan.when) return true;
	return !conditionConflicts(plan, occurrence, plan.when) && conditionHolds(plan.when, conditionReader(plan, occurrence));
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** Claims of a reconciled state by subject and slot, with conflicts kept together. */
class StateIndex {
	constructor(state, model) {
		this.model = model;
		this.sources = state.sources ?? {};
		this.instances = state.instances ?? {};
		this.scope = state.obs?.scope || state.obs?.ontology || "";
		this.values = new Map();
		this.exists = new Map();
		this.relations = [];
		for (const claim of state.claims ?? []) {
			if (claim.exists) {
				if (!this.exists.has(claim.s)) this.exists.set(claim.s, []);
				this.exists.get(claim.s).push(claim);
			} else if (Object.hasOwn(claim, "p")) {
				if (!this.values.has(claim.s)) this.values.set(claim.s, new Map());
				const slots = this.values.get(claim.s);
				if (!slots.has(claim.p)) slots.set(claim.p, []);
				slots.get(claim.p).push(claim);
			} else if (Object.hasOwn(claim, "rel")) this.relations.push(claim);
		}
	}

	typeOf(handle) { return this.instances[handle]?.type ?? null; }

	existence(handle) {
		const all = this.exists.get(handle) ?? [], claims = all.filter(claim => !claim.conflict);
		return (claims.length ? claims : all)[0] ?? null;
	}

	handlesOf(typePath) {
		return sortCodePoints(Object.keys(this.instances).filter(handle => this.model.isA(this.instances[handle].type, typePath)));
	}

	claims(handle, key, context) {
		return (this.values.get(handle)?.get(key) ?? []).filter(claim => (claim.ctx ?? null) === (context ?? null));
	}
}

/** A known lookup key: a reference by its handle, a scalar by its text. */
function comparedValue(value) {
	const text = textOf(value);
	if (text === null) return null;
	return `${isObject(value) && Object.hasOwn(value, "ref") ? "ref:" : "text:"}${text}`;
}

/** Turn scope instances into trees limited to the scope's reach, with metadata tables and conflicts. */
class Unfolder {
	/** `named`: source handle → {program scope: target} its named scope lines emitted (`{name=N}` references). */
	constructor(index, correspondence, targets = {}, scopeTargets = {}, skipped = {}, named = {}) {
		Object.assign(this, { index, correspondence, targets: targets ?? {}, scopeTargets: scopeTargets ?? {}, skipped: skipped ?? {}, named: named ?? {}, lookupTables: new Map() });
	}

	reference(handle, children, pointer, meta, conflicts, context = null) {
		const result = { ref: handle };
		if (this.correspondence && Object.hasOwn(this.correspondence, handle)) {
			result.target = this.correspondence[handle];
			if (Object.hasOwn(this.targets, handle)) result.targetType = Object.keys(this.targets[handle])[0];
		}
		if (this.targets[handle] && Object.keys(this.targets[handle]).length) result.targets = this.targets[handle];
		if (this.named[handle] && Object.keys(this.named[handle]).length) result.scopes = this.named[handle];
		if (this.skipped[handle]?.length) result.skipped = sortCodePoints(this.skipped[handle]);
		if (Object.keys(children).length) result.of = this.subtree(handle, children, `${pointer}/of`, meta, conflicts, context);
		return result;
	}

	value(value, segment, children, pointer, meta, conflicts, context) {
		if (segment.kind !== "ref" || !isObject(value)) return value;
		if (Object.hasOwn(value, "ref")) return this.reference(value.ref, children, pointer, meta, conflicts, context);
		if (Object.hasOwn(value, "set")) {
			return { ...value, set: value.set.map((item, index) => isObject(item) && Object.hasOwn(item, "ref") ? this.reference(item.ref, children, `${pointer}/set/${index}`, meta, conflicts, context) : item) };
		}
		return value;
	}

	subtree(handle, reach, base, meta, conflicts, context = null) {
		const tree = {}, sources = this.index.sources;
		for (const [key, { segment, children }] of Object.entries(reach)) {
			const pointer = `${base}/${escape(key)}`;
			if (segment.kind === "verb") {
				const members = this.verb(handle, segment, children, pointer, meta, conflicts, context);
				if (members !== null) tree[key] = members;
				continue;
			}
			if (segment.kind === "lookup") {
				const found = this.lookup(handle, segment.lookup);
				if (found === null) continue;
				if (found.length !== 1) {
					// Several, or a compared value in conflict: ambiguous (`Onto.Single`), and no condition reads through it
					tree[key] = { set: [], partial: true };
					continue;
				}
				tree[key] = this.reference(found[0], children, pointer, meta, conflicts, context);
				meta[pointer] = metaOf(this.index.existence(found[0]) ?? {}, sources);
				continue;
			}
			const claims = this.index.claims(handle, key, segment.context ? context : null);
			if (!claims.length) continue;
			if (claims.some(claim => claim.conflict)) {
				conflicts[pointer] = claims.map(claim => ({ value: claim.v, ...metaOf(claim, sources) }));
				meta[pointer] = conflicts[pointer];
				continue;
			}
			let value = claims[0].v;
			if (claims.length > 1 && claims.every(claim => isSet(claim.v))) {
				// Rule 9 keeps a complete collection and later additions apart; their members together are the slot.
				const members = new Map(claims.flatMap(claim => claim.v.set).map(item => [JSON.stringify(item), item]));
				value = { set: [...members.values()], ...(claims.some(claim => claim.v.partial) ? { partial: true } : {}) };
			}
			meta[pointer] = metaOf(claims.at(-1), sources);
			tree[key] = this.value(value, segment, children, pointer, meta, conflicts, context);
		}
		return tree;
	}

	/** The instances a lookup finds from `handle` (spec-04 Lookups): null when the owner has no value to compare, [] when a
	 * compared value is in conflict, else those whose compared attributes have the owner's values. */
	lookup(handle, lookup) {
		const key = [];
		for (const [, source] of lookup.lines) {
			const claims = this.index.claims(handle, source, null);
			const values = new Set(claims.map(claim => comparedValue(claim.v)));
			values.delete(null);
			if (claims.some(claim => claim.conflict) || values.size > 1) return [];
			key.push(values.values().next().value ?? null);
		}
		if (key.includes(null)) return null;
		const tableKey = JSON.stringify(lookup);
		if (!this.lookupTables.has(tableKey)) {
			const table = new Map();
			for (const candidate of this.index.handlesOf(lookup.type)) {
				const row = [];
				for (const [attr] of lookup.lines) {
					const claims = this.index.claims(candidate, attr, null);
					const values = new Set(claims.map(claim => comparedValue(claim.v)));
					values.delete(null);
					if (values.size !== 1 || claims.some(claim => claim.conflict)) break;
					row.push(...values);
				}
				if (row.length !== lookup.lines.length) continue;
				const rowKey = JSON.stringify(row);
				table.set(rowKey, [...(table.get(rowKey) ?? []), candidate]);
			}
			this.lookupTables.set(tableKey, table);
		}
		return this.lookupTables.get(tableKey).get(JSON.stringify(key)) ?? null;
	}

	roles(segment) {
		const found = this.index.model.verbs(segment.owner, segment.key);
		if (!found.length) return null;
		const [decl, inverse] = found[0];
		const [first, second] = decl.participants.map(item => item.role);
		return [decl, inverse ? second : first, inverse ? first : second];
	}

	verb(handle, segment, children, pointer, meta, conflicts, context) {
		const roles = this.roles(segment);
		if (!roles) return null;
		const [decl, mine, other] = roles;
		const claims = this.index.relations.filter(claim => claim.rel === decl.path && claim.roles[mine] === handle).sort((a, b) => compareCodePoints(a.roles[other], b.roles[other]));
		if (!claims.length) return null;
		const members = claims.map((claim, index) => {
			const member = this.reference(claim.roles[other], children, `${pointer}/set/${index}`, meta, conflicts, context);
			meta[`${pointer}/set/${index}`] = metaOf(claim, this.index.sources);
			return member;
		});
		meta[pointer] = metaOf(claims[0], this.index.sources);
		return { set: members };
	}

	/** Contexts supplied along finite read paths, including paths through references. */
	contexts(handle, reach) {
		const result = new Set();
		for (const [key, { segment, children }] of Object.entries(reach)) {
			if (segment.kind === "lookup") {
				const found = Object.keys(children).length ? this.lookup(handle, segment.lookup) : null;
				if (found?.length === 1) for (const item of this.contexts(found[0], children)) result.add(item);
				continue;
			}
			if (segment.kind === "verb") {
				const roles = this.roles({ ...segment, key });
				if (roles) {
					const [decl, mine, other] = roles;
					for (const claim of this.index.relations) if (claim.rel === decl.path && claim.roles[mine] === handle) for (const item of this.contexts(claim.roles[other], children)) result.add(item);
				}
				continue;
			}
			for (const claim of this.index.values.get(handle)?.get(key) ?? []) {
				if (segment.context && claim.ctx) result.add(claim.ctx);
				if (Object.keys(children).length && isObject(claim.v)) {
					for (const member of isSet(claim.v) ? claim.v.set : [claim.v]) if (isObject(member) && Object.hasOwn(member, "ref")) for (const item of this.contexts(member.ref, children)) result.add(item);
				}
			}
		}
		return result;
	}

	/** Return the tree, location, metadata, conflicts, existence metadata and context, or null without an existence claim. */
	occurrence(plan, handle, context = null) {
		const existence = this.index.existence(handle);
		if (existence === null) return null;
		const meta = {}, conflicts = {};
		const tree = this.subtree(handle, plan.reach, "", meta, conflicts, context);
		const existsMeta = metaOf(existence, this.index.sources);
		Object.assign(tree, { "@handle": handle, "@type": this.index.typeOf(handle), "@scope": this.index.scope, "@at": existence.at ?? null, "@src": existsMeta.src });
		if (Object.hasOwn(existence, "valid")) tree["@valid"] = existence.valid;
		if (Object.hasOwn(this.scopeTargets[handle] ?? {}, plan.name)) tree["@target"] = this.scopeTargets[handle][plan.name];
		else if (this.correspondence && Object.hasOwn(this.correspondence, handle)) tree["@target"] = this.targets[handle]?.[plan.target] ?? this.correspondence[handle];
		if (plan.readsSelf) tree["@self"] = this.reference(handle, {}, "", meta, conflicts, context);
		for (const [key, [typePath, keys]] of Object.entries(plan.sourceRefs)) {
			const value = valueAt(tree, keys);
			if (value !== null && !isAbsent(value) && !isUnknown(value) && !isObject(value)) tree[key] = this.reference(handleOf(typePath, textOf(value)), {}, "", meta, conflicts, context);
		}
		const location = `/${plan.name}/${escape(handle)}` + (context ? `/contexts/${escape(context)}` : "");
		return { value: tree, location, meta, conflicts, exists: existsMeta, context };
	}
}

/** Turn records and variants into claims with spec-04 metadata, conflicts, gaps and stale slots. */
class MappingEmitter {
	constructor(program, runTime) {
		this.program = program;
		this.plans = Object.fromEntries(program.plans.map(plan => [plan.name, plan]));
		this.runTime = runTime;
		this.by = program.by;
		this.builder = new ClaimsBuilder(program.targetModel, program.toNamespace, program.scope, this.by);
		Object.assign(this, { gaps: [], stale: [], mixed: [], unidentified: [], emittedExistence: new Set(), emittedHandles: new Set() });
	}

	inputs(occurrence, info, variant = null) {
		const tree = occurrence.value, conflicts = occurrence.conflicts;
		const paths = info.inputs.map(steps => pointersOf(tree, this.segmentKeys(occurrence, steps)));
		let hits = new Set(paths.flat().filter(pointer => Object.hasOwn(conflicts, pointer) && pointer !== variant));
		if (info.contextType) hits = new Set([...hits, ...this.contextConflicts(this.plans[occurrence.scope], occurrence)]);
		return [paths, sortCodePoints(hits)];
	}

	contextConflicts(plan, occurrence) {
		return new Set(plan.contextInputs.flatMap(keys => pointersOf(occurrence.value, keys)).filter(pointer => Object.hasOwn(occurrence.conflicts, pointer)));
	}

	segmentKeys(occurrence, steps) {
		return this.plans[occurrence.scope].segmentKeys.get(valueKey(steps));
	}

	metadata(occurrence, info, paths, variant) {
		const table = occurrence.meta;
		let entries = [];
		for (const pointers of paths) for (const pointer of pointers) {
			if (variant && pointer === variant[0]) entries.push(variant[1]);
			else if (isObject(table[pointer])) entries.push(table[pointer]);
		}
		if (!entries.length) entries = [occurrence.exists];
		const sources = [...new Set(entries.map(entry => entry.src))];
		let src = sources[0];
		if (sources.length > 1) {
			const last = sourcePath(info, paths).filter(pointer => variant && pointer === variant[0] || isObject(table[pointer]));
			if (last.length) src = variant && last.at(-1) === variant[0] ? variant[1].src : table[last.at(-1)].src;
		}
		const meta = { src, at: this.runTime, by: this.by };
		const valids = entries.filter(entry => Object.hasOwn(entry, "valid")).map(entry => entry.valid);
		if (valids.length) {
			const valid = intersect(valids);
			if (valid === null) return null;
			meta.valid = valid;
		}
		const confs = entries.filter(entry => Object.hasOwn(entry, "conf")).map(entry => entry.conf);
		if (confs.length) meta.conf = confs.reduce((a, b) => (Number(b) < Number(a) ? b : a));
		return [meta, sources.filter(item => item !== src)];
	}

	record(plan, occurrence, record, lines, variant = null) {
		const handle = record.handle;
		if (typeof handle !== "string") return;
		occurrence = { ...occurrence, scope: plan.name };
		if (plan.presence) {
			if (plan.presenceInputs.some(keys => pointersOf(occurrence.value, keys).some(pointer => Object.hasOwn(occurrence.conflicts, pointer)))) {
				if (variant === null) this.presenceGap(plan, occurrence, handle, InputConflicting, record);
				return;
			}
			if (!isPresent(record.present)) return;
		}
		if (plan.update && !this.emittedHandles.has(handle)) {
			this.gap(plan.target, ReferenceUnmapped, occurrence, handle);
			for (const info of activeLines(plan, occurrence)) this.markStale(plan, occurrence, info, handle, ReferenceUnmapped, record, variant);
			return;
		}
		if (variant === null && !plan.update) {
			const exists = occurrence.exists;
			const meta = { src: exists.src, at: this.runTime, by: this.by };
			const valid = typeof record.valid === "string" ? record.valid : exists.valid;
			if (valid) meta.valid = valid;
			if (Object.hasOwn(exists, "conf")) meta.conf = exists.conf;
			this.builder.instance(handle, plan.target);
			this.emittedHandles.add(handle);
			const existenceKey = handle + "\u0000" + valueKey(meta);
			if (!this.emittedExistence.has(existenceKey)) {
				this.builder.exists(handle, meta);
				this.emittedExistence.add(existenceKey);
			}
		}
		for (const info of lines ?? activeLines(plan, occurrence)) {
			const section = record[info.section] ?? {};
			const value = section[lineRecord(info)];
			const [paths, conflicting] = this.inputs(occurrence, info, variant ? variant[0] : null);
			const target = info.section === "facets" ? `${plan.target}[${info.key}]` : `${plan.target}.${info.key}`;
			if (conflicting.length && variant === null && valueKey(conflicting) === valueKey(sourcePath(info, paths).slice(-1))
				&& !this.contextConflicts(plan, occurrence).size && !conditionConflicts(plan, occurrence, info.when ?? info.unless)) continue;
			if (conflicting.length) {
				this.gap(target, InputConflicting, occurrence, handle);
				this.markStale(plan, occurrence, info, handle, InputConflicting, record, variant);
				continue;
			}
			if (value === undefined || value === null && !Object.hasOwn(section, lineRecord(info)) || isAbsent(value) || value === false && info.section === "facets") continue;
			const metadata = this.metadata(occurrence, info, paths, variant);
			if (metadata === null) continue;
			const [meta, others] = metadata;
			if (info.qualifiers.length) {
				const qualifiers = record.qualifiers?.[lineRecord(info)] ?? {};
				let valid = true;
				for (const key of info.qualifiers) {
					const member = qualifiers[key], kind = info.qualifierChecks?.[key] ?? null;
					if (typeof member !== "string" || member === "?" || !RE_TOKEN.test(member) || kind && !kind.open && !kind.values.includes(member)) { valid = false; break; }
					meta[key] = member;
				}
				if (!valid) {
					this.gap(target, ValueUnmapped, occurrence, handle);
					this.markStale(plan, occurrence, info, handle, ValueUnmapped, record, variant);
					continue;
				}
			}
			if (info.contextType) {
				const context = this.contextSlot(plan, occurrence, info, record).ctx;
				if (!context) {
					this.gap(target, ReferenceUnmapped, occurrence, handle);
					this.markStale(plan, occurrence, info, handle, ReferenceUnmapped, record, variant);
					continue;
				}
				this.builder.instance(context, info.contextType);
				meta.ctx = context;
			}
			if (others.length) this.mixed.push({ target, handle, src: meta.src, sources: others });
			this.claim(plan, handle, info, value, meta, record);
		}
	}

	contextSlot(plan, occurrence, info, record = null) {
		if (!info.contextType) return {};
		const value = plan.contextOverride ? record?.ctx : { ref: occurrence.targetContext };
		const context = isObject(value) ? value.ref : null;
		return typeof context === "string" ? { ctx: context } : {};
	}

	markStale(plan, occurrence, info, handle, reason, record = null, variant = null) {
		occurrence = { ...occurrence, scope: plan.name };
		const [paths] = this.inputs(occurrence, info);
		const chosen = sourcePath(info, paths);
		const pointers = chosen.length ? chosen : paths.flat();
		const entries = pointers.map(pointer => variant && pointer === variant[0] ? variant[1] : occurrence.meta[pointer]).filter(entry => entry !== undefined && entry !== null);
		const last = entries.length ? entries.at(-1) : occurrence.exists;
		const sources = new Set((Array.isArray(last) ? last : [last]).map(entry => entry.src));
		for (const src of [...sources].sort((a, b) => compareCodePoints(a ?? "", b ?? ""))) {
			this.stale.push({ src, s: handle, ...this.slotOf(info), ...this.contextSlot(plan, occurrence, info, record), reason });
		}
	}

	presenceGap(plan, occurrence, handle, reason, record) {
		this.gap(plan.target, reason, occurrence, handle);
		if (!plan.update) this.stale.push({ src: occurrence.exists.src, s: handle, exists: true, reason });
		for (const info of activeLines(plan, occurrence)) this.markStale(plan, occurrence, info, handle, reason, record);
	}

	projectionGap(plan, occurrence, record, entry, variant = null, lines = null) {
		const path = entry.path ?? [];
		if (path[0] === "present" && plan.presence) {
			if (variant === null) this.presenceGap(plan, occurrence, occurrence.value["@target"], reasonCode(entry.reason), record);
			return;
		}
		// A scope its presence does not select demands nothing of its lines (spec-04 Instances).
		if (plan.presence && record !== null && !isPresent(record.present)) return;
		if (path.length < 2) return;
		const [section, key] = path;
		const info = plan.sectionLines.get(`${section}\u0000${key}`);
		if (!info || !(lines ?? activeLines(plan, occurrence)).includes(info)) return;
		if (!lineApplies(plan, occurrence, info)) return;
		if (this.inputs({ ...occurrence, scope: plan.name }, info, variant ? variant[0] : null)[1].length) return;
		const handle = occurrence.value["@target"];
		const target = section === "facets" ? `${plan.target}[${info.key}]` : `${plan.target}.${info.key}`;
		this.gap(target, reasonCode(entry.reason), occurrence, handle);
		this.markStale(plan, occurrence, info, handle, reasonCode(entry.reason), record, variant);
	}

	slotOf(info) {
		return { values: { p: info.key }, facets: { facet: info.key }, links: { verb: info.key } }[info.section];
	}

	claim(plan, handle, info, value, meta, record) {
		const builder = this.builder, model = this.program.targetModel;
		if (info.section === "facets") { builder.facet(handle, info.key, meta, meta.ctx ?? null); return; }
		if (info.section === "links") {
			const found = model.verbs(plan.target, info.key);
			if (!found.length) return;
			for (const member of isSet(value) ? value.set : [value]) {
				if (!isObject(member) || !Object.hasOwn(member, "ref")) continue;
				const kind = member.type ?? builder.implicit[member.ref] ?? null;
				const matches = found.filter(([decl, inverse]) => kind === null || model.isA(kind, decl.participants[inverse ? 0 : 1].type));
				if (matches.length !== 1) {
					this.gaps.push({ target: `${plan.target}.${info.key}`, reason: ReferenceUnmapped, src: meta.src, handle });
					continue;
				}
				const [decl, inverse] = matches[0];
				const [first, second] = decl.participants.map(item => item.role);
				cleanValue(member, builder.implicit);
				const other = member.ref;
				builder.add({ rel: decl.path, roles: inverse ? { [first]: other, [second]: handle } : { [first]: handle, [second]: other }, ...meta });
			}
			return;
		}
		if (info.also) {
			const reference = record.values?.[info.also];
			if (isObject(reference) && Object.hasOwn(reference, "ref")) builder.add({ s: reference.ref, p: info.key.split(".").slice(1).join("."), ...meta, v: cleanValue(value, builder.implicit) });
			return;
		}
		builder.add({ s: handle, p: info.key, ...meta, v: cleanValue(value, builder.implicit) });
	}

	gap(target, reason, occurrence, handle) {
		this.gaps.push({ target, reason, src: occurrence.exists.src, location: occurrence.location, ...(handle ? { handle } : {}) });
	}
}

/** For each conflicting pointer that is some lines' source input, one tree per conflicting claim. */
function variantsOf(occurrence, plan, emitter) {
	const result = [];
	for (const [pointer, claims] of Object.entries(occurrence.conflicts)) {
		const lines = activeLines(plan, occurrence).filter(info => {
			if (conditionConflicts(plan, occurrence, info.when ?? info.unless) || info.contextType && emitter.contextConflicts(plan, occurrence).size) return false;
			const [paths] = emitter.inputs({ ...occurrence, scope: plan.name }, info);
			const chosen = sourcePath(info, paths);
			return chosen.length && chosen.at(-1) === pointer;
		});
		if (!lines.length) continue;
		claims.forEach((claim, index) => {
			const { value, ...meta } = claim;
			result.push([{ value: setAt(occurrence.value, pointer, value), location: `${occurrence.location}/variants/${index}` }, pointer, meta, lines]);
		});
	}
	return result;
}

/** Add missing instances named by `ref(S, Key)` source expressions without adding claims. */
function implicitReferences(state, model, plans) {
	if (!plans.some(plan => Object.keys(plan.sourceRefs).length)) return state;
	const index = new StateIndex(state, model), unfolder = new Unfolder(index, null);
	const instances = { ...state.instances };
	for (const plan of plans) {
		for (const handle of Object.keys(plan.sourceRefs).length ? index.handlesOf(plan.source) : []) {
			const occurrence = unfolder.occurrence(plan, handle);
			for (const [typePath, keys] of Object.values(plan.sourceRefs)) {
				const value = occurrence ? valueAt(occurrence.value, keys) : null;
				if (value !== null && !isAbsent(value) && !isUnknown(value) && !isObject(value)) instances[handleOf(typePath, textOf(value))] ??= { type: typePath };
			}
		}
	}
	return { ...state, instances };
}

/** The mapping's spec-02 log and report data. */
function emitMapping(program, collected, runTime) {
	const emitter = new MappingEmitter(program, runTime);
	const ordered = program.plans.map((plan, index) => [plan, collected.scopes[index]]).sort(([a], [b]) => Number(a.update) - Number(b.update));
	for (const [plan, scope] of ordered) {
		const byLocation = new Map(scope.occurrences.map(item => [item.location, item]));
		const records = new Map(scope.records.map(record => [record.source, record]));
		for (const entry of scope.gaps) {
			const occurrence = byLocation.get(entry.source);
			if (occurrence) emitter.projectionGap(plan, occurrence, records.get(occurrence.location) ?? null, entry);
		}
		for (const skipped of scope.skipped) {
			const { occurrence, ...gap } = skipped;
			emitter.gaps.push(gap);
			const handle = occurrence.value["@target"];
			emitter.stale.push({ src: skipped.src, s: handle, reason: skipped.reason });
			for (const info of activeLines(plan, occurrence)) emitter.markStale(plan, occurrence, info, handle, skipped.reason);
		}
		for (const occurrence of scope.occurrences) {
			const record = records.get(occurrence.location);
			if (record) emitter.record(plan, occurrence, record, null);
		}
		const variantRecords = new Map(scope.variantRecords.map(record => [record.source, record]));
		for (const variant of scope.variants) {
			const record = variantRecords.get(variant.location), occurrence = byLocation.get(variant.occurrence);
			if (!record) continue;
			const lines = variant.lines.map(([section, key]) => plan.sectionLines.get(`${section}\u0000${key}`));
			for (const entry of scope.variantGaps) if (entry.source === variant.location) emitter.projectionGap(plan, occurrence, record, entry, [variant.pointer, variant.meta], lines);
			emitter.record(plan, occurrence, record, lines, [variant.pointer, variant.meta]);
		}
	}
	for (const item of collected.unresolved) {
		emitter.unidentified.push({ src: "", type: item.type });
		emitter.gaps.push({ target: item.type, reason: item.reasons[0] ?? ReferenceUnmapped, location: item.location });
	}
	const log = emitter.builder.finish();
	const counts = new Map();
	for (const claim of log.claims) if (claim.src !== undefined && claim.src !== null) counts.set(claim.src, (counts.get(claim.src) ?? 0) + 1);
	const tokens = sortCodePoints(new Set([...collected.sources, ...counts.keys()]));
	const aliases = new Map(tokens.map((token, index) => [token, `d${index + 1}`]));
	log.sources = Object.fromEntries(tokens.map(token => [aliases.get(token), token]));
	for (const claim of [...log.claims, ...log.retractions]) {
		if (claim.src === undefined || claim.src === null) { delete claim.src; continue; }
		const src = claim.src;
		delete claim.src;
		claim.src = aliases.get(src);
	}
	return {
		log, stale: emitter.stale.map(item => ({ ...item })), unidentified: emitter.unidentified.flatMap(item => tokens.map(token => ({ src: token, type: item.type }))),
		deleted: [], formats: {}, gaps: emitter.gaps, mixed: emitter.mixed, correspondence: collected.correspondence,
		documents: tokens.map(token => ({ src: token, at: runTime, records: counts.get(token) ?? 0 })),
	};
}

function mappingStages(program) {
	const { plans, model } = program;
	const handleStages = {}, presenceStages = {}, projectStages = {}, variantStages = {};
	for (const plan of plans) {
		handleStages[plan.name] = each(project(plan.shape, plan.handleTemplate), Policy.Drop);
		if (plan.presence && !plan.update) presenceStages[plan.name] = each(project(plan.shape, { "present?": plan.template["present?"], source: Location }), Policy.Drop);
		projectStages[plan.name] = namedStage(`${plan.name}RecordsProject`, each(project(plan.shape, plan.template), Policy.Drop));
		variantStages[plan.name] = namedStage(`${plan.name}VariantsProject`, each(project(plan.shape, plan.template), Policy.Drop));
	}

	const HandlesResolve = named("HandlesResolve", function* (env, state) {
		state = implicitReferences(state, model, plans);
		const index = new StateIndex(state, model);
		let unfolder = new Unfolder(index, null);
		const correspondence = {}, targets = {}, scopeTargets = {}, named = {}, unresolved = [], selected = {}, present = new Set();
		for (const plan of [...plans].sort((a, b) => Number(a.update) - Number(b.update))) {
			if (plan.update) unfolder = new Unfolder(index, correspondence, targets, scopeTargets, {}, named);
			const occurrences = [], targetConflicts = new Set(), whenSelected = new Set(), presenceOccurrences = [];
			for (const handle of index.handlesOf(plan.source)) {
				const occurrence = unfolder.occurrence(plan, handle) ?? { value: { "@handle": handle, "@scope": index.scope, "@type": index.typeOf(handle) }, location: `/${plan.name}/${escape(handle)}` };
				if (Object.hasOwn(occurrence, "exists")) {
					present.add(occurrence.location);
					if (!plan.update && scopeSelected(plan, occurrence)) whenSelected.add(handle);
				}
				if (presenceStages[plan.name] && Object.hasOwn(occurrence, "exists")) {
					const contexts = plan.contextualScope ? sortCodePoints(unfolder.contexts(handle, plan.reach)) : [null];
					for (const context of contexts) {
						const candidate = context ? unfolder.occurrence(plan, handle, context) : occurrence;
						if (scopeSelected(plan, candidate) && !plan.presenceInputs.some(path => pointersOf(candidate.value, path).some(pointer => Object.hasOwn(candidate.conflicts, pointer)))) presenceOccurrences.push(candidate);
					}
				}
				if (plan.update) {
					const conflictsOf = paths => paths.some(path => pointersOf(occurrence.value, path).some(pointer => Object.hasOwn(occurrence.conflicts ?? {}, pointer)));
					if (plan.when) {
						if (conditionConflicts(plan, occurrence, plan.when)) {
							unresolved.push({ type: plan.target, handle, location: occurrence.location, reasons: [InputConflicting] });
							continue;
						}
						if (!conditionHolds(plan.when, conditionReader(plan, occurrence))) continue;
					}
					if (conflictsOf(plan.presenceInputs)) {
						unresolved.push({ type: plan.target, handle, location: occurrence.location, reasons: [InputConflicting] });
						continue;
					}
					if (conflictsOf(plan.targetInputs)) targetConflicts.add(occurrence.location);
				}
				occurrences.push({ value: occurrence.value, location: occurrence.location });
			}
			const result = yield* collect(handleStages[plan.name])(env, occurrences);
			let presenceSelected = new Set();
			if (presenceOccurrences.length) {
				const projected = yield* collect(presenceStages[plan.name])(env, presenceOccurrences);
				const byLocation = new Map(presenceOccurrences.map(item => [item.location, item.value["@handle"]]));
				presenceSelected = new Set(projected.value.filter(item => isPresent(item.present)).map(item => byLocation.get(item.source)));
			}
			const resolved = result.value[Symbol.iterator]();
			const failed = new Set(result.ledger.map(entry => entry.source));
			for (const occurrence of occurrences) {
				const handle = occurrence.value["@handle"];
				if (failed.has(occurrence.location)) {
					unresolved.push({ type: plan.target, handle, location: occurrence.location, reasons: result.ledger.filter(entry => entry.source === occurrence.location).map(entry => reasonCode(entry.reason)) });
					continue;
				}
				const value = resolved.next().value;
				if (plan.update && plan.presence && !isPresent(value.present)) continue;
				if (targetConflicts.has(occurrence.location)) {
					unresolved.push({ type: plan.target, handle, location: occurrence.location, reasons: [InputConflicting] });
					continue;
				}
				if (typeof value.handle === "string") {
					if (!plan.update) {
						const active = plan.presence ? presenceSelected : whenSelected;
						if (!present.has(occurrence.location) || active.has(handle)) {
							(selected[handle] ??= new Set()).add(plan.target);
							if (plan.scopeName) (named[handle] ??= {})[plan.name] = value.handle;
						}
						correspondence[handle] ??= value.handle;
						(targets[handle] ??= {})[plan.target] ??= value.handle;
					}
					(scopeTargets[handle] ??= {})[plan.name] = value.handle;
				} else if (plan.update) unresolved.push({ type: plan.target, handle, location: occurrence.location, reasons: [ReferenceUnmapped] });
			}
		}
		const skipped = {};
		for (const [handle, types] of Object.entries(targets)) {
			const rest = Object.keys(types).filter(type => !selected[handle]?.has(type));
			if (rest.length) skipped[handle] = rest;
		}
		return { state, correspondence, targets, scopeTargets, unresolved, skipped, named };
	});

	const unfold = resolved => {
		const index = new StateIndex(resolved.state, model);
		const unfolder = new Unfolder(index, resolved.correspondence, resolved.targets, resolved.scopeTargets, resolved.skipped, resolved.named);
		const scopes = [];
		for (const plan of plans) {
			const occurrences = [], skipped = [];
			for (const handle of index.handlesOf(plan.source)) {
				if (!Object.hasOwn(resolved.scopeTargets[handle] ?? {}, plan.name)) continue;
				const contexts = plan.lines.some(info => info.contextual) || plan.contextualScope ? [null, ...sortCodePoints(unfolder.contexts(handle, plan.reach))] : [null];
				for (const context of contexts) {
					if (context === null && plan.contextualScope) continue;
					const occurrence = unfolder.occurrence(plan, handle, context);
					if (occurrence === null) continue;
					occurrence.targetContext = resolved.correspondence[context] ?? null;
					if (plan.when) {
						if (conditionConflicts(plan, occurrence, plan.when)) {
							skipped.push({ occurrence, target: plan.target, reason: InputConflicting, src: occurrence.exists.src, location: occurrence.location });
							continue;
						}
						if (!conditionHolds(plan.when, conditionReader(plan, occurrence))) continue;
					}
					occurrences.push(occurrence);
				}
			}
			scopes.push({ name: plan.name, occurrences, skipped });
		}
		return { ...resolved, scopes, sources: sortCodePoints(new Set(Object.values(index.sources))) };
	};

	const MappingRecordsCollect = named("MappingRecordsCollect", function* (env, unfolded) {
		const scopes = [];
		for (const [index, plan] of plans.entries()) {
			const scope = unfolded.scopes[index];
			const main = yield* collect(projectStages[plan.name])(env, scope.occurrences.map(item => ({ value: item.value, location: item.location })));
			const emitter = new MappingEmitter(program, "");
			const variants = scope.occurrences.flatMap(occurrence => variantsOf(occurrence, plan, emitter).map(item => [occurrence, ...item]));
			let projected = { value: [], ledger: [] };
			if (variants.length) projected = yield* collect(variantStages[plan.name])(env, variants.map(item => item[1]));
			scopes.push({ ...scope, records: main.value, gaps: main.ledger, variantRecords: projected.value, variantGaps: projected.ledger,
				variants: variants.map(item => ({ occurrence: item[0].location, pointer: item[2], meta: item[3], lines: item[4].map(info => [info.section, lineRecord(info)]), location: item[1].location })) });
		}
		return { ...unfolded, scopes };
	});

	const ClaimsEmit = named("ClaimsEmit", function* (env, collected) {
		const runTime = yield env.ClockRead();
		return emitMapping(program, collected, runTime);
	});

	const InstancesUnfold = namedStage("InstancesUnfold", lift(unfold));
	return { HandlesResolve, InstancesUnfold, MappingRecordsCollect, ClaimsEmit,
		MappingRead: namedStage("MappingRead", collect(pipe(HandlesResolve, InstancesUnfold, MappingRecordsCollect, ClaimsEmit))) };
}

/**
 * A mapping program decoded from its `mappingProgramJson`, with its stages.
 * `implementations` supplies the code of declared library functions, by `Namespace/Name`.
 */
export function loadMappingProgram(data, sourceModel, targetModel, { implementations = {} } = {}) {
	const registry = new Registry();
	registry.declareSlots(data.slots);
	const evaluator = registerFunctions(registry, data, implementations);
	const plans = data.plans.map(plan => {
		const lines = plan.lines.map(info => ({ ...info }));
		return {
			...plan, lines, shape: registry.decode(plan.shape), template: registry.decode(plan.template), handleTemplate: registry.decode(plan.handleTemplate),
			segmentKeys: new Map(plan.segmentKeys.map(([steps, keys]) => [valueKey(steps), keys])),
			sectionLines: new Map(lines.map(info => [`${info.section}\u0000${lineRecord(info)}`, info])),
		};
	});
	const program = { ...data, plans, model: sourceModel, targetModel, evaluator };
	program.stages = mappingStages(program);
	return program;
}

export { StateIndex, Unfolder, pointersOf, valueAt, intersect };

// EOF
