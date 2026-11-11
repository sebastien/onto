"""Module: functions.formatter — canonical library text and detached JSON encoding."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from ..ontology.formatter import Namer
from ..text import printAnnotations
from .model import FUNCTIONS_FORMAT, FunctionExample, FunctionLibrary, SignatureType

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def _signatureToJson(signature: SignatureType) -> dict[str, Any]:
	value = {"builtin": signature.builtin} if signature.builtin else {"path": signature.path}
	return value | ({"collection": True} if signature.collection else {})


def _valueToJson(value: Any) -> Any:
	if isinstance(value, dict) and "set" in value:
		return value | {"set": sorted(value["set"], key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))}
	return value


def _valueText(value: Any) -> str:
	if value is None:
		return "null"
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, dict):
		if "unknown" in value:
			return "?"
		if "ref" in value:
			return value["ref"]
		members = sorted((_valueText(member) for member in value["set"]))
		return "[" + ", ".join(members + (["..."] if value.get("partial") else [])) + "]"
	# Function values have additional delimiters beyond observations: commas, arrows and docs.
	unsafe = not value or value != value.strip() or any(char in value for char in '\n\r",[]') or value in ("?", "null", "...") or "=>" in value or re.search(r"(^|\s)(\{|//|--(?:\s|$))", value)
	return json.dumps(value, ensure_ascii=False) if unsafe else value


def _exampleKey(example: FunctionExample) -> str:
	return json.dumps([_valueToJson(arg) for arg in example.args], sort_keys=True, ensure_ascii=False)


def functionBlock(function: Function, short: Namer) -> list[str]:
	"""Render one local or library function declaration and its sorted examples."""
	def signatureText(signature: SignatureType) -> str:
		return (signature.builtin or short(signature.path)) + ("*" if signature.collection else "")
	annotations = printAnnotations(function.ann, ["inverse", "nulls"])
	head = f"@fn {function.name} {', '.join(signatureText(arg) for arg in function.args)} -> {signatureText(function.result)}"
	lines = [head + (f" {annotations}" if annotations else "") + (f" -- {function.doc}" if function.doc else "")]
	for example in sorted(function.examples, key=_exampleKey):
		args = ", ".join(_valueText(value) for value in example.args)
		lines.append(f"  {args} => {_valueText(example.result)}")
	return lines


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printFunctions(library: FunctionLibrary) -> str:
	"""Print a typed library in normal form; this does not execute its examples."""
	short = Namer(library.namespace, sorted(library.uses.items()))
	lines = [f"@functions {library.namespace}" + (f" rev={library.header['rev']}" if "rev" in library.header else "")]
	lines += [f"@use {namespace} as {alias}" for alias, namespace in sorted(library.uses.items())]
	for function in sorted(library.functions, key=lambda item: item.name):
		lines += [""] + functionBlock(function, short)
	return "\n".join(lines) + "\n"


def functionsToJson(library: FunctionLibrary) -> dict[str, Any]:
	"""Encode a typed library as an independent spec-04 JSON value."""
	functions = []
	for function in sorted(library.functions, key=lambda item: item.name):
		value = {"name": function.name, "args": [_signatureToJson(arg) for arg in function.args], "result": _signatureToJson(function.result),
			"examples": [{"args": [_valueToJson(arg) for arg in example.args], "result": _valueToJson(example.result)} for example in sorted(function.examples, key=_exampleKey)]}
		if function.ann:
			value["ann"] = dict(function.ann)
		if function.doc is not None:
			value["doc"] = function.doc
		functions.append(value)
	return deepcopy({"format": FUNCTIONS_FORMAT, "namespace": library.namespace,
		**({"header": library.header} if library.header else {}), **({"uses": library.uses} if library.uses else {}), "functions": functions})


__all__ = ["printFunctions", "functionsToJson"]

# EOF
