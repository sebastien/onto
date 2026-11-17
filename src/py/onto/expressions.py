"""Module: expressions — shared spec-04 expression parsing, JSON validation and spelling."""

from __future__ import annotations

import json
import re
from typing import Any

from .observations.model import canonicalNumber
from .text import isName, isPath

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Expression = dict[str, Any]


RE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*")
RE_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
RESERVED = {"true", "false", "null"}
DECODER = json.JSONDecoder()


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def _path(steps: Any, binding: bool) -> list[str | dict[str, Any]]:
	if not isinstance(steps, list) or not steps:
		raise ValueError("An expression path needs at least one step")
	result = []
	for index, step in enumerate(steps):
		if isinstance(step, str):
			if not step or not binding and not (isPath(step) if index == 0 else isName(step)):
				raise ValueError("Invalid expression path field")
			result.append(step)
			continue
		if not binding and isinstance(step, dict) and set(step) == {"key"}:
			# In a mapping, `Phones[Mobile]` names an element of a keyed structure (spec-01 keyed structures)
			if index == 0 or not isinstance(steps[index - 1], str) or not isinstance(step["key"], str) or not isPath(step["key"]):
				raise ValueError("An element key follows an attribute: Attr[Key]")
			result.append(dict(step))
			continue
		if not binding and step == {"root": True} and len(steps) == 1:
			# In a mapping, `$` alone is the scope instance itself (spec-04 Expressions)
			result.append(dict(step))
			continue
		if not binding or not isinstance(step, dict) or len(step) != 1:
			raise ValueError("Document path steps are only allowed in bindings")
		key, value = next(iter(step.items()))
		valid = (
			key in ("each", "root") and value is True
			or key in ("index", "up") and type(value) is int and value >= (1 if key == "up" else 0)
		)
		if not valid or (key in ("root", "up")) != (index == 0):
			raise ValueError("Invalid document path step or position")
		result.append(dict(step))
	return result


def _read(data: Any, binding: bool, field: bool) -> Expression:
	if not isinstance(data, dict):
		raise ValueError("An expression must be an object")
	if set(data) == {"call", "args"}:
		if not isinstance(data["call"], str) or not isPath(data["call"]) or not isinstance(data["args"], list):
			raise ValueError("Invalid function call")
		return {"call": data["call"], "args": [_read(arg, binding, False) for arg in data["args"]]}
	if len(data) != 1:
		raise ValueError("An expression needs exactly one variant and no extra members")
	key, value = next(iter(data.items()))
	if key == "path":
		return {key: _path(value, binding)}
	if key == "coalesce":
		if not isinstance(value, list) or len(value) < 2:
			raise ValueError("Coalescing needs at least two expressions")
		# A nested coalesce has the same meaning, but no separate spelling in this grammar.
		items = [_read(item, binding, False) for item in value]
		if any("coalesce" in item for item in items):
			raise ValueError("Nested coalescing must use one flat expression")
		return {key: items}
	if key == "text" and isinstance(value, str):
		if binding and field:
			raise ValueError("A whole binding string is a quoted field, not a text literal")
		return {key: value}
	if key == "number" and isinstance(value, str) and canonicalNumber(value) == value:
		return {key: value}
	if key == "boolean" and type(value) is bool or key in ("null", "unknown") and value is True:
		return {key: value}
	if key == "meta" and isinstance(value, str) and value in (("format",) if binding else ("valid", "at", "src")):
		return {key: value}
	raise ValueError(f"Invalid expression variant '{key}'")


def _printPath(steps: list[str | dict[str, Any]]) -> str:
	result = ""
	for index, step in enumerate(steps):
		if isinstance(step, str):
			plain = (isPath(step) if index == 0 else isName(step)) and (index > 0 or step not in RESERVED)
			result += ("." if index else "") + (step if plain else json.dumps(step, ensure_ascii=False))
		elif "each" in step:
			result += "[*]"
		elif "index" in step:
			result += f"[{step['index']}]"
		elif "key" in step:
			result += f"[{step['key']}]"
		elif "up" in step:
			result += ".".join("^" for _ in range(step["up"]))
		else:
			result += "$"
	return result


def _print(expr: Expression) -> str:
	if "path" in expr:
		return _printPath(expr["path"])
	if "call" in expr:
		return expr["call"] + "(" + ", ".join(_print(arg) for arg in expr["args"]) + ")"
	if "coalesce" in expr:
		return " ?? ".join(_print(item) for item in expr["coalesce"])
	if "text" in expr:
		return json.dumps(expr["text"], ensure_ascii=False)
	if "number" in expr:
		return expr["number"]
	if "boolean" in expr:
		return "true" if expr["boolean"] else "false"
	if "meta" in expr:
		return "$" + expr["meta"]
	return "?" if "unknown" in expr else "null"


class _Parser:
	def __init__(self, text: str, binding: bool):
		self.text = text
		self.binding = binding
		self.pos = 0

	def spaces(self) -> None:
		while self.pos < len(self.text) and self.text[self.pos] in " \t":
			self.pos += 1

	def take(self, token: str) -> bool:
		if not self.text.startswith(token, self.pos):
			return False
		self.pos += len(token)
		return True

	def name(self) -> str:
		if not (match := RE_PATH.match(self.text, self.pos)):
			raise ValueError(f"Expected a name at expression offset {self.pos}")
		self.pos = match.end()
		return match[0]

	def string(self) -> str:
		value, end = DECODER.raw_decode(self.text, self.pos)
		self.pos = end
		return value

	def path(self, first: str | dict[str, Any]) -> Expression:
		steps = [first]
		while self.pos < len(self.text):
			if self.take("."):
				if self.binding and self.text.startswith('"', self.pos):
					steps.append(self.string())
				else:
					steps.append(self.name())
			elif self.binding and self.take("["):
				if self.take("*"):
					steps.append({"each": True})
				elif match := re.match(r"[0-9]+", self.text[self.pos:]):
					steps.append({"index": int(match[0])})
					self.pos += len(match[0])
				else:
					raise ValueError("Expected '*' or a nonnegative list index")
				if not self.take("]"):
					raise ValueError("Unclosed list step")
			elif not self.binding and isinstance(steps[-1], str) and self.take("["):
				match = re.match(r"[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*", self.text[self.pos:])
				if not match:
					raise ValueError("Expected an element key")
				steps.append({"key": match[0]})
				self.pos += len(match[0])
				if not self.take("]"):
					raise ValueError("Unclosed element key")
			else:
				break
		return {"path": steps}

	def term(self) -> Expression:
		self.spaces()
		if self.pos == len(self.text):
			raise ValueError("Expected an expression")
		if self.text[self.pos] == '"':
			value = self.string()
			if self.text[self.pos:self.pos + 1] in (".", "["):
				if not self.binding:
					raise ValueError("Quoted path fields are only allowed in bindings")
				return self.path(value)
			return {"text": value}
		if self.take("?"):
			return {"unknown": True}
		if self.take("$"):
			if self.pos < len(self.text) and (self.text[self.pos].isalpha() or self.text[self.pos] == "_"):
				return {"meta": self.name()}
			return self.path({"root": True})
		if self.take("^"):
			up = 1
			while self.take(".^"):
				up += 1
			return self.path({"up": up})
		if match := RE_NUMBER.match(self.text, self.pos):
			self.pos = match.end()
			return {"number": canonicalNumber(match[0])}
		name = self.name()
		end = self.pos
		self.spaces()
		if self.take("("):
			args = []
			self.spaces()
			if not self.take(")"):
				while True:
					args.append(self.expr())
					if self.take(")"):
						break
					if not self.take(","):
						raise ValueError("Expected ',' or ')' in function call")
			return {"call": name, "args": args}
		self.pos = end
		if name in RESERVED:
			return {"null": True} if name == "null" else {"boolean": name == "true"}
		return self.path(name)

	def expr(self) -> Expression:
		items = [self.term()]
		self.spaces()
		while self.text.startswith("??", self.pos):
			if self.pos == 0 or not self.text[self.pos - 1].isspace() or self.pos + 2 == len(self.text) or not self.text[self.pos + 2].isspace():
				raise ValueError("'??' must be surrounded by whitespace")
			self.pos += 2
			items.append(self.term())
			self.spaces()
		return items[0] if len(items) == 1 else {"coalesce": items}


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def keyedSteps(steps: list[Any]) -> list[Any]:
	"""Mapping path steps with element keys folded into their attribute: `Phones`, `{key: Mobile}` is `Phones[Mobile]`."""
	result: list[Any] = []
	for step in steps:
		if isinstance(step, dict) and set(step) == {"key"} and result and isinstance(result[-1], str):
			result[-1] += f"[{step['key']}]"
		else:
			result.append(step)
	return result


def parseExpression(text: str, *, binding: bool = False, field: bool = True) -> Expression:
	"""Parse one expression; `binding` admits document paths and `field` treats a whole string as a field."""
	if not isinstance(text, str) or "\n" in text or "\r" in text:
		raise ValueError("An expression must be a single line of text")
	parser = _Parser(text, binding)
	result = parser.expr()
	if parser.pos != len(text):
		raise ValueError(f"Unexpected text at expression offset {parser.pos}")
	if binding and field and "text" in result:
		result = {"path": [result["text"]]}
	return _read(result, binding, field)


def expressionFromJson(data: Any, *, binding: bool = False, field: bool = True) -> Expression:
	"""Validate and copy an expression, rejecting JSON that cannot preserve its meaning in text."""
	result = _read(data, binding, field)
	if parseExpression(_print(result), binding=binding, field=field) != result:
		raise ValueError("Expression JSON does not survive its text round trip")
	return result


def printExpression(expr: Expression, *, binding: bool = False, field: bool = True) -> str:
	"""Print a validated expression in canonical spacing without mutating it."""
	return _print(expressionFromJson(expr, binding=binding, field=field))


# EOF
