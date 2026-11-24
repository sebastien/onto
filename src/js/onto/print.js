/** Module: print — spec-02 audit log text, flat or compact, as `observations/formatter.py`'s `renderObservationsLog`. */

import { printText } from "./functions.js";
import { claimOrder } from "./observations.js";
import { activeHandles, compareCodePoints, compareTimestamps, jsonEqual } from "./values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const QUALIFIERS = ["cur", "unit", "period", "scale"];
const META_KEYS = ["src", "at", "valid", "ctx", "conf", "by", "of", "approved", ...QUALIFIERS, "conflict"];
const HEADER_KEYS = ["rev", "src", "at", "by", "conf"];

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** Paths in their shortest form: relative to the namespace, else through the most specific alias. */
function namer(namespace, uses) {
	const aliases = new Map(uses);
	return path => {
		const prefix = `${namespace}/`;
		if (path.startsWith(prefix)) {
			const relative = path.slice(prefix.length), [head] = relative.split("/");
			if (!relative.includes("/") || (aliases.get(head) ?? prefix + head) === prefix + head) return relative;
		}
		let best = null;
		for (const [alias, target] of uses) if (path.startsWith(`${target}/`) && (!best || target.length > best[1].length)) best = [alias, target];
		if (best) return best[0] + path.slice(best[1].length);
		throw new Error(`No short form for '${path}': add a @use alias`);
	};
}

function printAnnotations(pairs) {
	if (!pairs.length) return "";
	const rank = key => META_KEYS.includes(key) ? META_KEYS.indexOf(key) : META_KEYS.length;
	const ranked = [...pairs].sort(([a], [b]) => rank(a) - rank(b) || compareCodePoints(a, b));
	return "{" + ranked.map(([key, value]) => value === true ? key : `${key}=${value}`).join(", ") + "}";
}

const claimMeta = claim => Object.fromEntries(META_KEYS.filter(key => Object.hasOwn(claim, key)).map(key => [key, claim[key]]));

function observationDefaults(observations) {
	return Object.fromEntries(Object.entries(observations.obs).filter(([key]) => ["src", "at", "by", "conf"].includes(key)).map(([key, value]) => [key, key === "conf" ? Number(value) : value]));
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** Shared spelling for values, typed mentions and statement metadata. */
class ObservationPrinter {
	constructor(model, observations) {
		this.model = model;
		this.observations = observations;
		this.short = namer(model.namespace, model.uses ?? []);
		this.typed = new Set();
		this.aliases = new Map();
	}

	handle(name) {
		if (this.aliases.has(name)) return this.aliases.get(name);
		if (name === "?" || this.typed.has(name)) return name;
		this.typed.add(name);
		const type = this.observations.instances[name].type;
		return this.model.relations[type] ? name : `${name}:${this.short(type)}`;
	}

	value(value, inSet = false, typed = true) {
		if (value === null) return "null";
		if (typeof value === "boolean") return value ? "true" : "false";
		if (value && typeof value === "object") {
			if (Object.hasOwn(value, "unknown")) return "?";
			if (Object.hasOwn(value, "ref")) return typed ? this.handle(value.ref) : value.ref;
			const members = value.set.map(member => [this.value(member, true, false), member]).sort(([a], [b]) => compareCodePoints(a, b));
			const parts = members.map(([, member]) => this.value(member, true, typed));
			if (value.partial) parts.push("...");
			return `[${parts.join(", ")}]`;
		}
		return printText(value, inSet);
	}

	meta(claim, defaults) {
		const pairs = META_KEYS.filter(key => Object.hasOwn(claim, key) && (!Object.hasOwn(defaults, key) || claim[key] !== defaults[key]))
			.map(key => [key, key === "ctx" ? this.aliases.get(claim[key]) ?? claim[key] : claim[key]]);
		const text = printAnnotations(pairs);
		return text ? ` ${text}` : "";
	}

	linkParts(claim) {
		const decl = this.model.relations[claim.rel];
		const [left, right] = decl.participants;
		const subject = claim.roles[left.role], object = claim.roles[right.role];
		if (subject !== "?") return [subject, decl.verb, object];
		if (object === "?" || !decl.inverse) throw new Error("A relation with an unknown subject requires an inverse verb and a known object");
		return [object, decl.inverse, "?"];
	}

	statement(claim) {
		for (const [kind, operator] of [["same", "="], ["distinct", "!="]]) {
			if (Object.hasOwn(claim, kind)) return `${this.handle(claim[kind][0])} ${operator} ${this.handle(claim[kind][1])}`;
		}
		if (Object.hasOwn(claim, "rel")) {
			const prefix = Object.hasOwn(claim, "s") ? `${this.aliases.get(claim.s) ?? claim.s}: ` : "";
			const [subject, verb, object] = this.linkParts(claim);
			return `${prefix}${this.handle(subject)} ${verb} ${this.handle(object)}`;
		}
		const subject = this.handle(claim.s);
		if (Object.hasOwn(claim, "facet")) return `${subject}[${claim.facet}]`;
		if (Object.hasOwn(claim, "p")) return `${subject}.${claim.p}` + (Object.hasOwn(claim, "v") ? ` ${this.value(claim.v)}` : "");
		return subject;
	}

	typeName(handle) {
		const type = this.observations.instances[handle].type, decl = this.model.relations[type];
		if (decl) return `${this.short(decl.participants[0].type)}.${decl.verb}.${this.short(decl.participants[1].type)}`;
		return this.short(type);
	}

	blockSubject(claim, retract) {
		if (retract) return null;
		if (Object.hasOwn(claim, "p")) return claim.s;
		if (Object.hasOwn(claim, "rel") && !Object.hasOwn(claim, "s")) return this.linkParts(claim)[0];
		return null;
	}

	/** Allocate aliases for reused handles; return those without a body to bind them inline. */
	bindAliases(events) {
		const blocks = new Set(), uses = new Map();
		const count = handle => uses.set(handle, (uses.get(handle) ?? 0) + 1);
		let previous = null;
		for (const [claim, retract] of events) {
			const subject = this.blockSubject(claim, retract);
			const run = JSON.stringify([subject, claim.src ?? null, claim.at ?? null, claim.ctx ?? null]);
			if (subject && blocks.has(subject) && run !== previous) count(subject);
			if (subject) blocks.add(subject);
			const others = activeHandles([claim]);
			others.delete(subject);
			for (const handle of [...(claim.same ?? []), ...(claim.distinct ?? [])]) others.add(handle);
			for (const handle of others) count(handle);
			previous = run;
		}
		const reserved = new Set(Object.keys(this.observations.instances)), counts = new Map();
		for (const [handle, uses_] of [...uses].sort(([a], [b]) => compareCodePoints(a, b))) {
			if (["none", "null"].includes(handle) || !blocks.has(handle) && uses_ < 2) continue;
			const type = this.observations.instances[handle].type, decl = this.model.relations[type];
			const name = decl ? decl.verb : type.split("/").at(-1);
			const base = name.slice(0, 1).toLowerCase() + name.slice(1);
			let index = (counts.get(base) ?? 0) + 1, alias;
			while (reserved.has(alias = `${base}${index}`)) index += 1;
			// Estimate the cost in characters without depending on one model's tokenizer.
			const cost = blocks.has(handle) ? alias.length + 1 : `@entity ${alias}=${handle}\n`.length;
			if (uses_ * (handle.length - alias.length) > cost) {
				this.aliases.set(handle, alias);
				reserved.add(alias);
				counts.set(base, index);
			}
		}
		return [...this.aliases.keys()].filter(handle => !blocks.has(handle));
	}

	headers() {
		const obs = this.observations.obs;
		const args = HEADER_KEYS.filter(key => Object.hasOwn(obs, key)).map(key => `${key}=${obs[key]}`).join(" ");
		const lines = [`@obs ${obs.ontology}` + (args ? ` ${args}` : "")];
		const sources = Object.entries(this.observations.sources);
		if (sources.length) lines.push("@src " + sources.sort(([a], [b]) => compareCodePoints(a, b)).map(([alias, token]) => `${alias}=${token}`).join(" "));
		if (obs.scope !== null && obs.scope !== undefined) lines.push(`@scope ${obs.scope}`);
		const ordinary = new Set(), namedLinks = new Set();
		for (const claim of [...this.observations.claims, ...this.observations.retractions]) {
			if (Object.hasOwn(claim, "s")) {
				ordinary.add(claim.s);
				if (Object.hasOwn(claim, "rel")) namedLinks.add(claim.s);
			}
			for (const handle of Object.values(claim.roles ?? {})) if (handle !== "?") ordinary.add(handle);
			for (const kind of ["same", "distinct"]) for (const handle of claim[kind] ?? []) ordinary.add(handle);
			const value = claim.v, members = value && typeof value === "object" && Object.hasOwn(value, "set") ? value.set : [value];
			for (const member of members) if (member && typeof member === "object" && Object.hasOwn(member, "ref")) ordinary.add(member.ref);
		}
		for (const [handle, instance] of Object.entries(this.observations.instances).sort(([a], [b]) => compareCodePoints(a, b))) {
			if (this.aliases.has(handle) || (this.model.relations[instance.type] ? namedLinks : ordinary).has(handle)) continue;
			lines.push(`@type ${handle} ${this.typeName(handle)}`);
			this.typed.add(handle);
		}
		return lines;
	}
}

/** Directives and statements with their metadata suffix, in audit order. */
function* logEntries(p, events) {
	const observations = p.observations, current = observationDefaults(observations);
	const directiveKeys = new Set(["src", "at"].filter(key => events.every(([event]) => Object.hasOwn(event, key))));
	const grouped = new Set();
	for (const [claim, retract] of events) {
		if (grouped.has(claim)) continue;
		const meta = claimMeta(claim), facets = [];
		if (claim.exists && !retract) {
			// Reconstitute a record header's existence + facets as one statement.
			for (const facet of observations.claims) {
				if (!Object.hasOwn(facet, "facet") || facet.n !== claim.n || facet.s !== claim.s) continue;
				const { ctx: context = null, ...facetMeta } = claimMeta(facet);
				const headMeta = Object.fromEntries(Object.entries(meta).filter(([key]) => !["valid", "ctx"].includes(key)));
				if (!jsonEqual(facetMeta, headMeta)) continue;
				if (context !== null && (meta.ctx ?? context) !== context) continue;
				if (context !== null) meta.ctx = context;
				facets.push(facet.facet);
				grouped.add(facet);
			}
		}
		// There is no directive for clearing src/at. Do not set one when later claims lack it.
		for (const key of ["src", "at", "ctx"]) {
			const value = meta[key];
			if (value !== undefined && value !== null && value !== current[key] && (key === "ctx" || directiveKeys.has(key))) {
				yield `@${key} ${key === "ctx" ? p.aliases.get(value) ?? value : value}`;
				current[key] = value;
			}
		}
		yield [claim, retract, (facets.length ? `[${facets.sort(compareCodePoints).join(", ")}]` : "") + p.meta(meta, current)];
	}
}

/** Print a gap-free log as `.obs` text: flat, or `compact` with `@entity` blocks and aliases. */
export function printObservationsLog(model, observations, { compact = false } = {}) {
	const p = new ObservationPrinter(model, observations);
	const events = [...observations.claims.map(claim => [claim, false]), ...observations.retractions.map(claim => [claim, true])];
	events.sort(([a], [b]) => {
		const [x, n] = claimOrder(a), [y, m] = claimOrder(b);
		return compareTimestamps(x, y) || n - m || Number(!a.exists) - Number(!b.exists);
	});
	const prelude = compact ? p.bindAliases(events) : [];
	const lines = p.headers();
	for (const handle of prelude.sort(compareCodePoints)) lines.push(`@entity ${p.aliases.get(handle)}=${handle} ${p.typeName(handle)}`);
	const bound = new Set();
	const runs = [];
	for (const entry of logEntries(p, events)) {
		const key = compact && typeof entry !== "string" ? p.blockSubject(entry[0], entry[1]) : null;
		const last = runs.at(-1);
		if (last && last[0] === key) last[1].push(entry);
		else runs.push([key, [entry]]);
	}
	for (const [handle, run] of runs) {
		if (handle !== null) {
			const alias = p.aliases.get(handle);
			if (alias || run.length > 1) {
				lines.push(`@entity ${alias && !bound.has(handle) ? `${alias}=${handle}` : alias ?? handle} ${p.typeName(handle)}`);
				bound.add(handle);
				p.typed.add(handle);
				for (const [claim, , suffix] of run) {
					const body = Object.hasOwn(claim, "p") ? `${claim.p} ${p.value(claim.v)}` : `-> ${p.linkParts(claim)[1]} ${p.handle(p.linkParts(claim)[2])}`;
					lines.push("  " + body + suffix);
				}
				continue;
			}
		}
		for (const entry of run) {
			if (typeof entry === "string") lines.push(entry);
			else lines.push((entry[1] ? "- " : "") + p.statement(entry[0]) + entry[2]);
		}
	}
	return lines.join("\n") + "\n";
}

// EOF
