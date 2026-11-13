"""Module: ontology.formatter — canonical ontology ordering and text/JSON rendering."""

from __future__ import annotations

from dataclasses import (
	replace,
)
from typing import (
	Any,
)
from ..text import (
	Annotations,
	annotation,
	lastSegment,
	printAnnotations,
	printArguments,
	withDoc,
)
from .model import (
	ANNOTATION_KEYS,
	Attr,
	Decl,
	Dep,
	HEADER_KEYS,
	MapLine,
	ONTOLOGY_FORMAT,
	Ontology,
	PATH_KEYS,
	SECTIONS,
	TypeExpr,
	ViewLine,
	vocabularyValues,
)

# -----------------------------------------------------------------------------
#
# UTILITIES
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


def _normaliseType(type: TypeExpr | None, ordered: bool, hierarchical: bool = False) -> TypeExpr | None:
	if type and type.values is not None:
		values = vocabularyValues(type.values, ordered) if hierarchical else list(type.values) if ordered else sorted(type.values)
		return replace(type, values=values)
	return type


# -----------------------------------------------------------------------------
#
# OPERATIONS
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

	def _tail(self, ann: Annotations) -> list[str]:
		pairs = [(key, self.short(value)) if key in PATH_KEYS and isinstance(value, str) else (key, value) for key, value in ann]
		return [part for part in (printAnnotations(pairs, ANNOTATION_KEYS),) if part]

	@staticmethod
	def _Join(parts: list[str]) -> str:
		return " ".join(part for part in parts if part)

	def typeText(self, type: TypeExpr | None) -> str:
		"""Render `type` using shortest paths and vocabulary spelling."""
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
		"""Render dependency `dep` as a local name, input or attribute path."""
		if dep.ellipsis:
			return "..."
		if dep.input:
			return f"${dep.input}"
		return dep.local or f"{self.short(dep.path)}.{dep.attr}"

	def attr(self, item: Attr, doc: bool = True, indent: str = "") -> str:
		"""An attribute line after `indent`, with its doc aligned."""
		deps = f"<- {', '.join(self.depText(dep) for dep in item.deps)}" if item.deps else ""
		code = self._Join([item.card or "", "~" if item.derived else "", item.name, self.typeText(item.type), deps] + self._tail(item.ann))
		return withDoc(indent + code, item.doc if doc else None)

	def head(self, decl: Decl, doc: bool = True) -> str:
		"""A declaration's header line, with its doc aligned."""
		return withDoc(self.headCode(decl), decl.doc if doc else None)

	def headCode(self, decl: Decl) -> str:
		"""A declaration's header line without its doc."""
		short = self.short
		if decl.kind == "type":
			tree = decl.definition and decl.definition.values is not None and annotation(decl.ann, "hierarchical") is True
			return self._Join([f"{short(decl.path)} =", "" if tree else self.typeText(decl.definition)] + self._tail(decl.ann))
		if decl.kind == "entity":
			return self._Join([short(decl.path), f"< {short(decl.base)}" if decl.base else ""] + self._tail(decl.ann))
		if decl.kind == "facet":
			return self._Join([f"{short(decl.path)} of {short(decl.subject)}"] + self._tail(decl.ann))
		if decl.kind == "view":
			return self._Join([f"@view {short(decl.path)}"] + [])
		if decl.kind == "domain":
			return self._Join([f"@domain {short(decl.path)}"] + [])
		if decl.kind == "map":
			return self._Join([f"@map {short(decl.path)} {short(decl.mapFrom)} -> {short(decl.mapTo)}"] + self._tail(decl.ann))
		if decl.arrow:
			subject, obj = decl.participants
			verbs = decl.arrow.verb + (f"/{decl.arrow.inverse}" if decl.arrow.inverse else "")
			return self._Join(
				[short(subject.type), f"-{verbs}->", short(obj.type), decl.arrow.counts or ""] + self._tail(decl.ann)
			)
		parts = [
			("" if item.role == lastSegment(item.type) else f"{item.role}: ") + (f"{item.card} " if item.card else "") + short(item.type)
			for item in decl.participants
		]
		return self._Join([f"{short(decl.path)}({', '.join(parts)})"] + self._tail(decl.ann))

	def viewLine(self, line: ViewLine) -> str:
		"""Render the selected path, facets and member of `line`."""
		if "." in line.path:
			subject, verb, obj = line.path.split(".")
			return f"{self.short(subject)}.{verb}.{self.short(obj)}"
		facets = ""
		if line.facets is not None:
			facets = "[*]" if line.facets == "*" else f"[{', '.join(line.facets)}]"
		return f"{self.short(line.path)}{facets}{f'.{line.member}' if line.member else ''}"

	def mapLine(self, line: MapLine, doc: bool = True, indent: str = "") -> str:
		"""Render vocabulary map `line` after `indent`, optionally with its doc aligned."""
		return withDoc(indent + self._Join([line.fromValue, line.match, line.toValue]), line.doc if doc else None)

	def block(self, decl: Decl) -> list[str]:
		"""A declaration and its body lines."""
		if decl.kind == "view":
			body = [f"  {self.viewLine(line)}" for line in decl.viewLines]
		elif decl.kind == "map":
			body = [self.mapLine(line, indent="  ") for line in decl.mapLines]
		elif decl.kind == "type" and decl.definition and decl.definition.values is not None and annotation(decl.ann, "hierarchical") is True:
			body = ["  " * (path.count("/") + 1) + lastSegment(path) for path in decl.definition.values]
			if decl.definition.open:
				body.append("  ...")
		else:
			body = [self.attr(item, indent="  ") for item in (decl.fields or [] if decl.kind == "type" else decl.attrs)]
		return [self.head(decl)] + body

# -----------------------------------------------------------------------------
#
# JSON ENCODING
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


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def normaliseOntology(ontology: Ontology) -> Ontology:
	"""Return canonical `ontology`: sorted declarations, omitted defaults and ordered annotations."""
	header = dict(ontology.header)
	defaultCard = header.get("card", "?")
	defaultCounts = header.get("rel", "*:*")

	def normaliseAttr(attr: Attr) -> Attr:
		return replace(
			attr,
			card=None if attr.card == defaultCard else attr.card,
			ann=_sortAnnotations(attr.ann),
			type=_normaliseType(attr.type, annotation(attr.ann, "ordered") is True, annotation(attr.ann, "hierarchical") is True),
			deps=sorted(attr.deps, key=_depKey) if attr.deps else attr.deps,
		)

	def normaliseAttrs(attrs: list[Attr]) -> list[Attr]:
		return sorted((normaliseAttr(attr) for attr in attrs), key=lambda attr: attr.name)

	def normaliseDecl(decl: Decl) -> Decl:
		base = replace(decl, ann=_sortAnnotations(decl.ann))
		if decl.kind == "type":
			return replace(
				base,
				definition=_normaliseType(decl.definition, annotation(decl.ann, "ordered") is True, annotation(decl.ann, "hierarchical") is True),
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


def printOntology(ontology: Ontology) -> str:
	"""Render an already normalized `ontology`; use `Operator.print` to normalize first."""
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


# EOF
