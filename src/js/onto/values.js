/** Module: values — spec-02 value helpers shared by the runtime, with Python-compatible formatting. */

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

/** Sentinel for an unbound value; distinct from an observed null. */
export const ABSENT_VALUE = Object.freeze({ absent: true });
/** Sentinel for an unknown observed value. */
export const UNKNOWN = Object.freeze({ unknown: true });
export const RE_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const RE_PATH = /^[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*$/;
export const RE_DECIMAL = /^([+-]?)([0-9]*(?:\.[0-9]*)?)(?:[eE]([+-]?[0-9]+))?$/;
export const RE_TIME = /^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?$/;
export const RE_DURATION = /^P(?=[0-9]|T[0-9])(?:[0-9]+Y)?(?:[0-9]+M)?(?:[0-9]+W)?(?:[0-9]+D)?(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+(?:\.[0-9]+)?S)?)?$/;
// Python's str.isspace(), which str.strip() removes.
const PY_SPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0                　";

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

function isObject(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function escapeText(text, ascii) {
	let result = '"';
	for (const char of text) {
		const code = char.codePointAt(0);
		if (char === '"') result += '\\"';
		else if (char === "\\") result += "\\\\";
		else if (char === "\n") result += "\\n";
		else if (char === "\r") result += "\\r";
		else if (char === "\t") result += "\\t";
		else if (char === "\b") result += "\\b";
		else if (char === "\f") result += "\\f";
		else if (code < 0x20 || ascii && code > 0x7e) {
			// Python escapes astral characters as their UTF-16 surrogate pair.
			for (let index = 0; index < char.length; index++) result += "\\u" + char.charCodeAt(index).toString(16).padStart(4, "0");
		} else result += char;
	}
	return result + '"';
}

export function compareCodePoints(left, right) {
	const a = [...left], b = [...right];
	for (let index = 0; index < Math.min(a.length, b.length); index++) {
		const difference = a[index].codePointAt(0) - b[index].codePointAt(0);
		if (difference) return difference;
	}
	return a.length - b.length;
}

function daysInMonth(year, month) {
	return [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

function ordinal(year, month, day) {
	// Python's date.toordinal(): day 1 is 0001-01-01.
	const y = year - 1;
	let days = y * 365 + Math.floor(y / 4) - Math.floor(y / 100) + Math.floor(y / 400);
	for (let m = 1; m < month; m++) days += daysInMonth(year, m);
	return days + day;
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

/** Python-style JSON formatting for ordering and deduplication; rejects non-finite numbers. */
export function pyJson(value, { sortKeys = true, ascii = true } = {}) {
	if (value === null || value === undefined) return "null";
	if (value === true) return "true";
	if (value === false) return "false";
	if (typeof value === "number") {
		if (!Number.isFinite(value)) throw new TypeError("Not a finite number");
		// JSON parsing cannot tell `1` from `1.0`; integers print as Python prints a JSON integer.
		return Number.isInteger(value) ? BigInt(value).toString() : pyFloat(value);
	}
	if (typeof value === "string") return escapeText(value, ascii);
	if (Array.isArray(value)) return "[" + value.map(item => pyJson(item, { sortKeys, ascii })).join(", ") + "]";
	const keys = Object.keys(value);
	if (sortKeys) keys.sort(compareCodePoints);
	return "{" + keys.map(key => escapeText(key, ascii) + ": " + pyJson(value[key], { sortKeys, ascii })).join(", ") + "}";
}

/** Python's `repr(float)`. */
export function pyFloat(value) {
	const text = String(value);
	if (/e/.test(text)) {
		const [mantissa, exponent] = text.split("e");
		return mantissa + "e" + (exponent.startsWith("-") ? "-" : "+") + exponent.replace(/^[+-]/, "").padStart(2, "0");
	}
	if (Math.abs(value) >= 1e16) {
		const digits = text.replace(/^-/, "").replace(/0+$/, "");
		const exponent = text.replace(/^-/, "").length - 1;
		return (value < 0 ? "-" : "") + digits[0] + (digits.length > 1 ? "." + digits.slice(1) : "") + "e+" + String(exponent).padStart(2, "0");
	}
	return Number.isInteger(value) ? text + ".0" : text;
}

/** `valueKey`: canonical JSON with sorted keys and unescaped text. */
export function valueKey(value) {
	return pyJson(value, { ascii: false });
}

export function jsonEqual(left, right) {
	return valueKey(left) === valueKey(right);
}

export function clone(value) {
	return value === undefined ? undefined : structuredClone(value);
}

/** True for `undefined` or the exact absent sentinel shape. */
export function isAbsent(value) {
	return value === undefined || isObject(value) && Object.keys(value).length === 1 && value.absent === true;
}

/** True for the exact unknown sentinel shape. */
export function isUnknown(value) {
	return isObject(value) && Object.keys(value).length === 1 && value.unknown === true;
}

export function isSet(value) {
	return isObject(value) && Object.hasOwn(value, "set");
}

export function isRef(value) {
	return isObject(value) && Object.hasOwn(value, "ref");
}

/** Canonical decimal spelling, keeping a nonzero exponent; raises on anything else. */
export function canonicalNumber(text) {
	const match = typeof text === "string" ? RE_DECIMAL.exec(text) : null;
	if (!match || !/[0-9]/.test(match[2])) throw new Error(`Invalid decimal '${text}'`);
	const [, sign, mantissa, exponent] = match;
	const [rawWhole, rawFraction = ""] = mantissa.split(".");
	const whole = rawWhole.replace(/^0+/, "") || "0", fraction = rawFraction.replace(/0+$/, "");
	if (whole === "0" && !fraction) return "0";
	const value = (sign === "-" ? "-" : "") + whole + (fraction ? "." + fraction : "");
	return value + (exponent && Number(exponent) ? "e" + Number(exponent) : "");
}

/** Sign, coefficient digits and exponent of a canonical or plain decimal spelling. */
export function decimalParts(text) {
	const match = RE_DECIMAL.exec(text);
	if (!match || !/[0-9]/.test(match[2])) throw new Error(`Invalid decimal '${text}'`);
	const [, sign, mantissa, exponent = "0"] = match;
	const [whole, fraction = ""] = mantissa.split(".");
	return { negative: sign === "-", coefficient: BigInt((whole + fraction) || "0"), exponent: Number(exponent) - fraction.length };
}

/** A plain (exponent-free) spelling of coefficient × 10^exponent, without trailing fraction zeros. */
export function plainDecimal({ negative, coefficient, exponent }) {
	if (coefficient === 0n) return "0";
	let digits = coefficient.toString(), text;
	if (exponent >= 0) text = digits + "0".repeat(exponent);
	else {
		digits = digits.padStart(1 - exponent, "0");
		text = (digits.slice(0, exponent) + "." + digits.slice(exponent)).replace(/0+$/, "").replace(/\.$/, "");
	}
	return (negative ? "-" : "") + text;
}

/** `decimalText`: an exponent-free canonical decimal from a JSON number or decimal text. */
export function decimalText(value) {
	if (typeof value === "boolean" || !["number", "string"].includes(typeof value)) throw new Error("Not a number");
	if (typeof value === "number") {
		if (!Number.isFinite(value)) throw new Error("Not a finite number");
		return plainDecimal(decimalParts(String(value).replace(/e\+?/, "e")));
	}
	if (value !== value.trim()) throw new Error("A decimal has no surrounding whitespace");
	return plainDecimal(decimalParts(canonicalNumber(value)));
}

/**
 * Validate a spec-02 date or date-time and return its UTC instant as `[seconds, fraction]`
 * (a BigInt and a digit string), comparable with `compareTimestamps`.
 */
export function timestampValue(text) {
	if (typeof text !== "string" || !RE_TIME.test(text)) throw new Error(`Invalid date or date-time '${text}'`);
	const year = Number(text.slice(0, 4)), month = Number(text.slice(5, 7)), day = Number(text.slice(8, 10));
	if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) throw new Error(`Invalid date '${text}'`);
	let seconds = BigInt(ordinal(year, month, day)) * 86400n, fraction = "";
	if (text.length > 10) {
		const time = /^T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]+))?)?(Z|[+-][0-9]{2}:[0-9]{2})?$/.exec(text.slice(10));
		const [, hh, mm, ss = "00", digits = "", zone] = time;
		const hour = Number(hh), minute = Number(mm), second = Number(ss);
		// Treat 24:00 with a zero fractional part as the next midnight.
		const midnight = hour === 24 && minute === 0 && second === 0 && /^0*$/.test(digits);
		if (hour > 23 && !midnight || minute > 59 || second > 59) throw new Error(`Invalid time '${text}'`);
		seconds += BigInt(hour * 3600 + minute * 60 + second);
		fraction = digits.replace(/0+$/, "");
		if (zone && zone !== "Z") {
			const offsetHours = Number(zone.slice(1, 3)), offsetMinutes = Number(zone.slice(4, 6));
			if (offsetHours > 23 || offsetMinutes > 59) throw new Error(`Invalid offset '${text}'`);
			seconds -= BigInt((zone[0] === "-" ? -1 : 1) * (offsetHours * 3600 + offsetMinutes * 60));
		}
	}
	return [seconds, fraction];
}

export function compareTimestamps(left, right) {
	if (left[0] !== right[0]) return left[0] < right[0] ? -1 : 1;
	const width = Math.max(left[1].length, right[1].length);
	const a = left[1].padEnd(width, "0"), b = right[1].padEnd(width, "0");
	return a < b ? -1 : a > b ? 1 : 0;
}

/** Return `[start, end]` timestamps for a point or `start..end`; an open bound is null. */
export function parseInterval(text) {
	const parts = text.includes("..") ? text.split("..") : [text, text];
	if (parts.length !== 2 || !parts.some(Boolean)) throw new Error(`Invalid interval '${text}'`);
	const [start, end] = parts.map(part => part ? timestampValue(part) : null);
	if (start && end && compareTimestamps(start, end) > 0) throw new Error(`Reversed interval '${text}'`);
	return [start, end];
}

/** Intersect validity intervals, keeping their bound spellings; null for no inputs or disjoint bounds. */
export function intersectIntervals(valids) {
	if (!valids.length) return null;
	if (new Set(valids).size === 1) return valids[0];
	let start = null, end = null, startText = "", endText = "";
	for (const text of valids) {
		const [left, right = left] = text.split("..");
		const [low, high] = parseInterval(text);
		if (low !== null && (start === null || compareTimestamps(low, start) > 0)) [start, startText] = [low, left];
		if (high !== null && (end === null || compareTimestamps(high, end) < 0)) [end, endText] = [high, right];
	}
	if (start !== null && end !== null && compareTimestamps(start, end) > 0) return null;
	return startText === endText ? startText : `${startText}..${endText}`;
}

/** The handles in a reference value or in the members of a set. */
export function referenceHandles(value) {
	if (!isObject(value)) return [];
	return (isSet(value) ? value.set : [value]).filter(item => isRef(item)).map(item => item.ref);
}

/** The subjects, contexts and referenced instances appearing in active claims. */
export function activeHandles(claims) {
	const handles = new Set();
	for (const claim of claims) {
		if (Object.hasOwn(claim, "s")) handles.add(claim.s);
		if (Object.hasOwn(claim, "ctx")) handles.add(claim.ctx);
		for (const handle of Object.values(claim.roles ?? {})) if (handle !== "?") handles.add(handle);
		for (const handle of referenceHandles(claim.v)) handles.add(handle);
	}
	return handles;
}

/** The evidence status of an observed value. */
export function observationStatus(value) {
	if (value === null) return "absent";
	if (isObject(value)) {
		if (Object.hasOwn(value, "unknown")) return "unknown";
		if (isSet(value) && !value.set.length) return value.partial ? "unknown" : "absent";
	}
	return "supplied";
}

/** Encode each non-alphanumeric UTF-8 byte as `_` followed by uppercase hex. */
export function encodeKey(key) {
	let result = "";
	for (const char of key) {
		if (/^[A-Za-z0-9]$/.test(char)) result += char;
		else for (const byte of new TextEncoder().encode(char)) result += "_" + byte.toString(16).toUpperCase().padStart(2, "0");
	}
	return result;
}

/** Decode an encoded key, returning null for malformed hex or UTF-8. */
export function decodeKey(text) {
	if (!/^(?:[A-Za-z0-9]|_[0-9A-F]{2})*$/.test(text)) return null;
	const bytes = [];
	for (let index = 0; index < text.length;) {
		if (text[index] === "_") { bytes.push(parseInt(text.slice(index + 1, index + 3), 16)); index += 3; }
		else { bytes.push(...new TextEncoder().encode(text[index])); index += 1; }
	}
	try { return new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes)); }
	catch { return null; }
}

export function keyText(key) {
	if (typeof key === "string") return key;
	if (typeof key === "number") return decimalText(key);
	throw new Error("A key must be text or a number");
}

/** Build a handle from the final type path segment and an encoded text or numeric key. */
export function handleOf(typeName, key) {
	return `${typeName.split("/").at(-1)}_${encodeKey(keyText(key))}`;
}

/** A sorted copy, ordering by Python's `json.dumps(sort_keys=True)` of each item. */
export function sortedByJson(items, options) {
	return items.map(item => [pyJson(item, options), item]).sort(([a], [b]) => compareCodePoints(a, b)).map(([, item]) => item);
}

/** First-seen unique items by Python's `json.dumps(sort_keys=True)`. */
export function uniqueByJson(items, options) {
	const seen = new Map();
	for (const item of items) {
		const key = pyJson(item, options);
		if (!seen.has(key)) seen.set(key, item);
	}
	return [...seen.values()];
}

/** Python's `str.strip()`, which removes more whitespace than `String.prototype.trim`. */
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

// EOF
