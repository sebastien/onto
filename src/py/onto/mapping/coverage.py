"""Module: mapping.coverage — static coverage of a mapping's source and target elements (spec-04)."""

from __future__ import annotations

from ..coverage import CoverageReport, Elements, _selections, coverageRows
from ..expressions import Expression
from ..ontology.model import Model, Ontology
from .model import Mapping, MappingScope

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def expressionPaths(expr: Expression | None) -> list[list[str]]:
	"""Attribute paths an expression reads; `ref` type arguments and metadata are not reads."""
	if expr is None:
		return []
	if "path" in expr:
		# `$` (the scope instance) reads no source element
		return [] if expr["path"] == [{"root": True}] else [expr["path"]]
	if "call" in expr:
		args = expr["args"][1:] if expr["call"] == "ref" else expr["args"]
		return [path for arg in args for path in expressionPaths(arg)]
	if "coalesce" in expr:
		return [path for item in expr["coalesce"] for path in expressionPaths(item)]
	return []


def isDirect(expr: Expression | None) -> bool:
	"""A plain path, read with at most qualifier conversion."""
	return expr is not None and "path" in expr


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class MappingCoverage:
	"""Collect the reads of each scope and line, then rank them per source element."""

	def __init__(self, fromOntology: Ontology, toOntology: Ontology, mapping: Mapping):
		self.mapping = mapping
		self.source = Elements(Model(fromOntology), mapping.fromNamespace)
		self.target = Elements(Model(toOntology), mapping.toNamespace)
		self.reads: dict[str, list[tuple[str | None, str, str | None]]] = {}
		self.assigned: set[str] = set()

	def record(self, scope: MappingScope, paths: list[list[str]], target: str | None, status: str, note: str | None) -> None:
		for steps in paths:
			for key in self.source.read(scope.source, steps):
				self.reads.setdefault(self.source.display(key), []).append((target, status, note))

	def scope(self, scope: MappingScope) -> None:
		candidates = self.mapping.header.get("candidates") is True
		conditions = [scope.when["path"]] if scope.when else []
		conditions += expressionPaths(scope.ctx) + expressionPaths(scope.valid) + expressionPaths(scope.present) + expressionPaths(scope.into)
		self.record(scope, conditions, None, "condition", None)
		targetType = self.target.display(scope.target)
		for line in scope.lines:
			key = self.target.assigned(scope.target, line.target, line.facet, line.verb)
			if key and (candidates or not line.candidate):
				self.assigned.add(key)
			member = f"[{line.facet}]" if line.facet else f".{line.target or line.verb}"
			status = "ambiguous" if line.candidate and not candidates else "direct" if isDirect(line.expr) else "transformed"
			self.record(scope, expressionPaths(line.expr), targetType + member, status, line.doc)
			for expr in line.qualifiers.values():
				self.record(scope, expressionPaths(expr), targetType + member, "ambiguous" if status == "ambiguous" else "transformed", line.doc)
			if line.when:
				self.record(scope, [line.when["path"]], None, "ambiguous" if status == "ambiguous" else "condition", None)

	def keys(self) -> list[str]:
		"""Source elements, restricted to the mapping's view when it has one."""
		model = self.source.model
		view = self.mapping.header.get("view")
		selections = _selections(model, model.get(view)) if view else None
		keys: list[str] = []
		for decl in self.source.instanceTypes():
			for key in self.source.declared(decl.path):
				if selections is not None and not self.inView(key, selections):
					continue
				keys.append(self.source.display(key))
		return keys

	def inView(self, key: str, selections: set) -> bool:
		model = self.source.model
		if key.endswith("]"):
			owner, facet = key[:-1].split("[", 1)
			return any(item.facet and item.member == facet and model.isA(owner, item.owner) for item in selections)
		owner, _, member = key.partition(".")
		relation = next((decl for decl in model.ontology.decls if decl.kind == "relation" and decl.arrow and decl.arrow.verb == member and decl.participants[0].type == owner), None)
		if relation is not None:
			return any(item.owner == relation.path for item in selections)
		return any(not item.facet and item.member == member and (owner == item.owner or model.isA(item.owner, owner) or model.isA(owner, item.owner)) for item in selections)

	def report(self) -> CoverageReport:
		for scope in self.mapping.scopes:
			self.scope(scope)
		excluded = {self.source.display(item.path): (item.reason, item.doc) for item in self.mapping.exclusions}
		for key in self.keys():
			parents = [path for path in excluded if key.startswith(path + ".")]
			if parents:
				excluded.setdefault(key, excluded[max(parents, key=len)])
		targets: list[str] = []
		for path in dict.fromkeys(scope.target for scope in self.mapping.scopes):
			for entity in reversed(self.target.model.lineage(path)):
				targets += [key for key in self.target.declared(entity) if key not in targets]
		unassigned = sorted(self.target.display(key) for key in targets if key not in self.assigned and not self.coveredBy(key))
		return CoverageReport(coverageRows(self.keys(), self.reads, excluded), unassigned, [])

	def coveredBy(self, key: str) -> bool:
		"""A structure leaf is assigned when the line assigns the whole structure."""
		return any(key.startswith(item + ".") for item in self.assigned)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def mappingCoverage(fromOntology: Ontology, toOntology: Ontology, mapping: Mapping) -> CoverageReport:
	"""Rank how each `From` element is read (`direct`, `transformed`, `condition`, `ambiguous`), else excluded or `unmapped`.

	`unassigned` lists the elements of the scopes' target types (and their bases) that no line assigns.
	"""
	return MappingCoverage(fromOntology, toOntology, mapping).report()


__all__ = ["mappingCoverage", "expressionPaths"]

# EOF
