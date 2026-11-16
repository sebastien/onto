"""Module: ontology.model — declarations, grammar tables and semantic ontology lookups."""

from __future__ import annotations

import re
from dataclasses import (
	dataclass,
	field,
)
from ..text import (
	Annotations,
	Diagnostic,
	Loc,
	annotation,
	isPath,
	lastSegment,
)

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


ONTOLOGY_FORMAT = "onto.ontology/1"
BUILTINS = ("Text", "Integer", "Number", "Boolean", "Date", "DateTime", "Duration", "Amount", "Percent")

# NOTE: Where each annotation applies (None: anywhere); the key order is the normal-form order.
ANNOTATION_PLACES: dict[str, set[str] | None] = {
	"key": {"attribute"},
	"id": {"attribute"},
	"privacy": {"attribute"},
	"default": {"attribute"},
	"kind": {"relation"},
	"layer": {"entity", "relation"},
	"context": {"binary"},
	"subjectRole": {"binary"},
	"objectRole": {"binary"},
	"ctx": {"facet"},
	"ordered": {"vocabulary"},
	"hierarchical": {"vocabulary"},
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
HEADER_KEYS = ["rev", "src", "card", "cards", "rel", "layering"]
LAYERINGS = ("declared",)
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
RE_MAP_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)\s+([a-z]+)\s+([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)")
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
	diagnostics: list[Diagnostic] = field(default_factory=list)
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
	hierarchical: bool = False
	qualifiers: dict[str, str] = field(default_factory=dict)
	conflicts: list[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def _typeKey(type: TypeExpr) -> str:
	return f"{type.path}.{type.attr}" if type.attr else str(type.path)


def vocabularyValues(values: list[str], ordered: bool = False) -> list[str]:
	"""Expand taxonomy ancestors and return depth-first paths, sorting siblings unless `ordered`."""
	# NOTE: Preserve malformed input for validation rather than building cyclic empty paths.
	if not all(isPath(value) for value in values):
		return list(values)
	children: dict[str, dict[str, None]] = {"": {}}
	for value in values:
		parent = ""
		for segment in value.split("/"):
			path = f"{parent}/{segment}" if parent else segment
			children.setdefault(parent, {})[path] = None
			children.setdefault(path, {})
			parent = path
	result: list[str] = []
	pending = list(reversed(list(children[""]) if ordered else sorted(children[""])))
	while pending:
		path = pending.pop()
		result.append(path)
		pending.extend(reversed(list(children[path]) if ordered else sorted(children[path])))
	return result


# -----------------------------------------------------------------------------
#
# OPERATIONS
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
		"""Find declaration `path`, or return None when absent."""
		return self.index.get(path) if path else None

	def namespaces(self) -> set[str]:
		"""Known namespace prefixes, including imported declarations carried by this ontology."""
		result = {self.ontology.namespace} if self.ontology.namespace else set()
		for path in self.index:
			parts = path.split("/")
			result.update("/".join(parts[:index]) for index in range(1, len(parts)) if "." not in "/".join(parts[:index]))
		return result

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
		"""Whether `path` is `ancestor` or specializes it."""
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
		"""Return facets declared directly on `path`."""
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
		if resolved.kind == "vocab":
			resolved.ordered = any(annotation(pairs, "ordered") is True for pairs in sources)
			resolved.hierarchical = any(annotation(pairs, "hierarchical") is True for pairs in sources)
			if resolved.hierarchical:
				resolved.values = vocabularyValues(resolved.values or [], resolved.ordered)
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
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def arrowPath(subject: str, verb: str, obj: str) -> str:
	"""Return the binary relation path `subject.verb.obj`."""
	return f"{subject}.{verb}.{obj}"


def isAssociation(decl: Decl | None) -> bool:
	"""Whether `decl` is an identity-bearing n-ary relation, usable as a participant."""
	return decl is not None and decl.kind == "relation" and decl.arrow is None


def isSymmetric(decl: Decl) -> bool:
	"""Whether binary relation `decl` reads the same in both directions."""
	return (
		decl.arrow is not None
		and decl.arrow.inverse == decl.arrow.verb
		and decl.participants[0].type == decl.participants[1].type
	)


# EOF
