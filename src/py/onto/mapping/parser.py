"""Module: mapping.parser — mapping source declarations and strict JSON decoding."""

from __future__ import annotations

import re
from typing import Any

from ..binding.parser import annotationParts, bindingHeader, condition, qualifyPath, readCondition, readDoc
from ..expressions import expressionFromJson, parseExpression
from ..functions.model import FUNCTIONS_FORMAT, FunctionDeclaration
from ..functions.parser import _readFunctionsJson, parseFunctionDeclaration, parseFunctionExample
from ..observations.parser import _jsonObject, _jsonString
from ..ontology.model import Decl, RE_ATTR_PATH, RE_MAP, RE_VIEW_ARROW
from ..ontology.parser import _Context, _declFromJson, _parseMapLine
from ..text import Diagnostics, Loc, Source, isName, isPath, isToken, parseAnnotations, parseArguments, sourceLines, splitAnnotations, splitDoc
from .model import HEADER_KEYS, MAPPING_FORMAT, Mapping, MappingDocument, MappingExclusion, MappingLine, MappingScope

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def mappingHeader(header: dict[str, Any]) -> dict[str, str | int | bool]:
	result = {}
	for key, value in header.items():
		if key not in HEADER_KEYS:
			raise ValueError(f"Unknown mapping header key '{key}'")
		if key == "candidates":
			if type(value) is bool:
				result[key] = value
			elif value in ("true", "false"):
				result[key] = value == "true"
			else:
				raise ValueError("candidates must be true or false")
		elif key in ("confirm", "retract", "scope"):
			result.update(bindingHeader({key: value}))
		elif not isinstance(value, str) or not (isPath(value) if key in ("view", "referential") else isToken(value)):
			raise ValueError(f"Invalid mapping header value '{key}'")
		else:
			result[key] = value
	return result


def mappingAnnotations(text: str | None, allowed: tuple[str, ...]) -> dict[str, Any]:
	result = {}
	for part in annotationParts(text):
		key, separator, value = part.partition("=")
		key, value = key.strip(), value.strip()
		if key not in allowed or key in result:
			raise ValueError(f"Invalid or duplicate mapping annotation '{key}'")
		if key in ("reverse", "candidate"):
			if separator:
				raise ValueError(f"'{key}' is a flag")
			result[key] = True
		elif not separator:
			raise ValueError(f"'{key}' requires a value")
		elif key in ("ctx", "valid"):
			result[key] = parseExpression(value)
		elif key == "when":
			result[key] = condition(value, binding=False)
		elif key == "src" and RE_ATTR_PATH.fullmatch(value):
			result[key] = value
		elif key == "reason" and value in ("ignore", "out-of-scope"):
			result[key] = value
		else:
			raise ValueError(f"Invalid mapping annotation value '{key}'")
	return result


def elementPath(text: str, namespace: str, uses: dict[str, str]) -> str:
	if match := RE_VIEW_ARROW.fullmatch(text):
		left, verb, right = match.groups()
		return f"{qualifyPath(left, namespace, uses)}.{verb}.{qualifyPath(right, namespace, uses)}"
	if match := re.fullmatch(r"([^\[\]]+)\[([A-Za-z_][A-Za-z0-9_]*)\]", text):
		return qualifyPath(match[1], namespace, uses) + f"[{match[2]}]"
	owner, dot, member = text.partition(".")
	if dot and not RE_ATTR_PATH.fullmatch(member):
		raise ValueError("Invalid excluded source member path")
	return qualifyPath(owner, namespace, uses) + (dot + member if dot else "")


def readMappingJson(data: Any) -> Mapping:
	value = _jsonObject(data, ("format", "from", "to", "scopes"), ("header", "uses", "functions", "maps", "exclusions"))
	if value["format"] != MAPPING_FORMAT:
		raise ValueError("Unknown mapping JSON format")
	fromNamespace, toNamespace = _jsonString(value["from"], isPath), _jsonString(value["to"], isPath)
	header = _jsonObject(value.get("header", {}), (), HEADER_KEYS)
	if "confirm" in header and type(header["confirm"]) is not int or "candidates" in header and type(header["candidates"]) is not bool:
		raise ValueError("JSON confirm/candidates must be an integer/boolean")
	uses = value.get("uses", {})
	if not isinstance(uses, dict) or any(not isinstance(alias, str) or not isName(alias) for alias in uses):
		raise ValueError("Invalid mapping aliases")
	for namespace in uses.values():
		_jsonString(namespace, isPath)
	mapping = Mapping(fromNamespace, toNamespace, mappingHeader(header), dict(uses))
	if "functions" in value:
		if not isinstance(value["functions"], list):
			raise ValueError("functions must be an array")
		if value["functions"]:
			mapping.functions = _readFunctionsJson({"format": FUNCTIONS_FORMAT, "namespace": fromNamespace, "uses": uses, "functions": value["functions"]}).functions
	if not isinstance(value.get("maps", []), list):
		raise ValueError("maps must be an array")
	for item in value.get("maps", []):
		if not isinstance(item, dict) or item.get("kind") != "map":
			raise ValueError("Only vocabulary maps belong in maps")
		decl = _declFromJson(item, "local map")
		readDoc(item)
		for line in item["lines"]:
			readDoc(line)
		mapping.maps.append(decl)
	if not isinstance(value["scopes"], list):
		raise ValueError("scopes must be an array")
	for item in value["scopes"]:
		item = _jsonObject(item, ("source", "target"), ("when", "ctx", "valid", "doc", "lines"))
		scope = MappingScope(_jsonString(item["source"], isPath), _jsonString(item["target"], isPath), doc=readDoc(item))
		if "when" in item:
			scope.when = readCondition(item["when"], binding=False)
		for key in ("ctx", "valid"):
			if key in item:
				setattr(scope, key, expressionFromJson(item[key]))
		if not isinstance(item.get("lines", []), list):
			raise ValueError("Mapping lines must be an array")
		for line in item.get("lines", []):
			if not isinstance(line, dict) or len(set(line) & {"target", "facet", "verb"}) != 1:
				raise ValueError("A mapping line requires one target kind")
			kind = next(key for key in ("target", "facet", "verb") if key in line)
			line = _jsonObject(line, (kind,) if kind == "facet" else (kind, "expr"), ("when", "candidate", "doc") if kind == "facet" else ("when", "src", "reverse", "candidate", "doc"))
			name = _jsonString(line[kind], isName if kind == "facet" else lambda text: bool(RE_ATTR_PATH.fullmatch(text)))
			entry = MappingLine(**{kind: name}, doc=readDoc(line))
			if "expr" in line:
				entry.expr = expressionFromJson(line["expr"])
			if "when" in line:
				entry.when = readCondition(line["when"], binding=False)
			if "src" in line:
				entry.src = _jsonString(line["src"], lambda text: bool(RE_ATTR_PATH.fullmatch(text)))
			for key in ("reverse", "candidate"):
				if key in line:
					if line[key] is not True:
						raise ValueError(f"'{key}' must be true when present")
					setattr(entry, key, True)
			scope.lines.append(entry)
		mapping.scopes.append(scope)
	if not isinstance(value.get("exclusions", []), list):
		raise ValueError("exclusions must be an array")
	for item in value.get("exclusions", []):
		item = _jsonObject(item, ("path", "reason"), ("doc",))
		if item["reason"] not in ("ignore", "out-of-scope"):
			raise ValueError("Invalid mapping exclusion reason")
		mapping.exclusions.append(MappingExclusion(_jsonString(item["path"], lambda text: bool(text)), item["reason"], readDoc(item)))
	return mapping


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseMapping(source: Source) -> MappingDocument:
	"""Parse one mapping, resolving source/target signature paths but not ontology members."""
	diag = Diagnostics()
	if "\r" in source.text:
		diag.error("lexical", "Mappings require LF line endings", Loc(source.name, 0))
	lines = sourceLines(source)
	if not lines or lines[0].indent or not (match := re.fullmatch(r"@mapping\s+(\S+)\s+->\s+(\S+)(.*)", lines[0].text)) or not all(isPath(name) for name in match.groups()[:2]):
		diag.error("header", "@mapping must come first and name its two ontologies", Loc(source.name, 1))
		diag.check()
	doc = MappingDocument(match[1], match[2], loc=lines[0].loc)
	try:
		doc.header = mappingHeader(dict(parseArguments(match[3], lines[0].loc, diag)))
	except ValueError as error:
		diag.error("header", str(error), lines[0].loc)
	current: MappingScope | FunctionDeclaration | Decl | None = None
	names: set[str] = set()
	for line in lines[1:]:
		try:
			if line.tabs or line.indent not in (0, 2):
				raise ValueError("Bodies require exactly two spaces")
			if line.indent and isinstance(current, FunctionDeclaration):
				current.examples.append(parseFunctionExample(line.text, line.loc))
				continue
			if line.indent and isinstance(current, Decl):
				if value := _parseMapLine(line, _Context(diag)):
					current.mapLines.append(value)
				continue
			body, docText = splitDoc(line.text)
			body, annotations = splitAnnotations(body)
			if line.indent:
				if not isinstance(current, MappingScope):
					raise ValueError("Mapping line outside a scope")
				if match := re.fullmatch(r"\[([A-Za-z_][A-Za-z0-9_]*)\]", body):
					entry = MappingLine(facet=match[1], **mappingAnnotations(annotations, ("when", "candidate")), doc=docText, loc=line.loc)
				else:
					parts = re.split(r"[ \t]+<-[ \t]+", body, maxsplit=1)
					if len(parts) != 2 or not RE_ATTR_PATH.fullmatch(parts[0]):
						raise ValueError("Invalid mapping assignment")
					entry = MappingLine(target=parts[0], expr=parseExpression(parts[1]), **mappingAnnotations(annotations, ("when", "src", "reverse", "candidate")), doc=docText, loc=line.loc)
				current.lines.append(entry)
				continue
			current = None
			if line.text.startswith(("@fn ", "@fn\t")):
				current = parseFunctionDeclaration(line.text, doc.fromNamespace, doc.uses, line.loc, diag)
				name = current.name
				if name in names:
					raise ValueError(f"Duplicate local function/map '{name}'")
				names.add(name)
				doc.functions.append(current)
			elif match := RE_MAP.fullmatch(body):
				name, left, right = match.groups()
				if not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name) or name in names:
					raise ValueError(f"Invalid or duplicate local map '{name}'")
				names.add(name)
				current = Decl("map", name, ann=parseAnnotations(annotations, line.loc, diag), doc=docText, loc=line.loc,
					mapFrom=qualifyPath(left, doc.fromNamespace, doc.uses), mapTo=qualifyPath(right, doc.toNamespace, doc.uses))
				doc.maps.append(current)
			elif match := re.fullmatch(r"@use\s+(\S+)\s+as\s+(\S+)", body):
				namespace, alias = match.groups()
				if not isPath(namespace) or not isName(alias) or alias in doc.uses or annotations is not None or docText is not None:
					raise ValueError("Invalid or duplicate mapping alias")
				doc.uses[alias] = namespace
			elif body.startswith("- "):
				ann = mappingAnnotations(annotations, ("reason",))
				if "reason" not in ann:
					raise ValueError("An exclusion requires reason")
				doc.exclusions.append(MappingExclusion(elementPath(body[2:], doc.fromNamespace, doc.uses), ann["reason"], docText, line.loc))
			else:
				parts = re.split(r"[ \t]+->[ \t]+", body)
				if len(parts) != 2:
					raise ValueError("Invalid mapping scope or directive")
				current = MappingScope(qualifyPath(parts[0], doc.fromNamespace, doc.uses), qualifyPath(parts[1], doc.toNamespace, doc.uses),
					**mappingAnnotations(annotations, ("when", "ctx", "valid")), doc=docText, loc=line.loc)
				doc.scopes.append(current)
		except ValueError as error:
			diag.error("mapping", str(error), line.loc)
	for function in doc.functions:
		if not function.examples:
			diag.error("example", f"Function '{function.name}' needs examples", function.loc)
	doc.diagnostics = diag.check()
	return doc


__all__ = ["parseMapping"]

# EOF
