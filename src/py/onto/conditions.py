"""Module: conditions — the `when` and `deleted` conditions of bindings and mappings (spec-04 Conditions).

A condition is a test `path:value`, `path:A|B` for any of several values, or `path` alone for having a
value, combined with ` & ` and ` | ` (`&` first) and grouped with parentheses. Its JSON form is the test
`{path, value}`, `{path, values}` or `{path}`, and `{all: [...]}` or `{any: [...]}`.
"""

from __future__ import annotations

import re
from typing import Any

from .expressions import ExpressionParser, expressionFromJson, printExpression
from .observations.parser import jsonObject

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Condition = dict[str, Any]

# A value is an annotation token that cannot be mistaken for an operator, a group, an alternative or a
# test: without `:`, `A:x|B:y` is an error rather than the value `B:y`.
RE_VALUE = re.compile(r"[^\s{},=|&():]+")
OPERATORS = (("any", "|"), ("all", "&"))


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def isValue(text: Any) -> bool:
	return isinstance(text, str) and RE_VALUE.fullmatch(text) is not None


def combined(key: str, items: list[Condition]) -> Condition:
	"""One operand, or the flat `all`/`any` of several: nesting an operator in itself adds nothing."""
	flat = [member for item in items for member in (item[key] if key in item else [item])]
	return flat[0] if len(flat) == 1 else {key: flat}


def test(path: list[Any], values: list[str]) -> Condition:
	"""A test of the values listed, or with none, of having a value."""
	if len(set(values)) != len(values):
		raise ValueError("A condition test lists a value twice")
	if not values:
		return {"path": path}
	return {"path": path, "value": values[0]} if len(values) == 1 else {"path": path, "values": values}


class ConditionParser:
	"""Parse `condition := conjunction (" | " conjunction)*`, `conjunction := operand (" & " operand)*`."""

	def __init__(self, text: str, binding: bool):
		self.text = text
		self.binding = binding
		self.pos = 0

	def spaces(self) -> None:
		while self.pos < len(self.text) and self.text[self.pos] in " \t":
			self.pos += 1

	def operator(self, symbol: str) -> bool:
		"""An operator between operands, which whitespace surrounds (as it does `??`)."""
		start = self.pos
		self.spaces()
		if self.pos > start and self.text.startswith(symbol, self.pos) and self.text[self.pos + 1:self.pos + 2] in (" ", "\t"):
			self.pos += 1
			return True
		self.pos = start
		return False

	def condition(self) -> Condition:
		items = [self.conjunction()]
		while self.operator("|"):
			items.append(self.conjunction())
		return combined("any", items)

	def conjunction(self) -> Condition:
		items = [self.operand()]
		while self.operator("&"):
			items.append(self.operand())
		return combined("all", items)

	def operand(self) -> Condition:
		self.spaces()
		if self.text.startswith("(", self.pos):
			self.pos += 1
			inner = self.condition()
			self.spaces()
			if not self.text.startswith(")", self.pos):
				raise ValueError("Unclosed condition group")
			self.pos += 1
			return inner
		return self.test()

	def test(self) -> Condition:
		parser = ExpressionParser(self.text, self.binding)
		parser.pos = self.pos
		path = parser.term()
		self.pos = parser.pos
		if self.binding and "text" in path:
			path = {"path": [path["text"]]}  # a whole quoted string names a field, as a binding line's does
		if "path" not in path:
			raise ValueError("A condition requires a path")
		path = expressionFromJson(path, binding=self.binding)
		start = self.pos
		self.spaces()
		if not self.text.startswith(":", self.pos):
			# A path alone tests that it has a value; the whitespace may precede an operator.
			self.pos = start
			return test(path["path"], [])
		self.pos += 1
		self.spaces()
		values = [self.value()]
		# `A|B` lists alternatives; `|` with whitespace around it joins conditions instead.
		while self.text.startswith("|", self.pos) and RE_VALUE.match(self.text, self.pos + 1):
			self.pos += 1
			values.append(self.value())
		return test(path["path"], values)

	def value(self) -> str:
		match = RE_VALUE.match(self.text, self.pos)
		if not match:
			raise ValueError("A condition value must be a token")
		self.pos = match.end()
		return match[0]


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseCondition(text: str, *, binding: bool = True) -> Condition:
	"""Parse a condition; `binding` admits document paths."""
	if not isinstance(text, str) or "\n" in text or "\r" in text:
		raise ValueError("A condition must be a single line of text")
	parser = ConditionParser(text, binding)
	result = parser.condition()
	parser.spaces()
	if parser.pos != len(text):
		raise ValueError(f"Unexpected text at condition offset {parser.pos}")
	return result


def conditionFromJson(data: Any, *, binding: bool = True) -> Condition:
	"""Validate and copy a condition's JSON form, which must survive its text round trip."""
	if isinstance(data, dict) and len(data) == 1 and next(iter(data)) in ("all", "any"):
		key, items = next(iter(data.items()))
		if not isinstance(items, list) or len(items) < 2:
			raise ValueError(f"'{key}' combines at least two conditions")
		result = {key: [conditionFromJson(item, binding=binding) for item in items]}
		if any(key in item for item in result[key]):
			raise ValueError(f"A nested '{key}' must be written flat")
	else:
		value = jsonObject(data, ("path",), ("value", "values"))
		path = expressionFromJson({"path": value["path"]}, binding=binding)["path"]
		if "value" in value and "values" in value:
			raise ValueError("A condition test has a value, values, or neither")
		values = [value["value"]] if "value" in value else value.get("values", [])
		if not isinstance(values, list) or "values" in value and len(values) < 2 or not all(isValue(item) for item in values):
			raise ValueError("Condition values are two or more tokens")
		result = test(path, list(values))
	if parseCondition(printCondition(result, binding=binding), binding=binding) != result:
		raise ValueError("Condition JSON does not survive its text round trip")
	return result


def printCondition(condition: Condition, *, binding: bool = True) -> str:
	"""The canonical text of a condition: ` | ` joins alternatives of `&`, which needs no parentheses."""
	for key, symbol in OPERATORS:
		if key in condition:
			items = [printCondition(item, binding=binding) for item in condition[key]]
			if key == "all":
				items = [f"({text})" if "any" in item else text for item, text in zip(condition[key], items)]
			return f" {symbol} ".join(items)
	values = testValues(condition)
	return printExpression({"path": condition["path"]}, binding=binding) + (":" + "|".join(values) if values else "")


def conditionTests(condition: Condition | None) -> list[Condition]:
	"""The tests of a condition, in order."""
	if condition is None:
		return []
	for key, _ in OPERATORS:
		if key in condition:
			return [item for member in condition[key] for item in conditionTests(member)]
	return [condition]


def conditionPaths(condition: Condition | None) -> list[list[Any]]:
	"""The paths a condition reads, in order."""
	return [item["path"] for item in conditionTests(condition)]


def testValues(test: Condition) -> list[str]:
	"""The values a test accepts; none for a test of having a value."""
	return list(test["values"]) if "values" in test else [test["value"]] if "value" in test else []


def isSingleValueTest(condition: Condition | None) -> bool:
	"""Whether `condition` is a single test with exactly one expected value."""
	return condition is not None and "path" in condition and "value" in condition


def conditionOutcome(condition: Condition, known) -> bool | None:
	"""Whether `condition` holds (True), cannot hold (False) or may hold (None), knowing only the values some
	paths can have: `known(path)` gives them as a set, or None when they could be anything."""
	if "path" not in condition:
		key = "all" if "all" in condition else "any"
		outcomes = [conditionOutcome(item, known) for item in condition[key]]
		decisive = key == "any"  # The outcome that settles the operator on its own: True for `any`, False for `all`.
		return decisive if decisive in outcomes else (not decisive) if all(item is (not decisive) for item in outcomes) else None
	values = known(condition["path"])
	if values is None:
		return None
	listed = set(testValues(condition))
	if not values or not listed:
		return bool(values)  # Known to have no value, or a test of having one.
	return True if values <= listed else False if not values & listed else None


def mapConditionPaths(condition: Condition, change) -> Condition:
	"""A copy whose test paths are `change(path)`; tests keep their values."""
	for key, _ in OPERATORS:
		if key in condition:
			return {key: [mapConditionPaths(item, change) for item in condition[key]]}
	return {**condition, "path": change(condition["path"])}


__all__ = ["Condition", "conditionFromJson", "conditionOutcome", "conditionPaths", "conditionTests", "isSingleValueTest", "mapConditionPaths", "parseCondition", "printCondition", "testValues"]

# EOF
