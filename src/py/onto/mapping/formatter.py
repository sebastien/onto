"""Module: mapping.formatter — canonical mapping text and detached spec-04 JSON."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..conditions import printCondition
from ..expressions import printExpression
from ..functions.formatter import functionBlock, functionsToJson
from ..functions.model import FunctionLibrary
from ..ontology.formatter import Namer, Printer, encodeOntology, normaliseOntology
from ..ontology.model import ANNOTATION_KEYS as ONTOLOGY_ANNOTATIONS, Ontology
from ..text import printAnnotations, withDoc
from .model import ANNOTATION_KEYS, HEADER_KEYS, MAPPING_FORMAT, QUALIFIER_KEYS, Mapping, MappingLine

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def lineKey(line: MappingLine) -> tuple[int, str, str]:
	# Exclusive lines of one target: the default (no `when`) first, then by condition (one path, so by value).
	return (0 if line.facet else 1, line.facet or line.target or line.verb or "", "" if line.when is None else "\x01" + printCondition(line.when, binding=False))


def shortElement(path: str, short: Namer) -> str:
	if path.endswith("]"):
		owner, facet = path.split("[", 1)
		return short(owner) + "[" + facet
	parts = path.split(".")
	if len(parts) == 3 and "/" in parts[2]:
		return f"{short(parts[0])}.{parts[1]}.{short(parts[2])}"
	return short(parts[0]) + ("." + ".".join(parts[1:]) if len(parts) > 1 else "")


def expressionText(expr: dict[str, Any], short: Namer, localCalls: set[str], target: tuple[str, Namer] | None = None) -> str:
	"""`target`: the `To` namespace and its namer, for the type of a target reference `ref(T, Key)`."""
	def names(value: dict[str, Any]) -> dict[str, Any]:
		if "call" in value:
			args = [names(arg) for arg in value["args"]]
			if value["call"] == "ref" and args and len(args[0].get("path", [])) == 1 and "/" in str(args[0]["path"][0]):
				typePath = args[0]["path"][0]
				if target and typePath.startswith(target[0] + "/"):
					namer = target[1]
					# A bare name resolves in From first, even if the declaration is written in To.
					name = namer.aliasName(typePath) or namer(typePath)
				else:
					name = short(typePath)
				args[0] = {"path": [name]}  # ref(Type, Key): the type is a name
			path = value["call"]
			name = short(path) if "/" in path else path
			if "/" in path and name in localCalls:
				name = short.aliasName(path)
				if name is None:
					raise ValueError(f"Call '{path}' is shadowed by a local declaration: add a @use alias")
			return {"call": name, "args": args}
		if "coalesce" in value:
			return {"coalesce": [names(item) for item in value["coalesce"]]}
		return value
	return printExpression(names(expr))


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printMapping(mapping: Mapping) -> str:
	"""Print a resolved mapping without evaluating any function or instance correspondence."""
	left = Namer(mapping.fromNamespace, sorted(mapping.uses.items()))
	right = Namer(mapping.toNamespace, sorted(mapping.uses.items()))
	localCalls = {function.name for function in mapping.functions} | {decl.path for decl in mapping.maps}
	target = (mapping.toNamespace, right) if mapping.toNamespace != mapping.fromNamespace else None
	def annotations(item: Any, keys: tuple[str, ...]) -> str:
		parts = []
		for key in ANNOTATION_KEYS:
			value = (item.qualifiers.get(key) if key in QUALIFIER_KEYS else getattr(item, "asType" if key == "as" else key, None)) if key in keys else None
			if value is None or value is False:
				continue
			if key in ("reverse", "candidate"):
				parts.append(key)
				continue
			if key in ("ctx", "valid", "present", "into", *QUALIFIER_KEYS):
				value = expressionText(value, left, localCalls, target)
			elif key == "when":
				value = printCondition(value, binding=False)
			elif key == "as":
				value = right(value)
			parts.append(f"{key}={value}")
		return " {" + ", ".join(parts) + "}" if parts else ""
	header = dict(mapping.header)
	if "view" in header:
		header["view"] = left(header["view"])
	if "candidates" in header:
		header["candidates"] = "true" if header["candidates"] else "false"
	args = " ".join(f"{key}={header[key]}" for key in HEADER_KEYS if key in header)
	lines = [f"@mapping {mapping.fromNamespace} -> {mapping.toNamespace}" + (" " + args if args else "")]
	lines += [f"@use {namespace} as {alias}" for alias, namespace in sorted(mapping.uses.items())]
	for function in sorted(mapping.functions, key=lambda item: item.name):
		lines += [""] + functionBlock(function, left)
	printer = Printer(Ontology(namespace=mapping.fromNamespace))
	for decl in normaliseOntology(Ontology(decls=mapping.maps)).decls:
		ann = printAnnotations(decl.ann, ONTOLOGY_ANNOTATIONS)
		lines += ["", withDoc(f"@map {decl.path} {left(decl.mapFrom)} -> {right(decl.mapTo)}" + (" " + ann if ann else ""), decl.doc)]
		lines += [printer.mapLine(line, indent="  ") for line in decl.mapLines]
	for lookup in sorted(mapping.lookups, key=lambda item: (item.owner, item.name)):
		lines += ["", withDoc(f"@lookup {left(lookup.owner)}.{lookup.name} -> {left(lookup.type)}", lookup.doc)]
		lines += [withDoc(f"  {line.attr} <- {line.source}", line.doc) for line in sorted(lookup.lines, key=lambda item: item.attr)]
	for scope in sorted(mapping.scopes, key=lambda item: (item.source, item.target, item.name or "")):
		lines += ["", withDoc(f"{left(scope.source)} -> {right(scope.target)}" + annotations(scope, ("name", "into", "present", "when", "ctx", "valid")), scope.doc)]
		for line in sorted(scope.lines, key=lineKey):
			text = f"[{line.facet}]" if line.facet else f"{line.target or line.verb} <- {expressionText(line.expr, left, localCalls, target)}"
			lines.append(withDoc("  " + text + annotations(line, ("name", "when", "src", "as", *QUALIFIER_KEYS, "reverse", "candidate")), line.doc))
	if mapping.exclusions:
		lines.append("")
		for item in sorted(mapping.exclusions, key=lambda item: item.path):
			lines.append(withDoc(f"- {shortElement(item.path, left)} {{reason={item.reason}}}", item.doc))
	return "\n".join(lines) + "\n"


def mappingToJson(mapping: Mapping) -> dict[str, Any]:
	"""Export detached mapping data with qualified type, scope and imported call names."""
	data: dict[str, Any] = {"format": MAPPING_FORMAT, "from": mapping.fromNamespace, "to": mapping.toNamespace}
	if mapping.header:
		data["header"] = mapping.header
	if mapping.uses:
		data["uses"] = mapping.uses
	if mapping.functions:
		data["functions"] = functionsToJson(FunctionLibrary(mapping.fromNamespace, functions=mapping.functions))["functions"]
	if mapping.maps:
		data["maps"] = encodeOntology(normaliseOntology(Ontology(namespace=mapping.fromNamespace, decls=mapping.maps)), None)["decls"]
	if mapping.lookups:
		data["lookups"] = [{"owner": item.owner, "name": item.name, "type": item.type, **({"doc": item.doc} if item.doc is not None else {}),
			"lines": [{"attr": line.attr, "from": line.source, **({"doc": line.doc} if line.doc is not None else {})} for line in sorted(item.lines, key=lambda line: line.attr)]}
			for item in sorted(mapping.lookups, key=lambda item: (item.owner, item.name))]
	scopes = []
	for scope in sorted(mapping.scopes, key=lambda item: (item.source, item.target, item.name or "")):
		value = {"source": scope.source, "target": scope.target}
		for key in ("when", "ctx", "valid", "name", "present", "into", "doc"):
			if (member := getattr(scope, key)) is not None:
				value[key] = member
		lines = []
		for line in sorted(scope.lines, key=lineKey):
			entry = {key: getattr(line, key) for key in ("target", "facet", "verb", "expr", "when", "src", "doc") if getattr(line, key) is not None}
			entry.update({key: True for key in ("reverse", "candidate") if getattr(line, key)})
			if line.asType:
				entry["as"] = line.asType
			if line.name:
				entry["name"] = line.name
			if line.qualifiers:
				entry["qualifiers"] = line.qualifiers
			lines.append(entry)
		if lines:
			value["lines"] = lines
		scopes.append(value)
	data["scopes"] = scopes
	if mapping.exclusions:
		data["exclusions"] = [{"path": item.path, "reason": item.reason, **({"doc": item.doc} if item.doc is not None else {})} for item in sorted(mapping.exclusions, key=lambda item: item.path)]
	return deepcopy(data)


__all__ = ["printMapping", "mappingToJson"]

# EOF
