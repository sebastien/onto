/**
 * Module: observations — merge, reconcile and print spec-02 observation logs, as `observations/operations.py`.
 *
 * Logs are their JSON form (`onto.observations/1`). Unlike Python, loading does not re-validate a log
 * through its text form: the runtime only reads logs that compiled programs produced, and Python checks
 * the same programs on the same inputs.
 */

import { valueIdentity } from "./functions.js";
import { clone, compareCodePoints, compareTimestamps, isSet, parseInterval, referenceHandles, timestampValue, valueKey } from "./values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

export const OBSERVATIONS_FORMAT = "onto.observations/1";
const ZERO = [0n, ""];

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** `(subject, member, ctx)` as one comparable key. */
export function claimSlot(claim) {
	for (const kind of ["same", "distinct"]) if (Object.hasOwn(claim, kind)) return valueKey([kind, valueKey(claim[kind]), ""]);
	if (Object.hasOwn(claim, "rel")) return valueKey([claim.s ?? `${claim.rel}:${valueKey(claim.roles)}`, "", claim.ctx ?? ""]);
	return valueKey([claim.s, Object.hasOwn(claim, "facet") ? `[${claim.facet}]` : claim.p ?? "", claim.ctx ?? ""]);
}

export function claimOrder(claim) {
	return [Object.hasOwn(claim, "at") ? timestampValue(claim.at) : ZERO, claim.n];
}

export function compareClaims(left, right) {
	const [a, n] = claimOrder(left), [b, m] = claimOrder(right);
	return compareTimestamps(a, b) || n - m;
}

const byOrder = items => [...items].sort(compareClaims);

/** A bare assertion can update a live same-source relation, not supply new endpoints. */
function withNamedRelationRoles(claim, previous) {
	if (claim.exists && previous.length) {
		const link = previous.at(-1);
		if (Object.hasOwn(link, "rel") && Object.hasOwn(link, "s")) {
			const { exists, ...rest } = claim;
			return { ...rest, rel: link.rel, roles: link.roles };
		}
	}
	return claim;
}

export function markImplicit(instances, claims) {
	const explicit = new Set(claims.filter(claim => claim.exists || Object.hasOwn(claim, "rel") && Object.hasOwn(claim, "s")).map(claim => claim.s));
	const referenced = new Set();
	for (const claim of claims) {
		if (Object.hasOwn(claim, "ctx")) referenced.add(claim.ctx);
		for (const handle of Object.values(claim.roles ?? {})) if (handle !== "?") referenced.add(handle);
		for (const handle of referenceHandles(claim.v)) referenced.add(handle);
	}
	return Object.fromEntries(Object.entries(instances).map(([handle, instance]) => [handle,
		{ type: instance.type, ...(referenced.has(handle) && !explicit.has(handle) ? { implicit: true } : {}) }]));
}

export function sourceToken(observations, claim) {
	const name = claim.src;
	return Object.hasOwn(observations.sources, name ?? "") ? observations.sources[name] : name;
}

function overlaps(left, right) {
	const [a, b] = Object.hasOwn(left, "valid") ? parseInterval(left.valid) : [null, null];
	const [c, d] = Object.hasOwn(right, "valid") ? parseInterval(right.valid) : [null, null];
	return (a === null || d === null || compareTimestamps(a, d) <= 0) && (c === null || b === null || compareTimestamps(c, b) <= 0);
}

function retracts(retraction, claim, sources) {
	const withdrawn = retraction.of ?? retraction.src, claimed = claim.src;
	if ((sources[withdrawn] ?? withdrawn) !== (sources[claimed] ?? claimed) || compareClaims(claim, retraction) > 0) return false;
	if (Object.hasOwn(retraction, "by") && retraction.by !== claim.by) return false;
	if (Object.hasOwn(retraction, "ctx") && retraction.ctx !== claim.ctx) return false;
	for (const kind of ["same", "distinct"]) {
		if (Object.hasOwn(retraction, kind)) return Object.hasOwn(claim, kind) && valueKey([...new Set(retraction[kind])].sort()) === valueKey([...new Set(claim[kind])].sort());
		if (Object.hasOwn(claim, kind)) return !Object.hasOwn(retraction, "p") && !Object.hasOwn(retraction, "facet") && claim[kind].includes(retraction.s);
	}
	if (Object.hasOwn(retraction, "rel")) return claimSlot(retraction) === claimSlot(claim) || Boolean(retraction.s && retraction.s === claim.s);
	if (!Object.hasOwn(claim, "s") || retraction.s !== claim.s) {
		return !Object.hasOwn(retraction, "p") && !Object.hasOwn(retraction, "facet")
			&& (claim.ctx === retraction.s || Object.hasOwn(claim, "rel") && !Object.hasOwn(claim, "s") && Object.values(claim.roles).includes(retraction.s));
	}
	if (Object.hasOwn(retraction, "facet")) return claim.facet === retraction.facet || (claim.p ?? "").startsWith(`${retraction.facet}.`);
	if (Object.hasOwn(retraction, "p")) return claim.p === retraction.p || (claim.p ?? "").startsWith(retraction.p + ".") || (claim.p ?? "").startsWith(retraction.p + "[");
	return true;
}

/** Apply identity links before slot reconciliation. Conflicting joins are held back (lenient) or raise (strict). */
function canonicalise(model, claims, instances, mode, warnings) {
	const parents = new Map(Object.keys(instances).map(handle => [handle, handle]));
	const types = new Map(Object.entries(instances).map(([handle, instance]) => [handle, instance.type]));
	const groups = new Map(Object.keys(instances).map(handle => [handle, new Set([handle])]));
	const joins = [], held = new Set();
	const root = handle => {
		while (parents.get(handle) !== handle) {
			parents.set(handle, parents.get(parents.get(handle)));
			handle = parents.get(handle);
		}
		return handle;
	};
	const conflict = (claim, message) => {
		held.add(claim);
		if (mode === "strict") throw new Error(message);
		warnings.push({ code: "identity", message });
	};
	const distinct = claims.filter(claim => Object.hasOwn(claim, "distinct")).map(claim => claim.distinct);
	for (const claim of byOrder(claims.filter(claim => Object.hasOwn(claim, "same")))) {
		const [left, right] = claim.same, a = root(left), b = root(right);
		if (a === b) {
			if (joins.some(([canonical, aliases]) => aliases.has(left) && canonical.has(right))) conflict(claim, `Identity link '${left} = ${right}' opposes the earlier canonical choice '${a}'`);
			continue;
		}
		if (distinct.some(([x, y]) => new Set([root(x), root(y)]).size === 2 && [root(x), root(y)].every(item => item === a || item === b))) {
			conflict(claim, `Identity link '${left} = ${right}' contradicts a distinct link`);
			continue;
		}
		if (!(types.get(a) === types.get(b) || model.isA(types.get(a), types.get(b)) || model.isA(types.get(b), types.get(a)))) {
			conflict(claim, `Identity groups '${a}' and '${b}' have incompatible refined types`);
			continue;
		}
		joins.push([new Set(groups.get(a)), new Set(groups.get(b))]);
		parents.set(b, a);
		for (const handle of groups.get(b)) groups.get(a).add(handle);
		groups.delete(b);
		if (model.isA(types.get(b), types.get(a))) types.set(a, types.get(b));
	}
	const value = item => {
		if (item && typeof item === "object" && Object.hasOwn(item, "ref")) return { ref: root(item.ref) };
		if (isSet(item)) {
			const members = new Map(item.set.map(member => [valueKey(value(member)), value(member)]));
			return { ...item, set: [...members.keys()].sort(compareCodePoints).map(key => members.get(key)) };
		}
		return item;
	};
	const result = [];
	for (const claim of claims) {
		if (held.has(claim)) continue;
		if (Object.hasOwn(claim, "same") || Object.hasOwn(claim, "distinct")) { result.push(claim); continue; }
		const normal = { ...claim };
		for (const key of ["s", "ctx"]) if (Object.hasOwn(normal, key)) normal[key] = root(normal[key]);
		if (Object.hasOwn(normal, "v")) normal.v = value(normal.v);
		if (Object.hasOwn(normal, "roles")) {
			normal.roles = Object.fromEntries(Object.entries(normal.roles).map(([role, handle]) => [role, handle !== "?" ? root(handle) : "?"]));
			if (model.get(normal.rel)?.symmetric && !Object.values(normal.roles).includes("?")) {
				const roles = Object.keys(normal.roles), [left, right] = Object.values(normal.roles).sort(compareCodePoints);
				normal.roles = { [roles[0]]: left, [roles[1]]: right };
			}
		}
		result.push(normal);
	}
	const registry = Object.fromEntries(Object.entries(instances).map(([handle, instance]) => [handle, { type: root(handle) === handle ? types.get(root(handle)) : instance.type }]));
	return [result, registry];
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

/** A log's JSON as Python's `observationsFromJson` returns it: typed instances only, and an explicit `scope`. */
export function observationsFromJson(data) {
	return {
		format: OBSERVATIONS_FORMAT, obs: { ...clone(data.obs), scope: data.obs.scope ?? null }, sources: { ...data.sources },
		instances: Object.fromEntries(Object.entries(data.instances).map(([handle, instance]) => [handle, { type: instance.type }])),
		claims: clone(data.claims), retractions: clone(data.retractions ?? []),
	};
}

/** Combine logs of one ontology into one log, renumbering statements and source aliases. */
export function mergeObservationLogs(model, logs) {
	const bareSources = new Set();
	for (const log of logs) for (const claim of [...log.claims, ...log.retractions]) {
		for (const key of ["src", "of"]) if (claim[key] !== undefined && !Object.hasOwn(log.sources, claim[key])) bareSources.add(claim[key]);
	}
	let out = null, offset = 0, sourceNumber = 0;
	for (const log of logs) {
		const data = clone(log), scope = log.obs.scope ?? null;
		if (log.obs.ontology !== model.namespace) throw new Error(`expected observations of ${model.namespace}`);
		if (out === null) {
			out = { format: OBSERVATIONS_FORMAT, obs: Object.fromEntries(Object.entries(log.obs).filter(([key]) => ["ontology", "rev", "scope"].includes(key))), sources: {}, instances: {}, claims: [], retractions: [] };
		} else if (scope !== (out.obs.scope ?? null)) throw new Error(`@scope ${scope} does not match the first input's @scope ${out.obs.scope}`);
		const aliases = {};
		for (const [alias, token] of Object.entries(data.sources)) {
			sourceNumber += 1;
			while (bareSources.has(`d${sourceNumber}`)) sourceNumber += 1;
			aliases[alias] = `d${sourceNumber}`;
			out.sources[aliases[alias]] = token;
		}
		for (const [handle, item] of Object.entries(data.instances)) {
			const existing = out.instances[handle];
			if (existing && scope === null) throw new Error(`handle '${handle}' appears in multiple inputs without a shared @scope`);
			if (!existing || model.isA(item.type, existing.type)) out.instances[handle] = item;
			else if (item.type !== existing.type && !model.isA(existing.type, item.type)) throw new Error(`handle '${handle}' has incompatible types '${existing.type}' and '${item.type}'`);
		}
		let last = 0;
		for (const key of ["claims", "retractions"]) for (const claim of data[key]) {
			const renamed = Object.fromEntries(Object.entries(claim).map(([name, value]) => [name, ["src", "of"].includes(name) ? aliases[value] ?? value : value]));
			out[key].push({ ...renamed, n: offset + claim.n });
			last = Math.max(last, claim.n);
		}
		offset += last;
	}
	return out ?? { format: OBSERVATIONS_FORMAT, obs: { ontology: model.namespace, scope: null }, sources: {}, instances: {}, claims: [], retractions: [] };
}

/** Apply withdrawals, identity links and supersession, and mark conflicting claims across sources. */
export function reconcileObservations(model, observations, mode = "lenient") {
	const instances = observations.instances, warnings = [];
	const attrOf = (claim, registry) => Object.hasOwn(claim, "p") ? model.lookup(registry[claim.s]?.type, claim.p) : undefined;
	const multi = (claim, registry) => Object.hasOwn(claim, "p") && Boolean(attrOf(claim, registry)?.multi);
	const meaning = (claim, registry) => {
		const attr = attrOf(claim, registry);
		const qualifiers = Object.hasOwn(claim, "p") ? model.qualifiers(attr, claim) : {};
		const value = Object.hasOwn(claim, "v") ? valueIdentity(claim.v, Boolean(attr?.numeric), Boolean(attr?.numericRange)) : "missing";
		return valueKey([value, valueKey(claim.roles ?? null), valueKey(qualifiers)]);
	};
	const token = claim => sourceToken(observations, claim);
	const active = new Map();
	const items = [...observations.claims.map(claim => [claim, false]), ...observations.retractions.map(claim => [claim, true])].sort(([a], [b]) => compareClaims(a, b));
	for (let [item, retract] of items) {
		const { conflict, ...plain } = item;
		item = plain;
		if (!retract) {
			const key = valueKey([claimSlot(item), token(item) ?? null]);
			if (!active.has(key)) active.set(key, []);
			const history = active.get(key);
			history.push(withNamedRelationRoles(item, history));
			continue;
		}
		let removed = false;
		for (const [key, claims] of [...active]) {
			const kept = [];
			for (let claim of claims) {
				if (!retracts(item, claim, observations.sources)) { kept.push(claim); continue; }
				if (!Object.hasOwn(item, "v")) { removed = true; continue; }
				if (claimSlot(item) !== claimSlot(claim)) { kept.push(claim); continue; }
				if (meaning(item, instances) === meaning(claim, instances)) { removed = true; continue; }
				if (isSet(claim.v)) {
					const members = claim.v.set.filter(member => meaning({ ...claim, v: member }, instances) !== meaning(item, instances));
					if (members.length !== claim.v.set.length) {
						removed = true;
						if (!members.length) continue;
						claim = { ...claim, v: { ...claim.v, set: members } };
					}
				}
				kept.push(claim);
			}
			active.set(key, kept);
		}
		if (!removed) warnings.push({ code: "retraction", message: `Retraction of '${claimSlot(item)}' matched no claim` });
	}
	const live = [...active.values()].flat();
	const [rewritten, registry] = canonicalise(model, live, instances, mode, warnings);
	const slots = new Map();
	for (let claim of byOrder(rewritten)) {
		const key = valueKey([claimSlot(claim), token(claim) ?? null]);
		claim = withNamedRelationRoles(claim, slots.get(key) ?? []);
		if (Object.hasOwn(claim, "same") || Object.hasOwn(claim, "distinct")) {
			if (!slots.has(key)) slots.set(key, []);
			slots.get(key).push(claim);
			continue;
		}
		const complete = isSet(claim.v) && !claim.v.partial;
		if (!multi(claim, registry) || complete) slots.set(key, [claim]);
		else if (!(slots.get(key) ?? []).some(old => meaning(old, registry) === meaning(claim, registry))) {
			if (!slots.has(key)) slots.set(key, []);
			slots.get(key).push(claim);
		}
	}
	const claims = [...slots.values()].flat();
	const conflicted = new Set();
	claims.forEach((left, index) => {
		if (multi(left, registry)) return;
		for (let other = index + 1; other < claims.length; other++) {
			const right = claims[other];
			if (Object.hasOwn(left, "rel") !== Object.hasOwn(right, "rel") || claimSlot(left) !== claimSlot(right)) continue;
			if (token(left) !== token(right) && meaning(left, registry) !== meaning(right, registry) && overlaps(left, right)) {
				conflicted.add(index);
				conflicted.add(other);
			}
		}
	});
	const marked = claims.map((claim, index) => conflicted.has(index) ? { ...claim, conflict: true } : claim);
	return {
		format: OBSERVATIONS_FORMAT, obs: clone(observations.obs), sources: { ...observations.sources },
		instances: markImplicit(registry, marked), claims: clone(marked).sort((a, b) => a.n - b.n), retractions: [], warnings,
	};
}

/** The reconciled source state of several binding logs, as the mapping reads it. */
export function sourceState(model, logs) {
	const merged = mergeObservationLogs(model, logs.map(observationsFromJson));
	const { warnings, ...state } = reconcileObservations(model, observationsFromJson(merged));
	return state;
}

// EOF
