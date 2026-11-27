"""Module: mapping.reversal — the reverse of a mapping and the lines it loses (spec-04 Reversal)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from ..conditions import mapConditionPaths
from ..expressions import Expression, keyedSteps, parseExpression
from ..functions.model import BUILTIN_ARITIES, Function, FunctionLibrary
from ..ontology.model import Decl, MapLine, Model, Ontology
from ..text import Loc, annotation, lastSegment
from .model import Mapping, MappingLine, MappingScope, lookupOf

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


# NOTE: Built-ins that only change spelling; writing restores it from originals and formats.
SPELLING = ("trim", "lower", "upper")
DATE_PARTS = ("YYYY", "MM", "DD")
TIME_PARTS = ("hh", "mm", "ss")
DERIVED = "derived target, not written back"


@dataclass(slots=True, frozen=True)
class LossyLine:
	"""A forward line (of scope `source -> target`) the reverse cannot read back, and why."""

	source: str
	target: str
	line: str
	reason: str
	loc: Loc | None = None


class Lossy(Exception):
	"""Raised while solving a line that cannot be reversed; the message is the reason."""


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def call(name: str, *args: Expression) -> Expression:
	return {"call": name, "args": list(args)}


def lineLabel(line: MappingLine) -> str:
	return f"[{line.facet}]" if line.facet else line.target or line.verb or ""


def targetExpression(target: str) -> Expression:
	"""Read a forward target as a reverse expression, including any keyed element steps."""
	try:
		expr = parseExpression(target)
		if "path" in expr:
			return expr
	except ValueError:
		pass
	raise Lossy(f"target '{target}' cannot be read as a path")


def isDerived(model: Model, owner: str, path: str) -> bool:
	"""Whether `owner.path` (through facets and structure fields) ends at a derived attribute."""
	attr = model.lookup(owner, path)
	return attr is not None and attr.derived


def hasParts(pattern: str, parts: tuple[str, ...]) -> bool:
	return all(part in pattern for part in parts)


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Reverser:
	"""Solve each forward line for its input, building the reverse scopes and the lossy list."""

	def __init__(self, mapping: Mapping, fromOntology: Ontology, toOntology: Ontology, libraries: list[FunctionLibrary] | None = None):
		self.mapping = mapping
		self.model = Model(fromOntology)
		self.targetModel = Model(toOntology)
		self.functions: dict[str, tuple[Function, str]] = {item.name: (item, "") for item in mapping.functions}
		for library in libraries or []:
			self.functions.update({f"{library.namespace}/{item.name}": (item, library.namespace) for item in library.functions})
		# Like forward resolution, prefer the source declaration when a later revision reuses its path.
		self.maps: dict[str, Decl] = {decl.path: decl for ontology in (toOntology, fromOntology) for decl in ontology.decls if decl.kind == "map"}
		self.maps.update({decl.path: decl for decl in mapping.maps})
		self.reverseMaps: dict[str, Decl] = {}
		self.reverseNames: dict[str, str] = {}
		self.lossy: list[LossyLine] = []

	def reverseMap(self, name: str) -> str:
		"""The local name of `@map` `name` with its columns swapped; it must be exact and one-to-one."""
		if name in self.reverseNames:
			return self.reverseNames[name]
		decl = self.maps[name]
		froms = [line.fromValue for line in decl.mapLines]
		tos = [line.toValue for line in decl.mapLines]
		if any(line.match != "exact" for line in decl.mapLines) or len(set(froms)) != len(froms) or len(set(tos)) != len(tos):
			raise Lossy(f"@map '{name}' is not exact and one-to-one")
		base = local = lastSegment(name)
		suffix = 2
		while local in self.reverseMaps or local in self.functions or local in BUILTIN_ARITIES:
			local = f"{base}{suffix}"
			suffix += 1
		self.reverseMaps[local] = Decl("map", local, mapFrom=decl.mapTo, mapTo=decl.mapFrom,
			mapLines=[MapLine(line.toValue, "exact", line.fromValue) for line in decl.mapLines])
		self.reverseNames[name] = local
		return local

	def inverse(self, expr: Expression, value: Expression) -> tuple[Expression, Expression]:
		"""Solve a call for its single reversible argument: (that argument, the expression giving it)."""
		name, args = expr["call"], expr["args"]
		literal = args[1].get("text") if len(args) == 2 and "text" in args[1] else None
		if name in SPELLING and len(args) == 1:
			return args[0], value
		if name == "number" and len(args) == 1:
			return args[0], call("text", value)
		if name in ("date", "epoch") and len(args) == 1:
			return args[0], call("epoch" if name == "date" else "date", value)
		if name in ("date", "datetime") and literal is not None:
			if not hasParts(literal, DATE_PARTS + (TIME_PARTS if name == "datetime" else ())):
				raise Lossy(f"format '{literal}' does not hold every part {name} reads")
			return args[0], call("format", value, args[1])
		if name == "format" and literal is not None:
			if not hasParts(literal, DATE_PARTS):
				raise Lossy(f"format '{literal}' does not hold a whole date")
			return args[0], call("datetime" if hasParts(literal, TIME_PARTS) else "date", value, args[1])
		if name in ("split", "join") and literal is not None:
			if not literal:
				raise Lossy(f"function '{name}' requires a nonempty separator")
			return args[0], call("join" if name == "split" else "split", value, args[1])
		if name in self.functions and len(args) == 1:
			function, namespace = self.functions[name]
			if inverse := annotation(function.ann, "inverse"):
				return args[0], call(f"{namespace}/{inverse}" if namespace else str(inverse), value)
			raise Lossy(f"function '{name}' has no inverse")
		if name in self.maps and len(args) == 1:
			return args[0], call(self.reverseMap(name), value)
		raise Lossy(f"function '{name}' cannot be reversed")

	def solve(self, scope: MappingScope, line: MappingLine, expr: Expression, value: Expression) -> MappingLine:
		"""The reverse line assigning `expr`'s source path from `value`."""
		if "call" in expr:
			if expr["call"] == "ref" and str(expr["args"][0].get("path", [""])[0]).startswith(self.mapping.toNamespace + "/"):
				raise Lossy("a target reference writes nothing back")
			inner, solved = self.inverse(expr, value)
			return self.solve(scope, line, inner, solved)
		if "path" not in expr:
			raise Lossy("literals, metadata and '??' are not reversible")
		if expr["path"] == [{"root": True}]:
			raise Lossy("the scope instance '$' is not an assignable input")
		steps = keyedSteps(expr["path"])
		owner, index = scope.source, 0
		if lookupOf(self.mapping.lookups, steps[0], owner, self.model):
			raise Lossy(f"'{'.'.join(steps)}' reads through a lookup, which writes nothing back")
		facet = self.model.facetOf(owner, steps[0])
		attr = self.model.lookup(owner, ".".join(steps[:2])) if facet and len(steps) > 1 else self.model.lookup(owner, steps[0])
		if attr is None:
			if len(steps) == 1 and self.model.verbs(owner, steps[0]):
				return MappingLine(verb=steps[0], expr=value)
			raise Lossy(f"path '{'.'.join(steps)}' is not an attribute of '{owner}'")
		index = 2 if facet and len(steps) > 1 else 1
		while index < len(steps) and self.model.structOf(attr.type):
			index += 1
			attr = self.model.lookup(owner, ".".join(steps[:index]))
		if index == len(steps):
			return MappingLine(target=".".join(steps), expr=value)
		resolved = self.model.resolveType(attr.type, attr.ann)
		rest = steps[index:]
		if resolved.kind not in ("entity", "relation"):
			raise Lossy(f"path '{'.'.join(steps)}' does not resolve")
		key = self.model.lookup(resolved.path, rest[0]) if len(rest) == 1 else None
		if key is not None and annotation(key.ann, "key"):
			return MappingLine(target=".".join(steps[:index]), expr=call("ref", {"path": [resolved.path]}, value))
		if line.reverse:
			return MappingLine(target=".".join(steps), expr=value)
		raise Lossy(f"'{'.'.join(steps)}' reads another instance without {{reverse}}")

	def condition(self, when: dict, assigned: dict[str, str]) -> dict:
		"""Translate each test's path into the reverse input that assigns it, when a direct line does."""
		def translate(steps: list) -> list:
			if steps == [{"root": True}]:
				raise Lossy("the scope instance '$' is not read back by a direct line")
			path = ".".join(keyedSteps(steps))
			if path not in assigned:
				raise Lossy(f"condition '{path}' is not read back by a direct line")
			return targetExpression(assigned[path])["path"]
		return mapConditionPaths(when, translate)

	def scope(self, scope: MappingScope) -> MappingScope | None:
		candidates = self.mapping.header.get("candidates") is True
		lines = [line for line in scope.lines if candidates or not line.candidate]
		# Conditions translate only through direct lines (`Target <- Path`), whose values are equal.
		assigned = {".".join(keyedSteps(line.expr["path"])): line.target or line.verb for line in lines if line.expr and "path" in line.expr and line.expr["path"] != [{"root": True}] and not line.facet}
		reverse = MappingScope(source=scope.target, target=scope.source, doc=scope.doc)
		try:
			if scope.name or scope.present or scope.into:
				raise Lossy("named, presence-selected or into scopes are not reversed")
			if scope.when:
				reverse.when = self.condition(scope.when, assigned)
			if scope.ctx is not None:
				raise Lossy("contextual scopes are not reversed")
		except Lossy as error:
			for line in lines:
				self.lossy.append(LossyLine(scope.source, scope.target, lineLabel(line), str(error), line.loc))
			return None
		if scope.valid is not None and "path" in scope.valid and scope.valid["path"] != [{"root": True}]:
			reverse.lines.append(MappingLine(target=".".join(keyedSteps(scope.valid["path"])), expr={"meta": "valid"}))
		for line in lines:
			if line.facet and not line.when:
				continue
			try:
				if line.qualifiers:
					raise Lossy("measurement qualifier expressions cannot be written back")
				if line.facet:
					raise Lossy("a facet's condition cannot be written back")
				if line.expr == {"meta": "valid"}:
					reverse.valid = targetExpression(lineLabel(line))
					continue
				if not line.when and any(other is not line and other.when and lineLabel(other) == lineLabel(line) for other in lines):
					raise Lossy("the default of exclusive lines has no reversible condition")
				if line.target and isDerived(self.targetModel, scope.target, line.target):
					raise Lossy(DERIVED)
				if line.name:
					raise Lossy(f"a reference translated through the scope named {line.name} writes nothing back")
				value = targetExpression(lineLabel(line))
				solved = self.solve(scope, line, line.expr, value)
				if solved.target and isDerived(self.model, scope.source, solved.target):
					raise Lossy(DERIVED)
				if line.when:
					solved.when = self.condition(line.when, assigned)
				solved.candidate, solved.doc = line.candidate, line.doc
				reverse.lines.append(solved)
			except Lossy as error:
				self.lossy.append(LossyLine(scope.source, scope.target, lineLabel(line), str(error), line.loc))
		return reverse

	def reverse(self, referential: str | None) -> tuple[Mapping, list[LossyLine]]:
		header = {"from": self.mapping.header["to"]} if "to" in self.mapping.header else {}
		if "from" in self.mapping.header:
			header["to"] = self.mapping.header["from"]
		if referential:
			header["referential"] = referential
		for key in ("candidates", "retract", "confirm"):
			if key in self.mapping.header:
				header[key] = self.mapping.header[key]
		scopes = [item for scope in self.mapping.scopes if (item := self.scope(scope)) is not None]
		result = Mapping(self.mapping.toNamespace, self.mapping.fromNamespace, header, dict(self.mapping.uses),
			deepcopy(self.mapping.functions), sorted(self.reverseMaps.values(), key=lambda decl: decl.path), scopes)
		return result, self.lossy


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def mappingReverse(mapping: Mapping, fromOntology: Ontology, toOntology: Ontology, libraries: list[FunctionLibrary] | None = None,
	referential: str | None = None) -> tuple[Mapping, list[LossyLine]]:
	"""Return the mapping `To -> From` made of the reverses of the reversible lines, and the lossy ones.

	Reverses may use forms only generated reverses contain: `Ref <- ref(T, Key)` for a
	key read through a reference, `Ref.Attr <- Path` for `{reverse}` lines, and inverse
	calls. They are models to compile, not files to re-resolve. `referential` names
	the reverse referential, normally the one giving keys back their forward handles.
	"""
	return Reverser(mapping, fromOntology, toOntology, libraries).reverse(referential)


__all__ = ["LossyLine", "mappingReverse"]

# EOF
