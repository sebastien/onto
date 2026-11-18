"""Module: functions.formatter — canonical library text and detached JSON encoding."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from ..ontology.formatter import Namer
from ..text import printAnnotations, withDoc
from .model import FUNCTIONS_FORMAT, Function, FunctionExample, FunctionLibrary, SignatureType

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def signatureToJson(signature: SignatureType) -> dict[str, Any]:
	value = {"builtin": signature.builtin} if signature.builtin else {"path": signature.path}
	return value | ({"collection": True} if signature.collection else {}) | ({"range": True} if signature.range else {})


def valueToJson(value: Any) -> Any:
	if isinstance(value, dict) and "set" in value:
		return value | {"set": sorted(value["set"], key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))}
	return value


def valueText(value: Any) -> str:
	if value is None:
		return "null"
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, dict):
		if "unknown" in value:
			return "?"
		if "ref" in value:
			return value["ref"]
		members = sorted((valueText(member) for member in value["set"]))
		return "[" + ", ".join(members + (["..."] if value.get("partial") else [])) + "]"
	# Function values have additional delimiters beyond observations: commas, arrows and docs.
	unsafe = not value or value != value.strip() or any(char in value for char in '\n\r",[]') or value in ("?", "null", "...") or "=>" in value or re.search(r"(^|\s)(\{|//|--(?:\s|$))", value)
	return json.dumps(value, ensure_ascii=False) if unsafe else value


def exampleKey(example: FunctionExample) -> str:
	return json.dumps([valueToJson(arg) for arg in example.args], sort_keys=True, ensure_ascii=False)


def functionBlock(function: Function, short: Namer) -> list[str]:
	"""Render one local or library function declaration and its sorted examples."""
	def signatureText(signature: SignatureType) -> str:
		name = signature.builtin or short(signature.path)
		return (f"Range<{name}>" if signature.range else name) + ("*" if signature.collection else "")
	annotations = printAnnotations(function.ann, ["inverse", "nulls"])
	head = f"@fn {function.name} {', '.join(signatureText(arg) for arg in function.args)} -> {signatureText(function.result)}"
	lines = [withDoc(head + (f" {annotations}" if annotations else ""), function.doc)]
	for example in sorted(function.examples, key=exampleKey):
		args = ", ".join(valueText(value) for value in example.args)
		lines.append(f"  {args} => {valueText(example.result)}")
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
		value = {"name": function.name, "args": [signatureToJson(arg) for arg in function.args], "result": signatureToJson(function.result),
			"examples": [{"args": [valueToJson(arg) for arg in example.args], "result": valueToJson(example.result)} for example in sorted(function.examples, key=exampleKey)]}
		if function.ann:
			value["ann"] = dict(function.ann)
		if function.doc is not None:
			value["doc"] = function.doc
		functions.append(value)
	return deepcopy({"format": FUNCTIONS_FORMAT, "namespace": library.namespace,
		**({"header": library.header} if library.header else {}), **({"uses": library.uses} if library.uses else {}), "functions": functions})


__all__ = ["printFunctions", "functionsToJson"]

# EOF
