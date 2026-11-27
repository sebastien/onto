/**
 * Module: store/validate — spec-02's strict reading of an appended batch, from a store bundle's model facts alone
 * (spec-08 "Validation"), as `ObservationStore.validate` and `observationsFromJson(..., "strict")` do in Python.
 *
 * A batch is accepted exactly as written, or rejected: `400 invalid` with the `check` it fails and, where Python can
 * tell it, the statement `n`. Python validates by rendering the batch as text and parsing it with the ontology, then
 * comparing what it read with what it loaded; this module follows the same phases in the same order, so that it
 * reports the same first failure, and compares the batch with what Python would load instead of rendering it.
 */

import { Model, QUALIFIERS, unkeyed } from "../model.js";
import { claimOrder, compareClaims } from "../observations.js";
import { RE_DURATION, RE_NAME, RE_PATH, canonicalNumber, compareTimestamps, decimalParts, parseInterval, printText, timestampValue, valueKey } from "../values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

export const OBSERVATIONS_FORMAT = "onto.observations/1";
const HEADER_KEYS = ["rev", "src", "at", "by", "conf"];
const META_KEYS = ["src", "at", "valid", "ctx", "conf", "by", "of", "approved", ...QUALIFIERS, "conflict"];
const DEFAULT_KEYS = ["src", "at", "by", "conf"];
const FORMS = ["exists", "facet", "p", "rel", "same", "distinct"];
const NUMBERS = ["Integer", "Number", "Amount", "Percent"];
const SEGMENT = "[A-Za-z_][A-Za-z0-9_]*(?:\\[[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*\\])?";
const RE_ELEMENT_PATH = new RegExp(`^${SEGMENT}(?:\\.${SEGMENT})*$`);
const RE_REF = /^([A-Za-z_][A-Za-z0-9_]*)(?::[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*)?$/;
const RE_REL = /^[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*\.[a-z][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*$/;
// NOTE: Python's `\s` (annotation tokens) also counts \x1c-\x1f and \x85 as whitespace, and not ﻿.
const RE_TOKEN = new RegExp("^[^\\t\\n\\v\\f\\r \\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000{},=]+$", "u");

/** A store's error answer: an HTTP status, a stable `error` code, a message and details (spec-08 "Protocol"). */
export class StoreError extends Error {
	constructor(status, error, message, details = {}) {
		super(message);
		this.status = status;
		this.error = error;
		this.details = details;
	}

	toJSON() {
		return { error: this.error, message: this.message, ...this.details };
	}
}

/** `400 invalid` for a batch failing `check`, at statement `n` when it can be told. */
export function invalid(check, message, n = null) {
	return new StoreError(400, "invalid", message, { check, ...(n !== null && n !== undefined ? { n } : {}) });
}

/** A failure of the JSON form, reported as `json` without a statement. */
class JsonError extends Error {}

/** A diagnostic of the text phases: its check and statement. */
class Diagnostic extends Error {
	constructor(check, message, n = null) {
		super(message);
		this.check = check;
		this.n = n;
	}
}

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);
const isName = text => typeof text === "string" && RE_NAME.test(text);
const isPath = text => typeof text === "string" && RE_PATH.test(text);
const isToken = text => typeof text === "string" && RE_TOKEN.test(text);
const lastSegment = path => path.slice(path.lastIndexOf("/") + 1);

function jsonObject(value, required, optional = []) {
	if (!isObject(value)) throw new JsonError("Expected a JSON object");
	const keys = Object.keys(value);
	if (!required.every(key => keys.includes(key)) || keys.some(key => !required.includes(key) && !optional.includes(key)))
		throw new JsonError(`Expected members ${required}, optional ${optional}`);
	return value;
}

function jsonString(value, check = isToken) {
	if (typeof value !== "string" || !check(value)) throw new JsonError(`Invalid JSON string '${value}'`);
	return value;
}

function jsonValue(value, member = false) {
	if (typeof value === "string" || typeof value === "boolean" || (value === null && !member)) return;
	if (!isObject(value)) throw new JsonError("A value must be a string, boolean, reference, collection, unknown or null");
	const keys = Object.keys(value).sort().join(",");
	if (keys === "ref") jsonString(value.ref, isName);
	else if (keys === "unknown" && value.unknown === true && !member) return;
	else if ((keys === "set" || keys === "partial,set") && !member) {
		if (!Array.isArray(value.set) || (Object.hasOwn(value, "partial") && value.partial !== true)) throw new JsonError("Invalid collection");
		for (const item of value.set) jsonValue(item, true);
	} else throw new JsonError("Invalid value members or non-concrete collection member");
}

function jsonClaim(value, retract) {
	const claim = jsonObject(value, ["n"], ["s", "exists", "facet", "p", "v", "rel", "roles", "same", "distinct", ...META_KEYS]);
	if (!Number.isInteger(claim.n) || claim.n < 1) throw new JsonError("n must be a positive statement ordinal");
	const forms = FORMS.filter(key => Object.hasOwn(claim, key));
	if (forms.length !== 1) throw new JsonError("A claim must have exactly one form");
	const [form] = forms;
	if (form === "same" || form === "distinct") {
		const pair = claim[form];
		if (Object.hasOwn(claim, "s") || !Array.isArray(pair) || pair.length !== 2) throw new JsonError("Identity links require two handles and no s");
		for (const handle of pair) jsonString(handle, isName);
	}
	if (Object.hasOwn(claim, "s")) jsonString(claim.s, isName);
	else if (!["rel", "same", "distinct"].includes(form)) throw new JsonError("A non-relation claim requires s");
	if (form === "exists" && claim.exists !== true) throw new JsonError("exists must be true");
	if (form === "facet") jsonString(claim.facet, isName);
	if (form === "p") {
		jsonString(claim.p, text => RE_ELEMENT_PATH.test(text));
		if (!Object.hasOwn(claim, "v") && !retract) throw new JsonError("An attribute claim requires v");
	}
	if (Object.hasOwn(claim, "v")) {
		if (form !== "p") throw new JsonError("Only attribute claims have v");
		jsonValue(claim.v);
	}
	if (form === "rel") {
		jsonString(claim.rel, text => RE_REL.test(text));
		if (!isObject(claim.roles)) throw new JsonError("A binary claim requires roles");
		for (const [role, handle] of Object.entries(claim.roles)) {
			jsonString(role, isName);
			jsonString(handle, text => text === "?" || isName(text));
		}
	} else if (Object.hasOwn(claim, "roles")) throw new JsonError("Only binary claims have roles");
	for (const key of META_KEYS) {
		if (!Object.hasOwn(claim, key)) continue;
		if (key === "conflict") {
			if (claim[key] !== true) throw new JsonError("conflict must be true");
		} else if (key === "conf") {
			if (typeof claim[key] !== "number" || !(claim[key] >= 0 && claim[key] <= 1)) throw new JsonError("conf must be a number within 0..1");
		} else jsonString(claim[key]);
	}
}

/** Whether a decimal spelling denotes an integer, as `Decimal(text) == Decimal(text).to_integral_value()`. */
function integral(text) {
	const { coefficient, exponent } = decimalParts(text);
	return exponent >= 0 || coefficient % 10n ** BigInt(-exponent) === 0n;
}

/** Exact comparison of two decimals' parts. */
function compareDecimals(left, right) {
	const scale = Math.min(left.exponent, right.exponent);
	const a = (left.negative ? -1n : 1n) * left.coefficient * 10n ** BigInt(left.exponent - scale);
	const b = (right.negative ? -1n : 1n) * right.coefficient * 10n ** BigInt(right.exponent - scale);
	return a < b ? -1 : a > b ? 1 : 0;
}

/** The members of a value: a set's, or the value itself. */
const members = value => isObject(value) && Array.isArray(value.set) ? value.set : [value];

/** A claim without what the round trip ignores (`n`, `conflict`), its set members sorted, as Python's `claimContent`. */
function content(claim) {
	const { n, conflict, ...rest } = claim;
	if (isObject(rest.v) && Array.isArray(rest.v.set)) rest.v = { ...rest.v, set: [...rest.v.set].sort((a, b) => valueKey(a) < valueKey(b) ? -1 : valueKey(a) > valueKey(b) ? 1 : 0) };
	return valueKey(rest);
}

function sameMultiset(left, right) {
	const counts = new Map();
	for (const item of left) counts.set(content(item), (counts.get(content(item)) ?? 0) + 1);
	for (const item of right) {
		const key = content(item), count = counts.get(key);
		if (!count) return false;
		counts.set(key, count - 1);
	}
	return [...counts.values()].every(count => count === 0);
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** Validate batches against one store bundle's model facts. */
export class BatchValidator {
	constructor(bundle) {
		this.bundle = bundle;
		this.facts = bundle.model;
		this.model = new Model(this.facts);
		this.vocabs = this.facts.vocabs ?? {};
	}

	// -- Model ------------------------------------------------------------------

	/** The declaration of an instance type: an entity, an association or a binary relation. */
	decl(path) {
		return this.model.get(path);
	}

	isA(path, ancestor) {
		return this.model.isA(path, ancestor);
	}

	/** Attribute `path` of `owner` with its validation facts; a relation's role is one, with card `1` unless declared. */
	lookup(owner, path) {
		const segments = unkeyed(path).split(".");
		const decl = this.decl(owner);
		if (!decl) return undefined;
		const facet = this.model.facetOf(owner, segments.join("."));
		let attr, rest = segments.slice(1);
		if (facet) {
			if (segments.length < 2) return undefined;
			attr = facet.attrs[segments[1]];
			rest = segments.slice(2);
		} else if (decl.kind === "entity") attr = this.model.entityAttrs(owner)[segments[0]];
		else if (decl.kind === "relation") {
			attr = decl.attrs[segments[0]];
			const role = (decl.roles ?? decl.participants ?? []).find(item => item.role === segments[0]);
			if (!attr && role) attr = { card: role.card ?? "1", type: { kind: this.facts.types[role.type]?.kind === "entity" ? "entity" : "relation", path: role.type } };
		}
		for (const name of rest) {
			const struct = attr?.struct ? this.facts.structs[attr.struct] : undefined;
			if (!struct) return undefined;
			attr = struct.fields[name];
		}
		return attr;
	}

	multi(attr) {
		return ["+", "*"].includes(attr.card ?? this.model.defaultCard);
	}

	/** The key field keying the elements of a multi-valued structure attribute, if any. */
	elementKey(attr) {
		const struct = attr && this.multi(attr) && attr.struct ? this.facts.structs[attr.struct] : undefined;
		return struct?.key ? [struct.key, struct.fields[struct.key]] : undefined;
	}

	/** Why `path` misnames keyed elements, as `Model.elementPathError`; undefined when well formed. */
	elementPathError(owner, path) {
		if (!RE_ELEMENT_PATH.test(path)) return `Invalid attribute path '${path}'`;
		const parts = path.split(".");
		const facet = this.model.facetOf(owner, unkeyed(path));
		if (facet && parts[0].includes("[")) return `'${unkeyed(parts[0])}' is a facet and has no keyed elements`;
		for (let index = facet ? 1 : 0; index < parts.length; index++) {
			const [name, key = ""] = parts[index].split("[");
			const prefix = [...parts.slice(0, index).map(unkeyed), name].join(".");
			const attr = this.lookup(owner, prefix);
			if (!attr) return undefined;
			const keyed = this.elementKey(attr);
			if (!keyed) {
				if (key) return `'${prefix}' has no keyed elements`;
				continue;
			}
			if (!key) {
				if (index + 1 === parts.length) continue;
				return `'${prefix}' needs an element key: ${prefix}[Key]`;
			}
			const value = key.slice(0, -1), [field, fieldAttr] = keyed, vocab = fieldAttr.type?.kind === "vocab" ? this.vocabs[fieldAttr.type.vocab] : undefined;
			if (vocab && !vocab.open && !vocab.values.includes(value)) return `'${value}' is not a value of '${prefix}' keys (${field})`;
			if (index + 1 < parts.length && parts[index + 1] === field && index + 2 === parts.length) return `'${prefix}[${value}].${field}' is implied by the key`;
		}
		return undefined;
	}

	/** The effective qualifiers of an attribute's value, and their conflicts with what the claim observes (`useType`). */
	qualifiers(attr, meta) {
		const qualifiers = {}, conflicts = [];
		for (const name of QUALIFIERS) {
			const observed = typeof meta[name] === "string" ? meta[name] : undefined, declared = attr.qualifiers?.[name];
			const fixed = observed !== undefined && !observed.startsWith("?") ? observed : undefined;
			if (fixed !== undefined) qualifiers[name] = fixed;
			else if (declared !== undefined) qualifiers[name] = declared;
			else if (observed !== undefined) qualifiers[name] = "?";
			if (fixed !== undefined && declared !== undefined && declared !== "?" && declared !== fixed) conflicts.push(`${name}=${fixed} contradicts inherited ${name}=${declared}`);
			const vocab = attr.qualifierVocabs?.[name] ? this.vocabs[attr.qualifierVocabs[name]] : undefined;
			for (const value of new Set([fixed, declared !== "?" ? declared : undefined].filter(item => item !== undefined)))
				if (vocab && !vocab.open && !vocab.values.includes(value)) conflicts.push(`${name}=${value} is not a value of '${attr.qualifierVocabs[name]}'`);
		}
		return { qualifiers, conflicts };
	}

	// -- Values -----------------------------------------------------------------

	/** The order of a range's bounds: a comparable key, or null when unordered (`rangeOrder`). */
	order(type) {
		if (type.kind === "builtin" && NUMBERS.includes(type.builtin)) return text => decimalParts(canonicalNumber(text));
		if (type.kind === "builtin" && ["Date", "DateTime"].includes(type.builtin)) return timestampValue;
		if (type.kind === "builtin" && type.builtin === "Duration") return text => RE_DURATION.test(text) ? null : decimalParts(canonicalNumber(text));
		if (type.kind === "vocab" && type.ordered) {
			const values = this.vocabs[type.vocab]?.values ?? [];
			return text => values.includes(text) ? values.indexOf(text) : null;
		}
		return null;
	}

	/** A scalar's loaded value from its rendered text, or a `value` error (`ObservationResolver.scalar`). */
	scalar(raw, quoted, type, unit, queue) {
		const text = raw;
		if (type.kind === "entity" || type.kind === "relation") {
			if (quoted) throw new Error("Reference values must be unquoted handles");
			const match = RE_REF.exec(text);
			if (!match) throw new Error(`Invalid reference '${text}'`);
			queue(match[1], type.path);
			return { ref: match[1] };
		}
		if (type.kind === "range" && type.element) {
			if (quoted) throw new Error("A range is written unquoted: low..high, low.. or ..high");
			const at = text.indexOf("..");
			const [low, high] = at < 0 ? [text, text] : [text.slice(0, at), text.slice(at + 2)];
			if (!low && !high) throw new Error("A range needs at least one bound");
			const bounds = [low, high].map(bound => bound ? this.scalar(bound, false, type.element, unit, queue) : null);
			const key = this.order(type.element);
			if (key && bounds.every(bound => bound !== null)) {
				const [a, b] = bounds.map(key);
				if (a !== null && b !== null && (typeof a === "number" ? a - b : Array.isArray(a) ? compareTimestamps(a, b) : compareDecimals(a, b)) > 0)
					throw new Error(`Range '${text}' has its low bound above its high bound`);
			}
			return bounds.map(bound => bound === null ? "" : String(bound)).join("..");
		}
		if (type.kind === "vocab") {
			const vocab = this.vocabs[type.vocab] ?? { values: [], open: true };
			if (quoted || !(type.hierarchical ? isPath : isName)(text) || (!vocab.open && !vocab.values.includes(text))) throw new Error(`'${text}' is not a vocabulary value`);
			return text;
		}
		const builtin = type.kind === "builtin" ? type.builtin : null;
		if (quoted && builtin !== null && builtin !== "Text") throw new Error(`Quoted text is not a ${builtin}`);
		if (NUMBERS.includes(builtin)) {
			const canonical = canonicalNumber(text);
			if (builtin === "Integer" && !integral(text)) throw new Error(`'${text}' is not an integer`);
			return canonical;
		}
		if (builtin === "Boolean") {
			if (text !== "true" && text !== "false") throw new Error(`'${text}' is not a boolean`);
			return text === "true";
		}
		if (builtin === "Date" || builtin === "DateTime") {
			timestampValue(text);
			if (text.includes("T") !== (builtin === "DateTime")) throw new Error(`'${text}' is not a ${builtin}`);
		}
		if (builtin === "Duration") return (unit ?? "?") === "?" && RE_DURATION.test(text) ? text : canonicalNumber(text);
		if (type.kind === "struct") throw new Error("Structures require field paths");
		return text;
	}

	/** A claim's loaded value (`ObservationResolver.value`) from its JSON value, as text renders it. */
	value(value, attr, unit, render, queue) {
		const multi = this.multi(attr), card = attr.card ?? this.model.defaultCard, type = attr.type ?? { kind: "unspecified" };
		if (isObject(value) && value.unknown === true) return { unknown: true };
		if (value === null) {
			if (multi) throw new Error("null requires a single-valued slot");
			return null;
		}
		if (isObject(value) && Array.isArray(value.set)) {
			if (!multi) throw new Error("Collection on a single-valued slot");
			if (!value.set.length && !value.partial && card === "+") throw new Error("[] contradicts cardinality +");
			// NOTE: Members are rendered sorted by their untyped spelling, then each with its typed mention.
			const sorted = [...value.set].sort((a, b) => compareText(render(a, true, false), render(b, true, false)));
			const loaded = sorted.map(member => {
				const raw = render(member, true, true);
				return this.scalar(raw.quoted ? JSON.parse(raw.text) : raw.text, raw.quoted, type, unit, queue);
			});
			const numeric = type.kind === "builtin" && [...NUMBERS, "Duration"].includes(type.builtin);
			const numericRange = type.kind === "range" && type.element?.kind === "builtin" && [...NUMBERS, "Duration"].includes(type.element.builtin);
			const identities = loaded.map(item => identity(item, numeric, numericRange));
			if (new Set(identities).size !== identities.length) throw new Error("Duplicate collection members");
			return { set: loaded.sort((a, b) => compareText(valueKey(a), valueKey(b))), ...(value.partial ? { partial: true } : {}) };
		}
		const raw = render(value, false, true);
		return this.scalar(raw.quoted ? JSON.parse(raw.text) : raw.text, raw.quoted, type, unit, queue);
	}

	// -- Validation ---------------------------------------------------------------

	/**
	 * Validate `data` for `partition` (`{id, anchor, types}`: the handles it already types); throw `StoreError` or return
	 * the batch's registry, with the handles the partition types added, as the store keeps it.
	 */
	validate(data, partition) {
		if (!isObject(data) || data.format !== OBSERVATIONS_FORMAT) throw invalid("observations", "observations must be an onto.observations/1 document");
		data = structuredClone(data);
		if (!Object.hasOwn(data, "instances")) data.instances = {};
		if (!isObject(data.instances)) throw invalid("observations", "instances must be an object");
		const root = this.bundle.kinds.find(kind => partition.id.startsWith(kind.kind + "/"))?.root.type;
		const known = { ...partition.types, [partition.anchor]: partition.types[partition.anchor] ?? root };
		for (const [handle, item] of Object.entries(data.instances)) {
			const type = isObject(item) ? item.type : undefined;
			if (Object.hasOwn(partition.types, handle) && typeof type === "string" && !(this.isA(type, known[handle]) || this.isA(known[handle], type)))
				throw invalid("type", `'${handle}' is a ${known[handle]} in '${partition.id}', not a ${type}`);
		}
		for (const statement of [...(Array.isArray(data.claims) ? data.claims : []), ...(Array.isArray(data.retractions) ? data.retractions : [])])
			for (const handle of isObject(statement) ? mentioned(statement) : [])
				if (!Object.hasOwn(data.instances, handle) && Object.hasOwn(known, handle) && known[handle]) data.instances[handle] = { type: known[handle] };
		try {
			this.read(data);
			this.check(data);
		} catch (error) {
			if (error instanceof JsonError) throw invalid("json", error.message);
			if (error instanceof Diagnostic) throw invalid(error.check, error.message, error.n);
			throw error;
		}
		return data;
	}

	/** The JSON form (`readObservationsJson`) and strict mode's gaps; failures are `json`. */
	read(data) {
		jsonObject(data, ["format", "obs", "sources", "instances", "claims", "retractions"], ["gaps"]);
		const obs = jsonObject(data.obs, ["ontology"], [...HEADER_KEYS, "scope"]);
		jsonString(obs.ontology, isPath);
		for (const key of HEADER_KEYS) if (Object.hasOwn(obs, key)) jsonString(obs[key]);
		if (obs.scope !== undefined && obs.scope !== null) jsonString(obs.scope);
		if (!isObject(data.sources) || !isObject(data.instances)) throw new JsonError("sources and instances must be objects");
		for (const [alias, token] of Object.entries(data.sources)) {
			jsonString(alias, isName);
			jsonString(token);
		}
		for (const [handle, instance] of Object.entries(data.instances)) {
			jsonString(handle, isName);
			jsonObject(instance, ["type"], ["implicit"]);
			if (Object.hasOwn(instance, "implicit") && instance.implicit !== true) throw new JsonError("implicit must be true when present");
			if (!this.decl(instance.type)) throw new JsonError(`'${instance.type}' is not an instance type`);
		}
		for (const key of ["claims", "retractions"]) {
			if (!Array.isArray(data[key])) throw new JsonError(`${key} must be an array`);
			for (const claim of data[key]) jsonClaim(claim, key === "retractions");
			for (const claim of data[key]) {
				if (Object.hasOwn(claim, "s") && !Object.hasOwn(data.instances, claim.s)) throw new JsonError(`Unregistered subject '${claim.s}'`);
				for (const kind of ["same", "distinct"])
					if (Object.hasOwn(claim, kind) && claim[kind].some(handle => !Object.hasOwn(data.instances, handle))) throw new JsonError("Unregistered identity handle");
				if (Object.hasOwn(claim, "rel")) {
					const relation = this.facts.relations[claim.rel];
					if (!relation || valueKey(Object.keys(claim.roles).sort()) !== valueKey(relation.participants.map(item => item.role).sort()))
						throw new JsonError("Binary roles must match the declared relation");
				}
			}
		}
		const gaps = data.gaps ?? [];
		if (!Array.isArray(gaps)) throw new JsonError("gaps must be an array");
		if (gaps.length) throw new JsonError("Gap-bearing JSON requires lenient mode");
	}

	/** The text phases (rendering, parsing, resolving, statement checks) and the round trip. */
	check(data) {
		const { obs, instances } = data;
		const events = [...data.claims.map(claim => [claim, false]), ...data.retractions.map(claim => [claim, true])];
		// Rendering: the log's order, then each statement's spelling (`renderObservationsLog`).
		const order = events.map(([claim]) => {
			if (Object.hasOwn(claim, "at")) try { timestampValue(claim.at); } catch (error) { throw new JsonError(error.message); }
			return claimOrder(claim);
		});
		const rendered = events.map((event, index) => [...event, order[index], index])
			.sort((a, b) => compareClaims(a[0], b[0]) || (a[0].exists ? 0 : 1) - (b[0].exists ? 0 : 1) || a[3] - b[3]).map(([claim, retract]) => [claim, retract]);
		const typed = new Set();
		const mention = handle => {
			if (handle === "?" || typed.has(handle)) return handle;
			if (!Object.hasOwn(instances, handle)) throw new JsonError(`'${handle}'`);
			typed.add(handle);
			return this.facts.relations[instances[handle].type] ? handle : `${handle}:${lastSegment(instances[handle].type)}`;
		};
		const render = (value, inSet, typedMention) => {
			if (value === null) return { text: "null", quoted: false };
			if (typeof value === "boolean") return { text: String(value), quoted: false };
			if (isObject(value) && value.unknown) return { text: "?", quoted: false };
			if (isObject(value) && Object.hasOwn(value, "ref")) return { text: typedMention ? mention(value.ref) : value.ref, quoted: false };
			const text = printText(value, inSet);
			return { text, quoted: text !== value };
		};
		const grouped = new Set(), lines = [];
		for (const [claim, retract] of rendered) {
			if (grouped.has(claim)) continue;
			const meta = Object.fromEntries(META_KEYS.filter(key => Object.hasOwn(claim, key)).map(key => [key, claim[key]]));
			const facets = [];
			if (claim.exists && !retract) {
				// NOTE: The printer writes an existence and the facets stated with it (same subject, ordinal and metadata) as one line.
				for (const facet of data.claims) {
					if (!Object.hasOwn(facet, "facet") || facet.n !== claim.n || facet.s !== claim.s) continue;
					const { ctx: context = null, ...facetMeta } = Object.fromEntries(META_KEYS.filter(key => Object.hasOwn(facet, key)).map(key => [key, facet[key]]));
					const { valid, ctx, ...own } = meta;
					if (valueKey(facetMeta) !== valueKey(own)) continue;
					if (context !== null && (meta.ctx ?? context) !== context) continue;
					if (context !== null) meta.ctx = context;
					facets.push(facet.facet);
					grouped.add(facet);
				}
			}
			// The statement's spelling, introducing typed mentions in the printer's order: subject, then roles or value.
			if (Object.hasOwn(claim, "same") || Object.hasOwn(claim, "distinct")) {
				const form = Object.hasOwn(claim, "same") ? "same" : "distinct";
				for (const handle of claim[form]) mention(handle);
				lines.push({ claim, retract, meta, form });
			} else if (Object.hasOwn(claim, "rel")) {
				const relation = this.facts.relations[claim.rel], [left, right] = relation.participants;
				const subject = claim.roles[left.role], object = claim.roles[right.role];
				if (subject === "?" && (object === "?" || !relation.inverse)) throw new JsonError("A relation with an unknown subject requires an inverse verb and a known object");
				const [s, verb, o] = subject !== "?" ? [subject, relation.verb, object] : [object, relation.inverse, "?"];
				mention(s);
				mention(o);
				lines.push({ claim, retract, meta, form: "link", subject: s, verb, object: o });
			} else {
				mention(claim.s);
				const line = { claim, retract, meta, facets, form: Object.hasOwn(claim, "p") ? "value" : "exists" };
				if (Object.hasOwn(claim, "p") && Object.hasOwn(claim, "v")) line.spelling = this.spell(claim.v, render);
				lines.push(line);
			}
		}
		// Parsing: metadata and directives (`metadata`, `@ctx`), all reported before any statement is resolved.
		const defaults = Object.fromEntries(DEFAULT_KEYS.filter(key => Object.hasOwn(obs, key)).map(key => [key, key === "conf" ? Number(obs.conf) : obs[key]]));
		if (Object.hasOwn(obs, "at")) try { timestampValue(obs.at); } catch (error) { throw new Diagnostic("meta", error.message); }
		if (Object.hasOwn(obs, "conf")) {
			try { canonicalNumber(obs.conf); } catch (error) { throw new Diagnostic("meta", error.message); }
			if (!(Number(obs.conf) >= 0 && Number(obs.conf) <= 1)) throw new Diagnostic("meta", "conf must be within 0..1");
		}
		let current = null;
		for (const line of lines) {
			const { meta } = line;
			if (Object.hasOwn(meta, "ctx") && meta.ctx !== current) {
				if (!isName(meta.ctx)) throw new Diagnostic("directive", `Invalid directive '@ctx ${meta.ctx}'`);
				current = meta.ctx === "none" ? null : meta.ctx;
			}
			line.ctx = current;
			if (Object.hasOwn(meta, "valid")) try { parseInterval(meta.valid); } catch (error) { throw new Diagnostic("meta", error.message); }
			if (Object.hasOwn(meta, "scale") && !["?", "1", "100"].includes(meta.scale)) throw new Diagnostic("meta", "scale must be 1, 100 or ?");
		}
		// Resolving: the header, then links, then each statement in the log's order.
		if (obs.ontology !== this.facts.namespace) throw new Diagnostic("header", "Observation namespace does not match ontology");
		if (Object.hasOwn(obs, "rev") && obs.rev !== this.facts.rev) throw new Diagnostic("header", "Observation revision does not match ontology");
		const typeOf = handle => instances[handle]?.type;
		const references = [];
		const queue = n => (handle, expected) => references.push([handle, expected, n]);
		for (const line of lines.filter(line => line.form === "link")) line.loaded = this.link(line, typeOf, queue(line.claim.n));
		const loadedClaims = [], loadedRetractions = [];
		for (const line of lines) {
			const { claim, retract, meta } = line, n = claim.n, target = retract ? loadedRetractions : loadedClaims;
			const metaOf = extra => ({ ...defaults, ...Object.fromEntries(Object.entries(meta).filter(([key]) => key !== "ctx" && key !== "conflict")), ...extra });
			for (const key of ["of", "approved"]) if (!retract && Object.hasOwn(meta, key)) throw new Diagnostic("meta", `${key} is only valid on retractions`, n);
			if (line.form !== "value" && QUALIFIERS.some(key => Object.hasOwn(meta, key))) throw new Diagnostic("meta", "Measurement qualifiers require a value", n);
			if (QUALIFIERS.some(key => String(meta[key] ?? "").startsWith("?:"))) throw new Diagnostic("meta", "An observed qualifier is a value, not ?:V", n);
			if (line.form === "same" || line.form === "distinct") {
				const [left, right] = claim[line.form], leftType = typeOf(left), rightType = typeOf(right);
				if (left === right) throw new Diagnostic("identity", "An identity link cannot name the same handle twice", n);
				if (!leftType || !rightType || !(leftType === rightType || this.isA(leftType, rightType) || this.isA(rightType, leftType)))
					throw new Diagnostic("type", "Identity links require typed, compatible handles", n);
				target.push({ n, [line.form]: line.form === "distinct" ? [left, right].sort(compareText) : [left, right], ...metaOf({}) });
				continue;
			}
			if (line.form === "link") {
				if (line.loaded) {
					this.checkValid(line.loaded.rel, meta, n);
					target.push({ ...line.loaded, ...metaOf({}) });
				}
				continue;
			}
			const owner = typeOf(claim.s);
			if (line.form === "exists" || Object.hasOwn(claim, "facet")) {
				const names = Object.hasOwn(claim, "facet") ? [claim.facet] : line.facets;
				const facets = this.model.facets(owner);
				// NOTE: A facet claim alone is spelled `h[F]`, which states existence too.
				const exists = !(retract && names.length);
				if (exists) {
					this.checkValid(owner, meta, n);
					target.push({ n, s: claim.s, exists: true, ...metaOf({}) });
				}
				for (const name of names) {
					const facet = facets.get(name);
					if (!facet) throw new Diagnostic("reference", `Unknown facet '${name}' on '${owner}'`, n);
					const { valid, ...facetMeta } = metaOf({});
					target.push({ n, s: claim.s, facet: name, ...facetMeta, ...this.context(facet, line.ctx, n, queue(n)) });
				}
				continue;
			}
			const attr = this.lookup(owner, claim.p);
			if (!attr) throw new Diagnostic("reference", `Unknown attribute '${owner}.${claim.p}'`, n);
			const keyError = this.elementPathError(owner, claim.p);
			if (keyError) throw new Diagnostic("key", keyError, n);
			const facet = this.model.facetOf(owner, unkeyed(claim.p));
			const loaded = { n, s: claim.s, p: claim.p, ...metaOf({}), ...this.context(facet, line.ctx, n, queue(n)) };
			if (Object.hasOwn(claim, "v")) {
				const { qualifiers, conflicts } = this.qualifiers(attr, meta);
				try { loaded.v = this.value(claim.v, attr, qualifiers.unit, line.spelling, queue(n)); }
				catch (error) { if (error instanceof JsonError) throw error; throw new Diagnostic("value", error.message, n); }
				if (conflicts.length) throw new Diagnostic("qualifier", conflicts[0], n);
			} else if (QUALIFIERS.some(key => Object.hasOwn(meta, key))) throw new Diagnostic("meta", "Measurement qualifiers require a value", n);
			target.push(loaded);
		}
		for (const [handle, expected, n] of references) {
			const actual = typeOf(handle);
			if (!actual || !this.isA(actual, expected)) throw new Diagnostic("type", `'${handle}' is '${actual}', expected '${expected}'`, n);
		}
		this.exclusive(loadedClaims, data);
		this.conditions(loadedClaims, data);
		if (!sameMultiset(data.claims, loadedClaims) || !sameMultiset(data.retractions, loadedRetractions))
			throw new JsonError("Observations JSON does not survive its text round trip (including the instance registry)");
	}

	/** A value's spelling: its rendered text, member by member, with typed mentions where the printer makes them. */
	spell(value, render) {
		if (isObject(value) && Array.isArray(value.set)) {
			const untyped = new Map(value.set.map(member => [member, render(member, true, false)]));
			const sorted = [...value.set].sort((a, b) => compareText(untyped.get(a).text, untyped.get(b).text));
			const typed = new Map(sorted.map(member => [member, render(member, true, true)]));
			return (member, inSet, typedMention) => (typedMention ? typed : untyped).get(member) ?? render(member, inSet, typedMention);
		}
		const spelling = render(value, false, true);
		return () => spelling;
	}

	/** A link's loaded claim, or a diagnostic (`ObservationResolver.link`). */
	link(line, typeOf, queue) {
		const { claim, subject, verb, object } = line, n = claim.n;
		const subjectType = typeOf(subject), objectType = object === "?" ? undefined : typeOf(object);
		let candidates = this.model.verbs(subjectType, verb);
		candidates = candidates.filter(([decl, inverse]) => object === "?" || objectType === undefined || this.isA(objectType, decl.participants[inverse ? 0 : 1].type));
		if (candidates.length !== 1) throw new Diagnostic("reference", `Unknown, incompatible or ambiguous relation '${verb}'`, n);
		const [[decl, inverse]] = candidates;
		let [left, right] = inverse ? [object, subject] : [subject, object];
		if (decl.symmetric && left !== "?" && right !== "?") [left, right] = [left, right].sort(compareText);
		if (Object.hasOwn(claim, "s")) {
			const type = typeOf(claim.s);
			if (type && type !== decl.path) throw new Diagnostic("type", `Incompatible relation handle '${claim.s}'`, n);
		}
		for (const [handle, participant] of [[left, decl.participants[0]], [right, decl.participants[1]]]) if (handle !== "?") queue(handle, participant.type);
		return { n, ...(Object.hasOwn(claim, "s") ? { s: claim.s } : {}), rel: decl.path, roles: { [decl.participants[0].role]: left, [decl.participants[1].role]: right } };
	}

	/** An event takes a point, not an interval (`checkValid`). */
	checkValid(path, meta, n) {
		const decl = this.facts.types[path] ?? this.facts.relations[path];
		if (Object.hasOwn(meta, "valid") && meta.valid.includes("..") && decl?.event) throw new Diagnostic("meta", "event requires a point valid", n);
	}

	/** The context of a claim through `facet`: required and kept when the facet is contextual, dropped otherwise. */
	context(facet, ctx, n, queue) {
		if (!facet?.ctx) return {};
		if (!ctx) throw new Diagnostic("meta", `Contextual facet '${facet.path}' requires ctx`, n);
		queue(ctx, facet.ctx);
		return { ctx };
	}

	/** Two attributes of one `{one=G}` group stated with values by one source over overlapping periods (`checkExclusive`). */
	exclusive(claims, data) {
		const stated = new Map();
		for (const claim of [...claims].sort(compareClaims)) {
			const value = claim.v, owner = data.instances[claim.s]?.type;
			if (value === null || value === undefined || (isObject(value) && value.unknown) || typeof claim.p !== "string" || !owner) continue;
			if (isObject(value) && Array.isArray(value.set) && !value.set.length) continue;
			const group = this.lookup(owner, claim.p)?.one;
			if (typeof group !== "string") continue;
			const prefix = claim.p.includes(".") ? claim.p.slice(0, claim.p.lastIndexOf(".")) : "";
			const key = valueKey([claim.s, claim.ctx ?? null, prefix, group, source(data, claim)]);
			const accepted = stated.get(key) ?? [];
			stated.set(key, accepted);
			const clash = accepted.find(other => other.p !== claim.p && overlap(claim, other));
			if (clash) throw new Diagnostic("one", `'${prefix ? `${claim.s}.${prefix}` : claim.s}' states both '${clash.p}' and '${claim.p}' of exclusive group '${group}'`, claim.n);
			accepted.push(claim);
		}
	}

	/** A facet `{when=Attr:Value}` claimed by a source stating another value of `Attr` (`checkFacetConditions`). */
	conditions(claims, data) {
		const stated = new Map(), facetClaims = [];
		for (const claim of claims) {
			const owner = data.instances[claim.s]?.type;
			if (!owner) continue;
			const name = claim.facet ?? (typeof claim.p === "string" && claim.p.includes(".") ? claim.p.split(".")[0] : null);
			const facet = name ? this.model.facets(owner).get(name) : undefined;
			if (!facet) {
				if (typeof claim.p === "string") {
					const key = valueKey([claim.s, source(data, claim), claim.p]);
					stated.set(key, [...(stated.get(key) ?? []), claim]);
				}
				continue;
			}
			if (facet.when) facetClaims.push([claim, name, facet.when.attr, facet.when.value]);
		}
		for (const [claim, name, attr, value] of facetClaims) {
			const clash = (stated.get(valueKey([claim.s, source(data, claim), attr])) ?? [])
				.find(other => conditionText(other.v) !== null && conditionText(other.v) !== value && overlap(claim, other));
			if (clash) throw new Diagnostic("when", `'${claim.s}' has facet '${name}', which applies when ${attr} is ${value}, but states ${attr} ${conditionText(clash.v)}`, claim.n);
		}
	}
}

// -----------------------------------------------------------------------------
//
// HELPERS
//
// -----------------------------------------------------------------------------

/** Code-point order, as Python sorts strings. */
function compareText(left, right) {
	return left < right ? -1 : left > right ? 1 : 0;
}

/** An exact decimal's identity: its coefficient without trailing zeros, and its exponent. */
function exactDecimal(text) {
	let { negative, coefficient, exponent } = decimalParts(text);
	if (coefficient === 0n) return "0";
	while (coefficient % 10n === 0n) {
		coefficient /= 10n;
		exponent += 1;
	}
	return `${negative ? "-" : ""}${coefficient}e${exponent}`;
}

const RE_PLAIN_DECIMAL = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;

/** A value's identity in a collection: numbers and numeric range bounds by value (`typedValueIdentity`). */
function identity(value, numeric, numericRange) {
	if (numeric && typeof value === "string" && RE_PLAIN_DECIMAL.test(value)) return "n:" + exactDecimal(value);
	if (numericRange && typeof value === "string" && value.includes("..")) {
		const at = value.indexOf(".."), bounds = [value.slice(0, at), value.slice(at + 2)];
		if (bounds.every(bound => !bound || RE_PLAIN_DECIMAL.test(bound))) return "r:" + bounds.map(bound => bound ? exactDecimal(bound) : "").join("..");
	}
	return "v:" + valueKey(value);
}

/** The handles a statement names, as the store's `handlesOf`. */
function mentioned(statement) {
	const found = [];
	if (typeof statement.s === "string") found.push(statement.s);
	for (const kind of ["same", "distinct"]) if (Array.isArray(statement[kind])) found.push(...statement[kind]);
	if (isObject(statement.roles)) found.push(...Object.values(statement.roles).filter(handle => handle !== "?"));
	if (Object.hasOwn(statement, "v")) for (const member of members(statement.v)) if (isObject(member) && typeof member.ref === "string") found.push(member.ref);
	if (typeof statement.ctx === "string") found.push(statement.ctx);
	return found;
}

/** A claim's source token, its alias resolved (`sourceToken`). */
function source(data, claim) {
	const alias = claim.src ?? data.obs.src;
	return data.sources[alias] ?? alias ?? null;
}

/** Whether two claims' validity periods overlap; a claim without `valid` holds throughout. */
function overlap(left, right) {
	const [a, b] = Object.hasOwn(left, "valid") ? parseInterval(left.valid) : [null, null];
	const [c, d] = Object.hasOwn(right, "valid") ? parseInterval(right.valid) : [null, null];
	return (a === null || d === null || compareTimestamps(a, d) <= 0) && (c === null || b === null || compareTimestamps(c, b) <= 0);
}

/** A value as a facet condition spells it; null for `null` and `?` (`conditionText`). */
function conditionText(value) {
	if (value === null || value === undefined || isObject(value)) return null;
	return typeof value === "boolean" ? String(value) : String(value);
}

// EOF
