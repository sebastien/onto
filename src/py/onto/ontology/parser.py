"""Module: ontology.parser — source parsing and structural ontology JSON decoding."""

from __future__ import annotations

from collections.abc import Callable
import re
from dataclasses import (
	dataclass,
	field,
)
from typing import (
	Any,
)
from ..text import (
	Annotations,
	Diagnostics,
	Line,
	Loc,
	Source,
	annotation,
	isName,
	isPath,
	lastSegment,
	parseAnnotations,
	parseArguments,
	sourceLines,
	splitAnnotations,
	splitDoc,
)
from .model import (
	Arrow,
	Attr,
	BUILTINS,
	CARDS,
	DECL_MEMBERS,
	Decl,
	Dep,
	HEADER_DEFAULTS,
	HEADER_KEYS,
	LAYERINGS,
	MATCHES,
	MapLine,
	ONTOLOGY_FORMAT,
	Ontology,
	PATH_KEYS,
	QUALIFIERS,
	Participant,
	RE_ARROW_DECL,
	RE_ATTRIBUTE,
	RE_ATTR_PATH,
	RE_COUNTS,
	RE_DOMAIN,
	RE_ENTITY_DECL,
	RE_FACET_DECL,
	RE_INPUT,
	RE_MAP,
	RE_MAP_LINE,
	RE_ONTOLOGY,
	RE_PARTICIPANT,
	RE_RELATION_DECL,
	RE_TYPE_DECL,
	RE_USE,
	RE_VIEW,
	RE_VIEW_ARROW,
	RE_VIEW_LINE,
	ViewInput,
	STATUSES,
	TypeExpr,
	ViewLine,
	ViewPopulation,
	arrowPath,
)

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class OntologyParseContext:
	"""Per-file parsing state: namespace and aliases."""

	diag: Diagnostics
	namespace: str | None = None
	aliases: dict[str, str] = field(default_factory=dict)

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def effectiveHeader(header: list[tuple[str, str]]) -> dict[str, str]:
	return HEADER_DEFAULTS | dict(header)


def resolvePath(name: str, ctx: OntologyParseContext, loc: Loc | None) -> str | None:
	if not isPath(name):
		ctx.diag.error("name", f"Invalid name '{name}'", loc)
		return None
	head, slash, rest = name.partition("/")
	if slash and head in ctx.aliases:
		return f"{ctx.aliases[head]}/{rest}"
	return f"{ctx.namespace}/{name}"


def resolveDeclared(name: str, ctx: OntologyParseContext, loc: Loc | None) -> str | None:
	if name in BUILTINS:
		ctx.diag.error("reserved", f"'{name}' is a built-in type and cannot be declared", loc)
		return None
	return resolvePath(name, ctx, loc)


def parseAnn(text: str | None, ctx: OntologyParseContext, loc: Loc | None) -> Annotations:
	pairs: Annotations = []
	for key, value in parseAnnotations(text, loc, ctx.diag):
		if key in PATH_KEYS and isinstance(value, str):
			value = resolvePath(value, ctx, loc) or value
		elif key in QUALIFIERS and isinstance(value, str) and value.startswith("?:"):
			value = "?:" + (resolvePath(value[2:], ctx, loc) or value[2:])
		pairs.append((key, value))
	return pairs


def parseTypeExpr(text: str, ctx: OntologyParseContext, loc: Loc | None, hierarchical: bool = False) -> TypeExpr | None:
	value = re.sub(r"\s*\|\s*", "|", text.strip())
	if not value:
		return None
	if value == "...":
		return TypeExpr(unknown=True)
	if value.startswith("Range<") and value.endswith(">"):
		element = parseTypeExpr(value[6:-1], ctx, loc)
		if element and (element.builtin or element.path) and not element.range:
			return TypeExpr(range=element)
		ctx.diag.error("range", f"Range<T> takes a built-in or a named type: '{text}'", loc)
		return None
	if "|" in value:
		parts = value.split("|")
		if parts[0] == "":
			parts = parts[1:]
		isOpen = parts[-1] == "..."
		if isOpen:
			parts = parts[:-1]
		if not parts or not all((isPath if hierarchical else isName)(part) for part in parts):
			ctx.diag.error("vocabulary", f"Invalid vocabulary '{text}'", loc)
			return None
		if len(set(parts)) != len(parts):
			ctx.diag.error("vocabulary", f"Duplicate vocabulary value in '{text}'", loc)
		return TypeExpr(values=parts, open=isOpen)
	if re.search(r"\s", value):
		ctx.diag.error("syntax", f"Invalid type '{text}'", loc)
		return None
	if value in BUILTINS:
		return TypeExpr(builtin=value)
	owner, dot, attrPath = value.partition(".")
	if dot:
		if not RE_ATTR_PATH.fullmatch(attrPath):
			ctx.diag.error("syntax", f"Invalid attribute reference '{value}'", loc)
			return None
		path = resolvePath(owner, ctx, loc)
		return TypeExpr(path=path, attr=attrPath) if path else None
	path = resolvePath(value, ctx, loc)
	return TypeExpr(path=path) if path else None


def parseDeps(text: str, ctx: OntologyParseContext, loc: Loc | None) -> list[Dep]:
	deps: list[Dep] = []
	parts = [part.strip() for part in text.split(",")]
	for index, part in enumerate(parts):
		if part == "...":
			if index != len(parts) - 1:
				ctx.diag.error("derived", "'...' must be the last dependency", loc)
			deps.append(Dep(ellipsis=True))
		elif RE_INPUT.fullmatch(part):
			deps.append(Dep(input=part[1:]))
		elif isName(part):
			deps.append(Dep(local=part))
		else:
			ref = parseTypeExpr(part, ctx, loc)
			if ref and ref.attr:
				deps.append(Dep(path=ref.path, attr=ref.attr))
			else:
				ctx.diag.error("derived", f"Invalid dependency '{part}'", loc)
	if not deps:
		ctx.diag.error("derived", "Empty dependency list", loc)
	return deps


def parseAttribute(line: Line, ctx: OntologyParseContext) -> Attr | None:
	withAnnotations, doc = splitDoc(line.text)
	text, annotationText = splitAnnotations(withAnnotations)
	ann = parseAnn(annotationText, ctx, line.loc)
	match = RE_ATTRIBUTE.fullmatch(text)
	if not match:
		ctx.diag.error("syntax", f"Invalid attribute '{line.text}'", line.loc)
		return None
	card, derived, name, rest = match.group(1), match.group(2), match.group(3), match.group(4) or ""
	arrow = rest.find("<-")
	typeText = (rest if arrow < 0 else rest[:arrow]).strip()
	depsText = None if arrow < 0 else rest[arrow + 2 :].strip()
	if derived and depsText is None:
		ctx.diag.error("derived", f"Derived attribute '{name}' requires '<-' dependencies", line.loc)
	if not derived and depsText is not None:
		ctx.diag.error("derived", f"Only derived attributes (~) have dependencies: '{name}'", line.loc)
	return Attr(
		name=name,
		card=card,
		derived=bool(derived),
		type=parseTypeExpr(typeText, ctx, line.loc, annotation(ann, "hierarchical") is True),
		deps=None if depsText is None else parseDeps(depsText, ctx, line.loc),
		ann=ann,
		doc=doc,
		loc=line.loc,
	)


def parseViewLine(line: Line, ctx: OntologyParseContext) -> ViewLine | None:
	if match := RE_VIEW_ARROW.fullmatch(line.text):
		subject = resolvePath(match.group(1), ctx, line.loc)
		obj = resolvePath(match.group(3), ctx, line.loc)
		return ViewLine(path=arrowPath(subject, match.group(2), obj), loc=line.loc) if subject and obj else None
	match = RE_VIEW_LINE.fullmatch(line.text)
	if not match:
		ctx.diag.error("syntax", f"Invalid view line '{line.text}'", line.loc)
		return None
	path = resolvePath(match.group(1), ctx, line.loc)
	if not path:
		return None
	facets: str | list[str] | None = None
	if match.group(2) is not None:
		if match.group(2).strip() == "*":
			facets = "*"
		else:
			facets = [item.strip() for item in match.group(2).split(",")]
			if not all(isName(name) for name in facets) or len(set(facets)) != len(facets):
				ctx.diag.error("syntax", f"Invalid facet list in '{line.text}'", line.loc)
	return ViewLine(path=path, facets=facets, member=match.group(3), loc=line.loc)


def parseRootedLine(decl: Decl, line: Line, ctx: OntologyParseContext) -> None:
	"""Parse a typed population or a projection on one. Names are local to this view."""
	name = r"[A-Za-z_][A-Za-z0-9_]*"
	member = rf"{name}(?:\.{name})*"
	if found := re.fullmatch(rf"({name}):\s*(\S+)(?:\s*=\s*({name})\s+(->|<-)\s+({member})"
		rf"(?:\s+through\s+({name}))?(?:\s+where\s+({member})=(@?[\w/]+))?)?", line.text, re.ASCII):
		alias, typeName, parent, direction, via, through, where, value = found.groups()
		if path := resolvePath(typeName, ctx, line.loc):
			decl.viewPopulations.append(ViewPopulation(alias, path, parent or "", via or "", direction == "<-", through or "",
				where or "", {"true": True, "false": False}.get(value, value)))
	elif found := re.fullmatch(rf"(\?\s+)?({name})\.({member})(?:\s*:\s*(\S+))?", line.text):
		if not decl.viewPopulations:
			ctx.diag.error("view", "The first body line of a rooted view must declare its target root", line.loc)
			return
		optional, alias, key, target = found.groups()
		decl.viewLines.append(ViewLine(alias, member=key, optional=bool(optional), loc=line.loc,
			target=resolvePath(target, ctx, line.loc) if target else None))
	else:
		ctx.diag.error("syntax", f"Invalid rooted view line '{line.text}'", line.loc)


def parseMapLine(line: Line, ctx: OntologyParseContext) -> MapLine | None:
	text, doc = splitDoc(line.text)
	match = RE_MAP_LINE.fullmatch(text)
	if not match or match.group(2) not in MATCHES:
		ctx.diag.error("syntax", f"Invalid map line '{line.text}' (Value exact|broader|narrower|related Value)", line.loc)
		return None
	return MapLine(fromValue=match.group(1), match=match.group(2), toValue=match.group(3), doc=doc, loc=line.loc)


def parseDeclaration(line: Line, ctx: OntologyParseContext) -> Decl | None:
	loc = line.loc
	withAnnotations, doc = splitDoc(line.text)
	text, annotationText = splitAnnotations(withAnnotations)
	ann = parseAnn(annotationText, ctx, loc)
	if match := RE_TYPE_DECL.fullmatch(text):
		path = resolveDeclared(match.group(1), ctx, loc)
		if not path:
			return None
		return Decl(kind="type", path=path, definition=parseTypeExpr(match.group(2), ctx, loc, annotation(ann, "hierarchical") is True), ann=ann, doc=doc, loc=loc)
	if match := RE_FACET_DECL.fullmatch(text):
		path = resolveDeclared(match.group(1), ctx, loc)
		subject = resolvePath(match.group(2), ctx, loc)
		if not path or not subject:
			return None
		return Decl(kind="facet", path=path, subject=subject, ann=ann, doc=doc, loc=loc)
	if match := RE_ARROW_DECL.fullmatch(text):
		subjectName, verb, inverse, objectName, counts = match.groups()
		subject = resolvePath(subjectName, ctx, loc)
		obj = resolvePath(objectName, ctx, loc)
		if not subject or not obj:
			return None
		for name in (verb, inverse):
			if name and not name[0].islower():
				ctx.diag.error("name", f"Relation verb '{name}' must be lowerCamel", loc)
		if counts is not None and not RE_COUNTS.fullmatch(counts):
			ctx.diag.error("syntax", f"Invalid relation counts '{counts}'", loc)
		same = lastSegment(subject) == lastSegment(obj)
		participants = [
			Participant("Subject" if same else lastSegment(subject), None, subject),
			Participant("Object" if same else lastSegment(obj), None, obj),
		]
		return Decl(
			kind="relation", path=arrowPath(subject, verb, obj), participants=participants,
			arrow=Arrow(verb, inverse, counts), ann=ann, doc=doc, loc=loc,
		)
	if match := RE_RELATION_DECL.fullmatch(text):
		path = resolveDeclared(match.group(1), ctx, loc)
		if not path:
			return None
		participants: list[Participant] = []
		for part in (item.strip() for item in match.group(2).split(",")):
			found = RE_PARTICIPANT.fullmatch(part)
			if not found:
				ctx.diag.error("syntax", f"Invalid participant '{part}'", loc)
				continue
			typePath = resolvePath(found.group(3), ctx, loc)
			if typePath:
				participants.append(Participant(found.group(1) or lastSegment(typePath), found.group(2), typePath))
		return Decl(kind="relation", path=path, participants=participants, ann=ann, doc=doc, loc=loc)
	if match := RE_ENTITY_DECL.fullmatch(text):
		path = resolveDeclared(match.group(1), ctx, loc)
		base = resolvePath(match.group(2), ctx, loc) if match.group(2) else None
		if not path or (match.group(2) and not base):
			return None
		return Decl(kind="entity", path=path, base=base, ann=ann, doc=doc, loc=loc)
	ctx.diag.error("syntax", f"Unrecognised declaration '{line.text}'", loc)
	return None


def bodyParser(decl: Decl, ctx: OntologyParseContext) -> Callable[[Line], None]:
	tree = decl.kind == "type" and annotation(decl.ann, "hierarchical") is True and decl.definition is None
	parents: list[str] = []
	nodes: set[str] = set()
	if tree:
		decl.definition = TypeExpr(values=[])

	def parseNode(line: Line) -> None:
		definition = decl.definition
		depth = line.indent // 2
		if line.indent % 2 or depth > len(parents) + 1:
			ctx.diag.error("indent", "Taxonomy indentation must increase by exactly two spaces", line.loc)
			return
		if definition.open:
			ctx.diag.error("vocabulary", "'...' must be the final taxonomy line", line.loc)
			return
		if line.text == "..." and depth == 1:
			definition.open = True
			return
		if not isName(line.text):
			ctx.diag.error("vocabulary", "A taxonomy tree line must contain one name", line.loc)
			return
		parents[depth - 1:] = [line.text]
		path = "/".join(parents)
		if path in nodes:
			ctx.diag.error("vocabulary", f"Duplicate vocabulary value '{path}'", line.loc)
		nodes.add(path)
		definition.values.append(path)

	def parseField(line: Line) -> None:
		if decl.definition is not None:
			ctx.diag.error("syntax", "Only structures (`T =` with no right side) have a body", line.loc)
			return
		attr = parseAttribute(line, ctx)
		if attr:
			decl.fields = (decl.fields or []) + [attr]

	def parseAttr(line: Line) -> None:
		attr = parseAttribute(line, ctx)
		if attr:
			decl.attrs.append(attr)

	return parseNode if tree else parseField if decl.kind == "type" else parseAttr


def parseDirective(line: Line, position: int, ctx: OntologyParseContext, ontology: Ontology, seen: dict[str, Decl]) -> Callable[[Line], None] | None:
	loc, diag = line.loc, ctx.diag
	text, doc = splitDoc(line.text)

	def declare(decl: Decl) -> bool:
		if decl.path in seen:
			diag.error("duplicate", f"Duplicate declaration '{decl.path}'", loc)
			return False
		seen[decl.path] = decl
		ontology.decls.append(decl)
		return True

	if match := RE_ONTOLOGY.fullmatch(text):
		if position != 0:
			diag.error("header", "@ontology must be the first line", loc)
			return None
		namespace, rest = match.groups()
		if not isPath(namespace):
			diag.error("name", f"Invalid namespace '{namespace}'", loc)
		header = parseArguments(rest, loc, diag)
		for key, value in header:
			if key not in HEADER_KEYS:
				diag.error("header", f"Unknown @ontology key '{key}'", loc)
			elif key == "card" and value not in CARDS:
				diag.error("header", f"Invalid default cardinality '{value}'", loc)
			elif key == "cards" and value not in STATUSES:
				diag.error("header", f"Invalid cards status '{value}'", loc)
			elif key == "rel" and not RE_COUNTS.fullmatch(value):
				diag.error("header", f"Invalid relation counts '{value}'", loc)
			elif key == "layering" and value not in LAYERINGS:
				diag.error("header", f"Invalid layering '{value}'", loc)
		ctx.namespace = namespace
		if ontology.namespace is None:
			ontology.namespace, ontology.header = namespace, header
		elif ontology.namespace != namespace or dict(header).get("rev") != dict(ontology.header).get("rev"):
			diag.error("header", "All files of an ontology must have the same @ontology namespace and rev", loc)
		elif effectiveHeader(header) != effectiveHeader(ontology.header):
			# NOTE: Defaults are not per file: one normal form must print every declaration with one header.
			diag.error("header", "All files of an ontology must have the same @ontology defaults", loc)
		return None
	if match := RE_USE.fullmatch(text):
		namespace, alias = match.groups()
		if not isPath(namespace) or not isName(alias):
			diag.error("name", f"Invalid @use '{text}'", loc)
			return None
		if alias in ctx.aliases:
			diag.error("duplicate", f"Duplicate alias '{alias}'", loc)
			return None
		ctx.aliases[alias] = namespace
		existing = next((target for name, target in ontology.uses if name == alias), None)
		if existing is not None and existing != namespace:
			diag.error("alias", f"Alias '{alias}' means different namespaces across files", loc)
		if existing is None:
			ontology.uses.append((alias, namespace))
		return None
	if match := RE_VIEW.fullmatch(text):
		path = resolvePath(match.group(1), ctx, loc)
		if not path:
			return None
		param = None
		if match.group(2):
			owner = resolvePath(match.group(3), ctx, loc)
			if not owner:
				return None
			param = ViewInput(match.group(2), owner, match.group(4))
		decl = Decl(kind="view", path=path, doc=doc, loc=loc, viewInput=param)
		if not declare(decl):
			return None

		def parseView(body: Line) -> None:
			if decl.viewInput:
				parseRootedLine(decl, body, ctx)
				return
			viewLine = parseViewLine(body, ctx)
			if viewLine:
				decl.viewLines.append(viewLine)

		return parseView
	if text.split(maxsplit=1)[0] == "@view":
		diag.error("view", "Expected @view Name or @view Name(argument: Entity.Attribute) naming a source {key}", loc)
		return None
	if match := RE_DOMAIN.fullmatch(text):
		if not isName(match.group(1)):
			diag.error("name", f"Invalid domain name '{match.group(1)}'", loc)
			return None
		declare(Decl(kind="domain", path=f"{ctx.namespace}/{match.group(1)}", doc=doc, loc=loc))
		return None
	if text.startswith("@map ") or text.startswith("@map\t"):
		head, annotationText = splitAnnotations(text)
		match = RE_MAP.fullmatch(head)
		if not match:
			diag.error("syntax", f"Invalid @map '{text}'", loc)
			return None
		path, mapFrom, mapTo = (resolvePath(name, ctx, loc) for name in match.groups())
		if not path or not mapFrom or not mapTo:
			return None
		mapDecl = Decl(kind="map", path=path, mapFrom=mapFrom, mapTo=mapTo, ann=parseAnn(annotationText, ctx, loc), doc=doc, loc=loc)
		if not declare(mapDecl):
			return None

		def parseMap(body: Line) -> None:
			mapLine = parseMapLine(body, ctx)
			if mapLine:
				mapDecl.mapLines.append(mapLine)

		return parseMap
	diag.error("directive", f"Unknown directive '{text.split()[0]}'", loc)
	return None


def parseFile(source: Source, ontology: Ontology, seen: dict[str, Decl], diag: Diagnostics) -> None:
	ctx = OntologyParseContext(diag)
	current = None
	currentTree = False
	if "\r" in source.text:
		diag.error("syntax", "Line endings must be LF", Loc(source.name, source.text[: source.text.index("\r")].count("\n") + 1))
	for position, line in enumerate(sourceLines(source)):
		if line.tabs:
			diag.error("indent", "Tabs are not allowed in indentation", line.loc)
			continue
		if position == 0 and not line.text.startswith("@ontology"):
			diag.error("header", "File must start with @ontology", line.loc)
			continue
		if line.indent == 2 or (line.indent > 0 and currentTree):
			if current is None:
				diag.error("indent", "Body line without a declaration that accepts one", line.loc)
			else:
				current(line)
			continue
		current = None
		currentTree = False
		if line.indent != 0:
			diag.error("indent", "Body lines are indented by exactly two spaces", line.loc)
			continue
		if line.text.startswith("@"):
			current = parseDirective(line, position, ctx, ontology, seen)
			continue
		decl = parseDeclaration(line, ctx)
		if not decl:
			continue
		if decl.path in seen:
			diag.error("duplicate", f"Duplicate declaration '{decl.path}'", line.loc)
			continue
		seen[decl.path] = decl
		ontology.decls.append(decl)
		current = bodyParser(decl, ctx)
		currentTree = decl.kind == "type" and annotation(decl.ann, "hierarchical") is True


# -----------------------------------------------------------------------------
#
# JSON DECODING
#
# -----------------------------------------------------------------------------


def readJsonMembers(value: Any, what: str, required: tuple[str, ...], optional: tuple[str, ...] | None = ()) -> dict[str, Any]:
	if not isinstance(value, dict):
		raise ValueError(f"{what} must be an object")
	if missing := [key for key in required if key not in value]:
		raise ValueError(f"{what} lacks {', '.join(missing)}")
	if optional is not None and (unknown := [key for key in value if key not in required and key not in optional]):
		raise ValueError(f"{what} has unexpected {', '.join(unknown)}")
	return value


def readJsonString(value: Any, what: str) -> str:
	if not isinstance(value, str):
		raise ValueError(f"{what} must be a string")
	return value


def readJsonCardinality(value: Any, what: str) -> str:
	if value not in CARDS:
		raise ValueError(f"{what}: card must be one of {' '.join(CARDS)}")
	return value


def readJsonFlag(value: Any, what: str) -> bool:
	if value is not True:
		raise ValueError(f"{what} must be true when present")
	return True


def readJsonArray(value: Any, what: str, nonEmpty: bool = False) -> list[Any]:
	if not isinstance(value, list) or (nonEmpty and not value):
		raise ValueError(f"{what} must be a{' non-empty' if nonEmpty else 'n'} array")
	return value


def readJsonStringPairs(value: Any, what: str) -> list[tuple[str, str]]:
	return [(key, readJsonString(item, f"{what}.{key}")) for key, item in readJsonMembers(value, what, (), None).items()]


def annFromJson(value: Any, what: str) -> Annotations:
	pairs = readJsonMembers(value, what, (), None).items()
	return [(key, True if item is True else readJsonString(item, f"{what}.{key}")) for key, item in pairs]


def readOptionalMember(data: dict[str, Any], key: str, read, what: str, default: Any = None) -> Any:
	return read(data[key], f"{what}.{key}") if key in data else default


def typeFromJson(value: Any, what: str) -> TypeExpr:
	keys = set(value) if isinstance(value, dict) else None
	if keys == {"builtin"}:
		if value["builtin"] not in BUILTINS:
			raise ValueError(f"{what}: unknown built-in type")
		return TypeExpr(builtin=value["builtin"])
	if keys == {"unknown"}:
		return TypeExpr(unknown=readJsonFlag(value["unknown"], what))
	if keys == {"values", "open"}:
		if not isinstance(value["open"], bool):
			raise ValueError(f"{what}.open must be a boolean")
		values = [readJsonString(item, f"{what}.values") for item in readJsonArray(value["values"], f"{what}.values", True)]
		return TypeExpr(values=values, open=value["open"])
	if keys == {"range"}:
		element = typeFromJson(value["range"], f"{what}.range")
		if not (element.builtin or element.path):
			raise ValueError(f"{what}.range must be a built-in or a path")
		return TypeExpr(range=element)
	if keys in ({"path"}, {"path", "attr"}):
		return TypeExpr(path=readJsonString(value["path"], what), attr=readOptionalMember(value, "attr", readJsonString, what))
	raise ValueError(f"{what} must be one type expression: builtin, path[+attr], values+open, unknown or range")


def depFromJson(value: Any, what: str) -> Dep:
	keys = set(value) if isinstance(value, dict) else None
	if keys == {"local"}:
		return Dep(local=readJsonString(value["local"], what))
	if keys == {"input"}:
		return Dep(input=readJsonString(value["input"], what))
	if keys == {"path", "attr"}:
		return Dep(path=readJsonString(value["path"], what), attr=readJsonString(value["attr"], what))
	if keys == {"ellipsis"}:
		return Dep(ellipsis=readJsonFlag(value["ellipsis"], what))
	raise ValueError(f"{what} must be one dependency: local, input, path+attr or ellipsis")


def attrFromJson(value: Any, what: str) -> Attr:
	data = readJsonMembers(value, what, ("name", "card"), ("derived", "type", "deps", "ann", "doc"))
	return Attr(
		name=readJsonString(data["name"], what),
		card=readJsonCardinality(data["card"], what),
		derived=readOptionalMember(data, "derived", readJsonFlag, what, False),
		type=readOptionalMember(data, "type", typeFromJson, what),
		deps=readOptionalMember(data, "deps", lambda items, at: [depFromJson(item, at) for item in readJsonArray(items, at, True)], what),
		ann=readOptionalMember(data, "ann", annFromJson, what, []),
		doc=readOptionalMember(data, "doc", readJsonString, what),
	)


def attrsFromJson(value: Any, what: str) -> list[Attr]:
	return [attrFromJson(item, f"{what}[{index}]") for index, item in enumerate(readJsonArray(value, what, True))]


def participantFromJson(value: Any, what: str) -> Participant:
	data = readJsonMembers(value, what, ("role", "card", "type"))
	return Participant(readJsonString(data["role"], what), readJsonCardinality(data["card"], what), readJsonString(data["type"], what))


def arrowFromJson(value: Any, what: str) -> Arrow:
	data = readJsonMembers(value, what, ("verb", "counts"), ("inverse",))
	if not RE_COUNTS.fullmatch(readJsonString(data["counts"], what)):
		raise ValueError(f"{what}: invalid counts")
	return Arrow(readJsonString(data["verb"], what), readOptionalMember(data, "inverse", readJsonString, what), data["counts"])


def viewLineFromJson(value: Any, what: str) -> ViewLine:
	data = readJsonMembers(value, what, ("path",), ("facets", "member"))
	facets = data.get("facets")
	if "facets" in data and facets != "*":
		facets = [readJsonString(item, f"{what}.facets") for item in readJsonArray(facets, f"{what}.facets", True)]
	return ViewLine(readJsonString(data["path"], what), facets, readOptionalMember(data, "member", readJsonString, what))


def viewPopulationFromJson(value: Any, what: str) -> ViewPopulation:
	data = readJsonMembers(value, what, ("name", "type"), ("parent", "via", "reverse", "through", "where", "equals"))
	strings = {k: readJsonString(data[k], what) for k in ("name", "type", "parent", "via", "through", "where") if k in data}
	if any(not isName(strings[k]) for k in ("name", "parent", "through") if k in strings) or any(
		not RE_ATTR_PATH.fullmatch(strings[k]) for k in ("via", "where") if k in strings):
		raise ValueError(f"{what}: invalid population or member name")
	if ("where" in data) != ("equals" in data) or "equals" in data and type(data["equals"]) not in (str, bool):
		raise ValueError(f"{what}: a filter needs where and a literal or ancestor in equals")
	test = data.get("equals")
	if isinstance(test, str) and (not re.fullmatch(r"@?[\w/]+", test, re.ASCII) or test in ("true", "false")):
		raise ValueError(f"{what}: expected a filter token or boolean")
	if ("parent" in data) != ("via" in data) or "parent" not in data and data.keys() - {"name", "type"}:
		raise ValueError(f"{what}: a root has only name and type; a traversal needs parent and via")
	return ViewPopulation(strings.pop("name"), strings.pop("type"), reverse=readOptionalMember(data, "reverse", readJsonFlag, what, False),
		equals=data.get("equals"), **strings)


def mapLineFromJson(value: Any, what: str) -> MapLine:
	data = readJsonMembers(value, what, ("from", "match", "to"), ("doc",))
	return MapLine(readJsonString(data["from"], what), readJsonString(data["match"], what), readJsonString(data["to"], what), readOptionalMember(data, "doc", readJsonString, what))


def declFromJson(value: Any, what: str) -> Decl:
	kind = value.get("kind") if isinstance(value, dict) else None
	if not isinstance(kind, str) or kind not in DECL_MEMBERS:
		raise ValueError(f"{what}: unknown declaration kind '{kind}'")
	required, optional = DECL_MEMBERS[kind]
	data = readJsonMembers(value, what, ("kind", "path") + required, optional)
	what = f"{what} '{data['path']}'"
	decl = Decl(
		kind=kind, path=readJsonString(data["path"], what),
		ann=readOptionalMember(data, "ann", annFromJson, what, []), doc=readOptionalMember(data, "doc", readJsonString, what),
		attrs=readOptionalMember(data, "attrs", attrsFromJson, what, []),
	)
	if kind == "type":
		if "def" in data and "fields" in data:
			raise ValueError(f"{what} has both def and fields")
		decl.definition = readOptionalMember(data, "def", typeFromJson, what)
		decl.fields = readOptionalMember(data, "fields", attrsFromJson, what)
	elif kind == "entity":
		decl.base = readOptionalMember(data, "base", readJsonString, what)
	elif kind == "facet":
		decl.subject = readJsonString(data["subject"], what)
	elif kind == "relation":
		decl.participants = [participantFromJson(item, f"{what}.participants") for item in readJsonArray(data["participants"], what)]
		decl.arrow = readOptionalMember(data, "arrow", arrowFromJson, what)
		if decl.arrow and len(decl.participants) != 2:
			raise ValueError(f"{what}: a binary relation needs exactly two participants")
		if len(decl.participants) < 2:
			raise ValueError(f"{what}: a relation needs at least two participants")
	elif kind == "map":
		decl.mapFrom, decl.mapTo = readJsonString(data["from"], what), readJsonString(data["to"], what)
		decl.mapLines = [mapLineFromJson(item, f"{what}.lines") for item in readJsonArray(data["lines"], what)]
	elif kind == "view":
		lines = readJsonArray(data["lines"], what)
		if "input" in data or "populations" in data:
			readJsonMembers(data, what, ("input", "populations"), None)
			param = readJsonMembers(data["input"], f"{what}.input", ("name", "path", "attr"))
			decl.viewInput = ViewInput(*(readJsonString(param[k], f"{what}.input.{k}") for k in ("name", "path", "attr")))
			decl.viewPopulations = [viewPopulationFromJson(v, what) for v in readJsonArray(data["populations"], what, True)]
			for item in lines:
				v = readJsonMembers(item, what, ("population", "member"), ("optional", "target"))
				decl.viewLines.append(ViewLine(readJsonString(v["population"], what), member=readJsonString(v["member"], what),
					optional=readOptionalMember(v, "optional", readJsonFlag, what, False), target=readOptionalMember(v, "target", readJsonString, what)))
		else:
			decl.viewLines = [viewLineFromJson(item, f"{what}.lines") for item in lines]
	return decl


def decodeOntology(value: Any) -> Ontology:
	data = readJsonMembers(value, "ontology", ("format", "namespace", "decls"), ("header", "uses", "ids"))
	if data["format"] != ONTOLOGY_FORMAT:
		raise ValueError(f"format must be '{ONTOLOGY_FORMAT}'")
	return Ontology(
		namespace=readJsonString(data["namespace"], "namespace"),
		header=readOptionalMember(data, "header", readJsonStringPairs, "ontology", []),
		uses=readOptionalMember(data, "uses", readJsonStringPairs, "ontology", []),
		decls=[declFromJson(item, f"decls[{index}]") for index, item in enumerate(readJsonArray(data["decls"], "decls"))],
		ids=dict(readOptionalMember(data, "ids", readJsonStringPairs, "ontology", [])) or None,
	)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseOntology(sources: list[Source]) -> Ontology:
	"""Parse `sources` as one ontology with full paths, retaining locations and diagnostics."""
	diag = Diagnostics()
	ontology = Ontology()
	seen: dict[str, Decl] = {}
	for source in sources:
		parseFile(source, ontology, seen, diag)
	if ontology.namespace is None:
		diag.error("header", "Missing @ontology directive")
	ontology.diagnostics = diag.check()
	return ontology


# EOF
