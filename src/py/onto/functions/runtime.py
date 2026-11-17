"""Module: functions.runtime — pure function application, exact decimal built-ins and conformance."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, DecimalException, Inexact, MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, Underflow, localcontext
from fractions import Fraction
from itertools import product
import json
import re
from typing import Any

from ..observations.formatter import _Printer
from ..observations.model import Observations, ObservationsDocument, _time, _valueIdentity, _valueKey, canonicalNumber
from ..observations.parser import _Resolver, _jsonValue
from ..ontology.model import Decl, Model, Ontology
from ..text import Diagnostics, Loc, annotation
from .formatter import _valueText
from .model import BUILTIN_ARITIES, Function, FunctionLibrary, FunctionResult, SignatureType
from .operations import _resolveSignature

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


NUMERIC = ("Integer", "Number", "Amount", "Percent", "Duration")
PATTERN_TOKENS = {"YYYY": r"\d{4}", "MM": r"\d{2}", "DD": r"\d{2}", "hh": r"\d{2}", "mm": r"\d{2}", "ss": r"\d{2}", "Z": r"Z|[+-]\d{2}:\d{2}"}
RE_PATTERN = re.compile("|".join(PATTERN_TOKENS))
EPOCH = date(1970, 1, 1)


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def numeric(value: Any) -> Decimal:
	if not isinstance(value, str):
		raise ValueError("Numbers must be decimal strings")
	return Decimal(canonicalNumber(value))


def arithmetic(name: str, args: list[Any]) -> str:
	values = [numeric(value) for value in args]
	exact = True
	if name == "divide":
		if not values[1]:
			raise ValueError("Division by zero")
		# A reduced fraction terminates in base ten exactly when its denominator has only factors 2 and 5.
		ratio = Fraction(values[0]) / Fraction(values[1])
		denominator, twos, fives = ratio.denominator, 0, 0
		while denominator % 2 == 0:
			denominator //= 2
			twos += 1
		while denominator % 5 == 0:
			denominator //= 5
			fives += 1
		precision = len(Decimal(ratio.numerator).as_tuple().digits) + max(twos, fives) + 1 if denominator == 1 else 16
		exact = denominator == 1
	elif name == "multiply":
		precision = sum(len(value.as_tuple().digits) for value in values) + 1
	else:
		# Include every aligned decimal place plus carry digits, even across cancellation.
		precision = max(value.adjusted() for value in values) - min(value.as_tuple().exponent for value in values) + len(str(len(values))) + 2
	context = Context(prec=max(1, precision), rounding=ROUND_HALF_EVEN, Emin=MIN_EMIN, Emax=MAX_EMAX)
	# Outside Decimal's representable range, report a gap instead of silently underflowing to zero.
	context.traps[Inexact] = exact
	context.traps[Underflow] = True
	with localcontext(context):
		if name == "divide":
			result = values[0] / values[1]
		elif name == "subtract":
			result = values[0] - values[1]
		else:
			result = Decimal(1 if name == "multiply" else 0)
			for value in values:
				result = result * value if name == "multiply" else result + value
	return canonicalNumber(str(result))


def patternParse(value: str, pattern: str, withTime: bool) -> str:
	parts, offset, tokens = [], 0, set()
	for match in RE_PATTERN.finditer(pattern):
		token = match[0]
		if token in tokens:
			raise ValueError(f"Repeated date token '{token}'")
		tokens.add(token)
		parts += [re.escape(pattern[offset:match.start()]), f"(?P<{token}>{PATTERN_TOKENS[token]})"]
		offset = match.end()
	parts.append(re.escape(pattern[offset:]))
	matched = re.fullmatch("".join(parts), value, re.ASCII)
	if not matched or not {"YYYY", "MM", "DD"} <= tokens:
		raise ValueError("Value does not match a complete date pattern")
	fields = matched.groupdict()
	iso = f"{fields['YYYY']}-{fields['MM']}-{fields['DD']}"
	if withTime:
		if not {"hh", "mm", "ss"} <= tokens:
			raise ValueError("A date-time pattern needs hh, mm and ss")
		iso += f"T{fields['hh']}:{fields['mm']}:{fields['ss']}" + fields.get("Z", "")
	elif tokens & {"hh", "mm", "ss", "Z"}:
		raise ValueError("A date pattern cannot contain time fields")
	_time(iso)
	return iso


def patternFormat(value: str, pattern: str) -> str:
	_time(value)
	parsed = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
	fields = {"YYYY": f"{parsed.year:04}", "MM": f"{parsed.month:02}", "DD": f"{parsed.day:02}"}
	if isinstance(parsed, datetime):
		fields |= {"hh": f"{parsed.hour:02}", "mm": f"{parsed.minute:02}", "ss": f"{parsed.second:02}"}
		if parsed.tzinfo is not None:
			fields["Z"] = "Z" if parsed.utcoffset() == timedelta(0) else parsed.isoformat()[-6:]
	def replace(match):
		if match[0] not in fields:
			raise ValueError(f"Value has no '{match[0]}' field")
		return fields[match[0]]
	return RE_PATTERN.sub(replace, pattern)


def builtin(name: str, args: list[Any]) -> Any:
	if name in ("sum", "multiply", "subtract", "divide"):
		return arithmetic(name, args)
	if name == "text":
		# Function-example spelling quotes extra delimiters; text() uses observations spelling instead.
		return _Printer(Ontology(), Observations({}, {}, {}, [], [])).value(args[0], typed=False)
	if name in ("count", "join"):
		if not isinstance(args[0], dict) or "set" not in args[0]:
			raise ValueError(f"'{name}' requires a collection")
		if args[0].get("partial"):
			raise ValueError(f"'{name}' requires a complete collection")
		if name == "count":
			return str(len(args[0]["set"]))
		if not isinstance(args[1], str) or any(not isinstance(item, str) for item in args[0]["set"]):
			raise ValueError("join requires texts")
		return args[1].join(sorted(args[0]["set"]))
	if name == "date" and len(args) == 1:
		seconds = numeric(args[0])
		if seconds != seconds.to_integral_value():
			raise ValueError("date requires integer epoch seconds")
		return (EPOCH + timedelta(days=int(seconds) // 86400)).isoformat()
	if any(not isinstance(arg, str) for arg in args):
		raise ValueError(f"'{name}' requires text arguments")
	if name == "concat":
		return "".join(args)
	if name in ("trim", "lower", "upper"):
		return getattr(args[0], "strip" if name == "trim" else name)()
	if name == "split":
		return {"set": sorted(set(part for part in args[0].split(args[1]) if part))}
	if name == "number":
		return canonicalNumber(args[0])
	if name in ("date", "datetime"):
		return patternParse(*args, withTime=name == "datetime")
	if name == "epoch":
		_time(args[0])
		if "T" in args[0]:
			raise ValueError("epoch requires a date, not a date-time")
		return str((date.fromisoformat(args[0]) - EPOCH).days * 86400)
	if name == "format":
		return patternFormat(*args)
	if name == "ref":
		raise ValueError("ref requires binding execution context")
	raise ValueError(f"Unknown built-in '{name}'")


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class FunctionEvaluator:
	"""Apply resolved function names; return one outcome per Cartesian application, without claim assembly."""

	def __init__(self, ontologies: list[Ontology] | None = None, libraries: list[FunctionLibrary] | None = None,
		functions: list[Function] | None = None, maps: list[Decl] | None = None, implementations: dict[str, Callable[..., Any]] | None = None):
		self.ontology = Ontology(decls=[decl for ontology in ontologies or [] for decl in ontology.decls])
		self.model = Model(self.ontology)
		self.functions: dict[str, Function] = {}
		self.maps = {decl.path: decl for decl in self.ontology.decls if decl.kind == "map"}
		for decl in maps or []:
			if decl.path in self.maps or decl.kind != "map":
				raise ValueError(f"Invalid or duplicate map '{decl.path}'")
			self.maps[decl.path] = decl
		for namespace, items in [(library.namespace, library.functions) for library in libraries or []] + [("", functions or [])]:
			for function in items:
				name = f"{namespace}/{function.name}" if namespace else function.name
				if name in self.functions or name in self.maps or name in BUILTIN_ARITIES:
					raise ValueError(f"Duplicate function '{name}'")
				self.functions[name] = deepcopy(function)
		self.implementations = dict(implementations or {})

	def typedValue(self, value: Any, signature: SignatureType) -> Any:
		"""Validate and detach an observations-encoded value against its concrete signature."""
		_jsonValue(value)
		if value is None or value == {"unknown": True}:
			return deepcopy(value)
		resolved = _resolveSignature(self.model, signature)
		if signature.collection:
			if not isinstance(value, dict) or "set" not in value:
				raise ValueError("Expected a collection")
			scalar = SignatureType(signature.builtin, signature.path, range=signature.range)
			members = [self.typedValue(member, scalar) for member in value["set"]]
			if len({_valueIdentity(member, resolved.builtin in NUMERIC) for member in members}) != len(members):
				raise ValueError("Duplicate collection members")
			return {"set": sorted(members, key=_valueKey), **({"partial": True} if value.get("partial") else {})}
		if resolved.kind in ("entity", "relation"):
			if not isinstance(value, dict) or set(value) != {"ref"}:
				raise ValueError("Expected a reference")
		elif resolved.builtin == "Boolean":
			if type(value) is not bool:
				raise ValueError("Expected a boolean")
		elif not isinstance(value, str):
			raise ValueError("Expected a string-encoded scalar")
		raw = json.dumps(value, ensure_ascii=False) if resolved.builtin == "Text" else _valueText(value)
		return _Resolver(self.ontology, ObservationsDocument()).scalar(raw, resolved, Loc("function", 0))

	def evaluate(self, name: str, args: list[Any]) -> list[FunctionResult]:
		"""Apply a resolved name with isolated inputs; configuration errors raise, domain failures return reasons."""
		function = self.functions.get(name)
		mapping = self.maps.get(name)
		if name in BUILTIN_ARITIES:
			minimum, maximum = BUILTIN_ARITIES[name]
		elif function is not None:
			minimum = maximum = len(function.args)
			if name not in self.implementations:
				raise ValueError(f"Missing implementation for '{name}'")
		elif mapping is not None:
			minimum = maximum = 1
		else:
			raise ValueError(f"Unknown function '{name}'")
		if len(args) < minimum or maximum is not None and len(args) > maximum:
			raise ValueError(f"Invalid argument count for '{name}'")
		try:
			for index, arg in enumerate(args):
				_jsonValue(arg)
				if isinstance(arg, dict) and "set" in arg:
					isNumeric = name in ("sum", "multiply", "subtract", "divide") or name == "date" and len(args) == 1
					if function is not None:
						isNumeric = _resolveSignature(self.model, function.args[index]).builtin in NUMERIC
					if len({_valueIdentity(member, isNumeric) for member in arg["set"]}) != len(arg["set"]):
						raise ValueError("Duplicate collection members")
			collections = [signature.collection for signature in function.args] if function else [name in ("join", "count") and index == 0 for index in range(len(args))]
			lifted = [isinstance(arg, dict) and "set" in arg and not whole for arg, whole in zip(args, collections)]
			partial = any(lift and arg.get("partial", False) for arg, lift in zip(args, lifted))
			combinations = [sorted(arg["set"], key=_valueKey) if lift else [arg] for arg, lift in zip(args, lifted)]
		except (ValueError, TypeError, DecimalException) as error:
			return [FunctionResult(reason=str(error))]
		return [self.apply(name, list(items), function, mapping, partial) for items in product(*combinations)]

	def apply(self, name: str, args: list[Any], function: Function | None, mapping: Decl | None, partial: bool) -> FunctionResult:
		"""Apply one combination, propagating missing values before domain-specific work."""
		try:
			if function is None or not annotation(function.ann, "nulls"):
				if any(arg is None for arg in args):
					return FunctionResult(partial=partial)
				if any(arg == {"unknown": True} for arg in args):
					return FunctionResult({"unknown": True}, partial=partial)
			if function is not None:
				inputs = [self.typedValue(arg, signature) for arg, signature in zip(args, function.args)]
				result = self.implementations[name](*inputs)
				result = self.typedValue(result, function.result)
			elif mapping is not None:
				arg = self.typedValue(args[0], SignatureType(path=mapping.mapFrom))
				matches = {line.toValue for line in mapping.mapLines if line.fromValue == arg}
				if len(matches) != 1:
					raise ValueError("Missing or ambiguous value map entry")
				result = self.typedValue(matches.pop(), SignatureType(path=mapping.mapTo))
			else:
				result = builtin(name, args)
			return FunctionResult(deepcopy(result), partial=partial)
		except Exception as error:
			# Registered implementations signal domain failures with exceptions; KeyboardInterrupt/SystemExit still escape.
			return FunctionResult(reason=str(error) or type(error).__name__, partial=partial)

	def identity(self, value: Any, signature: SignatureType) -> Any:
		"""Compare sets without order and numeric values without decimal spelling differences."""
		resolved = _resolveSignature(self.model, signature)
		return _valueIdentity(value, resolved.builtin in NUMERIC)

	def conformance(self, declarations: FunctionLibrary | list[Function]) -> int:
		"""Execute every example and f(inverse(result)); raise located diagnostics on any failure."""
		namespace = declarations.namespace if isinstance(declarations, FunctionLibrary) else ""
		functions = declarations.functions if isinstance(declarations, FunctionLibrary) else declarations
		diag = Diagnostics()
		count = 0
		for function in functions:
			name = f"{namespace}/{function.name}" if namespace else function.name
			for example in function.examples:
				count += 1
				try:
					results = self.evaluate(name, example.args)
					if len(results) != 1 or results[0].reason or self.identity(results[0].value, function.result) != self.identity(example.result, function.result):
						raise ValueError(f"Failed example of '{name}': {results!r}")
					inverse = annotation(function.ann, "inverse")
					if inverse:
						inverseName = f"{namespace}/{inverse}" if namespace else inverse
						back = self.evaluate(inverseName, [example.result])
						if len(back) != 1 or back[0].reason:
							raise ValueError(f"Failed inverse '{inverseName}' of '{name}'")
						again = self.evaluate(name, [back[0].value])
						if len(again) != 1 or again[0].reason or self.identity(again[0].value, function.result) != self.identity(example.result, function.result):
							raise ValueError(f"Failed inverse round trip of '{name}'")
				except ValueError as error:
					diag.error("conformance", str(error), example.loc)
		diag.check()
		return count


__all__ = ["FunctionEvaluator"]

# EOF
