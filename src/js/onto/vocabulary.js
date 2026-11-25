/**
 * Module: vocabulary — the `Onto` constraints, codecs, transforms and codes, as `integrations/hexa/vocabulary.py`.
 *
 * Names, signatures and examples match the Python declarations, so programs compiled and encoded by
 * the Python integration decode here. Transforms accept `undefined` (hexa's unbound optional input) and
 * `ABSENT_VALUE`, and return `ABSENT_VALUE` for "no value, no gap", which claim emission drops.
 */

import { Any, Bool, DateOnly, DateTime, Decimal, Gap, Num, Text, Timed, codec, codes, either, refine, rest, transform, where } from "hexa/shapes.js";
import { Transform } from "hexa/template.js";
import { Codec, compileShape } from "hexa/shape.js";
import { FunctionEvaluator, arithmetic, joinText, patternFormat, patternParse, splitText } from "./functions.js";
import { ABSENT_VALUE, RE_DURATION, UNKNOWN, decimalText, decodeKey, handleOf, isAbsent, isRef, isSet, isUnknown, parseInterval, timestampValue, uniqueByJson, sortedByJson } from "./values.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const DURATION_SECONDS = { Second: 1, Minute: 60, Hour: 3600, Day: 86400, Week: 604800 };
const DURATION_MONTHS = { Month: 1, Year: 12 };
export const BUILTINS = {
	concat: "Concat", split: "Split", join: "Join", trim: "Trim", lower: "Lower", upper: "Upper", number: "Number", text: "Text",
	date: "Date", datetime: "DateTime", epoch: "Epoch", format: "Format", sum: "Sum", multiply: "Multiply", subtract: "Subtract",
	divide: "Divide", count: "Count",
};
export const BindingCodes = codes("Binding", "KeyMissing", "TypeMismatch", "PathUnsupported", "InputEmpty", "SnapshotOlder", "ParentMissing", "ReplacementConflicting");
export const MappingCodes = codes("Mapping", "InputConflicting", "ReferenceUnmapped", "ReferenceAmbiguous", "NotIntegral", "ValueUnmapped", "KeyReference", "ContextUnsupported", "PolicyUnsupported");
const EVALUATOR = new FunctionEvaluator();

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

const isPlainObject = value => value !== null && typeof value === "object" && !Array.isArray(value);

/** Convert an untyped document value to spec-02 encoding: numbers become decimal text and lists become deduplicated sets without null or absent members. */
export function documentValue(value) {
	if (value === null || typeof value === "boolean" || typeof value === "string") return value;
	if (typeof value === "number") return decimalText(value);
	if (Array.isArray(value)) {
		const members = value.filter(item => item !== null && !isAbsent(item)).map(documentValue);
		return { set: uniqueByJson(members) };
	}
	const keys = isPlainObject(value) ? Object.keys(value).sort().join(",") : null;
	if (["ref", "ref,type", "unknown"].includes(keys) || isSet(value) && Object.keys(value).every(key => ["set", "partial"].includes(key))) return value;
	throw new Error("Not a scalar or collection");
}

/** The text a `when`/`deleted` condition compares: strings, decimals, booleans and handles. */
export function textOf(value) {
	if (typeof value === "string") return value;
	if (typeof value === "boolean") return value ? "true" : "false";
	if (typeof value === "number") return decimalText(value);
	if (isRef(value)) return value.ref;
	return null;
}

/** Return a single complete outcome's value or a deduplicated set of outcomes; any reported failure is a gap. */
export function resultValue(results, reason) {
	if (results.some(item => item.reason)) throw new Gap(reason);
	if (results.length === 1 && !results[0].partial) return results[0].value;
	const members = uniqueByJson(results.map(item => item.value));
	return { set: members, ...(results.some(item => item.partial) ? { partial: true } : {}) };
}

/** Arguments in the spec-02 encoding, or null when one is absent (the call is then absent too). */
function callArguments(args) {
	if (args.some(isAbsent)) return null;
	return args.map(documentValue);
}

/** Apply `name`: absent in, absent out; any failure is the gap `reason`. */
export function evaluated(evaluator, name, args, reason) {
	let values;
	try { values = callArguments(args); }
	catch { throw new Gap(reason); }
	if (values === null) return ABSENT_VALUE;
	let results;
	try { results = evaluator.evaluate(name, values); }
	catch (error) { if (error instanceof Gap) throw error; throw new Gap(reason); }
	return resultValue(results, reason);
}

export const BUILTIN_TRANSFORMS = {};

function builtinTransform(name, examples) {
	const title = BUILTINS[name];
	BUILTIN_TRANSFORMS[title] = transform(`Onto.${title}`, (...args) => evaluated(EVALUATOR, name, args, BUILTIN_TRANSFORMS[title].Invalid),
		{ inputs: [rest(Any)], output: Any, gaps: ["Invalid"], examples });
	return BUILTIN_TRANSFORMS[title];
}

/** A program-local transform bound to its own evaluator; it is never registered process-wide. */
export function functionTransform(name, evaluator) {
	const transformName = name.replaceAll("/", ".");
	const reasons = codes(transformName, "Unmapped", "Unformattable", "Invalid");
	return new Transform({ ...FUNCTION_TRANSFORM, name: transformName, function: (...args) => evaluated(evaluator, name, args, reasons.Invalid), gaps: [reasons.Invalid] });
}

/** A program-local codec: parse with `name`, format with `inverse`, each through `evaluator`; never registered process-wide. */
export function functionCodec(name, inverse, canonical, evaluator) {
	const codecName = name.replaceAll("/", ".");
	const reasons = codes(codecName, "Unmapped", "Unformattable", "Invalid");
	return new Codec({
		name: codecName, source: Any, canonical: compileShape(canonical), codecFamily: false, gaps: [reasons.Unmapped, reasons.Unformattable, reasons.Invalid],
		losses: [], examples: [], arguments: [], family: null, table: null, gapTable: null,
		parse: value => evaluated(evaluator, name, [value], reasons.Invalid),
		format: value => evaluated(evaluator, inverse, [value], reasons.Invalid),
	});
}

// -----------------------------------------------------------------------------
//
// TRANSFORM FUNCTIONS
//
// -----------------------------------------------------------------------------

function readValue(value, spec) {
	if (isAbsent(value)) return ABSENT_VALUE;
	if (value === null || isUnknown(value)) return value;
	const [kind, ...rest] = spec.split(":"), detail = rest.join(":");
	try {
		if (kind === "Text") { if (typeof value === "string") return value; }
		else if (kind === "Decimal" || kind === "Integer") {
			const number = decimalText(value);
			if (kind === "Decimal" || !number.includes(".")) return number;
		} else if (kind === "Boolean") {
			if (typeof value === "boolean") return value;
			if (value === "true" || value === "false") return value === "true";
		} else if (kind === "Date" || kind === "DateTime") {
			if (typeof value === "string" && value.includes("T") === (kind === "DateTime")) { timestampValue(value); return value; }
		} else if (kind === "Duration") {
			if (detail === "iso") { if (typeof value === "string" && RE_DURATION.test(value)) return value; }
			else return decimalText(value);
		} else if (kind === "Vocab") {
			if (typeof value === "string" && detail.split("|").includes(value)) return value;
		} else if (kind === "Ref") {
			if (isRef(value)) return value;
		} else if (kind === "Any") return documentValue(value);
	} catch { /* a mismatch below */ }
	throw new Gap(Read.TypeMismatch);
}

function readSet(value, spec) {
	if (isAbsent(value)) return ABSENT_VALUE;
	if (value === null || isUnknown(value)) return value;
	const items = isSet(value) ? value.set : Array.isArray(value) ? value : [value];
	const members = [];
	for (const item of items) {
		if (item === null) continue;
		try { members.push(readValue(item, spec)); }
		catch (error) { if (error instanceof Gap) throw new Gap(Set_.TypeMismatch); throw error; }
	}
	return { set: sortedByJson(uniqueByJson(members)), ...(isSet(value) && value.partial ? { partial: true } : {}) };
}

/** The texts a condition test compares: a value's, or each member's of a collection (spec-04 Conditions). */
export function memberTexts(value) {
	if (value === undefined || value === null || isAbsent(value)) return [];
	if (Array.isArray(value)) return value.flatMap(memberTexts);
	if (isSet(value)) return value.set.flatMap(memberTexts);
	const text = textOf(value);
	return text === null ? [] : [text];
}

/**
 * Whether a condition holds, `valueAt(path)` reading a test's path (null when absent): the value, or a member
 * of a collection, is one the test lists; `all` and `any` combine tests (spec-04 Conditions).
 */
export function conditionHolds(condition, valueAt) {
	if (condition.all) return condition.all.every(item => conditionHolds(item, valueAt));
	if (condition.any) return condition.any.some(item => conditionHolds(item, valueAt));
	if (!Object.hasOwn(condition, "value") && !Object.hasOwn(condition, "values")) return hasValue(valueAt(condition.path));
	return textIn(valueAt(condition.path), condition.values ?? [condition.value]);
}

/**
 * A test of having a value: known and nonempty, as `present=` reads it (false and zero are values);
 * a list of document values has one when a member does.
 */
export function hasValue(value) {
	if (Array.isArray(value)) return value.some(hasValue);
	return !(value === undefined || value === null || isAbsent(value) || isUnknown(value) || value === "" || isSet(value) && !value.set.length);
}

function textEquals(value, text) { return memberTexts(value).includes(text); }
function textIn(value, texts) { return memberTexts(value).some(text => texts.includes(text)); }
function unset(value, text) { return isAbsent(value) || textOf(value) === text ? ABSENT_VALUE : value; }
function whenValue(condition, value) { return condition === true && !isAbsent(value) ? value : ABSENT_VALUE; }
function whenNone(value, texts, result) { return !isAbsent(value) && texts.includes(textOf(value)) || isAbsent(result) ? ABSENT_VALUE : result; }
function coalesce(...items) {
	const index = items.findIndex(item => !isAbsent(item));
	return index < 0 ? ABSENT_VALUE : items[index];
}

function handle(typeName, key) {
	if (isAbsent(key) || key === null || isUnknown(key)) throw new Gap(Handle.KeyMissing);
	try { return handleOf(typeName, key); }
	catch { throw new Gap(Handle.TypeMismatch); }
}

/** Build a scoped target handle, decoding a source key when its type prefix and encoding match. */
export function sourceHandle(typeName, scope, source, sourceType) {
	const short = sourceType.split("/").at(-1), prefix = short + "_";
	const key = source.startsWith(prefix) ? decodeKey(source.slice(prefix.length)) : null;
	return handleOf(typeName, `${scope}/${short}/${key ?? source}`);
}

function keyedHandle(typeName, key, scope, source, sourceType) {
	if (isAbsent(key) || key === null || isUnknown(key)) return sourceHandle(typeName, scope, source, sourceType);
	try { return handleOf(typeName, key); }
	catch { throw new Gap(KeyedHandle.TypeMismatch); }
}

function reference(typePath, key) {
	if (isAbsent(key)) return ABSENT_VALUE;
	if (key === null || isUnknown(key)) return key;
	if (isSet(key)) return { ...key, set: key.set.filter(item => item !== null).map(item => reference(typePath, item)) };
	if (Array.isArray(key)) return key.filter(item => item !== null).map(item => reference(typePath, item));
	try { return { ref: handleOf(typePath, key), type: typePath }; }
	catch { throw new Gap(Ref.TypeMismatch); }
}

/** Decode a handle or reference's key for `typeName`; absent stays absent and invalid handles produce a gap. */
export function handleKey(value, typeName) {
	if (isAbsent(value)) return ABSENT_VALUE;
	const ref = isPlainObject(value) ? value.ref : value, prefix = typeName.split("/").at(-1) + "_";
	const key = typeof ref === "string" && ref.startsWith(prefix) ? decodeKey(ref.slice(prefix.length)) : null;
	if (key === null) throw new Gap(HandleKey.Undecodable);
	return key;
}

function correspond(value) {
	if (isAbsent(value)) return ABSENT_VALUE;
	if (value === null || isUnknown(value)) return value;
	if (isSet(value)) return { set: value.set.map(correspond), ...(value.partial ? { partial: true } : {}) };
	if (!isPlainObject(value) || !Object.hasOwn(value, "target")) throw new Gap(Correspond.ReferenceUnmapped);
	return { ref: value.target, ...(Object.hasOwn(value, "targetType") ? { type: value.targetType } : {}) };
}

function correspondAs(value, typePath, emitted = false) {
	if (isAbsent(value)) return ABSENT_VALUE;
	if (value === null || isUnknown(value)) return value;
	if (isSet(value)) return { set: value.set.map(item => correspondAs(item, typePath, emitted)), ...(value.partial ? { partial: true } : {}) };
	const target = isPlainObject(value) ? value.targets?.[typePath] : undefined;
	if (target === undefined || target === null || emitted && (value.skipped ?? []).includes(typePath)) throw new Gap((emitted ? CorrespondEmitted : CorrespondAs).ReferenceUnmapped);
	return { ref: target, type: typePath };
}

function single(value) {
	if (isAbsent(value) || !isSet(value)) return value;
	const members = value.set;
	if (!members.length && !value.partial) return ABSENT_VALUE;
	if (members.length !== 1 || value.partial) throw new Gap(Single.ReferenceAmbiguous);
	return members[0];
}

function valid(value) {
	if (isAbsent(value)) return ABSENT_VALUE;
	try { parseInterval(value); return value; }
	catch { throw new Gap(Valid.Invalid); }
}

function timeValue(value) {
	if (isAbsent(value)) return ABSENT_VALUE;
	try { timestampValue(value); return value; }
	catch { throw new Gap(At.Invalid); }
}

function formatName(name) {
	if (isAbsent(name) || typeof name !== "string" || !name.includes("(")) return ABSENT_VALUE;
	return JSON.parse("[" + name.slice(name.indexOf("(") + 1, -1) + "]")[0];
}

function field(value, steps) {
	let current = [value];
	for (const step of steps) {
		const following = [];
		for (const item of current) {
			if (step === "*" && Array.isArray(item)) following.push(...item);
			else if (Number.isInteger(step) && Array.isArray(item)) following.push(...item.slice(step, step + 1));
			else if (isPlainObject(item) && Object.hasOwn(item, step)) following.push(item[step]);
		}
		current = following;
	}
	if (!current.length || isAbsent(value)) return ABSENT_VALUE;
	return steps.includes("*") ? current : current[0];
}

function nullable(value, marker, kind) {
	if (!isAbsent(marker)) return kind === "absent" ? null : { ...UNKNOWN };
	return isAbsent(value) ? ABSENT_VALUE : value;
}

function given(value, result) { return isAbsent(value) || value === null || isUnknown(value) ? ABSENT_VALUE : result; }

function members(value, key) {
	if (isAbsent(value) || !isSet(value)) return ABSENT_VALUE;
	const items = sortedByJson(value.set);
	return key ? items.map(item => ({ [key]: item })) : items;
}

function qualifierConvert(value, source, target) {
	if (isAbsent(value)) return ABSENT_VALUE;
	if (value === null || isUnknown(value)) return value;
	if (isSet(value)) return { ...value, set: value.set.map(item => qualifierConvert(item, source, target)) };
	let result = value;
	if (Object.hasOwn(source, "scale") && Object.hasOwn(target, "scale")) result = arithmetic("divide", [arithmetic("multiply", [result, target.scale]), source.scale]);
	if (Object.hasOwn(source, "unit") && Object.hasOwn(target, "unit") && source.unit !== target.unit) {
		const table = [DURATION_SECONDS, DURATION_MONTHS].find(item => Object.hasOwn(item, source.unit) && Object.hasOwn(item, target.unit));
		if (!table) throw new Gap(QualifierConvert.Inconvertible);
		result = arithmetic("divide", [arithmetic("multiply", [result, String(table[source.unit])]), String(table[target.unit])]);
	}
	return decimalText(result);
}

function toInteger(value) {
	if (isAbsent(value)) return ABSENT_VALUE;
	if (value === null || isUnknown(value)) return value;
	if (isSet(value)) return { ...value, set: value.set.map(toInteger) };
	if (typeof value !== "string" || decimalText(value).includes(".")) throw new Gap(ToInteger.NotIntegral);
	return decimalText(value);
}

function toVocabulary(value, values) {
	if (isAbsent(value)) return ABSENT_VALUE;
	if (value === null || isUnknown(value)) return value;
	if (isSet(value)) return { ...value, set: value.set.map(item => toVocabulary(item, values)) };
	if (!values.includes(value)) throw new Gap(ToVocabulary.ValueUnmapped);
	return value;
}

// -----------------------------------------------------------------------------
//
// CODEC FUNCTIONS
//
// -----------------------------------------------------------------------------

function epochParse(value) {
	let result;
	try { result = EVALUATOR.evaluate("date", [decimalText(value)])[0]; }
	catch { throw new Gap(EpochDate.Invalid); }
	if (result.reason) throw new Gap(EpochDate.Invalid);
	return result.value;
}

function epochFormat(value, original) {
	const seconds = EVALUATOR.evaluate("epoch", [value])[0].value;
	return typeof original === "string" ? seconds : Number(seconds);
}

function integerParse(value) {
	let number;
	try { number = decimalText(value); }
	catch { throw new Gap(IntegerText.Invalid); }
	if (number.includes(".")) throw new Gap(IntegerText.Invalid);
	return number;
}

function decimalNumberFormat(value) {
	if (!value.includes(".") && Math.abs(Number(value)) <= 2 ** 53 - 1) return Number(value);
	const number = Number(value);
	if (value.includes(".") && decimalText(number) === value) return number;
	throw new Gap(DecimalNumber.Inexact);
}

function placesFormat(places, value) {
	const [whole, fraction = ""] = value.split(".");
	if (fraction.length > places) throw new Gap(DecimalPlaces.Inexact);
	return whole + (places ? "." + fraction.padEnd(places, "0") : "");
}

// -----------------------------------------------------------------------------
//
// HIGH-LEVEL API
//
// -----------------------------------------------------------------------------

export const Integral = where(value => typeof value === "string" && !value.includes("."), "Onto.Integral");
export const IsoDuration = where(value => typeof value === "string" && RE_DURATION.test(value), "Onto.IsoDuration");

export const EpochDate = codec("Onto.EpochDate", { source: either(Num, Text), canonical: refine(DateTime, DateOnly), parse: epochParse, format: epochFormat, gaps: ["Invalid"],
	examples: [{ input: 1907712000, output: "2030-06-15" }, { input: "x", gap: "Invalid" }] });
export const IntegerText = codec("Onto.IntegerText", { source: either(Text, Num), canonical: refine(Decimal, Integral), parse: integerParse, format: value => value, gaps: ["Invalid"],
	examples: [{ input: 6, output: "6", direction: "forward" }, { input: "6.5", gap: "Invalid" }] });
export const SplitText = codec("Onto.SplitText", { source: Text, canonical: { set: [Text] }, params: { Separator: Text },
	parse: (separator, value) => { try { return { set: splitText(value, separator) }; } catch { throw new Gap(SplitText.Invalid); } },
	format: (separator, value) => {
		try { return joinText(value.set, separator); } catch { throw new Gap(SplitText.Unformattable); }
	},
	gaps: ["Invalid"], examples: [{ arguments: [","], input: "b,a", output: { set: ["a", "b"] }, direction: "forward" }] });
export const DateTimePattern = codec("Onto.DateTimePattern", { source: Text, canonical: refine(DateTime, Timed), params: { Pattern: Text },
	parse: (pattern, value) => { try { return patternParse(value, pattern, true); } catch { throw new Gap(DateTimePattern.Invalid); } },
	format: (pattern, value) => { try { return patternFormat(value, pattern); } catch { throw new Gap(DateTimePattern.Unformattable); } },
	gaps: ["Invalid"], examples: [{ arguments: ["YYYYMMDD hh:mm:ss"], input: "20260915 10:30:00", output: "2026-09-15T10:30:00" }] });
export const DecimalNumber = codec("Onto.DecimalNumber", { source: Num, canonical: Decimal, parse: decimalText, format: decimalNumberFormat, gaps: ["Inexact"],
	examples: [{ input: 0.0525, output: "0.0525" }, { input: "0.1000000000000000055511151231257827", gap: "Inexact", direction: "backward" }] });
export const DecimalPlaces = codec("Onto.DecimalPlaces", { source: Text, canonical: Decimal, params: { Places: Num },
	parse: (places, value) => { try { return decimalText(value); } catch { throw new Gap(DecimalPlaces.Invalid); } }, format: placesFormat,
	gaps: ["Invalid", "Inexact"], examples: [{ arguments: [2], input: "0.50", output: "0.5" }, { arguments: [2], input: "0.125", gap: "Inexact", direction: "backward" }] });
export const Case = codec("Onto.Case", { source: Text, canonical: Text, params: { Case: either("upper", "lower") },
	parse: (_, value) => value, format: (kind, value) => kind === "upper" ? value.toUpperCase() : value.toLowerCase(),
	examples: [{ arguments: ["upper"], input: "ACME", output: "acme", direction: "backward" }] });

export const Read = transform("Onto.Read", readValue, { inputs: [Any, Text], output: Any, gaps: ["TypeMismatch"],
	examples: [{ input: [0.42, "Decimal"], output: "0.42" }, { input: ["x", "Integer"], gap: "TypeMismatch" }] });
const Set_ = transform("Onto.Set", readSet, { inputs: [Any, Text], output: Any, gaps: ["TypeMismatch"],
	examples: [{ input: [["b", "a", "b"], "Text"], output: { set: ["a", "b"] } }, { input: [["a", false], "Text"], gap: "TypeMismatch" }] });
export { Set_ as Set };
export const TextEquals = transform("Onto.TextEquals", textEquals, { inputs: [Any, Text], output: Bool,
	examples: [{ input: ["F", "F"], output: true }, { input: [6, "6"], output: true }, { input: [{ set: ["A", "F"] }, "F"], output: true },
		{ input: [ABSENT_VALUE, "F"], output: false }] });
export const TextIn = transform("Onto.TextIn", textIn, { inputs: [Any, Any], output: Bool,
	examples: [{ input: ["Home", ["Home", "Investment"]], output: true }, { input: ["Car", ["Home", "Investment"]], output: false },
		{ input: [["Car", "Home"], ["Home"]], output: true }] });
export const HasValue = transform("Onto.HasValue", hasValue, { inputs: [Any], output: Bool,
	examples: [{ input: ["800000"], output: true }, { input: [false], output: true }, { input: [""], output: false },
		{ input: [ABSENT_VALUE], output: false }, { input: [{ set: [] }], output: false }] });
export const AllOf = transform("Onto.AllOf", (...items) => items.every(item => item === true), { inputs: [rest(Any)], output: Bool,
	examples: [{ input: [true, true], output: true }, { input: [true, false], output: false }] });
export const AnyOf = transform("Onto.AnyOf", (...items) => items.some(item => item === true), { inputs: [rest(Any)], output: Bool,
	examples: [{ input: [false, true], output: true }, { input: [false, false], output: false }] });
export const Unset = transform("Onto.Unset", unset, { inputs: [Any, Text], output: Any,
	examples: [{ input: ["0", "0"], output: ABSENT_VALUE }, { input: ["120000", "0"], output: "120000" }, { input: [null, "0"], output: null },
		{ input: [ABSENT_VALUE, "0"], output: ABSENT_VALUE }] });
export const When = transform("Onto.When", whenValue, { inputs: [Any, Any], output: Any,
	examples: [{ input: [true, "x"], output: "x" }, { input: [false, "x"], output: ABSENT_VALUE }] });
export const WhenNone = transform("Onto.WhenNone", whenNone, { inputs: [Any, Any, Any], output: Any,
	examples: [{ input: ["A", ["A", "B"], "x"], output: ABSENT_VALUE }, { input: ["C", ["A", "B"], "x"], output: "x" }, { input: [ABSENT_VALUE, ["A"], "x"], output: "x" }] });
export const Coalesce = transform("Onto.Coalesce", coalesce, { inputs: [rest(Any)], output: Any,
	examples: [{ input: [ABSENT_VALUE, "ACM30"], output: "ACM30" }, { input: [null, "x"], output: null }] });
export const Handle = transform("Onto.Handle", handle, { inputs: [Text, Any], output: Text, gaps: ["KeyMissing", "TypeMismatch"],
	examples: [{ input: ["Issuer", "C-17"], output: "Issuer_C_2D17" }, { input: ["Issuer", ABSENT_VALUE], gap: "KeyMissing" }] });
export const KeyedHandle = transform("Onto.KeyedHandle", keyedHandle, { inputs: [Text, Any, Any, Any, Text], output: Text, gaps: ["TypeMismatch"],
	examples: [{ input: ["Organisation", "1234567", "AdviceLink", "MemberCompany_1", "MemberCompany"], output: "Organisation_1234567" },
		{ input: ["Organisation", ABSENT_VALUE, "AdviceLink", "MemberCompany_1", "MemberCompany"], output: "Organisation_AdviceLink_2FMemberCompany_2F1" }] });
export const SourceHandle = transform("Onto.SourceHandle", sourceHandle, { inputs: [Text, Any, Any, Text], output: Text,
	examples: [{ input: ["Company", "Exchange", "Issuer_C_2D17", "Issuer"], output: "Company_Exchange_2FIssuer_2FC_2D17" }] });
export const Ref = transform("Onto.Ref", reference, { inputs: [Text, Any], output: Any, gaps: ["TypeMismatch"],
	examples: [{ input: ["Exchange/Issuer", "C-17"], output: { ref: "Issuer_C_2D17", type: "Exchange/Issuer" } }] });
export const HandleKey = transform("Onto.HandleKey", handleKey, { inputs: [Any, Text], output: Any, gaps: ["Undecodable"],
	examples: [{ input: [{ ref: "Issuer_C_2D17" }, "Issuer"], output: "C-17" }] });
export const Correspond = transform("Onto.Correspond", correspond, { inputs: [Any], output: Any, gaps: ["ReferenceUnmapped"],
	examples: [{ input: [{ ref: "Issuer_C_2D17", target: "Company_ACME" }], output: { ref: "Company_ACME" } }, { input: [{ ref: "x" }], gap: "ReferenceUnmapped" }] });
export const Single = transform("Onto.Single", single, { inputs: [Any], output: Any, gaps: ["ReferenceAmbiguous"],
	examples: [{ input: [{ set: [{ ref: "Person_1" }] }], output: { ref: "Person_1" } }, { input: [{ set: [] }], output: ABSENT_VALUE },
		{ input: [{ set: [{ ref: "a" }, { ref: "b" }] }], gap: "ReferenceAmbiguous" }, { input: [{ ref: "a" }], output: { ref: "a" } }] });
export const CorrespondAs = transform("Onto.CorrespondAs", correspondAs, { inputs: [Any, Text], output: Any, gaps: ["ReferenceUnmapped"],
	examples: [{ input: [{ ref: "Client_9", target: "Person_9", targets: { "Crm/Person": "Person_9", "Crm/Relationship": "Relationship_9" } }, "Crm/Person"], output: { ref: "Person_9", type: "Crm/Person" } },
		{ input: [{ ref: "x", targets: {} }, "Crm/Person"], gap: "ReferenceUnmapped" }] });
export const CorrespondEmitted = transform("Onto.CorrespondEmitted", (value, typePath) => correspondAs(value, typePath, true), { inputs: [Any, Text], output: Any,
	gaps: ["ReferenceUnmapped"], examples: [
		{ input: [{ ref: "MA_1", targets: { "T/Application": "Application_1" } }, "T/Application"], output: { ref: "Application_1", type: "T/Application" } },
		{ input: [{ ref: "MA_2", targets: { "T/Application": "Application_2" }, skipped: ["T/Application"] }, "T/Application"], gap: "ReferenceUnmapped" }] });
export const Valid = transform("Onto.Valid", valid, { inputs: [Any], output: Any, gaps: ["Invalid"],
	examples: [{ input: ["2026-09-01"], output: "2026-09-01" }, { input: ["2026-02-30"], gap: "Invalid" }] });
export const At = transform("Onto.At", timeValue, { inputs: [Any], output: Any, gaps: ["Invalid"],
	examples: [{ input: ["2026-11-10"], output: "2026-11-10" }, { input: ["soon"], gap: "Invalid" }] });
export const FormatName = transform("Onto.FormatName", formatName, { inputs: [Any], output: Any,
	examples: [{ input: ['DatePattern("YYYYMMDD")'], output: "YYYYMMDD" }] });
export const Field = transform("Onto.Field", field, { inputs: [Any, Any], output: Any,
	examples: [{ input: [{ bond: { interval: 6 } }, ["bond", "interval"]], output: 6 }] });
export const Nullable = transform("Onto.Nullable", nullable, { inputs: [Any, Any, Text], output: Any,
	examples: [{ input: [ABSENT_VALUE, null, "unknown"], output: UNKNOWN }, { input: [ABSENT_VALUE, ABSENT_VALUE, "unknown"], output: ABSENT_VALUE }] });
export const QualifierConvert = transform("Onto.QualifierConvert", qualifierConvert, { inputs: [Any, Any, Any], output: Any, gaps: ["Inconvertible"],
	examples: [{ input: ["0.0525", { scale: "1" }, { scale: "100" }], output: "5.25" }, { input: ["90", { unit: "Minute" }, { unit: "Hour" }], output: "1.5" }] });
export const ToInteger = transform("Onto.ToInteger", toInteger, { inputs: [Any], output: Any, gaps: ["NotIntegral"],
	examples: [{ input: ["6"], output: "6" }, { input: ["6.5"], gap: "NotIntegral" }] });
export const Given = transform("Onto.Given", given, { inputs: [Any, Any], output: Any,
	examples: [{ input: ["2026-09-15", "F"], output: "F" }, { input: [ABSENT_VALUE, "F"], output: ABSENT_VALUE }] });
export const Members = transform("Onto.Members", members, { inputs: [Any, Text], output: Any,
	examples: [{ input: [{ set: ["b", "a"] }, ""], output: ["a", "b"] }, { input: [{ set: ["a"] }, "b"], output: [{ b: "a" }] }] });
export const ToVocabulary = transform("Onto.ToVocabulary", toVocabulary, { inputs: [Any, Any], output: Any, gaps: ["ValueUnmapped"],
	examples: [{ input: ["Bond", ["Bond", "Equity"]], output: "Bond" }, { input: ["Cash", ["Bond"]], gap: "ValueUnmapped" }] });
// Registered as prototypes only, as in Python: compiled calls carry their own evaluator.
const FUNCTION_TRANSFORM = transform("Onto.Function", () => null, { inputs: [rest(Any)], output: Any });
codec("Onto.FunctionCodec", { source: Any, canonical: Any, parse: value => value, format: value => value });

const BUILTIN_EXAMPLES = {
	concat: [{ input: ["US0000000001", "/", "2026-09-01"], output: "US0000000001/2026-09-01" }],
	split: [{ input: ["b,a,,b", ","], output: { set: ["a", "b"] } }],
	join: [{ input: [{ set: ["b", "a"] }, ","], output: "a,b" }],
	trim: [{ input: [" Acme 5.25% 2030 "], output: "Acme 5.25% 2030" }],
	lower: [{ input: ["ACME"], output: "acme" }],
	upper: [{ input: ["acme"], output: "ACME" }],
	number: [{ input: ["5.50"], output: "5.5" }, { input: ["five"], gap: "Invalid" }],
	text: [{ input: ["5.5"], output: "5.5" }],
	date: [{ input: [1907712000], output: "2030-06-15" }, { input: ["20260915", "YYYYMMDD"], output: "2026-09-15" }],
	datetime: [{ input: ["20260915103000", "YYYYMMDDhhmmss"], output: "2026-09-15T10:30:00" }],
	epoch: [{ input: ["2030-06-15"], output: "1907712000" }],
	format: [{ input: ["2026-09-15", "YYYYMMDD"], output: "20260915" }],
	sum: [{ input: ["0.1", "0.2"], output: "0.3" }],
	multiply: [{ input: ["98.5", "100"], output: "9850" }],
	subtract: [{ input: ["1", "0.25"], output: "0.75" }],
	divide: [{ input: ["1", "3"], output: "0.3333333333333333" }, { input: ["1", "0"], gap: "Invalid" }],
	count: [{ input: [{ set: ["a", "b"] }], output: "2" }],
};
for (const [name, examples] of Object.entries(BUILTIN_EXAMPLES)) builtinTransform(name, examples);

export const CODECS = { EpochDate, IntegerText, SplitText, DateTimePattern, DecimalNumber, DecimalPlaces, Case };
export const TRANSFORMS = Object.fromEntries([Read, Set_, TextEquals, TextIn, HasValue, AllOf, AnyOf, Unset, When, WhenNone, Coalesce, Handle, KeyedHandle, SourceHandle, Ref, HandleKey, Correspond,
	CorrespondAs, CorrespondEmitted, Single, Valid, At, FormatName, Field, Nullable, QualifierConvert, ToInteger, ToVocabulary, Given, Members,
	...Object.values(BUILTIN_TRANSFORMS)].map(item => [item.name, item]));

/** Report codes: `Onto.Handle.KeyMissing` is `Binding.KeyMissing`; other reasons are kept. */
export function reasonCode(reason) {
	const name = typeof reason === "symbol" ? reason.description.replace(/^member:/, "") : String(reason);
	const short = name.split(".").at(-1);
	for (const [namespace, members] of [["Binding", BindingCodes], ["Mapping", MappingCodes]]) {
		try { if (members[short]) return `${namespace}.${short}`; }
		catch { /* not a member */ }
	}
	return name;
}

// EOF
