"""Module: integrations.hexa.vocabulary — the `Onto` constraints, codecs, transforms and codes, with their examples.

Built-in transforms wrap onto's `FunctionEvaluator`; they never reimplement spec-04
functions. Every transform also accepts hexa's sentinel for an unbound optional input
and returns `ABSENT_VALUE`, the integration's marker for "no value, no gap", which
`ClaimsEmit` drops: hexa derivations cannot leave a key out without a hole.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal as Exact, InvalidOperation
import json
import math
import re
from typing import Any as AnyValue

from hexa.shapes import Any, Bool, DateOnly, DatePattern, DateTime, Decimal, DecimalText, Failure, Gap, Num, Text, Timed, codec, codes, either, transform, where

from ...functions.model import FunctionResult
from ...functions.runtime import FunctionEvaluator, patternFormat, patternParse
from ...observations.model import RE_DURATION, timestampValue, canonicalNumber, parseInterval

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


ABSENT_VALUE = {"absent": True}
UNKNOWN = {"unknown": True}
RE_ENCODED = re.compile(r"(?:[A-Za-z0-9]|_[0-9A-F]{2})*")
RE_PLAIN = re.compile(r"[A-Za-z0-9]")
DURATION_SECONDS = {"Second": 1, "Minute": 60, "Hour": 3600, "Day": 86400, "Week": 604800}
DURATION_MONTHS = {"Month": 1, "Year": 12}
BUILTINS = {
	"concat": "Concat", "split": "Split", "join": "Join", "trim": "Trim", "lower": "Lower", "upper": "Upper",
	"number": "Number", "text": "Text", "date": "Date", "datetime": "DateTime", "epoch": "Epoch", "format": "Format",
	"sum": "Sum", "multiply": "Multiply", "subtract": "Subtract", "divide": "Divide", "count": "Count",
}
BindingCodes = codes("Binding", "KeyMissing", "TypeMismatch", "PathUnsupported", "InputEmpty", "SnapshotOlder", "ParentMissing", "ReplacementConflicting")
MappingCodes = codes("Mapping", "InputConflicting", "ReferenceUnmapped", "ReferenceAmbiguous", "NotIntegral", "ValueUnmapped", "KeyReference", "ContextUnsupported", "PolicyUnsupported")
# NOTE: Only these prototypes are registered. Compiled calls carry their own evaluator,
# like program-local stages, without competing for hexa's process-wide names.
FUNCTION_TRANSFORM = transform("Onto.Function", lambda *args: None, inputs=[[Any, ...]], output=Any)
FUNCTION_CODEC = codec("Onto.FunctionCodec", source=Any, canonical=Any, parse=lambda value: value, format=lambda value, original=None: value)


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def isAbsent(value: AnyValue) -> bool:
	"""hexa passes a bare `object()` for an unbound optional input; nested derivations pass `ABSENT_VALUE`."""
	return type(value) is object or value == ABSENT_VALUE


def decimalText(value: AnyValue) -> str:
	"""An exponent-free canonical decimal from a JSON number or decimal text; never through binary rounding of text."""
	if isinstance(value, bool) or not isinstance(value, (int, float, str)):
		raise ValueError("Not a number")
	if isinstance(value, int):
		return str(value)
	if isinstance(value, float) and not math.isfinite(value):
		raise ValueError("Not a finite number")
	if isinstance(value, str) and value != value.strip():
		raise ValueError("A decimal has no surrounding whitespace")
	try:
		text = format(Exact(repr(value) if isinstance(value, float) else canonicalNumber(value)), "f")
	except (InvalidOperation, ValueError) as error:
		raise ValueError("Not a decimal") from error
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return "0" if text in ("-0", "") else text


def documentValue(value: AnyValue) -> AnyValue:
	"""A document value in the spec-02 JSON encoding, untyped: numbers become decimal text, lists sets."""
	if value is None or isinstance(value, (bool, str)):
		return value
	if isinstance(value, (int, float)):
		return decimalText(value)
	if isinstance(value, list):
		members: dict[str, AnyValue] = {}
		for item in value:
			if item is not None and not isAbsent(item):
				member = documentValue(item)
				members.setdefault(json.dumps(member, sort_keys=True), member)
		return {"set": list(members.values())}
	if isinstance(value, dict) and (set(value) in ({"ref"}, {"ref", "type"}, {"unknown"}) or "set" in value and set(value) <= {"set", "partial"}):
		return value
	raise ValueError("Not a scalar or collection")


def textOf(value: AnyValue) -> str | None:
	"""The text a `when`/`deleted` condition compares: strings, decimals, booleans and handles."""
	if isinstance(value, str):
		return value
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, (int, float)):
		return decimalText(value)
	if isinstance(value, dict) and "ref" in value:
		return value["ref"]
	return None


def encodeKey(key: str) -> str:
	"""Every character outside `[A-Za-z0-9]` as `_` and the uppercase hex of its UTF-8 bytes (spec-04)."""
	return "".join(char if RE_PLAIN.fullmatch(char) else "".join(f"_{byte:02X}" for byte in char.encode()) for char in key)


def decodeKey(text: str) -> str | None:
	"""Invert `encodeKey`, or None when `text` is not such an encoding."""
	if not RE_ENCODED.fullmatch(text):
		return None
	data = bytearray()
	index = 0
	while index < len(text):
		if text[index] == "_":
			data.append(int(text[index + 1:index + 3], 16))
			index += 3
		else:
			data += text[index].encode()
			index += 1
	try:
		return data.decode()
	except UnicodeDecodeError:
		return None


def keyText(key: AnyValue) -> str:
	if isinstance(key, str):
		return key
	if isinstance(key, (int, float)) and not isinstance(key, bool):
		return decimalText(key)
	raise ValueError("A key must be text or a number")


def handleOf(typeName: str, key: AnyValue) -> str:
	"""`<Type>_<encoded key>`, `Type` being the last segment of the type path."""
	return f"{typeName.rsplit('/', 1)[-1]}_{encodeKey(keyText(key))}"


def resultValue(results: list[FunctionResult], reason: AnyValue) -> AnyValue:
	"""One application gives its value; several (collection arguments) give a set; any failure is a gap."""
	if any(item.reason for item in results):
		raise Gap(reason)
	if len(results) == 1 and not results[0].partial:
		return results[0].value
	members: dict[str, AnyValue] = {}
	for item in results:
		members.setdefault(json.dumps(item.value, sort_keys=True), item.value)
	return {"set": list(members.values()), **({"partial": True} if any(item.partial for item in results) else {})}


def callArguments(args: tuple) -> list[AnyValue] | None:
	"""Arguments in the spec-02 encoding, or None when one is absent (the call is then absent too).

	Raises `ValueError` for a document value no function can read (an object).
	"""
	if any(isAbsent(arg) for arg in args):
		return None
	return [documentValue(arg) for arg in args]


def evaluated(evaluator: FunctionEvaluator, name: str, args: tuple, reason: AnyValue) -> AnyValue:
	"""Apply `name` to hexa arguments: absent in, absent out; any failure is the gap `reason`."""
	try:
		values = callArguments(args)
		return ABSENT_VALUE if values is None else resultValue(evaluator.evaluate(name, values), reason)
	except ValueError as error:
		raise Gap(reason) from error


EVALUATOR = FunctionEvaluator()
BUILTIN_TRANSFORMS: dict[str, AnyValue] = {}


def builtinTransform(name: str, examples: list[dict]) -> AnyValue:
	"""`Onto.<Name>`: the spec-04 built-in `name`, through onto's evaluator."""
	title = BUILTINS[name]

	def apply(*args):
		return evaluated(EVALUATOR, name, args, BUILTIN_TRANSFORMS[title].Invalid)

	BUILTIN_TRANSFORMS[title] = transform(f"Onto.{title}", apply, inputs=[[Any, ...]], output=Any, gaps=["Invalid"], examples=examples)
	return BUILTIN_TRANSFORMS[title]


def functionTransform(name: str, evaluator: FunctionEvaluator) -> AnyValue:
	"""A program-local transform bound to its library, local function or map evaluator."""
	transformName = name.replace("/", ".")
	reason = codes(transformName, "Unmapped", "Unformattable", "Invalid").Invalid

	def apply(*args):
		return evaluated(evaluator, name, args, reason)

	return replace(FUNCTION_TRANSFORM, name=transformName, function=apply, gaps=(reason,))


def functionCodec(name: str, inverse: str, canonical: AnyValue, evaluator: FunctionEvaluator) -> AnyValue:
	"""A program-local codec: parse with `name`, format with `inverse`, using its own evaluator."""
	codecName = name.replace("/", ".")
	reasons = codes(codecName, "Unmapped", "Unformattable", "Invalid")

	def parse(value):
		return evaluated(evaluator, name, (value,), reasons.Invalid)

	def formatValue(value, original=None):
		return evaluated(evaluator, inverse, (value,), reasons.Invalid)

	return replace(FUNCTION_CODEC, name=codecName, canonical=canonical, parse=parse, format=formatValue, gaps=tuple(reasons.members.values()))


# -----------------------------------------------------------------------------
#
# TRANSFORMS
#
# -----------------------------------------------------------------------------


def readValue(value: AnyValue, spec: str) -> AnyValue:
	"""Read a document or function value as the canonical value of target type `spec`."""
	if isAbsent(value):
		return ABSENT_VALUE
	if value is None or value == UNKNOWN:
		return value
	kind, _, detail = spec.partition(":")
	try:
		if kind == "Text":
			if isinstance(value, str):
				return value
		elif kind in ("Decimal", "Integer"):
			number = decimalText(value)
			if kind == "Decimal" or "." not in number:
				return number
		elif kind == "Boolean":
			if isinstance(value, bool):
				return value
			if value in ("true", "false"):
				return value == "true"
		elif kind in ("Date", "DateTime"):
			if isinstance(value, str) and ("T" in value) == (kind == "DateTime"):
				timestampValue(value)
				return value
		elif kind == "Duration":
			if detail == "iso":
				if isinstance(value, str) and RE_DURATION.fullmatch(value):
					return value
			else:
				return decimalText(value)
		elif kind == "Vocab":
			if isinstance(value, str) and value in detail.split("|"):
				return value
		elif kind == "Ref":
			if isinstance(value, dict) and "ref" in value:
				return value
		elif kind == "Any":
			return documentValue(value)
	except ValueError:
		pass
	raise Gap(Read.TypeMismatch)


def readSet(value: AnyValue, spec: str) -> AnyValue:
	"""A complete collection of members read as `spec`; a lone value is a one-member collection."""
	if isAbsent(value):
		return ABSENT_VALUE
	if value is None or value == UNKNOWN:
		return value
	items = value["set"] if isinstance(value, dict) and "set" in value else value if isinstance(value, list) else [value]
	members: dict[str, AnyValue] = {}
	for item in items:
		if item is not None:
			try:
				member = readValue(item, spec)
			except Gap as error:
				raise Gap(Set.TypeMismatch) from error
			members.setdefault(json.dumps(member, sort_keys=True), member)
	result = {"set": sorted(members.values(), key=lambda item: json.dumps(item, sort_keys=True))}
	return result | ({"partial": True} if isinstance(value, dict) and value.get("partial") else {})


def textEquals(value: AnyValue, text: str) -> bool:
	return not isAbsent(value) and textOf(value) == text


def whenValue(condition: AnyValue, value: AnyValue) -> AnyValue:
	return value if condition is True and not isAbsent(value) else ABSENT_VALUE


def whenNone(value: AnyValue, texts: list[str], result: AnyValue) -> AnyValue:
	"""The default of exclusive lines: `result` when `value` is absent or none of `texts`."""
	return ABSENT_VALUE if not isAbsent(value) and textOf(value) in texts or isAbsent(result) else result


def coalesce(*items: AnyValue) -> AnyValue:
	return next((item for item in items if not isAbsent(item)), ABSENT_VALUE)


def handle(typeName: str, key: AnyValue) -> str:
	if isAbsent(key) or key is None or key == UNKNOWN:
		raise Gap(Handle.KeyMissing)
	try:
		return handleOf(typeName, key)
	except ValueError as error:
		raise Gap(Handle.TypeMismatch) from error


def sourceHandle(typeName: str, scope: str, source: str, sourceType: str) -> str:
	"""`<T>_` + enc(`<scope>/<S>/<key>`), the key being the source handle without `<S>_`, decoded (spec-04).

	`<S>` keeps instances of two source types mapped to one target type apart (a client and a user
	with the same id are two people)."""
	short = sourceType.rsplit("/", 1)[-1]
	prefix = short + "_"
	key = decodeKey(source[len(prefix):]) if source.startswith(prefix) else None
	return handleOf(typeName, f"{scope}/{short}/{key if key is not None else source}")


def keyedHandle(typeName: str, key: AnyValue, scope: str, source: str, sourceType: str) -> str:
	"""A referential key's handle (spec-05 "Producing handles"): derived from the key, else source-qualified."""
	if isAbsent(key) or key is None or key == UNKNOWN:
		return sourceHandle(typeName, scope, source, sourceType)
	try:
		return handleOf(typeName, key)
	except ValueError as error:
		raise Gap(KeyedHandle.TypeMismatch) from error


def reference(typePath: str, key: AnyValue) -> AnyValue:
	if isAbsent(key):
		return ABSENT_VALUE
	if key is None or key == UNKNOWN:
		return key
	# spec-04: a function given a collection where it expects one value applies to each member
	if isinstance(key, dict) and "set" in key:
		return {**key, "set": [reference(typePath, item) for item in key["set"] if item is not None]}
	if isinstance(key, list):
		return [reference(typePath, item) for item in key if item is not None]
	try:
		return {"ref": handleOf(typePath, key), "type": typePath}
	except ValueError as error:
		raise Gap(Ref.TypeMismatch) from error


def handleKey(value: AnyValue, typeName: str) -> AnyValue:
	"""The key a reference's handle was formed from, decoded."""
	if isAbsent(value):
		return ABSENT_VALUE
	ref = value.get("ref") if isinstance(value, dict) else value
	prefix = typeName.rsplit("/", 1)[-1] + "_"
	key = decodeKey(ref[len(prefix):]) if isinstance(ref, str) and ref.startswith(prefix) else None
	if key is None:
		raise Gap(HandleKey.Undecodable)
	return key


def correspond(value: AnyValue) -> AnyValue:
	"""`{ref, target}` → `{ref: target}`; an unmapped reference is a gap."""
	if isAbsent(value):
		return ABSENT_VALUE
	if isAbsent(value) or value is None or value == UNKNOWN:
		return value
	if isinstance(value, dict) and "set" in value:
		return {"set": [correspond(item) for item in value["set"]], **({"partial": True} if value.get("partial") else {})}
	if not isinstance(value, dict) or "target" not in value:
		raise Gap(Correspond.ReferenceUnmapped)
	return {"ref": value["target"], **({"type": value["targetType"]} if "targetType" in value else {})}


def correspondAs(value: AnyValue, typePath: str, emitted: bool = False) -> AnyValue:
	"""`{ref, targets}` → `{ref: targets[typePath]}`: a source instance with several target instances
	(several scope lines for its type) is referred to by the one of the type the receiver accepts.
	`emitted` (`{as=T}`): a target its scope lines' conditions skip is a gap, not an implicit instance."""
	if isAbsent(value):
		return ABSENT_VALUE
	if value is None or value == UNKNOWN:
		return value
	if isinstance(value, dict) and "set" in value:
		return {"set": [correspondAs(item, typePath, emitted) for item in value["set"]], **({"partial": True} if value.get("partial") else {})}
	target = value.get("targets", {}).get(typePath) if isinstance(value, dict) else None
	if target is None or emitted and typePath in value.get("skipped", ()):
		raise Gap((CorrespondEmitted if emitted else CorrespondAs).ReferenceUnmapped)
	return {"ref": target, "type": typePath}


def single(value: AnyValue) -> AnyValue:
	"""The one member of a collection (`into` over a multi-valued reference); several, or an incomplete set, are ambiguous."""
	if isAbsent(value) or not isinstance(value, dict) or "set" not in value:
		return value
	members = value["set"]
	if not members and not value.get("partial"):
		return ABSENT_VALUE
	if len(members) != 1 or value.get("partial"):
		raise Gap(Single.ReferenceAmbiguous)
	return members[0]


def valid(value: AnyValue) -> AnyValue:
	if isAbsent(value):
		return ABSENT_VALUE
	try:
		parseInterval(value)
		return value
	except (ValueError, TypeError) as error:
		raise Gap(Valid.Invalid) from error


def timeValue(value: AnyValue) -> AnyValue:
	if isAbsent(value):
		return ABSENT_VALUE
	try:
		timestampValue(value)
		return value
	except (ValueError, TypeError) as error:
		raise Gap(At.Invalid) from error


def formatName(name: AnyValue) -> AnyValue:
	"""`DatePattern("YYYYMMDD")` → `YYYYMMDD`: the formats-file name of the codec that parsed a value."""
	if isAbsent(name) or not isinstance(name, str) or "(" not in name:
		return ABSENT_VALUE
	return json.loads("[" + name[name.index("(") + 1:-1] + "]")[0]


def field(value: AnyValue, steps: list[str | int]) -> AnyValue:
	"""Navigate captured JSON by field names; `*` maps over list items, an integer picks one."""
	current = [value]
	for step in steps:
		following = []
		for item in current:
			if step == "*" and isinstance(item, list):
				following += item
			elif type(step) is int and isinstance(item, list):
				following += item[step:step + 1]
			elif isinstance(item, dict) and step in item:
				following.append(item[step])
		current = following
	if not current or isAbsent(value):
		return ABSENT_VALUE
	return current if "*" in steps else current[0]


def nullable(value: AnyValue, marker: AnyValue, kind: str) -> AnyValue:
	"""A JSON `null` caught by a null policy reads as `null` (`absent`) or `?` (`unknown`)."""
	if not isAbsent(marker):
		return None if kind == "absent" else dict(UNKNOWN)
	return ABSENT_VALUE if isAbsent(value) else value


def given(value: AnyValue, result: AnyValue) -> AnyValue:
	"""`result` when `value` is present: a `when` condition written back beside its line."""
	return ABSENT_VALUE if isAbsent(value) or value is None or value == UNKNOWN else result


def members(value: AnyValue, key: str) -> AnyValue:
	"""A collection's members as a JSON list, sorted; with `key`, as `{key: member}` objects."""
	if isAbsent(value) or not isinstance(value, dict) or "set" not in value:
		return ABSENT_VALUE
	items = sorted(value["set"], key=lambda item: json.dumps(item, sort_keys=True))
	return [{key: item} for item in items] if key else items


def arithmetic(name: str, *args: str) -> str:
	return EVALUATOR.evaluate(name, list(args))[0].value


def qualifierConvert(value: AnyValue, source: dict, target: dict) -> AnyValue:
	"""Exact `scale` and `unit` conversion (spec-04 qualifier conversion)."""
	if isAbsent(value):
		return ABSENT_VALUE
	if isAbsent(value) or value is None or value == UNKNOWN:
		return value
	if isinstance(value, dict) and "set" in value:
		return {**value, "set": [qualifierConvert(item, source, target) for item in value["set"]]}
	result = value
	if "scale" in source and "scale" in target:
		result = arithmetic("divide", arithmetic("multiply", result, target["scale"]), source["scale"])
	if "unit" in source and "unit" in target and source["unit"] != target["unit"]:
		for table in (DURATION_SECONDS, DURATION_MONTHS):
			if source["unit"] in table and target["unit"] in table:
				result = arithmetic("divide", arithmetic("multiply", result, str(table[source["unit"]])), str(table[target["unit"]]))
				break
		else:
			raise Gap(QualifierConvert.Inconvertible)
	return decimalText(result)


def toInteger(value: AnyValue) -> AnyValue:
	if isAbsent(value):
		return ABSENT_VALUE
	if isAbsent(value) or value is None or value == UNKNOWN:
		return value
	if isinstance(value, dict) and "set" in value:
		return {**value, "set": [toInteger(item) for item in value["set"]]}
	if not isinstance(value, str) or "." in decimalText(value):
		raise Gap(ToInteger.NotIntegral)
	return decimalText(value)


def toVocabulary(value: AnyValue, values: list[str]) -> AnyValue:
	if isAbsent(value):
		return ABSENT_VALUE
	if isAbsent(value) or value is None or value == UNKNOWN:
		return value
	if isinstance(value, dict) and "set" in value:
		return {**value, "set": [toVocabulary(item, values) for item in value["set"]]}
	if value not in values:
		raise Gap(ToVocabulary.ValueUnmapped)
	return value


# -----------------------------------------------------------------------------
#
# CODEC FUNCTIONS
#
# -----------------------------------------------------------------------------


def epochParse(value):
	try:
		result = EVALUATOR.evaluate("date", [decimalText(value)])[0]
	except ValueError as error:
		raise Gap(EpochDate.Invalid) from error
	if result.reason:
		raise Gap(EpochDate.Invalid)
	return result.value


def epochFormat(value, original=None):
	seconds = EVALUATOR.evaluate("epoch", [value])[0].value
	return seconds if isinstance(original, str) else int(seconds)


def integerParse(value):
	try:
		number = decimalText(value)
	except ValueError as error:
		raise Gap(IntegerText.Invalid) from error
	if "." in number:
		raise Gap(IntegerText.Invalid)
	return number


def identityFormat(value, original=None):
	return value


def splitParse(separator, value):
	if not separator:
		raise Gap(SplitText.Invalid)
	return {"set": sorted({part for part in value.split(separator) if part})}


def splitFormat(separator, value, original=None):
	members = value["set"]
	if not separator:
		raise Gap(SplitText.Unformattable)
	result = separator.join(sorted(members))
	if set(splitParse(separator, result)["set"]) != set(members):
		raise Gap(SplitText.Unformattable)
	return result


def dateTimeParse(pattern, value):
	try:
		return patternParse(value, pattern, withTime=True)
	except ValueError as error:
		raise Gap(DateTimePattern.Invalid) from error


def dateTimeFormat(pattern, value, original=None):
	try:
		return patternFormat(value, pattern)
	except ValueError as error:
		raise Gap(DateTimePattern.Unformattable) from error


def decimalNumberParse(value):
	return decimalText(value)


def decimalNumberFormat(value, original=None):
	"""A JSON number only when it reads back as the same decimal; precision is never lost silently."""
	if "." not in value and abs(int(value)) <= 2**53 - 1:
		return int(value)
	number = float(value)
	if "." in value and decimalText(number) == value:
		return number
	raise Gap(DecimalNumber.Inexact)


def placesParse(places, value):
	try:
		return decimalText(value)
	except ValueError as error:
		raise Gap(DecimalPlaces.Invalid) from error


def placesFormat(places, value, original=None):
	whole, _, fraction = value.partition(".")
	if len(fraction) > places:
		raise Gap(DecimalPlaces.Inexact)
	return whole + ("." + fraction.ljust(places, "0") if places else "")


def caseFormat(case, value, original=None):
	return value.upper() if case == "upper" else value.lower()


def caseParse(case, value):
	return value


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


Integral = where(lambda value: isinstance(value, str) and "." not in value, "Onto.Integral")
IsoDuration = where(lambda value: isinstance(value, str) and RE_DURATION.fullmatch(value) is not None, "Onto.IsoDuration")

EpochDate = codec("Onto.EpochDate", source=either(Num, Text), canonical=DateTime & DateOnly, parse=epochParse, format=epochFormat, gaps=["Invalid"],
	examples=[{"input": 1907712000, "output": "2030-06-15"}, {"input": "x", "gap": "Invalid"}])
IntegerText = codec("Onto.IntegerText", source=either(Text, Num), canonical=Decimal & Integral, parse=integerParse, format=identityFormat, gaps=["Invalid"],
	examples=[{"input": 6, "output": "6", "direction": "forward"}, {"input": "6.5", "gap": "Invalid"}])
SplitText = codec("Onto.SplitText", source=Text, canonical={"set": [Text]}, params={"Separator": Text}, parse=splitParse, format=splitFormat,
	gaps=["Invalid"],
	examples=[{"arguments": [","], "input": "b,a", "output": {"set": ["a", "b"]}, "direction": "forward"}])
DateTimePattern = codec("Onto.DateTimePattern", source=Text, canonical=DateTime & Timed, params={"Pattern": Text}, parse=dateTimeParse, format=dateTimeFormat,
	gaps=["Invalid"], examples=[{"arguments": ["YYYYMMDD hh:mm:ss"], "input": "20260915 10:30:00", "output": "2026-09-15T10:30:00"}])
DecimalNumber = codec("Onto.DecimalNumber", source=Num, canonical=Decimal, parse=decimalNumberParse, format=decimalNumberFormat, gaps=["Inexact"],
	examples=[{"input": 0.0525, "output": "0.0525"}, {"input": "0.1000000000000000055511151231257827", "gap": "Inexact", "direction": "backward"}])
DecimalPlaces = codec("Onto.DecimalPlaces", source=Text, canonical=Decimal, params={"Places": Num}, parse=placesParse, format=placesFormat,
	gaps=["Invalid", "Inexact"], examples=[{"arguments": [2], "input": "0.50", "output": "0.5"}, {"arguments": [2], "input": "0.125", "gap": "Inexact", "direction": "backward"}])
Case = codec("Onto.Case", source=Text, canonical=Text, params={"Case": either("upper", "lower")}, parse=caseParse, format=caseFormat,
	examples=[{"arguments": ["upper"], "input": "ACME", "output": "acme", "direction": "backward"}])

Read = transform("Onto.Read", readValue, inputs=[Any, Text], output=Any, gaps=["TypeMismatch"],
	examples=[{"input": [0.42, "Decimal"], "output": "0.42"}, {"input": ["x", "Integer"], "gap": "TypeMismatch"}])
Set = transform("Onto.Set", readSet, inputs=[Any, Text], output=Any, gaps=["TypeMismatch"],
	examples=[{"input": [["b", "a", "b"], "Text"], "output": {"set": ["a", "b"]}}, {"input": [["a", False], "Text"], "gap": "TypeMismatch"}])
TextEquals = transform("Onto.TextEquals", textEquals, inputs=[Any, Text], output=Bool,
	examples=[{"input": ["F", "F"], "output": True}, {"input": [6, "6"], "output": True}])
When = transform("Onto.When", whenValue, inputs=[Any, Any], output=Any,
	examples=[{"input": [True, "x"], "output": "x"}, {"input": [False, "x"], "output": ABSENT_VALUE}])
WhenNone = transform("Onto.WhenNone", whenNone, inputs=[Any, Any, Any], output=Any,
	examples=[{"input": ["A", ["A", "B"], "x"], "output": ABSENT_VALUE}, {"input": ["C", ["A", "B"], "x"], "output": "x"},
		{"input": [ABSENT_VALUE, ["A"], "x"], "output": "x"}])
Coalesce = transform("Onto.Coalesce", coalesce, inputs=[[Any, ...]], output=Any,
	examples=[{"input": [ABSENT_VALUE, "ACM30"], "output": "ACM30"}, {"input": [None, "x"], "output": None}])
Handle = transform("Onto.Handle", handle, inputs=[Text, Any], output=Text, gaps=["KeyMissing", "TypeMismatch"],
	examples=[{"input": ["Issuer", "C-17"], "output": "Issuer_C_2D17"}, {"input": ["Issuer", ABSENT_VALUE], "gap": "KeyMissing"}])
KeyedHandle = transform("Onto.KeyedHandle", keyedHandle, inputs=[Text, Any, Any, Any, Text], output=Text, gaps=["TypeMismatch"],
	examples=[{"input": ["Organisation", "1234567", "AdviceLink", "MemberCompany_1", "MemberCompany"], "output": "Organisation_1234567"},
		{"input": ["Organisation", ABSENT_VALUE, "AdviceLink", "MemberCompany_1", "MemberCompany"], "output": "Organisation_AdviceLink_2FMemberCompany_2F1"}])
SourceHandle = transform("Onto.SourceHandle", sourceHandle, inputs=[Text, Any, Any, Text], output=Text,
	examples=[{"input": ["Company", "Exchange", "Issuer_C_2D17", "Issuer"], "output": "Company_Exchange_2FIssuer_2FC_2D17"}])
Ref = transform("Onto.Ref", reference, inputs=[Text, Any], output=Any, gaps=["TypeMismatch"],
	examples=[{"input": ["Exchange/Issuer", "C-17"], "output": {"ref": "Issuer_C_2D17", "type": "Exchange/Issuer"}}])
HandleKey = transform("Onto.HandleKey", handleKey, inputs=[Any, Text], output=Any, gaps=["Undecodable"],
	examples=[{"input": [{"ref": "Issuer_C_2D17"}, "Issuer"], "output": "C-17"}])
Correspond = transform("Onto.Correspond", correspond, inputs=[Any], output=Any, gaps=["ReferenceUnmapped"],
	examples=[{"input": [{"ref": "Issuer_C_2D17", "target": "Company_ACME"}], "output": {"ref": "Company_ACME"}}, {"input": [{"ref": "x"}], "gap": "ReferenceUnmapped"}])
Single = transform("Onto.Single", single, inputs=[Any], output=Any, gaps=["ReferenceAmbiguous"],
	examples=[{"input": [{"set": [{"ref": "Person_1"}]}], "output": {"ref": "Person_1"}}, {"input": [{"set": []}], "output": ABSENT_VALUE},
		{"input": [{"set": [{"ref": "a"}, {"ref": "b"}]}], "gap": "ReferenceAmbiguous"}, {"input": [{"ref": "a"}], "output": {"ref": "a"}}])
CorrespondAs = transform("Onto.CorrespondAs", correspondAs, inputs=[Any, Text], output=Any, gaps=["ReferenceUnmapped"],
	examples=[{"input": [{"ref": "Client_9", "target": "Person_9", "targets": {"Crm/Person": "Person_9", "Crm/Relationship": "Relationship_9"}}, "Crm/Person"], "output": {"ref": "Person_9", "type": "Crm/Person"}},
		{"input": [{"ref": "x", "targets": {}}, "Crm/Person"], "gap": "ReferenceUnmapped"}])
CorrespondEmitted = transform("Onto.CorrespondEmitted", lambda value, typePath: correspondAs(value, typePath, True), inputs=[Any, Text], output=Any,
	gaps=["ReferenceUnmapped"], examples=[
		{"input": [{"ref": "MA_1", "targets": {"T/Application": "Application_1"}}, "T/Application"], "output": {"ref": "Application_1", "type": "T/Application"}},
		{"input": [{"ref": "MA_2", "targets": {"T/Application": "Application_2"}, "skipped": ["T/Application"]}, "T/Application"], "gap": "ReferenceUnmapped"}])
Valid = transform("Onto.Valid", valid, inputs=[Any], output=Any, gaps=["Invalid"],
	examples=[{"input": ["2026-09-01"], "output": "2026-09-01"}, {"input": ["2026-02-30"], "gap": "Invalid"}])
At = transform("Onto.At", timeValue, inputs=[Any], output=Any, gaps=["Invalid"],
	examples=[{"input": ["2026-11-10"], "output": "2026-11-10"}, {"input": ["soon"], "gap": "Invalid"}])
FormatName = transform("Onto.FormatName", formatName, inputs=[Any], output=Any,
	examples=[{"input": ['DatePattern("YYYYMMDD")'], "output": "YYYYMMDD"}])
Field = transform("Onto.Field", field, inputs=[Any, Any], output=Any,
	examples=[{"input": [{"bond": {"interval": 6}}, ["bond", "interval"]], "output": 6}])
Nullable = transform("Onto.Nullable", nullable, inputs=[Any, Any, Text], output=Any,
	examples=[{"input": [ABSENT_VALUE, None, "unknown"], "output": UNKNOWN},
		{"input": [ABSENT_VALUE, ABSENT_VALUE, "unknown"], "output": ABSENT_VALUE}])
QualifierConvert = transform("Onto.QualifierConvert", qualifierConvert, inputs=[Any, Any, Any], output=Any, gaps=["Inconvertible"],
	examples=[{"input": ["0.0525", {"scale": "1"}, {"scale": "100"}], "output": "5.25"}, {"input": ["90", {"unit": "Minute"}, {"unit": "Hour"}], "output": "1.5"}])
ToInteger = transform("Onto.ToInteger", toInteger, inputs=[Any], output=Any, gaps=["NotIntegral"],
	examples=[{"input": ["6"], "output": "6"}, {"input": ["6.5"], "gap": "NotIntegral"}])
Given = transform("Onto.Given", given, inputs=[Any, Any], output=Any,
	examples=[{"input": ["2026-09-15", "F"], "output": "F"}, {"input": [ABSENT_VALUE, "F"], "output": ABSENT_VALUE}])
Members = transform("Onto.Members", members, inputs=[Any, Text], output=Any,
	examples=[{"input": [{"set": ["b", "a"]}, ""], "output": ["a", "b"]}, {"input": [{"set": ["a"]}, "b"], "output": [{"b": "a"}]}])
ToVocabulary = transform("Onto.ToVocabulary", toVocabulary, inputs=[Any, Any], output=Any, gaps=["ValueUnmapped"],
	examples=[{"input": ["Bond", ["Bond", "Equity"]], "output": "Bond"}, {"input": ["Cash", ["Bond"]], "gap": "ValueUnmapped"}])

BUILTIN_EXAMPLES = {
	"concat": [{"input": ["US0000000001", "/", "2026-09-01"], "output": "US0000000001/2026-09-01"}],
	"split": [{"input": ["b,a,,b", ","], "output": {"set": ["a", "b"]}}],
	"join": [{"input": [{"set": ["b", "a"]}, ","], "output": "a,b"}],
	"trim": [{"input": [" Acme 5.25% 2030 "], "output": "Acme 5.25% 2030"}],
	"lower": [{"input": ["ACME"], "output": "acme"}],
	"upper": [{"input": ["acme"], "output": "ACME"}],
	"number": [{"input": ["5.50"], "output": "5.5"}, {"input": ["five"], "gap": "Invalid"}],
	"text": [{"input": ["5.5"], "output": "5.5"}],
	"date": [{"input": [1907712000], "output": "2030-06-15"}, {"input": ["20260915", "YYYYMMDD"], "output": "2026-09-15"}],
	"datetime": [{"input": ["20260915103000", "YYYYMMDDhhmmss"], "output": "2026-09-15T10:30:00"}],
	"epoch": [{"input": ["2030-06-15"], "output": "1907712000"}],
	"format": [{"input": ["2026-09-15", "YYYYMMDD"], "output": "20260915"}],
	"sum": [{"input": ["0.1", "0.2"], "output": "0.3"}],
	"multiply": [{"input": ["98.5", "100"], "output": "9850"}],
	"subtract": [{"input": ["1", "0.25"], "output": "0.75"}],
	"divide": [{"input": ["1", "3"], "output": "0.3333333333333333"}, {"input": ["1", "0"], "gap": "Invalid"}],
	"count": [{"input": [{"set": ["a", "b"]}], "output": "2"}],
}
for builtinName, builtinExamples in BUILTIN_EXAMPLES.items():
	builtinTransform(builtinName, builtinExamples)

CODECS = {"EpochDate": EpochDate, "IntegerText": IntegerText, "SplitText": SplitText, "DateTimePattern": DateTimePattern,
	"DecimalNumber": DecimalNumber, "DecimalPlaces": DecimalPlaces, "Case": Case}
TRANSFORMS = {item.name: item for item in (Read, Set, TextEquals, When, WhenNone, Coalesce, Handle, KeyedHandle, SourceHandle, Ref, HandleKey, Correspond, CorrespondAs, CorrespondEmitted, Single, Valid, At,
	FormatName, Field, Nullable, QualifierConvert, ToInteger, ToVocabulary, Given, Members, *BUILTIN_TRANSFORMS.values())}


def builtin(name: str) -> AnyValue:
	"""The `Onto` transform of spec-04 built-in `name`."""
	return BUILTIN_TRANSFORMS[BUILTINS[name]]


def reasonCode(reason: str) -> str:
	"""Report codes: `Onto.Handle.KeyMissing` is `Binding.KeyMissing`; other reasons are kept."""
	short = reason.rsplit(".", 1)[-1]
	for namespace in (BindingCodes, MappingCodes):
		if short in namespace.members:
			return str(namespace.members[short])
	return reason


def plain(value: AnyValue) -> AnyValue:
	"""Thaw hexa's frozen example data into JSON values."""
	if isinstance(value, Mapping):
		return {key: plain(item) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		return [plain(item) for item in value]
	return value


def vocabularyConformance() -> int:
	"""Run every example of the `Onto` codecs and transforms; raise `AssertionError` on a difference.

	This stands in for hexa's conformance run, which the Python language binding does not ship yet.
	"""
	count = 0
	for item in TRANSFORMS.values():
		for example in map(plain, item.examples):
			count += 1
			try:
				result = item.function(*example["input"])
			except Gap as gap:
				assert "gap" in example and gap.code.short == example["gap"], (item.name, example, gap.code)
				continue
			assert "gap" not in example and result == example["output"], (item.name, example, result)
	for family in CODECS.values():
		for example in map(plain, family.examples):
			count += 1
			instance = family(*example["arguments"]) if "arguments" in example else family
			direction = example.get("direction", "both")
			try:
				if direction == "backward":
					value = instance.convert(example.get("output", example["input"]), formatting=True)
					assert "gap" not in example and value == example["input"], (family.name, example, value)
				else:
					value = instance.convert(example["input"])
					assert "gap" not in example and value == example["output"], (family.name, example, value)
					if direction == "both":
						assert instance.convert(value, formatting=True) == example["input"], (family.name, example)
			except Gap as gap:
				assert "gap" in example and gap.code.short == example["gap"], (family.name, example, gap.code)
			except Failure as failure:
				raise AssertionError((family.name, example, failure.code)) from failure
	return count


__all__ = [
	"ABSENT_VALUE", "BindingCodes", "MappingCodes", "Integral", "IsoDuration", "EpochDate", "IntegerText", "SplitText",
	"DateTimePattern", "DecimalNumber", "DecimalPlaces", "Case", "DatePattern", "DecimalText", "Read", "Set", "TextEquals", "When", "WhenNone",
	"Coalesce", "Handle", "KeyedHandle", "SourceHandle", "Ref", "HandleKey", "Correspond", "CorrespondAs", "CorrespondEmitted", "Single", "Valid", "At", "FormatName", "Field", "Nullable",
	"QualifierConvert", "ToInteger", "ToVocabulary", "Given", "Members", "TRANSFORMS", "CODECS", "builtin", "functionTransform", "functionCodec",
	"reasonCode", "vocabularyConformance", "isAbsent", "decimalText", "documentValue", "encodeKey", "decodeKey",
	"handleOf", "textOf",
]

# EOF
