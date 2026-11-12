"""Module: binding.formatter — canonical binding text and detached JSON encoding."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from ..expressions import Expression, printExpression
from ..functions.formatter import functionBlock, functionsToJson
from ..functions.model import FunctionLibrary
from ..ontology.formatter import Namer
from ..text import isName, withDoc
from .model import ANNOTATION_KEYS, BINDING_FORMAT, HEADER_KEYS, Binding, BindingLine

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def lineKey(line: BindingLine) -> tuple[int, str]:
	return (0 if line.facet else 1, line.facet or line.target or line.verb or "")


def shortExpression(expr: Expression, short: Namer) -> Expression:
	if "call" in expr:
		args = [shortExpression(arg, short) for arg in expr["args"]]
		if expr["call"] == "ref" and args and "path" in args[0]:
			args[0] = {"path": [short(args[0]["path"][0])]}
		name = short(expr["call"]) if "/" in expr["call"] else expr["call"]
		return {"call": name, "args": args}
	if "coalesce" in expr:
		return {"coalesce": [shortExpression(item, short) for item in expr["coalesce"]]}
	return expr


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printBinding(binding: Binding) -> str:
	"""Print a resolved binding without evaluating expressions or reading documents."""
	short = Namer(binding.ontology, sorted(binding.uses.items()))

	def exprText(expr: Expression, field: bool = True) -> str:
		return printExpression(shortExpression(expr, short), binding=True, field=field)

	def annotations(item: Any, keys: tuple[str, ...]) -> str:
		parts = []
		for key in ANNOTATION_KEYS:
			value = getattr(item, key, None) if key in keys else None
			if value is None:
				continue
			if key in ("id", "valid", "ctx"):
				value = exprText(value, field=False)
			elif key in ("when", "deleted"):
				value = exprText({"path": value["path"]}) + ":" + value["value"]
			parts.append(f"{key}={value}")
		return " {" + ", ".join(parts) + "}" if parts else ""

	args = " ".join(f"{key}={binding.header[key]}" for key in HEADER_KEYS if key in binding.header)
	lines = [f"@binding {binding.ontology}" + (f" {args}" if args else "")]
	lines += [f"@use {namespace} as {alias}" for alias, namespace in sorted(binding.uses.items())]
	if binding.at is not None:
		lines.append("@at <- " + exprText(binding.at))
	if binding.columns is not None:
		lines.append("@columns " + ", ".join(column if isName(column) else json.dumps(column, ensure_ascii=False) for column in binding.columns))
	for function in sorted(binding.functions, key=lambda item: item.name):
		lines += [""] + functionBlock(function, short)
	for scope in sorted(binding.scopes, key=lambda item: (item.type, exprText(item.path))):
		lines += ["", withDoc(f"{short(scope.type)} <- {exprText(scope.path)}" + annotations(scope, ("id", "ctx", "valid", "deleted")), scope.doc)]
		for line in sorted(scope.lines, key=lineKey):
			text = f"[{line.facet}]" if line.facet else f"{line.target or line.verb} <- {exprText(line.expr)}"
			lines.append(withDoc("  " + text + annotations(line, ("when", "null")), line.doc))
	if binding.exclusions:
		lines.append("")
		for exclusion in sorted(binding.exclusions, key=lambda item: exprText(item.path)):
			lines.append(withDoc("- " + exprText(exclusion.path) + f" {{reason={exclusion.reason}}}", exclusion.doc))
	return "\n".join(lines) + "\n"


def bindingToJson(binding: Binding) -> dict[str, Any]:
	"""Export a detached spec-04 binding JSON value with fully qualified names."""
	data: dict[str, Any] = {"format": BINDING_FORMAT, "ontology": binding.ontology}
	if binding.header:
		data["header"] = binding.header
	if binding.uses:
		data["uses"] = binding.uses
	if binding.at is not None:
		data["at"] = binding.at
	if binding.columns is not None:
		data["columns"] = binding.columns
	if binding.functions:
		data["functions"] = functionsToJson(FunctionLibrary(binding.ontology, functions=binding.functions))["functions"]
	scopes = []
	for scope in sorted(binding.scopes, key=lambda item: (item.type, printExpression(item.path, binding=True))):
		value = {"type": scope.type, "path": scope.path, "id": scope.id}
		for key in ("valid", "ctx", "deleted", "doc"):
			if (member := getattr(scope, key)) is not None:
				value[key] = member
		lines = []
		for line in sorted(scope.lines, key=lineKey):
			entry = {key: getattr(line, key) for key in ("target", "facet", "verb", "expr", "when", "null", "doc") if getattr(line, key) is not None}
			lines.append(entry)
		if lines:
			value["lines"] = lines
		scopes.append(value)
	data["scopes"] = scopes
	if binding.exclusions:
		data["exclusions"] = [{"path": printExpression(item.path, binding=True), "reason": item.reason,
			**({"doc": item.doc} if item.doc is not None else {})} for item in sorted(binding.exclusions, key=lambda item: printExpression(item.path, binding=True))]
	return deepcopy(data)


__all__ = ["printBinding", "bindingToJson"]

# EOF
