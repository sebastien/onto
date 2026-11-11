"""Module: functions.parser — function-library source parsing and strict JSON decoding."""

from __future__ import annotations

import re
from typing import Any

from ..observations.parser import _jsonObject, _jsonString, _jsonValue
from ..ontology.model import BUILTINS
from ..text import Diagnostics, Loc, Source, isName, isPath, parseAnnotations, parseArguments, scanUnquoted, sourceLines, splitAnnotations, splitDoc
from .model import FUNCTIONS_FORMAT, ExampleSource, Function, FunctionDeclaration, FunctionExample, FunctionLibrary, FunctionsDocument, SignatureType

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def _splitValues(text: str, separator: str) -> list[str]:
	parts = []
	start = 0
	depth = 0
	for index in scanUnquoted(text):
		char = text[index]
		if char == "[":
			depth += 1
		elif char == "]":
			depth -= 1
			if depth < 0:
				raise ValueError("Unexpected collection terminator")
		elif depth == 0 and text.startswith(separator, index):
			parts.append(text[start:index].strip())
			start = index + len(separator)
	if depth:
		raise ValueError("Unclosed collection")
	parts.append(text[start:].strip())
	if not all(parts):
		raise ValueError("An example needs nonempty arguments and a result")
	return parts


def _signature(text: str, namespace: str, uses: dict[str, str]) -> SignatureType:
	collection = text.endswith("*")
	name = text[:-1] if collection else text
	if name in BUILTINS:
		return SignatureType(builtin=name, collection=collection)
	if name == "any":
		raise ValueError("any and any* are reserved for built-ins; @fn signatures need concrete types")
	if not isPath(name):
		raise ValueError(f"Invalid signature type '{text}'")
	head, slash, rest = name.partition("/")
	path = f"{uses[head]}/{rest}" if slash and head in uses else f"{namespace}/{name}"
	return SignatureType(path=path, collection=collection)


def _functionAnnotations(text: str | None, loc: Loc, diag: Diagnostics) -> list[tuple[str, str | bool]]:
	pairs = parseAnnotations(text, loc, diag)
	for key, value in pairs:
		if key == "inverse" and isinstance(value, str) and isName(value):
			continue
		if key == "nulls" and value is True:
			continue
		diag.error("annotation", f"Invalid function annotation '{key}'", loc)
	return pairs


def _signatureFromJson(data: Any) -> SignatureType:
	value = _jsonObject(data, (), ("builtin", "path", "collection"))
	variants = set(value) & {"builtin", "path"}
	if len(variants) != 1 or "collection" in value and value["collection"] is not True:
		raise ValueError("Invalid signature type variant or collection flag")
	if "builtin" in value and value["builtin"] not in BUILTINS:
		raise ValueError("Unknown signature built-in")
	if "path" in value:
		_jsonString(value["path"], isPath)
	return SignatureType(**value)


def _readFunctionsJson(data: Any) -> FunctionLibrary:
	value = _jsonObject(data, ("format", "namespace", "functions"), ("header", "uses"))
	if value["format"] != FUNCTIONS_FORMAT:
		raise ValueError("Unknown function-library format")
	namespace = _jsonString(value["namespace"], isPath)
	header = _jsonObject(value.get("header", {}), (), ("rev",))
	for token in header.values():
		_jsonString(token)
	uses = value.get("uses", {})
	if not isinstance(uses, dict) or any(not isinstance(key, str) or not isName(key) for key in uses):
		raise ValueError("Invalid function-library aliases")
	for path in uses.values():
		_jsonString(path, isPath)
	if not isinstance(value["functions"], list) or not value["functions"]:
		raise ValueError("A function library needs declarations")
	functions = []
	for item in value["functions"]:
		item = _jsonObject(item, ("name", "args", "result", "examples"), ("ann", "doc"))
		name = _jsonString(item["name"], isName)
		if not isinstance(item["args"], list) or not item["args"]:
			raise ValueError("A function needs argument types")
		args = [_signatureFromJson(arg) for arg in item["args"]]
		result = _signatureFromJson(item["result"])
		ann = _jsonObject(item.get("ann", {}), (), ("inverse", "nulls"))
		if "inverse" in ann:
			_jsonString(ann["inverse"], isName)
		if "nulls" in ann and ann["nulls"] is not True:
			raise ValueError("nulls must be true")
		doc = item.get("doc")
		if "doc" in item and (not isinstance(doc, str) or not doc or "\n" in doc or "\r" in doc):
			raise ValueError("Invalid function doc string")
		if not isinstance(item["examples"], list) or not item["examples"]:
			raise ValueError("A function needs examples")
		examples = []
		for example in item["examples"]:
			example = _jsonObject(example, ("args", "result"))
			if not isinstance(example["args"], list) or not example["args"]:
				raise ValueError("An example needs arguments")
			examples.append(FunctionExample([_jsonValue(arg) for arg in example["args"]], _jsonValue(example["result"])))
		functions.append(Function(name, args, result, examples, list(ann.items()), doc))
	return FunctionLibrary(namespace, dict(header), dict(uses), functions)


def parseFunctionDeclaration(text: str, namespace: str, uses: dict[str, str], loc: Loc, diag: Diagnostics) -> FunctionDeclaration:
	"""Parse one library or local `@fn` header with the active namespace and aliases."""
	body, doc = splitDoc(text)
	body, annotations = splitAnnotations(body)
	match = re.fullmatch(r"@fn\s+([A-Z][A-Za-z0-9_]*)\s+(.+?)\s+->\s+(\S+)", body)
	if not match:
		raise ValueError("Invalid function declaration")
	name, args, result = match.groups()
	return FunctionDeclaration(name, [_signature(arg.strip(), namespace, uses) for arg in args.split(",")], _signature(result, namespace, uses),
		ann=_functionAnnotations(annotations, loc, diag), doc=doc, loc=loc)


def parseFunctionExample(text: str, loc: Loc) -> ExampleSource:
	"""Parse an example without choosing its signature-dependent value types."""
	body, doc = splitDoc(text)
	if doc is not None:
		raise ValueError("Example values containing '--' must be quoted")
	parts = _splitValues(body, "=>")
	if len(parts) != 2:
		raise ValueError("An example needs exactly one '=>' separator")
	return ExampleSource(_splitValues(parts[0], ","), parts[1], loc)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseFunctions(sources: list[Source]) -> FunctionsDocument:
	"""Parse files of one library, resolving signature aliases but not typing examples."""
	diag = Diagnostics()
	doc = FunctionsDocument("")
	names: set[str] = set()
	for source in sources:
		if "\r" in source.text:
			diag.error("lexical", "Function libraries require LF line endings", Loc(source.name, 0))
		lines = sourceLines(source)
		if not lines:
			diag.error("header", "Missing @functions header", Loc(source.name, 0))
			continue
		headerLine = lines[0]
		match = re.fullmatch(r"@functions\s+(\S+)(.*)", headerLine.text)
		if not match or not isPath(match[1]) or headerLine.indent:
			diag.error("header", "@functions must come first and name a namespace", headerLine.loc)
			continue
		namespace = match[1]
		header = dict(parseArguments(match[2], headerLine.loc, diag))
		if set(header) - {"rev"}:
			diag.error("header", "Only rev is allowed on @functions", headerLine.loc)
		if not doc.namespace:
			doc.namespace, doc.header = namespace, header
		elif doc.namespace != namespace or doc.header != header:
			diag.error("header", "Library files must share namespace and revision", headerLine.loc)
		uses: dict[str, str] = {}
		current = None
		for line in lines[1:]:
			if line.tabs or line.indent not in (0, 2):
				diag.error("indent", "Bodies require exactly two spaces", line.loc)
				continue
			body, docText = splitDoc(line.text)
			if line.indent:
				if current is None:
					diag.error("syntax", "Example outside a function declaration", line.loc)
					continue
				try:
					current.examples.append(parseFunctionExample(line.text, line.loc))
				except ValueError as error:
					diag.error("example", str(error), line.loc)
				continue
			current = None
			if match := re.fullmatch(r"@use\s+(\S+)\s+as\s+(\S+)", body):
				path, alias = match.groups()
				if not isPath(path) or not isName(alias) or docText is not None or alias in uses or alias in doc.uses and doc.uses[alias] != path:
					diag.error("alias", "Invalid or conflicting @use alias", line.loc)
				else:
					uses[alias] = doc.uses[alias] = path
				continue
			try:
				current = parseFunctionDeclaration(line.text, namespace, uses, line.loc, diag)
				if current.name in names:
					diag.error("duplicate", f"Duplicate function '{current.name}'", line.loc)
				names.add(current.name)
				doc.functions.append(current)
			except ValueError as error:
				diag.error("signature", str(error), line.loc)
	if not doc.functions:
		diag.error("function", "A library needs at least one function")
	for function in doc.functions:
		if not function.examples:
			diag.error("example", f"Function '{function.name}' needs examples", function.loc)
	doc.diagnostics = diag.check()
	return doc


__all__ = ["parseFunctions"]

# EOF
