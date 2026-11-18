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
	BUILTINS,
	Decl,
	Dep,
	HEADER_KEYS,
	MapLine,
	ONTOLOGY_FORMAT,
	Ontology,
	PATH_KEYS,
	QUALIFIERS,
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


def annotationRank(key: str) -> tuple[int, str]:
	return (ANNOTATION_KEYS.index(key) if key in ANNOTATION_KEYS else len(ANNOTATION_KEYS), key)


def sortAnnotations(ann: Annotations) -> Annotations:
	pairs = [
		(key, "+".join(sorted(value.split("+"))) if key == "privacy" and isinstance(value, str) else value)
		for key, value in ann
	]
	return sorted(pairs, key=lambda pair: annotationRank(pair[0]))


def depKey(dep: Dep) -> tuple[int, int, str]:
	# NOTE: `$inputs` first, then names and paths, `...` last.
	if dep.ellipsis:
		return (2, 0, "...")
	if dep.input:
		return (0, 0, dep.input)
	return (1, 0, dep.local or f"{dep.path}.{dep.attr}")


def normaliseType(type: TypeExpr | None, ordered: bool, hierarchical: bool = False) -> TypeExpr | None:
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
			if not slash or self.aliases.get(head, prefix + head) == prefix + head:
				return relative
		if name := self.aliasName(path):
			return name
		raise ValueError(f"No short form for '{path}': add a @use alias")

	def aliasName(self, path: str) -> str | None:
		"""Write `path` through the most specific alias, if any."""
		best: tuple[str, str] | None = None
		for alias, target in self.uses:
			if path.startswith(f"{target}/") and (not best or len(target) > len(best[1])):
				best = (alias, target)
		return f"{best[0]}{path[len(best[1]) :]}" if best else None


class Printer:
	"""Renders the lines of one ontology: shortest names, annotations and docs."""

	def __init__(self, ontology: Ontology):
		self.namer = Namer(ontology.namespace, ontology.uses)
		self.short = self.namer

	def typeName(self, path: str) -> str:
		"""Use an alias when `path` would otherwise look like a built-in type."""
		short = self.short(path)
		return (self.namer.aliasName(path) or short) if short in BUILTINS else short

	def tail(self, ann: Annotations) -> list[str]:
		pairs = [(key, self.annotationValue(key, value)) for key, value in ann]
		return [part for part in (printAnnotations(pairs, ANNOTATION_KEYS),) if part]

	def annotationValue(self, key: str, value: str | bool) -> str | bool:
		"""Annotation `value` with its paths in shortest form: path keys, and the vocabulary of a `?:V` qualifier."""
		if not isinstance(value, str):
			return value
		if key in PATH_KEYS:
			return self.short(value)
		if key in QUALIFIERS and value.startswith("?:"):
			return "?:" + self.short(value[2:])
		return value

	@staticmethod
	def AnnotationJoin(parts: list[str]) -> str:
		return " ".join(part for part in parts if part)

	def typeText(self, type: TypeExpr | None) -> str:
		"""Render `type` using shortest paths and vocabulary spelling."""
		if not type:
			return ""
		if type.builtin:
			return type.builtin
		if type.unknown:
			return "..."
		if type.range:
			return f"Range<{self.typeText(type.range)}>"
		if type.values is not None:
			prefix = "|" if len(type.values) == 1 and not type.open else ""
			return prefix + "|".join(type.values) + ("|..." if type.open else "")
		return f"{self.short(type.path)}.{type.attr}" if type.attr else self.typeName(type.path)

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
		code = self.AnnotationJoin([item.card or "", "~" if item.derived else "", item.name, self.typeText(item.type), deps] + self.tail(item.ann))
		return withDoc(indent + code, item.doc if doc else None)

	def head(self, decl: Decl, doc: bool = True) -> str:
		"""A declaration's header line, with its doc aligned."""
		return withDoc(self.headCode(decl), decl.doc if doc else None)

	def headCode(self, decl: Decl) -> str:
		"""A declaration's header line without its doc."""
		short = self.short
		if decl.kind == "type":
			tree = decl.definition and decl.definition.values is not None and annotation(decl.ann, "hierarchical") is True
			return self.AnnotationJoin([f"{self.typeName(decl.path)} =", "" if tree else self.typeText(decl.definition)] + self.tail(decl.ann))
		if decl.kind == "entity":
			return self.AnnotationJoin([self.typeName(decl.path), f"< {short(decl.base)}" if decl.base else ""] + self.tail(decl.ann))
		if decl.kind == "facet":
			return self.AnnotationJoin([f"{self.typeName(decl.path)} of {short(decl.subject)}"] + self.tail(decl.ann))
		if decl.kind == "view":
			param = decl.viewInput
			return f"@view {short(decl.path)}" + (f"({param.name}: {short(param.path)}.{param.attr})" if param else "")
		if decl.kind == "domain":
			return self.AnnotationJoin([f"@domain {short(decl.path)}"] + [])
		if decl.kind == "map":
			return self.AnnotationJoin([f"@map {short(decl.path)} {short(decl.mapFrom)} -> {short(decl.mapTo)}"] + self.tail(decl.ann))
		if decl.arrow:
			subject, obj = decl.participants
			verbs = decl.arrow.verb + (f"/{decl.arrow.inverse}" if decl.arrow.inverse else "")
			return self.AnnotationJoin(
				[short(subject.type), f"-{verbs}->", short(obj.type), decl.arrow.counts or ""] + self.tail(decl.ann)
			)
		parts = [
			("" if item.role == lastSegment(item.type) else f"{item.role}: ") + (f"{item.card} " if item.card else "") + short(item.type)
			for item in decl.participants
		]
		return self.AnnotationJoin([f"{self.typeName(decl.path)}({', '.join(parts)})"] + self.tail(decl.ann))

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
		return withDoc(indent + self.AnnotationJoin([line.fromValue, line.match, line.toValue]), line.doc if doc else None)

	def block(self, decl: Decl) -> list[str]:
		"""A declaration and its body lines."""
		if decl.kind == "view" and decl.viewInput:
			body = []
			for population in decl.viewPopulations:
				line = f"  {population.name}: {self.short(population.type)}"
				if population.parent:
					line += f" = {population.parent} {'<-' if population.reverse else '->'} {population.via}"
				if population.through:
					line += f" through {population.through}"
				if population.where:
					value = str(population.equals).lower() if isinstance(population.equals, bool) else population.equals
					line += f" where {population.where}={value}"
				body.append(line)
			body += [f"  {'? ' if l.optional else ''}{l.path}.{l.member}" + (f": {self.short(l.target)}" if l.target else "") for l in decl.viewLines]
		elif decl.kind == "view":
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


def typeToJson(type: TypeExpr) -> dict[str, Any]:
	if type.builtin:
		return {"builtin": type.builtin}
	if type.unknown:
		return {"unknown": True}
	if type.range:
		return {"range": typeToJson(type.range)}
	if type.values is not None:
		return {"values": list(type.values), "open": type.open}
	return {"path": type.path, "attr": type.attr} if type.attr else {"path": type.path}


def depToJson(dep: Dep) -> dict[str, Any]:
	if dep.ellipsis:
		return {"ellipsis": True}
	if dep.input:
		return {"input": dep.input}
	if dep.local:
		return {"local": dep.local}
	return {"path": dep.path, "attr": dep.attr}


def compact(data: dict[str, Any]) -> dict[str, Any]:
	return {key: value for key, value in data.items() if value is not None}


def annToJson(ann: Annotations) -> dict[str, Any] | None:
	return dict(ann) if ann else None


def encodeOntology(ontology: Ontology, ids: dict[str, str] | None) -> dict[str, Any]:
	header = dict(ontology.header)
	defaultCard = header.get("card", "?")
	defaultCounts = header.get("rel", "*:*")

	def attr(item: Attr) -> dict[str, Any]:
		return compact({
			"name": item.name,
			"card": item.card or defaultCard,
			"derived": True if item.derived else None,
			"type": typeToJson(item.type) if item.type else None,
			"deps": [depToJson(dep) for dep in item.deps] if item.deps else None,
			"ann": annToJson(item.ann),
			"doc": item.doc,
		})

	def attrs(items: list[Attr]) -> list[dict[str, Any]] | None:
		return [attr(item) for item in items] or None

	def decl(item: Decl) -> dict[str, Any]:
		common = {"kind": item.kind, "path": item.path}
		tail = {"ann": annToJson(item.ann), "doc": item.doc}
		if item.kind == "type":
			return compact({
				**common,
				"def": typeToJson(item.definition) if item.definition else None,
				"fields": [attr(field) for field in item.fields] if item.fields is not None else None,
				**tail,
			})
		if item.kind == "entity":
			return compact({**common, "base": item.base, "attrs": attrs(item.attrs), **tail})
		if item.kind == "facet":
			return compact({**common, "subject": item.subject, "attrs": attrs(item.attrs), **tail})
		if item.kind == "view":
			if item.viewInput:
				populations = [compact({"name": p.name, "type": p.type, "parent": p.parent or None, "via": p.via or None,
					"reverse": p.reverse or None, "through": p.through or None, "where": p.where or None, "equals": p.equals}) for p in item.viewPopulations]
				lines = [compact({"population": l.path, "member": l.member, "target": l.target, "optional": l.optional or None}) for l in item.viewLines]
				p = item.viewInput
				return compact({**common, "input": {"name": p.name, "path": p.path, "attr": p.attr}, "populations": populations, "lines": lines, "doc": item.doc})
			lines = [compact({"path": line.path, "facets": line.facets, "member": line.member}) for line in item.viewLines]
			return compact({**common, "lines": lines, "doc": item.doc})
		if item.kind == "domain":
			return compact({**common, "doc": item.doc})
		if item.kind == "map":
			lines = [
				compact({"from": line.fromValue, "match": line.match, "to": line.toValue, "doc": line.doc})
				for line in item.mapLines
			]
			return compact({**common, "from": item.mapFrom, "to": item.mapTo, "lines": lines, **tail})
		arrow = None
		if item.arrow:
			arrow = compact({"verb": item.arrow.verb, "inverse": item.arrow.inverse, "counts": item.arrow.counts or defaultCounts})
		return compact({
			**common,
			"participants": [{"role": p.role, "card": p.card or "1", "type": p.type} for p in item.participants],
			"arrow": arrow,
			"attrs": attrs(item.attrs),
			**tail,
		})

	return compact({
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


def normaliseUses(ontology: Ontology) -> list[tuple[str, str]]:
	"""Keep aliases, adding a self-alias if the combined scope shadows a local path."""
	uses = sorted(ontology.uses)
	namespace = ontology.namespace
	if not uses or namespace is None:
		return uses
	namer = Namer(namespace, uses)
	prefix = f"{namespace}/"
	# NOTE: Authored references may also name a generated history concept.
	localPaths = [decl.path[len(prefix):] for decl in ontology.decls if not decl.arrow and decl.path.startswith(prefix)]
	shadowed = {alias for alias, target in uses if target != prefix + alias}
	if any(
		"/" in path and path.split("/", 1)[0] in shadowed and not namer.aliasName(prefix + path)
		for path in localPaths
	):
		# NOTE: Do not let the added alias change the meaning of another relative path or rule.
		reserved = set(namer.aliases) | {path.split("/", 1)[0] for path in localPaths}
		for decl in ontology.decls:
			for ann in [decl.ann, *(attr.ann for attr in decl.fields or decl.attrs)]:
				if isinstance(rule := annotation(ann, "rule"), str):
					reserved.add(rule.split("/", 1)[0])
		alias, suffix = "Local", 2
		while alias in reserved:
			alias = f"Local{suffix}"
			suffix += 1
		uses = sorted([*uses, (alias, namespace)])
	return uses


def normaliseOntology(ontology: Ontology) -> Ontology:
	"""Return canonical `ontology`: sorted declarations, omitted defaults and ordered annotations."""
	header = dict(ontology.header)
	defaultCard = header.get("card", "?")
	defaultCounts = header.get("rel", "*:*")

	def normaliseAttr(attr: Attr) -> Attr:
		return replace(
			attr,
			card=None if attr.card == defaultCard else attr.card,
			ann=sortAnnotations(attr.ann),
			type=normaliseType(attr.type, annotation(attr.ann, "ordered") is True, annotation(attr.ann, "hierarchical") is True),
			deps=sorted(attr.deps, key=depKey) if attr.deps else attr.deps,
		)

	def normaliseAttrs(attrs: list[Attr]) -> list[Attr]:
		return sorted((normaliseAttr(attr) for attr in attrs), key=lambda attr: attr.name)

	def normaliseDecl(decl: Decl) -> Decl:
		base = replace(decl, ann=sortAnnotations(decl.ann))
		if decl.kind == "type":
			return replace(
				base,
				definition=normaliseType(decl.definition, annotation(decl.ann, "ordered") is True, annotation(decl.ann, "hierarchical") is True),
				fields=normaliseAttrs(decl.fields) if decl.fields is not None else None,
			)
		if decl.kind == "view":
			if decl.viewInput:
				return base  # Population dependency and projected output order are significant.
			lines = [
				replace(line, facets=sorted(line.facets) if isinstance(line.facets, list) else line.facets)
				for line in decl.viewLines
			]
			return replace(base, viewLines=sorted(lines, key=lambda line: (
				line.path + (f".{line.member}" if line.member else ""),
				",".join(line.facets) if isinstance(line.facets, list) else line.facets or "",
			)))
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

	decls = [normaliseDecl(decl) for decl in ontology.decls if not decl.generated]

	def byPath(kind: str) -> list[Decl]:
		return sorted((decl for decl in decls if decl.kind == kind), key=lambda decl: decl.path)

	facets = byPath("facet")
	relations = byPath("relation")
	relationPaths = {decl.path for decl in relations}
	# NOTE: Under `layering=declared` the order of domains is their dependency order, so it is kept.
	layered = dict(ontology.header).get("layering") == "declared"
	domains = [decl for decl in decls if decl.kind == "domain"] if layered else byPath("domain")
	ordered = domains + byPath("type")
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
		uses=normaliseUses(ontology),
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
