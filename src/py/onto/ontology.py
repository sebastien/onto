"""Module: ontology — parse, validate, normalise, print and convert ontologies (spec-01)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from .text import (
	Annotations,
	Diagnostics,
	FormatError,
	Line,
	Loc,
	Source,
	annotation,
	isName,
	isPath,
	lastSegment,
	parseAnnotations,
	parseArguments,
	printAnnotations,
	printArguments,
	sourceLines,
	splitAnnotations,
	splitDoc,
)

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class TypeExpr:
	"""A type expression: built-in, path (with optional attribute reuse), vocabulary or `...`."""

	builtin: str | None = None
	path: str | None = None
	attr: str | None = None
	values: list[str] | None = None
	open: bool = False
	unknown: bool = False


@dataclass(slots=True)
class Dep:
	"""A derived attribute dependency: local name, `$input`, `Owner.Attr` or `...`."""

	local: str | None = None
	input: str | None = None
	path: str | None = None
	attr: str | None = None
	ellipsis: bool = False


@dataclass(slots=True)
class Attr:
	"""An attribute of an entity, facet, relation or structure."""

	name: str
	card: str | None = None
	derived: bool = False
	type: TypeExpr | None = None
	deps: list[Dep] | None = None
	ann: Annotations = field(default_factory=list)
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class Participant:
	"""A relation participant: role, cardinality per instance, type path."""

	role: str
	card: str | None
	type: str


@dataclass(slots=True)
class Arrow:
	"""The binary shorthand of a relation: verbs and participation counts."""

	verb: str
	inverse: str | None = None
	counts: str | None = None


@dataclass(slots=True)
class ViewLine:
	"""A view body line: path, selected facets (`*` or names) and member."""

	path: str
	facets: str | list[str] | None = None
	member: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class MapLine:
	"""A value map line: `FromValue match ToValue`."""

	fromValue: str
	match: str
	toValue: str
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class Decl:
	"""A declaration; `kind` selects which fields are meaningful."""

	kind: str
	path: str
	ann: Annotations = field(default_factory=list)
	doc: str | None = None
	loc: Loc | None = None
	base: str | None = None
	subject: str | None = None
	attrs: list[Attr] = field(default_factory=list)
	definition: TypeExpr | None = None
	fields: list[Attr] | None = None
	participants: list[Participant] = field(default_factory=list)
	arrow: Arrow | None = None
	viewLines: list[ViewLine] = field(default_factory=list)
	mapLines: list[MapLine] = field(default_factory=list)
	mapFrom: str | None = None
	mapTo: str | None = None


@dataclass(slots=True)
class Ontology:
	"""An ontology with fully qualified paths."""

	namespace: str | None = None
	header: list[tuple[str, str]] = field(default_factory=list)
	uses: list[tuple[str, str]] = field(default_factory=list)
	decls: list[Decl] = field(default_factory=list)
	diagnostics: list = field(default_factory=list)
	ids: dict[str, str] | None = None


@dataclass(slots=True)
class ResolvedType:
	"""A type expression resolved through aliases: its final kind and qualifiers."""

	kind: str
	path: str | None = None
	builtin: str | None = None
	values: list[str] | None = None
	open: bool = False
	ordered: bool = False
	qualifiers: dict[str, str] = field(default_factory=dict)
	conflicts: list[str] = field(default_factory=list)


ONTOLOGY_FORMAT = "onto.ontology/1"
BUILTINS = ("Text", "Integer", "Number", "Boolean", "Date", "DateTime", "Duration", "Amount", "Percent")
# NOTE: Where each annotation applies (None: anywhere); the key order is the normal-form order.
ANNOTATION_PLACES: dict[str, set[str] | None] = {
	"key": {"attribute"},
	"id": {"attribute"},
	"privacy": {"attribute"},
	"kind": {"relation"},
	"context": {"binary"},
	"subjectRole": {"binary"},
	"objectRole": {"binary"},
	"ctx": {"facet"},
	"ordered": {"vocabulary"},
	"cur": {"type", "attribute"},
	"unit": {"type", "attribute"},
	"period": {"type", "attribute"},
	"scale": {"type", "attribute"},
	"status": None,
	"cards": {"attribute"},
	"deps": {"derived"},
	"rule": {"derived", "map"},
	"src": None,
	"check": None,
	"elided": {"vocabulary"},
}
ANNOTATION_KEYS = list(ANNOTATION_PLACES)
HEADER_KEYS = ["rev", "src", "card", "cards", "rel"]
HEADER_DEFAULTS = {"card": "?", "cards": "stated", "rel": "*:*"}
IDENTIFIERS = ("key", "narrow", "broad", "none")
MATCHES = ("exact", "broader", "narrower", "related")
QUALIFIERS = ("cur", "unit", "period", "scale")
CARDS = ("1", "?", "+", "*")
STATUSES = ("stated", "inferred", "assumed")
PATH_KEYS = ("context", "ctx")
MULTI = ("+", "*")
SECTIONS = {"domain": 0, "type": 1, "entity": 2, "facet": 2, "relation": 3, "map": 4, "view": 5}

# NOTE: Members of each declaration kind beyond `kind` and `path`: (required, optional).
DECL_MEMBERS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
	"type": ((), ("def", "fields", "ann", "doc")),
	"entity": ((), ("base", "attrs", "ann", "doc")),
	"facet": (("subject",), ("attrs", "ann", "doc")),
	"relation": (("participants",), ("arrow", "attrs", "ann", "doc")),
	"domain": ((), ("doc",)),
	"map": (("from", "to", "lines"), ("ann", "doc")),
	"view": (("lines",), ("doc",)),
}

RE_COUNTS = re.compile(r"[?1*+]:[?1*+]")
RE_ONTOLOGY = re.compile(r"@ontology\s+(\S+)(.*)")
RE_USE = re.compile(r"@use\s+(\S+)\s+as\s+(\S+)")
RE_VIEW = re.compile(r"@view\s+(\S+)")
RE_DOMAIN = re.compile(r"@domain\s+(\S+)")
RE_MAP = re.compile(r"@map\s+(\S+)\s+(\S+)\s+->\s+(\S+)")
RE_MAP_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s+([a-z]+)\s+([A-Za-z_][A-Za-z0-9_]*)")
RE_TYPE_DECL = re.compile(r"([^\s=(]+)\s*=\s*(.*)")
RE_FACET_DECL = re.compile(r"(\S+)\s+of\s+(\S+)")
RE_ARROW_DECL = re.compile(
	r"(\S+)\s+-([A-Za-z_][A-Za-z0-9_]*)(?:/([A-Za-z_][A-Za-z0-9_]*))?->\s+(\S+)(?:\s+(\S+))?"
)
RE_RELATION_DECL = re.compile(r"([^\s(]+)\((.*)\)")
RE_PARTICIPANT = re.compile(r"(?:([A-Za-z_][A-Za-z0-9_]*)\s*:\s*)?(?:([1?+*])\s+)?(\S+)")
RE_ENTITY_DECL = re.compile(r"(\S+)(?:\s+<\s+(\S+))?")
RE_ATTRIBUTE = re.compile(r"(?:([1?+*])\s+)?(?:(~)\s+)?([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?")
RE_ATTR_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
RE_INPUT = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")
RE_VIEW_ARROW = re.compile(r"([A-Za-z_][A-Za-z0-9_/]*)\.([a-z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_/]*)")
RE_VIEW_LINE = re.compile(
	r"([A-Za-z_][A-Za-z0-9_/]*)(?:\[([^\]]*)\])?(?:\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?))?"
)

# -----------------------------------------------------------------------------
#
# PARSING
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class _Context:
	"""Per-file parsing state: namespace and aliases."""

	diag: Diagnostics
	namespace: str | None = None
	aliases: dict[str, str] = field(default_factory=dict)


# Function: arrowPath
# The path of a binary relation, `S.verb.T`.
def arrowPath(subject: str, verb: str, obj: str) -> str:
	return f"{subject}.{verb}.{obj}"


# Function: isAssociation
# True for an n-ary relation: it has identity and may be a participant.
def isAssociation(decl: Decl | None) -> bool:
	return decl is not None and decl.kind == "relation" and decl.arrow is None


# Function: isSymmetric
# True when a binary relation reads the same in both directions.
def isSymmetric(decl: Decl) -> bool:
	return (
		decl.arrow is not None
		and decl.arrow.inverse == decl.arrow.verb
		and decl.participants[0].type == decl.participants[1].type
	)


def _effectiveHeader(header: list[tuple[str, str]]) -> dict[str, str]:
	return HEADER_DEFAULTS | dict(header)


def _typeKey(type: TypeExpr) -> str:
	return f"{type.path}.{type.attr}" if type.attr else str(type.path)


def _resolvePath(name: str, ctx: _Context, loc: Loc | None) -> str | None:
	if not isPath(name):
		ctx.diag.error("name", f"Invalid name '{name}'", loc)
		return None
	head, slash, rest = name.partition("/")
	if slash and head in ctx.aliases:
		return f"{ctx.aliases[head]}/{rest}"
	return f"{ctx.namespace}/{name}"


def _resolveDeclared(name: str, ctx: _Context, loc: Loc | None) -> str | None:
	if name in BUILTINS:
		ctx.diag.error("reserved", f"'{name}' is a built-in type and cannot be declared", loc)
		return None
	return _resolvePath(name, ctx, loc)


def _parseAnn(text: str | None, ctx: _Context, loc: Loc | None) -> Annotations:
	pairs: Annotations = []
	for key, value in parseAnnotations(text, loc, ctx.diag):
		if key in PATH_KEYS and isinstance(value, str):
			value = _resolvePath(value, ctx, loc) or value
		pairs.append((key, value))
	return pairs


def _parseTypeExpr(text: str, ctx: _Context, loc: Loc | None) -> TypeExpr | None:
	value = re.sub(r"\s*\|\s*", "|", text.strip())
	if not value:
		return None
	if value == "...":
		return TypeExpr(unknown=True)
	if "|" in value:
		parts = value.split("|")
		if parts[0] == "":
			parts = parts[1:]
		isOpen = parts[-1] == "..."
		if isOpen:
			parts = parts[:-1]
		if not parts or not all(isName(part) for part in parts):
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
		path = _resolvePath(owner, ctx, loc)
		return TypeExpr(path=path, attr=attrPath) if path else None
	path = _resolvePath(value, ctx, loc)
	return TypeExpr(path=path) if path else None


def _parseDeps(text: str, ctx: _Context, loc: Loc | None) -> list[Dep]:
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
			ref = _parseTypeExpr(part, ctx, loc)
			if ref and ref.attr:
				deps.append(Dep(path=ref.path, attr=ref.attr))
			else:
				ctx.diag.error("derived", f"Invalid dependency '{part}'", loc)
	if not deps:
		ctx.diag.error("derived", "Empty dependency list", loc)
	return deps


def _parseAttribute(line: Line, ctx: _Context) -> Attr | None:
	withAnnotations, doc = splitDoc(line.text)
	text, annotationText = splitAnnotations(withAnnotations)
	ann = _parseAnn(annotationText, ctx, line.loc)
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
		type=_parseTypeExpr(typeText, ctx, line.loc),
		deps=None if depsText is None else _parseDeps(depsText, ctx, line.loc),
		ann=ann,
		doc=doc,
		loc=line.loc,
	)


def _parseViewLine(line: Line, ctx: _Context) -> ViewLine | None:
	if match := RE_VIEW_ARROW.fullmatch(line.text):
		subject = _resolvePath(match.group(1), ctx, line.loc)
		obj = _resolvePath(match.group(3), ctx, line.loc)
		return ViewLine(path=arrowPath(subject, match.group(2), obj), loc=line.loc) if subject and obj else None
	match = RE_VIEW_LINE.fullmatch(line.text)
	if not match:
		ctx.diag.error("syntax", f"Invalid view line '{line.text}'", line.loc)
		return None
	path = _resolvePath(match.group(1), ctx, line.loc)
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


def _parseMapLine(line: Line, ctx: _Context) -> MapLine | None:
	text, doc = splitDoc(line.text)
	match = RE_MAP_LINE.fullmatch(text)
	if not match or match.group(2) not in MATCHES:
		ctx.diag.error("syntax", f"Invalid map line '{line.text}' (Value exact|broader|narrower|related Value)", line.loc)
		return None
	return MapLine(fromValue=match.group(1), match=match.group(2), toValue=match.group(3), doc=doc, loc=line.loc)


def _parseDeclaration(line: Line, ctx: _Context) -> Decl | None:
	loc = line.loc
	withAnnotations, doc = splitDoc(line.text)
	text, annotationText = splitAnnotations(withAnnotations)
	ann = _parseAnn(annotationText, ctx, loc)
	if match := RE_TYPE_DECL.fullmatch(text):
		path = _resolveDeclared(match.group(1), ctx, loc)
		if not path:
			return None
		return Decl(kind="type", path=path, definition=_parseTypeExpr(match.group(2), ctx, loc), ann=ann, doc=doc, loc=loc)
	if match := RE_FACET_DECL.fullmatch(text):
		path = _resolveDeclared(match.group(1), ctx, loc)
		subject = _resolvePath(match.group(2), ctx, loc)
		if not path or not subject:
			return None
		return Decl(kind="facet", path=path, subject=subject, ann=ann, doc=doc, loc=loc)
	if match := RE_ARROW_DECL.fullmatch(text):
		subjectName, verb, inverse, objectName, counts = match.groups()
		subject = _resolvePath(subjectName, ctx, loc)
		obj = _resolvePath(objectName, ctx, loc)
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
		path = _resolveDeclared(match.group(1), ctx, loc)
		if not path:
			return None
		participants: list[Participant] = []
		for part in (item.strip() for item in match.group(2).split(",")):
			found = RE_PARTICIPANT.fullmatch(part)
			if not found:
				ctx.diag.error("syntax", f"Invalid participant '{part}'", loc)
				continue
			typePath = _resolvePath(found.group(3), ctx, loc)
			if typePath:
				participants.append(Participant(found.group(1) or lastSegment(typePath), found.group(2), typePath))
		return Decl(kind="relation", path=path, participants=participants, ann=ann, doc=doc, loc=loc)
	if match := RE_ENTITY_DECL.fullmatch(text):
		path = _resolveDeclared(match.group(1), ctx, loc)
		base = _resolvePath(match.group(2), ctx, loc) if match.group(2) else None
		if not path or (match.group(2) and not base):
			return None
		return Decl(kind="entity", path=path, base=base, ann=ann, doc=doc, loc=loc)
	ctx.diag.error("syntax", f"Unrecognised declaration '{line.text}'", loc)
	return None


def _bodyParser(decl: Decl, ctx: _Context):
	def parseField(line: Line) -> None:
		if decl.definition is not None:
			ctx.diag.error("syntax", "Only structures (`T =` with no right side) have a body", line.loc)
			return
		attr = _parseAttribute(line, ctx)
		if attr:
			decl.fields = (decl.fields or []) + [attr]

	def parseAttr(line: Line) -> None:
		attr = _parseAttribute(line, ctx)
		if attr:
			decl.attrs.append(attr)

	return parseField if decl.kind == "type" else parseAttr


def _parseDirective(line: Line, position: int, ctx: _Context, ontology: Ontology, seen: dict[str, Decl]):
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
		ctx.namespace = namespace
		if ontology.namespace is None:
			ontology.namespace, ontology.header = namespace, header
		elif ontology.namespace != namespace or dict(header).get("rev") != dict(ontology.header).get("rev"):
			diag.error("header", "All files of an ontology must have the same @ontology namespace and rev", loc)
		elif _effectiveHeader(header) != _effectiveHeader(ontology.header):
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
		path = _resolvePath(match.group(1), ctx, loc)
		if not path:
			return None
		decl = Decl(kind="view", path=path, doc=doc, loc=loc)
		if not declare(decl):
			return None

		def parseView(body: Line) -> None:
			viewLine = _parseViewLine(body, ctx)
			if viewLine:
				decl.viewLines.append(viewLine)

		return parseView
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
		path, mapFrom, mapTo = (_resolvePath(name, ctx, loc) for name in match.groups())
		if not path or not mapFrom or not mapTo:
			return None
		mapDecl = Decl(kind="map", path=path, mapFrom=mapFrom, mapTo=mapTo, ann=_parseAnn(annotationText, ctx, loc), doc=doc, loc=loc)
		if not declare(mapDecl):
			return None

		def parseMap(body: Line) -> None:
			mapLine = _parseMapLine(body, ctx)
			if mapLine:
				mapDecl.mapLines.append(mapLine)

		return parseMap
	diag.error("directive", f"Unknown directive '{text.split()[0]}'", loc)
	return None


def _parseFile(source: Source, ontology: Ontology, seen: dict[str, Decl], diag: Diagnostics) -> None:
	ctx = _Context(diag)
	current = None
	if "\r" in source.text:
		diag.error("syntax", "Line endings must be LF", Loc(source.name, source.text[: source.text.index("\r")].count("\n") + 1))
	for position, line in enumerate(sourceLines(source)):
		if line.tabs:
			diag.error("indent", "Tabs are not allowed in indentation", line.loc)
			continue
		if position == 0 and not line.text.startswith("@ontology"):
			diag.error("header", "File must start with @ontology", line.loc)
			continue
		if line.indent == 2:
			if current is None:
				diag.error("indent", "Body line without a declaration that accepts one", line.loc)
			else:
				current(line)
			continue
		current = None
		if line.indent != 0:
			diag.error("indent", "Body lines are indented by exactly two spaces", line.loc)
			continue
		if line.text.startswith("@"):
			current = _parseDirective(line, position, ctx, ontology, seen)
			continue
		decl = _parseDeclaration(line, ctx)
		if not decl:
			continue
		if decl.path in seen:
			diag.error("duplicate", f"Duplicate declaration '{decl.path}'", line.loc)
			continue
		seen[decl.path] = decl
		ontology.decls.append(decl)
		current = _bodyParser(decl, ctx)


# -----------------------------------------------------------------------------
#
# MODEL
#
# -----------------------------------------------------------------------------


class Model:
	"""Lookups over an ontology: declarations, lineage, attributes, facets and types."""

	def __init__(self, ontology: Ontology):
		self.ontology = ontology
		self.index: dict[str, Decl] = {decl.path: decl for decl in ontology.decls}
		self.facetsBySubject: dict[str, list[Decl]] = {}
		for decl in ontology.decls:
			if decl.kind == "facet" and decl.subject:
				self.facetsBySubject.setdefault(decl.subject, []).append(decl)
		header = dict(ontology.header)
		self.defaultCard = header.get("card", "?")
		self.defaultCounts = header.get("rel", "*:*")
		self._looking: set[str] = set()

	def get(self, path: str | None) -> Decl | None:
		return self.index.get(path) if path else None

	def lineage(self, path: str) -> list[str]:
		"""Entity `path` and its bases, nearest first; an association is its own lineage."""
		if isAssociation(self.get(path)):
			return [path]
		chain: list[str] = []
		current: str | None = path
		while current and current not in chain:
			decl = self.get(current)
			if not decl or decl.kind != "entity":
				break
			chain.append(current)
			current = decl.base
		return chain

	def isA(self, path: str, ancestor: str) -> bool:
		return ancestor in self.lineage(path)

	def entityAttrs(self, path: str) -> dict[str, Attr]:
		"""Attributes of entity `path` by name, including inherited ones."""
		attrs: dict[str, Attr] = {}
		for entity in reversed(self.lineage(path)):
			for attr in self.index[entity].attrs:
				attrs[attr.name] = attr
		return attrs

	def ownNames(self, path: str) -> set[str]:
		"""Attribute and role names of `path`, which facet names must not shadow."""
		decl = self.get(path)
		if isAssociation(decl):
			return {item.role for item in decl.participants} | {attr.name for attr in decl.attrs}
		if decl and decl.kind == "entity":
			return set(self.entityAttrs(path))
		return set()

	def facetsOf(self, path: str) -> list[Decl]:
		return self.facetsBySubject.get(path, [])

	def facets(self, path: str) -> dict[str, Decl]:
		"""Facets applicable to `path` (including inherited ones), by addressing name."""
		facets: dict[str, Decl] = {}
		for entity in reversed(self.lineage(path)):
			for facet in self.facetsOf(entity):
				facets[lastSegment(facet.path)] = facet
		return facets

	def facetOf(self, ownerPath: str, attrPath: str) -> Decl | None:
		"""The facet that `attrPath` goes through on `ownerPath`, if any."""
		name = attrPath.split(".")[0]
		if name in self.ownNames(ownerPath):
			return None
		return self.facets(ownerPath).get(name)

	def lookup(self, ownerPath: str, attrPath: str) -> Attr | None:
		"""Attribute `attrPath` of `ownerPath`, through facets and structures; roles act as attributes."""
		# NOTE: A structure reached through attribute reuse may lead back here (`A P.A.X`): the guard stops it.
		key = f"{ownerPath}.{attrPath}"
		if key in self._looking:
			return None
		self._looking.add(key)
		try:
			return self._lookup(ownerPath, attrPath)
		finally:
			self._looking.discard(key)

	def _lookup(self, ownerPath: str, attrPath: str) -> Attr | None:
		decl = self.get(ownerPath)
		if not decl:
			return None
		segments = attrPath.split(".")
		attr: Attr | None = None
		rest = segments[1:]
		facet = self.facetOf(ownerPath, attrPath)
		if facet:
			if len(segments) < 2:
				return None
			attr = next((item for item in facet.attrs if item.name == segments[1]), None)
			rest = segments[2:]
		elif decl.kind == "entity":
			attr = self.entityAttrs(ownerPath).get(segments[0])
		elif decl.kind in ("facet", "relation"):
			attr = next((item for item in decl.attrs if item.name == segments[0]), None)
			if not attr and decl.kind == "relation":
				role = next((item for item in decl.participants if item.role == segments[0]), None)
				if role:
					attr = Attr(name=role.role, card=role.card or "1", type=TypeExpr(path=role.type))
		elif decl.kind == "type":
			attr = next((item for item in decl.fields or [] if item.name == segments[0]), None)
		for name in rest:
			struct = self.structOf(attr.type) if attr else None
			if not struct:
				return None
			attr = next((item for item in struct.fields or [] if item.name == name), None)
		return attr

	def structOf(self, type: TypeExpr | None) -> Decl | None:
		"""The structure declaration a type expression denotes, following aliases."""
		target = self.typeDecl(type)
		return target if target and target.fields is not None else None

	def typeDecl(self, type: TypeExpr | None, seen: set[str] | None = None) -> Decl | None:
		"""The final type declaration of a type expression, following aliases and reuse."""
		seen = set() if seen is None else seen
		if not type or not type.path:
			return None
		key = _typeKey(type)
		if key in seen:
			return None
		seen.add(key)
		if type.attr:
			attr = self.lookup(type.path, type.attr)
			return self.typeDecl(attr.type, seen) if attr else None
		decl = self.get(type.path)
		if not decl or decl.kind != "type":
			return None
		if decl.definition and decl.definition.path:
			return self.typeDecl(decl.definition, seen) or decl
		return decl

	def resolveType(self, type: TypeExpr | None, ann: Annotations | None = None) -> ResolvedType:
		"""Resolves a type expression to its final kind; qualifiers come from `ann`, then reused attributes and aliases."""
		# NOTE: Qualifier sources are listed nearest first: a nearer fixed value wins, `?` never overrides.
		sources: list[Annotations] = [ann or []]
		seen: set[str] = set()
		resolved = ResolvedType("unspecified")
		current = type
		while current:
			if current.builtin:
				resolved = ResolvedType("builtin", builtin=current.builtin)
				break
			if current.values is not None or current.unknown:
				resolved = ResolvedType("vocab", values=list(current.values or []), open=current.open or current.unknown)
				break
			key = _typeKey(current)
			if not current.path or key in seen:
				break
			seen.add(key)
			if current.attr:
				attr = self.lookup(current.path, current.attr)
				if not attr:
					break
				sources.append(attr.ann)
				current = attr.type
				continue
			decl = self.get(current.path)
			if decl and decl.kind == "entity":
				resolved = ResolvedType("entity", path=decl.path)
				break
			if decl and decl.kind == "relation":
				resolved = ResolvedType("relation", path=decl.path)
				break
			if not decl or decl.kind != "type":
				break
			sources.append(decl.ann)
			if decl.fields is not None:
				resolved = ResolvedType("struct", path=decl.path)
				break
			definition = decl.definition
			if definition and (definition.values is not None or definition.unknown):
				resolved = ResolvedType(
					"vocab", path=decl.path, values=list(definition.values or []),
					open=definition.open or definition.unknown, ordered=annotation(decl.ann, "ordered") is True,
				)
				break
			current = definition
		for name in QUALIFIERS:
			values = [value for pairs in sources if isinstance(value := annotation(pairs, name), str)]
			fixed = [value for value in values if value != "?"]
			if values:
				resolved.qualifiers[name] = fixed[0] if fixed else "?"
			if other := next((value for value in fixed if value != fixed[0]), None):
				resolved.conflicts.append(f"{name}={fixed[0]} contradicts inherited {name}={other}")
		return resolved

	def verbs(self, path: str, verb: str) -> list[tuple[Decl, bool]]:
		"""Binary relations usable from `path` with `verb` → `(relation, inverse)` pairs."""
		found: list[tuple[Decl, bool]] = []
		lineage = self.lineage(path)
		for decl in self.ontology.decls:
			if decl.kind != "relation" or not decl.arrow:
				continue
			if decl.arrow.verb == verb and decl.participants[0].type in lineage:
				found.append((decl, False))
			elif decl.arrow.inverse == verb and decl.participants[1].type in lineage:
				found.append((decl, True))
		return found


# -----------------------------------------------------------------------------
#
# VALIDATION
#
# -----------------------------------------------------------------------------


# Function: viewRelations
# The binary relations a view line `S.verb` (forward or inverse) or `S.verb.T` selects, or None.
def viewRelations(model: Model, line: ViewLine) -> list[Decl] | None:
	if "." in line.path:
		decl = model.get(line.path)
		return [decl] if decl and decl.arrow else []
	if not line.member or not line.member[0].islower():
		return None
	return [decl for decl, _ in model.verbs(line.path, line.member)]


# Function: placesOf
# Where annotations of `item` (a declaration or an attribute) may apply, for `ANNOTATION_PLACES`.
def placesOf(item: Decl | Attr) -> set[str]:
	if isinstance(item, Attr):
		places = {"attribute"}
		if item.derived:
			places.add("derived")
		if item.type and item.type.values is not None:
			places.add("vocabulary")
		return places
	places = {item.kind}
	if item.kind == "type" and item.definition and item.definition.values is not None:
		places.add("vocabulary")
	if item.arrow:
		places.add("binary")
	return places


def _checkAnnotations(model: Model, ann: Annotations, places: set[str], loc: Loc | None, diag: Diagnostics) -> None:
	for key, value in ann:
		allowed = ANNOTATION_PLACES.get(key, set())
		if key not in ANNOTATION_PLACES:
			diag.error("annotation", f"Unknown annotation '{key}'", loc)
		elif allowed is not None and not allowed & places:
			diag.error("annotation", f"'{key}' applies to {' or '.join(sorted(allowed))}, not here", loc)
		elif key == "kind" and value not in ("event", "state"):
			diag.error("annotation", "kind must be event or state", loc)
		elif key in ("status", "cards") and value not in STATUSES:
			diag.error("annotation", f"{key} must be stated, inferred or assumed", loc)
		elif key == "scale" and value not in ("1", "100", "?"):
			diag.error("annotation", "scale must be 1, 100 or ?", loc)
		elif key == "deps" and value != "candidate":
			diag.error("annotation", "deps must be candidate", loc)
		elif key == "elided" and not (isinstance(value, str) and value.isdigit()):
			diag.error("annotation", "elided must be a count", loc)
		elif key in ("key", "ordered") and value is not True:
			diag.error("annotation", f"{key} is a flag", loc)
		elif key == "id" and value not in IDENTIFIERS:
			diag.error("annotation", f"id must be {', '.join(IDENTIFIERS)}", loc)
		elif key in ("subjectRole", "objectRole") and not (isinstance(value, str) and isName(value)):
			diag.error("annotation", f"{key} must name a role", loc)
		elif key == "privacy":
			names = value.split("+") if isinstance(value, str) else []
			if not names or not all(isName(name) for name in names) or len(set(names)) != len(names):
				diag.error("annotation", "privacy must be distinct audience names joined with +", loc)
		elif key == "context" and not isAssociation(model.get(value if isinstance(value, str) else None)):
			diag.error("reference", f"context must name an n-ary relation: '{value}'", loc)
		elif key == "ctx":
			target = model.get(value if isinstance(value, str) else None)
			if not target or (target.kind != "entity" and not isAssociation(target)):
				diag.error("reference", f"ctx must name an entity or an n-ary relation: '{value}'", loc)


def _typeCycle(model: Model, type: TypeExpr | None) -> bool:
	"""True when following aliases and attribute reuse from `type` comes back to a visited type."""
	seen: set[str] = set()
	while type and type.path:
		key = _typeKey(type)
		if key in seen:
			return True
		seen.add(key)
		if type.attr:
			attr = model.lookup(type.path, type.attr)
			type = attr.type if attr else None
		else:
			decl = model.get(type.path)
			type = decl.definition if decl and decl.kind == "type" else None
	return False


def _checkType(model: Model, type: TypeExpr | None, ann: Annotations, loc: Loc | None, what: str, diag: Diagnostics) -> None:
	for conflict in model.resolveType(type, ann).conflicts:
		diag.error("qualifier", f"{what}: {conflict}", loc)
	if not type or type.builtin or type.values is not None or type.unknown:
		return
	if _typeCycle(model, type):
		diag.error("cycle", f"{what}: type alias or attribute reuse cycle through '{_typeKey(type)}'", loc)
		return
	decl = model.get(type.path)
	if not decl:
		diag.error("reference", f"{what}: unknown '{type.path}'", loc)
	elif type.attr:
		if not model.lookup(type.path, type.attr):
			diag.error("reference", f"{what}: unknown attribute '{type.path}.{type.attr}'", loc)
	elif decl.kind not in ("type", "entity") and not isAssociation(decl):
		kind = "binary relation" if decl.arrow else decl.kind
		diag.error("reference", f"{what}: '{type.path}' is a {kind}, not a type, entity or association", loc)


def _checkAttrs(model: Model, owner: Decl, attrs: list[Attr], localNames, diag: Diagnostics) -> None:
	names: set[str] = set()
	for attr in attrs:
		if attr.name in names:
			diag.error("duplicate", f"Duplicate attribute '{owner.path}.{attr.name}'", attr.loc)
		names.add(attr.name)
		_checkType(model, attr.type, attr.ann, attr.loc, f"{owner.path}.{attr.name}", diag)
		_checkAnnotations(model, attr.ann, placesOf(attr), attr.loc, diag)
		for dep in attr.deps or []:
			if dep.local and dep.local not in localNames():
				diag.error("reference", f"Unknown dependency '{dep.local}' of '{owner.path}.{attr.name}'", attr.loc)
			if dep.path and not model.lookup(dep.path, dep.attr):
				diag.error("reference", f"Unknown dependency '{dep.path}.{dep.attr}'", attr.loc)


def _validateMap(model: Model, decl: Decl, diag: Diagnostics) -> None:
	def vocabulary(path: str) -> set[str] | None:
		target = model.get(path)
		resolved = model.resolveType(TypeExpr(path=path)) if target and target.kind == "type" else None
		if not resolved or resolved.kind != "vocab":
			diag.error("reference", f"Map '{decl.path}': '{path}' is not a vocabulary type", decl.loc)
			return None
		return set(resolved.values or [])

	fromValues, toValues = vocabulary(decl.mapFrom), vocabulary(decl.mapTo)
	pairs: set[tuple[str, str]] = set()
	for line in decl.mapLines:
		if fromValues is not None and line.fromValue not in fromValues:
			diag.error("reference", f"Unknown value '{line.fromValue}' of '{decl.mapFrom}'", line.loc)
		if toValues is not None and line.toValue not in toValues:
			diag.error("reference", f"Unknown value '{line.toValue}' of '{decl.mapTo}'", line.loc)
		pair = (line.fromValue, line.toValue)
		if pair in pairs:
			diag.error("duplicate", f"Duplicate map line '{line.fromValue} {line.toValue}'", line.loc)
		pairs.add(pair)


def _validateViewLine(model: Model, line: ViewLine, diag: Diagnostics) -> None:
	relations = viewRelations(model, line)
	if relations is not None:
		if not relations or line.facets is not None:
			name = line.path + (f".{line.member}" if line.member else "")
			diag.error("reference", f"View selects unknown binary relation '{name}'", line.loc)
		return
	decl = model.get(line.path)
	if not decl:
		diag.error("reference", f"View selects unknown '{line.path}'", line.loc)
		return
	if decl.kind == "view" and (line.facets is not None or line.member):
		diag.error("reference", f"View '{line.path}' is selected whole: no facets or members", line.loc)
		return
	if line.facets:
		if decl.kind != "entity" and not isAssociation(decl):
			diag.error("reference", f"Facets selected on '{line.path}', which is not an entity or association", line.loc)
			return
		if line.facets != "*":
			facets = model.facets(line.path)
			for name in line.facets:
				if name not in facets:
					diag.error("reference", f"Unknown facet '{name}' on '{line.path}'", line.loc)
	if line.member and not model.lookup(line.path, line.member):
		diag.error("reference", f"View selects unknown '{line.path}.{line.member}'", line.loc)
	if decl.kind not in ("entity", "relation", "view"):
		diag.error("reference", f"View cannot select {decl.kind} '{line.path}'", line.loc)


def _validateRelation(model: Model, decl: Decl, diag: Diagnostics) -> None:
	if len(decl.participants) < 2:
		diag.error("relation", f"Relation '{decl.path}' needs at least two participants", decl.loc)
	roles: set[str] = set()
	for participant in decl.participants:
		target = model.get(participant.type)
		if not target or (target.kind != "entity" and not isAssociation(target)):
			diag.error("reference", f"Participant of '{decl.path}' is not an entity or association: '{participant.type}'", decl.loc)
		if participant.role in roles:
			diag.error("duplicate", f"Duplicate role '{participant.role}' in '{decl.path}'", decl.loc)
		roles.add(participant.role)
	for attr in decl.attrs:
		if attr.name in roles:
			diag.error("collision", f"Attribute '{attr.name}' collides with a role of '{decl.path}'", attr.loc)
	context = model.get(annotation(decl.ann, "context"))
	contextRoles = {item.role: item for item in context.participants} if context else {}
	for index, key in enumerate(("subjectRole", "objectRole")):
		role = annotation(decl.ann, key)
		if role is None:
			continue
		participant = contextRoles.get(role)
		if not decl.arrow or not participant or not model.isA(decl.participants[index].type, participant.type):
			diag.error("reference", f"{key} '{role}' must select a compatible role on the relation context", decl.loc)
	subjectRole, objectRole = annotation(decl.ann, "subjectRole"), annotation(decl.ann, "objectRole")
	if subjectRole is not None and subjectRole == objectRole:
		shared = contextRoles.get(subjectRole)
		if not shared or shared.card not in MULTI:
			diag.error("reference", "A role selected for both subject and object must be multi-valued", decl.loc)
	_checkAttrs(model, decl, decl.attrs, lambda: roles | {attr.name for attr in decl.attrs}, diag)


def _checkViewCycles(model: Model, diag: Diagnostics) -> None:
	# NOTE: A view including itself, directly or through other views, selects nothing definite: an error.
	def includes(view: Decl) -> list[str]:
		return [line.path for line in view.viewLines if (target := model.get(line.path)) and target.kind == "view"]

	for view in (decl for decl in model.ontology.decls if decl.kind == "view"):
		pending, seen = includes(view), set()
		while pending:
			path = pending.pop()
			if path == view.path:
				diag.error("cycle", f"View '{view.path}' includes itself", view.loc)
				break
			if path not in seen:
				seen.add(path)
				pending += includes(model.index[path])


def _validate(model: Model, diag: Diagnostics) -> None:
	ontology = model.ontology
	for decl in ontology.decls:
		_checkAnnotations(model, decl.ann, placesOf(decl), decl.loc, diag)
		if decl.kind == "type":
			_checkType(model, decl.definition, decl.ann, decl.loc, decl.path, diag)
			if decl.fields is not None:
				fieldNames = {item.name for item in decl.fields}
				_checkAttrs(model, decl, decl.fields, lambda names=fieldNames: names, diag)
		elif decl.kind == "entity":
			if decl.base:
				base = model.get(decl.base)
				if not base or base.kind != "entity":
					diag.error("reference", f"Base of '{decl.path}' is not an entity: '{decl.base}'", decl.loc)
				elif decl.path in model.lineage(decl.base):
					diag.error("cycle", f"Specialisation cycle through '{decl.path}'", decl.loc)
				else:
					inherited = model.entityAttrs(decl.base)
					for attr in decl.attrs:
						if attr.name in inherited:
							diag.error("duplicate", f"'{decl.path}.{attr.name}' redeclares an inherited attribute", attr.loc)
			_checkAttrs(model, decl, decl.attrs, lambda path=decl.path: set(model.entityAttrs(path)), diag)
			# NOTE: Facets of a base apply here too, so their names must not equal this entity's attributes.
			for attr in decl.attrs:
				facet = model.facets(decl.path).get(attr.name)
				if facet and facet.subject != decl.path:
					diag.error("collision", f"'{decl.path}.{attr.name}' collides with inherited facet '{facet.path}'", attr.loc)
		elif decl.kind == "facet":
			subject = model.get(decl.subject)
			if not subject or (subject.kind != "entity" and not isAssociation(subject)):
				diag.error("reference", f"Facet subject is not an entity or association: '{decl.subject}'", decl.loc)
				continue
			name = lastSegment(decl.path)
			if name in model.ownNames(decl.subject):
				diag.error("collision", f"Facet '{name}' collides with an attribute or role of '{decl.subject}'", decl.loc)
			clash = [
				other
				for path in model.lineage(decl.subject)
				for other in model.facetsOf(path)
				if other is not decl and lastSegment(other.path) == name
			]
			if clash:
				diag.error("collision", f"Facet name '{name}' is used twice on '{decl.subject}'", decl.loc)
			_checkAttrs(
				model, decl, decl.attrs,
				lambda facet=decl: {attr.name for attr in facet.attrs} | model.ownNames(facet.subject), diag,
			)
		elif decl.kind == "relation":
			_validateRelation(model, decl, diag)
		elif decl.kind == "view":
			for line in decl.viewLines:
				_validateViewLine(model, line, diag)
		elif decl.kind == "map":
			_validateMap(model, decl, diag)
	_checkViewCycles(model, diag)
	# NOTE: A verb read from an entity must identify one relation for any compatible object type.
	uses: list[tuple[str, str, str, Decl]] = []
	for decl in ontology.decls:
		if decl.kind != "relation" or not decl.arrow:
			continue
		subject, obj = decl.participants[0].type, decl.participants[1].type
		uses.append((subject, decl.arrow.verb, obj, decl))
		if decl.arrow.inverse and not isSymmetric(decl):
			uses.append((obj, decl.arrow.inverse, subject, decl))

	def related(a: str, b: str) -> bool:
		return model.isA(a, b) or model.isA(b, a)

	for i, (fromA, verbA, toA, declA) in enumerate(uses):
		for fromB, verbB, toB, declB in uses[i + 1 :]:
			if verbA == verbB and related(fromA, fromB) and related(toA, toB):
				diag.error(
					"collision",
					f"Verb '{verbA}' is ambiguous from '{fromA}' to '{toA}' ('{declA.path}', '{declB.path}')",
					declB.loc,
				)


# -----------------------------------------------------------------------------
#
# NORMAL FORM
#
# -----------------------------------------------------------------------------


def _annotationRank(key: str) -> tuple[int, str]:
	return (ANNOTATION_KEYS.index(key) if key in ANNOTATION_KEYS else len(ANNOTATION_KEYS), key)


def _sortAnnotations(ann: Annotations) -> Annotations:
	pairs = [
		(key, "+".join(sorted(value.split("+"))) if key == "privacy" and isinstance(value, str) else value)
		for key, value in ann
	]
	return sorted(pairs, key=lambda pair: _annotationRank(pair[0]))


def _depKey(dep: Dep) -> tuple[int, int, str]:
	# NOTE: `$inputs` first, then names and paths, `...` last.
	if dep.ellipsis:
		return (2, 0, "...")
	if dep.input:
		return (0, 0, dep.input)
	return (1, 0, dep.local or f"{dep.path}.{dep.attr}")


def _normaliseType(type: TypeExpr | None, ordered: bool) -> TypeExpr | None:
	if type and type.values is not None and not ordered:
		return replace(type, values=sorted(type.values))
	return type


# Function: normaliseOntology
# Returns the canonical form of `ontology`: sorted, defaults omitted, annotations ordered.
def normaliseOntology(ontology: Ontology) -> Ontology:
	header = dict(ontology.header)
	defaultCard = header.get("card", "?")
	defaultCounts = header.get("rel", "*:*")

	def normaliseAttr(attr: Attr) -> Attr:
		return replace(
			attr,
			card=None if attr.card == defaultCard else attr.card,
			ann=_sortAnnotations(attr.ann),
			type=_normaliseType(attr.type, annotation(attr.ann, "ordered") is True),
			deps=sorted(attr.deps, key=_depKey) if attr.deps else attr.deps,
		)

	def normaliseAttrs(attrs: list[Attr]) -> list[Attr]:
		return sorted((normaliseAttr(attr) for attr in attrs), key=lambda attr: attr.name)

	def normaliseDecl(decl: Decl) -> Decl:
		base = replace(decl, ann=_sortAnnotations(decl.ann))
		if decl.kind == "type":
			return replace(
				base,
				definition=_normaliseType(decl.definition, annotation(decl.ann, "ordered") is True),
				fields=normaliseAttrs(decl.fields) if decl.fields is not None else None,
			)
		if decl.kind == "view":
			lines = [
				replace(line, facets=sorted(line.facets) if isinstance(line.facets, list) else line.facets)
				for line in decl.viewLines
			]
			return replace(base, viewLines=sorted(lines, key=lambda line: line.path + (f".{line.member}" if line.member else "")))
		if decl.kind == "map":
			return replace(base, mapLines=sorted(decl.mapLines, key=lambda line: (line.fromValue, line.toValue, line.match)))
		if decl.kind == "domain":
			return base
		normal = replace(base, attrs=normaliseAttrs(decl.attrs))
		if decl.kind == "relation":
			participants = [replace(item, card=None if item.card == "1" else item.card) for item in decl.participants]
			if decl.arrow:
				normal.arrow = replace(decl.arrow, counts=None if decl.arrow.counts == defaultCounts else decl.arrow.counts)
			else:
				participants.sort(key=lambda item: item.role)
			normal.participants = participants
		return normal

	decls = [normaliseDecl(decl) for decl in ontology.decls]

	def byPath(kind: str) -> list[Decl]:
		return sorted((decl for decl in decls if decl.kind == kind), key=lambda decl: decl.path)

	facets = byPath("facet")
	relations = byPath("relation")
	relationPaths = {decl.path for decl in relations}
	ordered = byPath("domain") + byPath("type")
	placed: set[str] = set()
	for entity in byPath("entity"):
		ordered.append(entity)
		for facet in facets:
			if facet.subject == entity.path:
				ordered.append(facet)
				placed.add(facet.path)
	ordered += [facet for facet in facets if facet.path not in placed and facet.subject not in relationPaths]
	for relation in relations:
		ordered.append(relation)
		ordered += [facet for facet in facets if facet.subject == relation.path]
	ordered += byPath("map") + byPath("view")
	return replace(
		ontology,
		header=sorted(ontology.header, key=lambda pair: HEADER_KEYS.index(pair[0]) if pair[0] in HEADER_KEYS else len(HEADER_KEYS)),
		uses=sorted(ontology.uses),
		decls=ordered,
	)


# -----------------------------------------------------------------------------
#
# PRINTING
#
# -----------------------------------------------------------------------------


class Namer:
	"""Writes paths in their shortest form: relative to the namespace, else through an alias."""

	def __init__(self, namespace: str | None, uses: list[tuple[str, str]]):
		self.namespace = namespace
		self.uses = uses
		self.aliases = dict(uses)

	def __call__(self, path: str) -> str:
		prefix = f"{self.namespace}/"
		if path.startswith(prefix):
			relative = path[len(prefix) :]
			head, slash, _ = relative.partition("/")
			if not slash or head not in self.aliases:
				return relative
		best: tuple[str, str] | None = None
		for alias, target in self.uses:
			if path.startswith(f"{target}/") and (not best or len(target) > len(best[1])):
				best = (alias, target)
		if best:
			return f"{best[0]}{path[len(best[1]) :]}"
		raise ValueError(f"No short form for '{path}': add a @use alias")


class Printer:
	"""Renders the lines of one ontology: shortest names, annotations and docs."""

	def __init__(self, ontology: Ontology):
		self.short = Namer(ontology.namespace, ontology.uses)

	def _tail(self, ann: Annotations, doc: str | None) -> list[str]:
		pairs = [(key, self.short(value)) if key in PATH_KEYS and isinstance(value, str) else (key, value) for key, value in ann]
		return [part for part in (printAnnotations(pairs, ANNOTATION_KEYS), f"-- {doc}" if doc else "") if part]

	@staticmethod
	def _join(parts: list[str]) -> str:
		return " ".join(part for part in parts if part)

	def typeText(self, type: TypeExpr | None) -> str:
		if not type:
			return ""
		if type.builtin:
			return type.builtin
		if type.unknown:
			return "..."
		if type.values is not None:
			prefix = "|" if len(type.values) == 1 and not type.open else ""
			return prefix + "|".join(type.values) + ("|..." if type.open else "")
		return f"{self.short(type.path)}.{type.attr}" if type.attr else self.short(type.path)

	def depText(self, dep: Dep) -> str:
		if dep.ellipsis:
			return "..."
		if dep.input:
			return f"${dep.input}"
		return dep.local or f"{self.short(dep.path)}.{dep.attr}"

	def attr(self, item: Attr, doc: bool = True) -> str:
		"""An attribute line without indentation."""
		deps = f"<- {', '.join(self.depText(dep) for dep in item.deps)}" if item.deps else ""
		return self._join(
			[item.card or "", "~" if item.derived else "", item.name, self.typeText(item.type), deps]
			+ self._tail(item.ann, item.doc if doc else None)
		)

	def head(self, decl: Decl, doc: bool = True) -> str:
		"""A declaration's header line."""
		docText = decl.doc if doc else None
		short = self.short
		if decl.kind == "type":
			return self._join([f"{short(decl.path)} =", self.typeText(decl.definition)] + self._tail(decl.ann, docText))
		if decl.kind == "entity":
			return self._join([short(decl.path), f"< {short(decl.base)}" if decl.base else ""] + self._tail(decl.ann, docText))
		if decl.kind == "facet":
			return self._join([f"{short(decl.path)} of {short(decl.subject)}"] + self._tail(decl.ann, docText))
		if decl.kind == "view":
			return self._join([f"@view {short(decl.path)}"] + self._tail([], docText))
		if decl.kind == "domain":
			return self._join([f"@domain {short(decl.path)}"] + self._tail([], docText))
		if decl.kind == "map":
			return self._join([f"@map {short(decl.path)} {short(decl.mapFrom)} -> {short(decl.mapTo)}"] + self._tail(decl.ann, docText))
		if decl.arrow:
			subject, obj = decl.participants
			verbs = decl.arrow.verb + (f"/{decl.arrow.inverse}" if decl.arrow.inverse else "")
			return self._join(
				[short(subject.type), f"-{verbs}->", short(obj.type), decl.arrow.counts or ""] + self._tail(decl.ann, docText)
			)
		parts = [
			("" if item.role == lastSegment(item.type) else f"{item.role}: ") + (f"{item.card} " if item.card else "") + short(item.type)
			for item in decl.participants
		]
		return self._join([f"{short(decl.path)}({', '.join(parts)})"] + self._tail(decl.ann, docText))

	def viewLine(self, line: ViewLine) -> str:
		if "." in line.path:
			subject, verb, obj = line.path.split(".")
			return f"{self.short(subject)}.{verb}.{self.short(obj)}"
		facets = ""
		if line.facets is not None:
			facets = "[*]" if line.facets == "*" else f"[{', '.join(line.facets)}]"
		return f"{self.short(line.path)}{facets}{f'.{line.member}' if line.member else ''}"

	def mapLine(self, line: MapLine, doc: bool = True) -> str:
		return self._join([line.fromValue, line.match, line.toValue, f"-- {line.doc}" if doc and line.doc else ""])

	def block(self, decl: Decl) -> list[str]:
		"""A declaration and its body lines."""
		if decl.kind == "view":
			body = [self.viewLine(line) for line in decl.viewLines]
		elif decl.kind == "map":
			body = [self.mapLine(line) for line in decl.mapLines]
		else:
			body = [self.attr(item) for item in (decl.fields or [] if decl.kind == "type" else decl.attrs)]
		return [self.head(decl)] + [f"  {line}" for line in body]


# Function: printOntology
# Prints a normalised `ontology` as normal-form text.
def printOntology(ontology: Ontology) -> str:
	printer = Printer(ontology)
	headLine = f"@ontology {ontology.namespace}" + (f" {printArguments(ontology.header)}" if ontology.header else "")
	sections: list[list[list[str]]] = [[[headLine] + [f"@use {target} as {alias}" for alias, target in ontology.uses]]]
	bodies: list[list[list[str]]] = [[] for _ in range(6)]
	relationPaths = {decl.path for decl in ontology.decls if decl.kind == "relation"}
	for decl in ontology.decls:
		section = SECTIONS["relation"] if decl.kind == "facet" and decl.subject in relationPaths else SECTIONS[decl.kind]
		bodies[section].append(printer.block(decl))
	sections += [section for section in bodies if section]
	texts: list[str] = []
	for section in sections:
		text = ""
		for index, lines in enumerate(section):
			if index > 0:
				# NOTE: Declarations with a body are surrounded by a blank line; bodiless ones are adjacent.
				text += "\n\n" if len(lines) > 1 or len(section[index - 1]) > 1 else "\n"
			text += "\n".join(lines)
		texts.append(text)
	return "\n\n".join(texts) + "\n"


# -----------------------------------------------------------------------------
#
# JSON FORM
#
# -----------------------------------------------------------------------------


def _typeToJson(type: TypeExpr) -> dict[str, Any]:
	if type.builtin:
		return {"builtin": type.builtin}
	if type.unknown:
		return {"unknown": True}
	if type.values is not None:
		return {"values": list(type.values), "open": type.open}
	return {"path": type.path, "attr": type.attr} if type.attr else {"path": type.path}


def _depToJson(dep: Dep) -> dict[str, Any]:
	if dep.ellipsis:
		return {"ellipsis": True}
	if dep.input:
		return {"input": dep.input}
	if dep.local:
		return {"local": dep.local}
	return {"path": dep.path, "attr": dep.attr}


def _compact(data: dict[str, Any]) -> dict[str, Any]:
	return {key: value for key, value in data.items() if value is not None}


def _annToJson(ann: Annotations) -> dict[str, Any] | None:
	return dict(ann) if ann else None


def _toJson(ontology: Ontology, ids: dict[str, str] | None) -> dict[str, Any]:
	header = dict(ontology.header)
	defaultCard = header.get("card", "?")
	defaultCounts = header.get("rel", "*:*")

	def attr(item: Attr) -> dict[str, Any]:
		return _compact({
			"name": item.name,
			"card": item.card or defaultCard,
			"derived": True if item.derived else None,
			"type": _typeToJson(item.type) if item.type else None,
			"deps": [_depToJson(dep) for dep in item.deps] if item.deps else None,
			"ann": _annToJson(item.ann),
			"doc": item.doc,
		})

	def attrs(items: list[Attr]) -> list[dict[str, Any]] | None:
		return [attr(item) for item in items] or None

	def decl(item: Decl) -> dict[str, Any]:
		common = {"kind": item.kind, "path": item.path}
		tail = {"ann": _annToJson(item.ann), "doc": item.doc}
		if item.kind == "type":
			return _compact({
				**common,
				"def": _typeToJson(item.definition) if item.definition else None,
				"fields": [attr(field) for field in item.fields] if item.fields is not None else None,
				**tail,
			})
		if item.kind == "entity":
			return _compact({**common, "base": item.base, "attrs": attrs(item.attrs), **tail})
		if item.kind == "facet":
			return _compact({**common, "subject": item.subject, "attrs": attrs(item.attrs), **tail})
		if item.kind == "view":
			lines = [_compact({"path": line.path, "facets": line.facets, "member": line.member}) for line in item.viewLines]
			return _compact({**common, "lines": lines, "doc": item.doc})
		if item.kind == "domain":
			return _compact({**common, "doc": item.doc})
		if item.kind == "map":
			lines = [
				_compact({"from": line.fromValue, "match": line.match, "to": line.toValue, "doc": line.doc})
				for line in item.mapLines
			]
			return _compact({**common, "from": item.mapFrom, "to": item.mapTo, "lines": lines, **tail})
		arrow = None
		if item.arrow:
			arrow = _compact({"verb": item.arrow.verb, "inverse": item.arrow.inverse, "counts": item.arrow.counts or defaultCounts})
		return _compact({
			**common,
			"participants": [{"role": p.role, "card": p.card or "1", "type": p.type} for p in item.participants],
			"arrow": arrow,
			"attrs": attrs(item.attrs),
			**tail,
		})

	return _compact({
		"format": ONTOLOGY_FORMAT,
		"namespace": ontology.namespace,
		"header": header or None,
		"uses": dict(ontology.uses) or None,
		"decls": [decl(item) for item in ontology.decls],
		"ids": dict(sorted(ids.items())) if ids else None,
	})


# NOTE: JSON is read strictly: every object has exactly the members the schema allows, with no
# nulls and no `false` flags, so that nothing is silently dropped before the text round trip.
# Each reader takes `(value, what)`, `what` naming the location for messages.


def _members(value: Any, what: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
	if not isinstance(value, dict):
		raise ValueError(f"{what} must be an object")
	if missing := [key for key in required if key not in value]:
		raise ValueError(f"{what} lacks {', '.join(missing)}")
	if unknown := [key for key in value if key not in required and key not in optional]:
		raise ValueError(f"{what} has unexpected {', '.join(unknown)}")
	return value


def _string(value: Any, what: str) -> str:
	if not isinstance(value, str):
		raise ValueError(f"{what} must be a string")
	return value


def _card(value: Any, what: str) -> str:
	if value not in CARDS:
		raise ValueError(f"{what}: card must be one of {' '.join(CARDS)}")
	return value


def _flag(value: Any, what: str) -> bool:
	if value is not True:
		raise ValueError(f"{what} must be true when present")
	return True


def _array(value: Any, what: str, nonEmpty: bool = False) -> list[Any]:
	if not isinstance(value, list) or (nonEmpty and not value):
		raise ValueError(f"{what} must be a{' non-empty' if nonEmpty else 'n'} array")
	return value


def _strings(value: Any, what: str) -> list[tuple[str, str]]:
	return [(key, _string(item, f"{what}.{key}")) for key, item in _members(value, what, (), tuple(value or ())).items()]


def _annFromJson(value: Any, what: str) -> Annotations:
	pairs = _members(value, what, (), tuple(value or ())).items()
	return [(key, True if item is True else _string(item, f"{what}.{key}")) for key, item in pairs]


def _optional(data: dict[str, Any], key: str, read, what: str, default: Any = None) -> Any:
	return read(data[key], f"{what}.{key}") if key in data else default


def _typeFromJson(value: Any, what: str) -> TypeExpr:
	keys = set(value) if isinstance(value, dict) else None
	if keys == {"builtin"}:
		if value["builtin"] not in BUILTINS:
			raise ValueError(f"{what}: unknown built-in type")
		return TypeExpr(builtin=value["builtin"])
	if keys == {"unknown"}:
		return TypeExpr(unknown=_flag(value["unknown"], what))
	if keys == {"values", "open"}:
		if not isinstance(value["open"], bool):
			raise ValueError(f"{what}.open must be a boolean")
		values = [_string(item, f"{what}.values") for item in _array(value["values"], f"{what}.values", True)]
		return TypeExpr(values=values, open=value["open"])
	if keys in ({"path"}, {"path", "attr"}):
		return TypeExpr(path=_string(value["path"], what), attr=_optional(value, "attr", _string, what))
	raise ValueError(f"{what} must be one type expression: builtin, path[+attr], values+open or unknown")


def _depFromJson(value: Any, what: str) -> Dep:
	keys = set(value) if isinstance(value, dict) else None
	if keys == {"local"}:
		return Dep(local=_string(value["local"], what))
	if keys == {"input"}:
		return Dep(input=_string(value["input"], what))
	if keys == {"path", "attr"}:
		return Dep(path=_string(value["path"], what), attr=_string(value["attr"], what))
	if keys == {"ellipsis"}:
		return Dep(ellipsis=_flag(value["ellipsis"], what))
	raise ValueError(f"{what} must be one dependency: local, input, path+attr or ellipsis")


def _attrFromJson(value: Any, what: str) -> Attr:
	data = _members(value, what, ("name", "card"), ("derived", "type", "deps", "ann", "doc"))
	return Attr(
		name=_string(data["name"], what),
		card=_card(data["card"], what),
		derived=_optional(data, "derived", _flag, what, False),
		type=_optional(data, "type", _typeFromJson, what),
		deps=_optional(data, "deps", lambda items, at: [_depFromJson(item, at) for item in _array(items, at, True)], what),
		ann=_optional(data, "ann", _annFromJson, what, []),
		doc=_optional(data, "doc", _string, what),
	)


def _attrsFromJson(value: Any, what: str) -> list[Attr]:
	return [_attrFromJson(item, f"{what}[{index}]") for index, item in enumerate(_array(value, what, True))]


def _participantFromJson(value: Any, what: str) -> Participant:
	data = _members(value, what, ("role", "card", "type"))
	return Participant(_string(data["role"], what), _card(data["card"], what), _string(data["type"], what))


def _arrowFromJson(value: Any, what: str) -> Arrow:
	data = _members(value, what, ("verb", "counts"), ("inverse",))
	if not RE_COUNTS.fullmatch(_string(data["counts"], what)):
		raise ValueError(f"{what}: invalid counts")
	return Arrow(_string(data["verb"], what), _optional(data, "inverse", _string, what), data["counts"])


def _viewLineFromJson(value: Any, what: str) -> ViewLine:
	data = _members(value, what, ("path",), ("facets", "member"))
	facets = data.get("facets")
	if "facets" in data and facets != "*":
		facets = [_string(item, f"{what}.facets") for item in _array(facets, f"{what}.facets", True)]
	return ViewLine(_string(data["path"], what), facets, _optional(data, "member", _string, what))


def _mapLineFromJson(value: Any, what: str) -> MapLine:
	data = _members(value, what, ("from", "match", "to"), ("doc",))
	return MapLine(_string(data["from"], what), _string(data["match"], what), _string(data["to"], what), _optional(data, "doc", _string, what))


def _declFromJson(value: Any, what: str) -> Decl:
	kind = value.get("kind") if isinstance(value, dict) else None
	if kind not in DECL_MEMBERS:
		raise ValueError(f"{what}: unknown declaration kind '{kind}'")
	required, optional = DECL_MEMBERS[kind]
	data = _members(value, what, ("kind", "path") + required, optional)
	what = f"{what} '{data['path']}'"
	decl = Decl(
		kind=kind, path=_string(data["path"], what),
		ann=_optional(data, "ann", _annFromJson, what, []), doc=_optional(data, "doc", _string, what),
		attrs=_optional(data, "attrs", _attrsFromJson, what, []),
	)
	if kind == "type":
		if "def" in data and "fields" in data:
			raise ValueError(f"{what} has both def and fields")
		decl.definition = _optional(data, "def", _typeFromJson, what)
		decl.fields = _optional(data, "fields", _attrsFromJson, what)
	elif kind == "entity":
		decl.base = _optional(data, "base", _string, what)
	elif kind == "facet":
		decl.subject = _string(data["subject"], what)
	elif kind == "relation":
		decl.participants = [_participantFromJson(item, f"{what}.participants") for item in _array(data["participants"], what)]
		decl.arrow = _optional(data, "arrow", _arrowFromJson, what)
	elif kind == "map":
		decl.mapFrom, decl.mapTo = _string(data["from"], what), _string(data["to"], what)
		decl.mapLines = [_mapLineFromJson(item, f"{what}.lines") for item in _array(data["lines"], what)]
	elif kind == "view":
		decl.viewLines = [_viewLineFromJson(item, f"{what}.lines") for item in _array(data["lines"], what)]
	return decl


def _fromJson(value: Any) -> Ontology:
	data = _members(value, "ontology", ("format", "namespace", "decls"), ("header", "uses", "ids"))
	if data["format"] != ONTOLOGY_FORMAT:
		raise ValueError(f"format must be '{ONTOLOGY_FORMAT}'")
	return Ontology(
		namespace=_string(data["namespace"], "namespace"),
		header=_optional(data, "header", _strings, "ontology", []),
		uses=_optional(data, "uses", _strings, "ontology", []),
		decls=[_declFromJson(item, f"decls[{index}]") for index, item in enumerate(_array(data["decls"], "decls"))],
		ids=dict(_optional(data, "ids", _strings, "ontology", [])) or None,
	)


# -----------------------------------------------------------------------------
#
# API
#
# -----------------------------------------------------------------------------


# Function: parseOntology
# Parses `sources` (one or several files of one ontology) into an ontology with full paths.
def parseOntology(sources: list[Source]) -> Ontology:
	diag = Diagnostics()
	ontology = Ontology()
	seen: dict[str, Decl] = {}
	for source in sources:
		_parseFile(source, ontology, seen, diag)
	if ontology.namespace is None:
		diag.error("header", "Missing @ontology directive")
	ontology.diagnostics = diag.check()
	return ontology


# Function: validateOntology
# Checks references, names and structure of `ontology`; raises `FormatError` on errors.
def validateOntology(ontology: Ontology) -> Ontology:
	diag = Diagnostics(list(ontology.diagnostics))
	_validate(Model(ontology), diag)
	ontology.diagnostics = diag.check()
	return ontology


# Function: loadOntology
# Parses and validates `sources`.
def loadOntology(sources: list[Source]) -> Ontology:
	return validateOntology(parseOntology(sources))


# Function: formatOntology
# Normal-form text of `sources`.
def formatOntology(sources: list[Source]) -> str:
	return printOntology(normaliseOntology(loadOntology(sources)))


# Function: ontologyToJson
# The JSON form of `ontology`, with the identity sidecar `ids` when given.
def ontologyToJson(ontology: Ontology, ids: dict[str, str] | None = None) -> dict[str, Any]:
	return _toJson(normaliseOntology(ontology), ids if ids is not None else ontology.ids)


# Function: ontologyFromJson
# Loads the JSON form through its normal-form text; data that does not round-trip is rejected.
def ontologyFromJson(data: Any, name: str = "ontology.json") -> Ontology:
	loc = Loc(name, 0)

	def fail(message: str) -> FormatError:
		diag = Diagnostics()
		diag.error("json", message, loc)
		return FormatError(diag.items)

	try:
		read = _fromJson(data)
		normal = normaliseOntology(read)
		text = printOntology(normal)
		expected = _toJson(normal, None)
	except ValueError as error:
		raise fail(f"Invalid ontology JSON: {error}") from error
	ontology = loadOntology([Source(name, text)])
	if _toJson(normaliseOntology(ontology), None) != expected:
		raise fail("Ontology JSON does not round-trip through its text form")
	ontology.ids = read.ids
	return ontology


# EOF
