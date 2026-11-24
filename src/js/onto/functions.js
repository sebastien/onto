/** Module: functions — pure function application and exact decimal built-ins (spec-04), as `functions/runtime.py`. */

import { canonicalNumber, clone, compareCodePoints, decimalParts, isSet, isUnknown, plainDecimal, pyJson, sortedByJson, timestampValue, valueKey } from "./values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

export const BUILTIN_ARITIES = {
	concat: [1, null], split: [2, 2], join: [2, 2], trim: [1, 1], lower: [1, 1], upper: [1, 1], number: [1, 1], text: [1, 1],
	date: [1, 2], datetime: [2, 2], epoch: [1, 1], format: [2, 2], sum: [1, null], multiply: [1, null], subtract: [2, 2],
	divide: [2, 2], count: [1, 1], ref: [2, 2],
};
const PATTERN_TOKENS = { YYYY: "[0-9]{4}", MM: "[0-9]{2}", DD: "[0-9]{2}", hh: "[0-9]{2}", mm: "[0-9]{2}", ss: "[0-9]{2}", Z: "Z|[+-][0-9]{2}:[0-9]{2}" };
const RE_PATTERN = /YYYY|MM|DD|hh|mm|ss|Z/g;
// Python's str.isspace(), which str.strip() removes.
const PY_SPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0                　";

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

export function pyStrip(text) {
	let start = 0, end = text.length;
	while (start < end && PY_SPACE.includes(text[start])) start++;
	while (end > start && PY_SPACE.includes(text[end - 1])) end--;
	return text.slice(start, end);
}

/** A text value as observations write it: bare, or a JSON string when bare text would read as something else. */
export function printText(value, inSet = false) {
	const unsafe = !value || value !== pyStrip(value) || /[\n\r"]/.test(value) || /(^|\s)(\{|\/\/)/u.test(value) || ["?", "null"].includes(value)
		|| value.startsWith("[") || inSet && (value === "..." || /[,\]]/.test(value));
	return unsafe ? pyJson(value, { ascii: false }) : value;
}

/** `ObservationPrinter.value(value, typed=False)`. */
export function printValue(value, inSet = false) {
	if (value === null) return "null";
	if (typeof value === "boolean") return value ? "true" : "false";
	if (value && typeof value === "object") {
		if (Object.hasOwn(value, "unknown")) return "?";
		if (Object.hasOwn(value, "ref")) return value.ref;
		const members = value.set.map(member => [printValue(member, true), member]).sort(([a], [b]) => compareCodePoints(a, b));
		const parts = members.map(([text]) => text);
		if (value.partial) parts.push("...");
		return `[${parts.join(", ")}]`;
	}
	return printText(value, inSet);
}

function numeric(value) {
	if (typeof value !== "string") throw new Error("Numbers must be decimal strings");
	return decimalParts(canonicalNumber(value));
}

function signed({ negative, coefficient }) { return negative ? -coefficient : coefficient; }
function make(value, exponent) { return { negative: value < 0n, coefficient: value < 0n ? -value : value, exponent }; }
function digits(value) { return (value < 0n ? -value : value).toString().length; }

function align(left, right) {
	const exponent = Math.min(left.exponent, right.exponent);
	return [signed(left) * 10n ** BigInt(left.exponent - exponent), signed(right) * 10n ** BigInt(right.exponent - exponent), exponent];
}

/** `canonicalNumber(str(Decimal))`: scientific spelling when the exponent is positive or the value is tiny. */
function decimalString(value) {
	if (value.coefficient === 0n) return "0";
	const text = value.coefficient.toString(), adjusted = value.exponent + text.length - 1;
	if (value.exponent <= 0 && adjusted >= -6) return plainDecimal(value);
	const fraction = text.slice(1).replace(/0+$/, "");
	return (value.negative ? "-" : "") + text[0] + (fraction ? "." + fraction : "") + (adjusted ? "e" + adjusted : "");
}

function roundHalfEven(numerator, denominator) {
	const negative = numerator < 0n !== denominator < 0n;
	const n = numerator < 0n ? -numerator : numerator, d = denominator < 0n ? -denominator : denominator;
	let quotient = n / d;
	const twice = (n % d) * 2n;
	if (twice > d || twice === d && quotient % 2n === 1n) quotient += 1n;
	return negative ? -quotient : quotient;
}

function divide(left, right) {
	if (right.coefficient === 0n) throw new Error("Division by zero");
	// value = (a × 10^ea) / (b × 10^eb) = p/q × 10^(ea - eb)
	let p = signed(left), q = signed(right), shift = left.exponent - right.exponent;
	if (q < 0n) { p = -p; q = -q; }
	const gcd = (a, b) => { a = a < 0n ? -a : a; while (b) [a, b] = [b, a % b]; return a; };
	const g = gcd(p, q) || 1n;
	p /= g; q /= g;
	let rest = q, twos = 0, fives = 0;
	while (rest % 2n === 0n) { rest /= 2n; twos++; }
	while (rest % 5n === 0n) { rest /= 5n; fives++; }
	if (p === 0n) return make(0n, shift);
	if (rest === 1n) {
		// Exact: the exponent nearest the ideal one (ea - eb) that keeps an integer coefficient.
		const places = Math.max(twos, fives);
		let coefficient = p * 10n ** BigInt(places) / q, exponent = shift - places;
		while (exponent < shift && coefficient % 10n === 0n) { coefficient /= 10n; exponent++; }
		return make(coefficient, exponent);
	}
	// Inexact: 16 significant digits, rounded half to even.
	const magnitude = (p < 0n ? -p : p) * 10n ** 40n / q;
	const adjusted = digits(magnitude) - 41 + shift;
	const exponent = adjusted - 15, scale = exponent - shift;
	const coefficient = scale >= 0 ? roundHalfEven(p, q * 10n ** BigInt(scale)) : roundHalfEven(p * 10n ** BigInt(-scale), q);
	return digits(coefficient) > 16 ? make(roundHalfEven(coefficient, 10n), exponent + 1) : make(coefficient, exponent);
}

/** Exact decimal arithmetic, spelled as Python's `Decimal` results are. */
export function arithmetic(name, args) {
	const values = args.map(numeric);
	let result;
	if (name === "divide") result = divide(values[0], values[1]);
	else if (name === "subtract") {
		const [a, b, exponent] = align(values[0], values[1]);
		result = make(a - b, exponent);
	} else if (name === "multiply") {
		result = values.reduce((acc, value) => make(signed(acc) * signed(value), acc.exponent + value.exponent), make(1n, 0));
	} else {
		result = values.reduce((acc, value) => { const [a, b, exponent] = align(acc, value); return make(a + b, exponent); }, make(0n, 0));
	}
	return canonicalNumber(decimalString(result));
}

function isoDate(days) {
	const date = new Date(Date.UTC(1970, 0, 1) + days * 86400000);
	if (Number.isNaN(date.getTime()) || date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) throw new Error("date out of range");
	return date.toISOString().slice(0, 10);
}

export function patternParse(value, pattern, withTime) {
	const tokens = new Set();
	let regex = "", offset = 0;
	for (const match of pattern.matchAll(RE_PATTERN)) {
		const token = match[0];
		if (tokens.has(token)) throw new Error(`Repeated date token '${token}'`);
		tokens.add(token);
		regex += pattern.slice(offset, match.index).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + `(?<${token}>${PATTERN_TOKENS[token]})`;
		offset = match.index + token.length;
	}
	regex += pattern.slice(offset).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	const matched = new RegExp(`^(?:${regex})$`).exec(value);
	if (!matched || !["YYYY", "MM", "DD"].every(token => tokens.has(token))) throw new Error("Value does not match a complete date pattern");
	const fields = matched.groups;
	let iso = `${fields.YYYY}-${fields.MM}-${fields.DD}`;
	if (withTime) {
		if (!["hh", "mm", "ss"].every(token => tokens.has(token))) throw new Error("A date-time pattern needs hh, mm and ss");
		iso += `T${fields.hh}:${fields.mm}:${fields.ss}` + (fields.Z ?? "");
	} else if (["hh", "mm", "ss", "Z"].some(token => tokens.has(token))) throw new Error("A date pattern cannot contain time fields");
	timestampValue(iso);
	return iso;
}

export function patternFormat(value, pattern) {
	timestampValue(value);
	const fields = { YYYY: value.slice(0, 4), MM: value.slice(5, 7), DD: value.slice(8, 10) };
	if (value.includes("T")) {
		const time = /^T([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?(?:\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})?$/.exec(value.slice(10));
		Object.assign(fields, { hh: time[1], mm: time[2], ss: time[3] ?? "00" });
		if (time[4]) fields.Z = time[4] === "+00:00" || time[4] === "-00:00" ? "Z" : time[4];
	}
	return pattern.replace(RE_PATTERN, token => {
		if (!Object.hasOwn(fields, token)) throw new Error(`Value has no '${token}' field`);
		return fields[token];
	});
}

/** A spec-04 built-in applied to one combination of arguments. */
export function builtin(name, args) {
	if (["sum", "multiply", "subtract", "divide"].includes(name)) return arithmetic(name, args);
	if (name === "text") return printValue(args[0]);
	if (["count", "join"].includes(name)) {
		if (!isSet(args[0])) throw new Error(`'${name}' requires a collection`);
		if (args[0].partial) throw new Error(`'${name}' requires a complete collection`);
		if (name === "count") return String(args[0].set.length);
		if (typeof args[1] !== "string" || args[0].set.some(item => typeof item !== "string")) throw new Error("join requires texts");
		return [...args[0].set].sort(compareCodePoints).join(args[1]);
	}
	if (name === "date" && args.length === 1) {
		const seconds = numeric(args[0]);
		const value = seconds.exponent >= 0 ? signed(seconds) * 10n ** BigInt(seconds.exponent) : null;
		if (value === null && signed(seconds) % 10n ** BigInt(-seconds.exponent) !== 0n) throw new Error("date requires integer epoch seconds");
		const whole = value ?? signed(seconds) / 10n ** BigInt(-seconds.exponent);
		const days = whole >= 0n ? whole / 86400n : -((-whole + 86399n) / 86400n);
		return isoDate(Number(days));
	}
	if (args.some(arg => typeof arg !== "string")) throw new Error(`'${name}' requires text arguments`);
	if (name === "concat") return args.join("");
	if (name === "trim") return pyStrip(args[0]);
	if (name === "lower") return args[0].toLowerCase();
	if (name === "upper") return args[0].toUpperCase();
	if (name === "split") return { set: [...new Set(args[0].split(args[1]).filter(Boolean))].sort(compareCodePoints) };
	if (name === "number") return canonicalNumber(args[0]);
	if (name === "date" || name === "datetime") return patternParse(args[0], args[1], name === "datetime");
	if (name === "epoch") {
		timestampValue(args[0]);
		if (args[0].includes("T")) throw new Error("epoch requires a date, not a date-time");
		return String(Math.round(Date.parse(args[0] + "T00:00:00Z") / 1000));
	}
	if (name === "format") return patternFormat(args[0], args[1]);
	if (name === "ref") throw new Error("ref requires binding execution context");
	throw new Error(`Unknown built-in '${name}'`);
}

function product(lists) {
	return lists.reduce((acc, list) => acc.flatMap(prefix => list.map(item => [...prefix, item])), [[]]);
}

function isNumericValue(value) {
	return typeof value === "string" && /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(value);
}

const exactNumber = value => plainDecimal(decimalParts(canonicalNumber(value)));

/** `valueIdentity`: numbers (and numeric range bounds) compare by value, sets without order, anything else by its canonical JSON. */
export function valueIdentity(value, numeric, numericRange = false) {
	if (numeric && isNumericValue(value)) return "n:" + exactNumber(value);
	if (numericRange && typeof value === "string" && value.includes("..")) {
		const [low, high] = [value.slice(0, value.indexOf("..")), value.slice(value.indexOf("..") + 2)];
		if ([low, high].every(bound => !bound || isNumericValue(bound))) return "r:" + [low, high].map(bound => bound ? exactNumber(bound) : "").join("..");
	}
	if (isSet(value)) return "s:" + [...new Set(value.set.map(item => valueIdentity(item, numeric, numericRange)))].sort().join("\u0000") + (value.partial ? ":partial" : "");
	return "v:" + valueKey(value);
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/**
 * Apply resolved function names; one outcome per Cartesian application.
 *
 * `functions`: name → `{args: [{collection, numeric}], nulls}` with an implementation in `implementations`;
 * `maps`: name → `{lines: [[from, to], ...]}`; `typed(value, type)` checks and canonicalises values
 * against a bundle type (see `types.js`) and defaults to the identity.
 */
export class FunctionEvaluator {
	constructor({ functions = {}, maps = {}, implementations = {}, typed = (value) => value } = {}) {
		Object.assign(this, { functions, maps, implementations, typed });
	}

	/** Configuration errors throw; domain failures return reasons. */
	evaluate(name, args) {
		const fn = this.functions[name], map = this.maps[name];
		let minimum, maximum;
		if (Object.hasOwn(BUILTIN_ARITIES, name)) [minimum, maximum] = BUILTIN_ARITIES[name];
		else if (fn) {
			minimum = maximum = fn.args.length;
			if (!Object.hasOwn(this.implementations, name)) throw new Error(`Missing implementation for '${name}'`);
		} else if (map) minimum = maximum = 1;
		else throw new Error(`Unknown function '${name}'`);
		if (args.length < minimum || maximum !== null && args.length > maximum) throw new Error(`Invalid argument count for '${name}'`);
		let combinations, partial;
		try {
			args.forEach((arg, index) => {
				if (!isSet(arg)) return;
				const numericArg = fn ? fn.args[index].numeric : ["sum", "multiply", "subtract", "divide"].includes(name) || name === "date" && args.length === 1;
				if (new Set(arg.set.map(member => valueIdentity(member, numericArg, fn?.args[index].numericRange))).size !== arg.set.length) throw new Error("Duplicate collection members");
			});
			const collections = fn ? fn.args.map(signature => signature.collection) : args.map((_, index) => ["join", "count"].includes(name) && index === 0);
			const lifted = args.map((arg, index) => isSet(arg) && !collections[index]);
			partial = args.some((arg, index) => lifted[index] && Boolean(arg.partial));
			combinations = args.map((arg, index) => lifted[index] ? sortedByJson(arg.set, { ascii: false }) : [arg]);
		} catch (error) {
			return [{ value: null, reason: error.message || "Error", partial: false }];
		}
		return product(combinations).map(items => this.apply(name, items, fn, map, partial));
	}

	apply(name, args, fn, map, partial) {
		try {
			if (!fn || !fn.nulls) {
				if (args.some(arg => arg === null)) return { value: null, reason: null, partial };
				if (args.some(isUnknown)) return { value: { unknown: true }, reason: null, partial };
			}
			let result;
			if (fn) {
				const inputs = args.map((arg, index) => this.typed(arg, fn.args[index]));
				result = this.typed(this.implementations[name](...inputs), fn.result);
			} else if (map) {
				const arg = this.typed(args[0], map.from);
				const key = valueKey(arg);
				const matches = new Map(map.lines.filter(([from]) => valueKey(from) === key).map(([, to]) => [valueKey(to), to]));
				if (matches.size !== 1) throw new Error("Missing or ambiguous value map entry");
				result = this.typed([...matches.values()][0], map.to);
			} else result = builtin(name, args);
			return { value: clone(result), reason: null, partial };
		} catch (error) {
			return { value: null, reason: error?.message || String(error), partial };
		}
	}
}


// EOF
