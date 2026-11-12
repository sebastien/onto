"""Module: binding.parser — binding syntax, expression annotations and strict JSON decoding."""

from __future__ import annotations

import json
import re
from typing import Any

from ..expressions import Expression, expressionFromJson, parseExpression
from ..functions.model import FUNCTIONS_FORMAT, FunctionDeclaration
from ..functions.parser import _readFunctionsJson, _splitValues, parseFunctionDeclaration, parseFunctionExample
from ..observations.parser import _jsonObject, _jsonString
from ..text import Diagnostics, Loc, Source, isName, isPath, isToken, parseArguments, scanUnquoted, sourceLines, splitAnnotations, splitDoc
from .model import BINDING_FORMAT, HEADER_KEYS, Binding, BindingDocument, BindingExclusion, BindingLine, BindingScope, Condition

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def qualifyPath(name: str, namespace: str, uses: dict[str, str]) -> str:
	if not isPath(name):
		raise ValueError(f"Invalid ontology path '{name}'")
	head, slash, rest = name.partition("/")
	return f"{uses[head]}/{rest}" if slash and head in uses else f"{namespace}/{name}"


def bindingHeader(header: dict[str, str | int]) -> dict[str, str | int]:
	result = dict(header)
	for key, value in header.items():
		if key not in HEADER_KEYS:
			raise ValueError(f"Unknown binding header key '{key}'")
		if key == "confirm":
			if type(value) not in (int, str) or not re.fullmatch(r"[0-9]+", str(value)) or int(value) < 1:
				raise ValueError("confirm must be a positive integer")
			result[key] = int(value)
		elif not isinstance(value, str) or not isToken(value):
			raise ValueError(f"Invalid binding header value '{key}'")
		elif key == "format" and value not in ("json", "csv"):
			raise ValueError("format must be json or csv")
		elif key == "complete" and value not in ("document", "record", "none"):
			raise ValueError("complete must be document, record or none")
		elif key == "null" and value not in ("absent", "unknown"):
			raise ValueError("null must be absent or unknown")
		elif key == "retract" and not re.fullmatch(r"(?:100|[1-9]?[0-9])%", value):
			raise ValueError("retract must be an integer percentage from 0% to 100%")
	return result


def documentPath(text: str) -> Expression:
	expr = parseExpression(text, binding=True)
	if "path" not in expr:
		raise ValueError("A document path is required")
	return expr


def condition(text: str, *, binding: bool = True) -> Condition:
	for index in scanUnquoted(text):
		if text[index] == ":":
			path = parseExpression(text[:index].strip(), binding=binding)
			if "path" not in path:
				raise ValueError("A condition requires a path")
			value = text[index + 1:].strip()
			if not isToken(value):
				raise ValueError("A condition value must be a token")
			return {"path": path["path"], "value": value}
	raise ValueError("A condition requires path:value")


def annotationParts(text: str | None) -> list[str]:
	if text is None or not text.strip():
		return []
	# Annotation commas inside calls, strings or list steps do not end a value.
	depth = 0
	start = 0
	parts = []
	for index in scanUnquoted(text):
		char = text[index]
		if char in "([":
			depth += 1
		elif char in ")]":
			depth -= 1
			if depth < 0:
				raise ValueError("Unbalanced annotation expression")
		elif char == "," and depth == 0:
			parts.append(text[start:index].strip())
			start = index + 1
	if depth:
		raise ValueError("Unbalanced annotation expression")
	parts.append(text[start:].strip())
	return parts


def bindingAnnotations(text: str | None, allowed: tuple[str, ...]) -> dict[str, Any]:
	result = {}
	for part in annotationParts(text):
		key, separator, value = part.partition("=")
		key, value = key.strip(), value.strip()
		if not separator or key not in allowed or key in result:
			raise ValueError(f"Invalid or duplicate binding annotation '{key}'")
		if key in ("id", "valid", "ctx"):
			result[key] = parseExpression(value, binding=True, field=False)
		elif key in ("when", "deleted"):
			result[key] = condition(value)
		elif key == "null" and value in ("absent", "unknown") or key == "reason" and value in ("ignore", "out-of-scope"):
			result[key] = value
		else:
			raise ValueError(f"Invalid binding annotation value '{key}'")
	return result


def readDoc(value: dict[str, Any]) -> str | None:
	if "doc" not in value:
		return None
	doc = value["doc"]
	if not isinstance(doc, str) or not doc or "\r" in doc or "\n" in doc:
		raise ValueError("Invalid doc string")
	return doc


def readCondition(data: Any, *, binding: bool = True) -> Condition:
	value = _jsonObject(data, ("path", "value"))
	path = expressionFromJson({"path": value["path"]}, binding=binding)
	return {"path": path["path"], "value": _jsonString(value["value"])}


def readBindingJson(data: Any) -> Binding:
	value = _jsonObject(data, ("format", "ontology", "scopes"), ("header", "uses", "at", "columns", "functions", "exclusions"))
	if value["format"] != BINDING_FORMAT:
		raise ValueError("Unknown binding JSON format")
	namespace = _jsonString(value["ontology"], isPath)
	header = _jsonObject(value.get("header", {}), (), HEADER_KEYS)
	if "confirm" in header and type(header["confirm"]) is not int:
		raise ValueError("JSON confirm must be an integer")
	header = bindingHeader(header)
	uses = value.get("uses", {})
	if not isinstance(uses, dict) or any(not isinstance(alias, str) or not isName(alias) for alias in uses):
		raise ValueError("Invalid binding aliases")
	for path in uses.values():
		_jsonString(path, isPath)
	binding = Binding(namespace, header, dict(uses))
	if "at" in value:
		binding.at = expressionFromJson(value["at"], binding=True)
	if "columns" in value:
		if not isinstance(value["columns"], list) or not value["columns"] or any(not isinstance(column, str) for column in value["columns"]):
			raise ValueError("columns must be a nonempty string array")
		binding.columns = list(value["columns"])
	if "functions" in value:
		if not isinstance(value["functions"], list):
			raise ValueError("functions must be an array")
		if value["functions"]:
			binding.functions = _readFunctionsJson({"format": FUNCTIONS_FORMAT, "namespace": namespace, "uses": uses, "functions": value["functions"]}).functions
	if not isinstance(value["scopes"], list):
		raise ValueError("scopes must be an array")
	for item in value["scopes"]:
		item = _jsonObject(item, ("type", "path", "id"), ("valid", "ctx", "deleted", "doc", "lines"))
		path = expressionFromJson(item["path"], binding=True)
		if "path" not in path:
			raise ValueError("A scope requires a document path")
		scope = BindingScope(_jsonString(item["type"], isPath), path, expressionFromJson(item["id"], binding=True, field=False), doc=readDoc(item))
		for key in ("valid", "ctx"):
			if key in item:
				setattr(scope, key, expressionFromJson(item[key], binding=True, field=False))
		if "deleted" in item:
			scope.deleted = readCondition(item["deleted"])
		if not isinstance(item.get("lines", []), list):
			raise ValueError("Scope lines must be an array")
		for line in item.get("lines", []):
			if not isinstance(line, dict) or len(set(line) & {"target", "facet", "verb"}) != 1:
				raise ValueError("A binding line needs exactly one target kind")
			kind = next(key for key in ("target", "facet", "verb") if key in line)
			line = _jsonObject(line, (kind,) if kind == "facet" else (kind, "expr"), ("when", "doc") if kind == "facet" else ("when", "null", "doc"))
			name = _jsonString(line[kind], isName if kind == "facet" else lambda text: bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", text)))
			entry = BindingLine(**{kind: name}, doc=readDoc(line))
			if "expr" in line:
				entry.expr = expressionFromJson(line["expr"], binding=True)
			if "when" in line:
				entry.when = readCondition(line["when"])
			if "null" in line:
				if line["null"] not in ("absent", "unknown"):
					raise ValueError("Invalid null policy")
				entry.null = line["null"]
			scope.lines.append(entry)
		binding.scopes.append(scope)
	if not isinstance(value.get("exclusions", []), list):
		raise ValueError("exclusions must be an array")
	for item in value.get("exclusions", []):
		item = _jsonObject(item, ("path", "reason"), ("doc",))
		if item["reason"] not in ("ignore", "out-of-scope"):
			raise ValueError("Invalid exclusion reason")
		binding.exclusions.append(BindingExclusion(documentPath(_jsonString(item["path"], lambda text: bool(text))), item["reason"], readDoc(item)))
	return binding


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseBinding(source: Source) -> BindingDocument:
	"""Parse one binding file, retaining locations and unresolved local function examples."""
	diag = Diagnostics()
	if "\r" in source.text:
		diag.error("lexical", "Bindings require LF line endings", Loc(source.name, 0))
	lines = sourceLines(source)
	if not lines or lines[0].indent or not (match := re.fullmatch(r"@binding\s+(\S+)(.*)", lines[0].text)) or not isPath(match[1]):
		diag.error("header", "@binding must come first and name an ontology", Loc(source.name, 1))
		diag.check()
	doc = BindingDocument(match[1], loc=lines[0].loc)
	try:
		doc.header = bindingHeader(dict(parseArguments(match[2], lines[0].loc, diag)))
	except ValueError as error:
		diag.error("header", str(error), lines[0].loc)
	current: BindingScope | FunctionDeclaration | None = None
	functionNames: set[str] = set()
	for line in lines[1:]:
		try:
			if line.tabs or line.indent not in (0, 2):
				raise ValueError("Bodies require exactly two spaces")
			if line.indent and isinstance(current, FunctionDeclaration):
				current.examples.append(parseFunctionExample(line.text, line.loc))
				continue
			body, docText = splitDoc(line.text)
			body, annotations = splitAnnotations(body)
			if line.indent:
				if not isinstance(current, BindingScope):
					raise ValueError("Binding line outside a scope")
				if match := re.fullmatch(r"\[([A-Za-z_][A-Za-z0-9_]*)\]", body):
					entry = BindingLine(facet=match[1], **bindingAnnotations(annotations, ("when",)), doc=docText, loc=line.loc)
				else:
					parts = re.split(r"[ \t]+<-[ \t]+", body, maxsplit=1)
					if len(parts) != 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", parts[0]):
						raise ValueError("Invalid binding body line")
					entry = BindingLine(target=parts[0], expr=parseExpression(parts[1], binding=True), **bindingAnnotations(annotations, ("when", "null")), doc=docText, loc=line.loc)
				current.lines.append(entry)
				continue
			current = None
			if line.text.startswith("@fn ") or line.text.startswith("@fn\t"):
				current = parseFunctionDeclaration(line.text, doc.ontology, doc.uses, line.loc, diag)
				if current.name in functionNames:
					raise ValueError(f"Duplicate local function '{current.name}'")
				functionNames.add(current.name)
				doc.functions.append(current)
			elif match := re.fullmatch(r"@use\s+(\S+)\s+as\s+(\S+)", body):
				namespace, alias = match.groups()
				if not isPath(namespace) or not isName(alias) or alias in doc.uses or annotations is not None or docText is not None:
					raise ValueError("Invalid or duplicate binding alias")
				doc.uses[alias] = namespace
			elif match := re.fullmatch(r"@at[ \t]+<-[ \t]+(.+)", body):
				if doc.at is not None or annotations is not None or docText is not None:
					raise ValueError("Invalid or duplicate @at directive")
				doc.at = parseExpression(match[1], binding=True)
			elif match := re.fullmatch(r"@columns[ \t]+(.+)", body):
				if doc.columns is not None or annotations is not None or docText is not None:
					raise ValueError("Invalid or duplicate @columns directive")
				doc.columns = []
				for name in _splitValues(match[1], ","):
					column = json.loads(name) if name.startswith('"') else name
					if not isinstance(column, str) or not column or not (name.startswith('"') or isName(name)) or column in doc.columns:
						raise ValueError("Invalid or duplicate CSV column")
					doc.columns.append(column)
			elif body.startswith("- "):
				ann = bindingAnnotations(annotations, ("reason",))
				if "reason" not in ann:
					raise ValueError("An exclusion requires reason")
				doc.exclusions.append(BindingExclusion(documentPath(body[2:]), ann["reason"], docText, line.loc))
			else:
				parts = re.split(r"[ \t]+<-[ \t]+", body, maxsplit=1)
				if len(parts) != 2:
					raise ValueError("Invalid binding scope or directive")
				ann = bindingAnnotations(annotations, ("id", "valid", "ctx", "deleted"))
				if "id" not in ann:
					raise ValueError("A binding scope requires id")
				current = BindingScope(qualifyPath(parts[0], doc.ontology, doc.uses), documentPath(parts[1]), **ann, doc=docText, loc=line.loc)
				doc.scopes.append(current)
		except ValueError as error:
			diag.error("binding", str(error), line.loc)
	for function in doc.functions:
		if not function.examples:
			diag.error("example", f"Function '{function.name}' needs examples", function.loc)
	doc.diagnostics = diag.check()
	return doc


__all__ = ["parseBinding"]

# EOF
