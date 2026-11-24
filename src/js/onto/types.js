/**
 * Module: types — check and canonicalise function values against a resolved type, as
 * `FunctionEvaluator.typedValue` and `ObservationResolver.scalar` do.
 *
 * A type is the bundle's descriptor of a resolved signature: `{kind, builtin?, values?, open?,
 * hierarchical?, ordered?, unit?, element?, collection?, numeric?}`.
 */

import { pyStrip, valueIdentity } from "./functions.js";
import { RE_DURATION, canonicalNumber, compareCodePoints, compareTimestamps, decimalParts, isSet, isUnknown, pyJson, sortedByJson, timestampValue } from "./values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const RE_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const RE_PATH = /^[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*$/;
const RE_REF = /^[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*)?$/;
const NUMBERS = ["Integer", "Number", "Amount", "Percent"];

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** `valueText`: a function value's spelling, quoted when bare text would read as something else. */
function valueText(value) {
	if (value === null) return "null";
	if (typeof value === "boolean") return value ? "true" : "false";
	if (value && typeof value === "object") {
		if (Object.hasOwn(value, "unknown")) return "?";
		if (Object.hasOwn(value, "ref")) return value.ref;
		return "[" + [...value.set.map(valueText).sort(compareCodePoints), ...(value.partial ? ["..."] : [])].join(", ") + "]";
	}
	const unsafe = !value || value !== pyStrip(value) || /[\n\r",[\]]/.test(value) || ["?", "null", "..."].includes(value) || value.includes("=>")
		|| /(^|\s)(\{|\/\/|--(?:\s|$))/u.test(value);
	return unsafe ? pyJson(value, { ascii: false }) : value;
}

function order(element) {
	if (NUMBERS.includes(element.builtin)) return value => decimalParts(canonicalNumber(value));
	if (["Date", "DateTime"].includes(element.builtin)) return timestampValue;
	if (element.builtin === "Duration") return value => RE_DURATION.test(String(value)) ? null : decimalParts(canonicalNumber(value));
	if (element.kind === "vocab" && element.ordered) return value => element.values.includes(value) ? element.values.indexOf(value) : null;
	return null;
}

function compare(left, right) {
	if (typeof left === "number") return left - right;
	if (Array.isArray(left)) return compareTimestamps(left, right);
	// Decimal parts: compare as exact rationals.
	const scale = Math.min(left.exponent, right.exponent);
	const a = (left.negative ? -1n : 1n) * left.coefficient * 10n ** BigInt(left.exponent - scale);
	const b = (right.negative ? -1n : 1n) * right.coefficient * 10n ** BigInt(right.exponent - scale);
	return a < b ? -1 : a > b ? 1 : 0;
}

function scalar(raw, type) {
	const quoted = raw.startsWith('"');
	const text = quoted ? JSON.parse(raw) : raw;
	if (typeof text !== "string") throw new Error("Quoted values must be JSON strings");
	if (["entity", "relation"].includes(type.kind)) {
		if (quoted || !RE_REF.test(text)) throw new Error("Reference values must be unquoted handles");
		return { ref: text.split(":")[0] };
	}
	if (type.kind === "range" && type.element) {
		if (quoted) throw new Error("A range is written unquoted");
		let [low, high] = text.includes("..") ? [text.slice(0, text.indexOf("..")), text.slice(text.indexOf("..") + 2)] : [text, text];
		if (!low && !high) throw new Error("A range needs at least one bound");
		const bounds = [low, high].map(bound => bound ? scalar(bound, type.element) : null);
		const key = order(type.element);
		if (key && bounds.every(bound => bound !== null)) {
			const [a, b] = bounds.map(key);
			if (a !== null && b !== null && compare(a, b) > 0) throw new Error(`Range '${text}' has its low bound above its high bound`);
		}
		return bounds.map(bound => bound ?? "").join("..");
	}
	if (type.kind === "vocab") {
		if (quoted || !(type.hierarchical ? RE_PATH : RE_NAME).test(text) || !type.open && !type.values.includes(text)) throw new Error(`'${text}' is not a vocabulary value`);
		return text;
	}
	const builtin = type.builtin;
	if (quoted && builtin && builtin !== "Text") throw new Error(`Quoted text is not a ${builtin}`);
	if (NUMBERS.includes(builtin)) {
		const canonical = canonicalNumber(text);
		if (builtin === "Integer") {
			const parts = decimalParts(canonical);
			if (parts.exponent < 0 && parts.coefficient % 10n ** BigInt(-parts.exponent) !== 0n) throw new Error(`'${text}' is not an integer`);
		}
		return canonical;
	}
	if (builtin === "Boolean") {
		if (!["true", "false"].includes(text)) throw new Error(`'${text}' is not a boolean`);
		return text === "true";
	}
	if (["Date", "DateTime"].includes(builtin)) {
		timestampValue(text);
		if (text.includes("T") !== (builtin === "DateTime")) throw new Error(`'${text}' is not a ${builtin}`);
	}
	if (builtin === "Duration") {
		if ((type.unit ?? "?") === "?" && RE_DURATION.test(text)) return text;
		return canonicalNumber(text);
	}
	if (type.kind === "struct") throw new Error("Structures require field paths");
	return text;
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

/** Validate and detach a spec-02 encoded value against its concrete signature type. */
export function typed(value, type) {
	if (value === null || isUnknown(value)) return structuredClone(value);
	if (type.collection) {
		if (!isSet(value)) throw new Error("Expected a collection");
		const element = { ...type, collection: false };
		const members = value.set.map(member => typed(member, element));
		if (new Set(members.map(member => valueIdentity(member, type.numeric, type.numericRange))).size !== members.length) throw new Error("Duplicate collection members");
		return { set: sortedByJson(members, { ascii: false }), ...(value.partial ? { partial: true } : {}) };
	}
	if (["entity", "relation"].includes(type.kind)) {
		if (!value || typeof value !== "object" || Object.keys(value).join() !== "ref") throw new Error("Expected a reference");
	} else if (type.builtin === "Boolean") {
		if (typeof value !== "boolean") throw new Error("Expected a boolean");
	} else if (typeof value !== "string") throw new Error("Expected a string-encoded scalar");
	return scalar(type.builtin === "Text" ? pyJson(value, { ascii: false }) : valueText(value), type);
}


// EOF
