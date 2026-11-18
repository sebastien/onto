"""Module: binding.coverage — static coverage of a binding: ontology side and document side (spec-04)."""

from __future__ import annotations

from typing import Any

from ..coverage import CoverageReport, CoverageRow, Elements, coverageRows, impliedKeys
from ..expressions import Expression, printExpression
from ..inventory.model import CONTAINER_TYPES, Inventory
from ..ontology.model import Model, Ontology
from .model import Binding, BindingScope
from .operations import enclosingPath, enclosingScope, rootSteps

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Steps = list[Any]

EACH = {"each": True}


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def documentPaths(expr: Expression | None) -> list[Steps]:
	"""Document paths an expression reads; the type argument of `ref` is not one."""
	if expr is None:
		return []
	if "path" in expr:
		return [expr["path"]]
	if "call" in expr:
		args = expr["args"][1:] if expr["call"] == "ref" else expr["args"]
		return [path for arg in args for path in documentPaths(arg)]
	if "coalesce" in expr:
		return [path for item in expr["coalesce"] for path in documentPaths(item)]
	return []


def absolute(scope: Steps | None, steps: Steps, scopes: list[BindingScope] | None = None) -> Steps:
	"""Steps of a path read from a record at `scope`, from the document root, indexes as `[*]`.

	`^` climbs to an enclosing record; `$` restarts at the root. A JSON root
	object is implicit (`asOf`); a root list keeps its `$[*]`.
	"""
	first = steps[0] if steps else None
	if isinstance(first, dict) and "root" in first:
		base, steps = [], steps[1:]
	elif isinstance(first, dict) and "up" in first:
		base = enclosingPath(rootSteps({"path": scope or []}), first["up"], scopes or [])
		steps = steps[1:]
	else:
		base = list(scope or [])
	result = base + [EACH if isinstance(step, dict) and "index" in step else step for step in steps]
	if result and isinstance(result[0], dict) and "root" in result[0] and (len(result) < 2 or result[1] != EACH):
		result = result[1:]
	if not result:
		return []
	if result[0] == EACH:
		result = [{"root": True}] + result
	return result


def pathText(steps: Steps) -> str:
	return printExpression({"path": steps}, binding=True) if steps else "$"


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class BindingCoverage:
	"""Collect the fields each scope reads and the elements its lines assign."""

	def __init__(self, ontology: Ontology, binding: Binding):
		self.binding = binding
		self.elements = Elements(Model(ontology), binding.ontology)
		self.reads: dict[str, list[tuple[str | None, str, str | None]]] = {}
		self.assigned: set[str] = set()

	def record(self, scope: Steps | None, paths: list[Steps], target: str | None, status: str, note: str | None = None) -> None:
		for steps in paths:
			if len(steps) == 1 and isinstance(steps[0], dict) and "up" in steps[0]:
				# A bare ancestor reference reads the enclosing record's key, not the record itself.
				scopes = self.binding.scopes
				parent = enclosingScope(enclosingPath(rootSteps({"path": scope or []}), steps[0]["up"], scopes), scopes)
				if parent is not None:
					self.record(parent.path["path"], documentPaths(parent.id), None, "condition")
				continue
			path = absolute(scope, steps, self.binding.scopes)
			if path:
				self.reads.setdefault(pathText(path), []).append((target, status, note))

	def scope(self, scope: BindingScope) -> None:
		steps = scope.path["path"]
		typeName = self.elements.display(scope.type)
		self.record(None, [scope.path["path"]], typeName, "direct", scope.doc)
		conditions = documentPaths(scope.id) + documentPaths(scope.valid) + documentPaths(scope.ctx)
		conditions += [scope.deleted["path"]] if scope.deleted else []
		self.record(steps, conditions, None, "condition")
		for line in scope.lines:
			key = self.elements.assigned(scope.type, line.target, line.facet, line.verb)
			if key:
				self.assigned.update(impliedKeys(self.elements, scope.type, line.target))
			if key:
				self.assigned.add(key)
			member = f"[{line.facet}]" if line.facet else f".{line.target or line.verb}"
			expr = line.expr
			status = "direct" if expr is not None and "path" in expr else "transformed"
			self.record(steps, documentPaths(expr), typeName + member, status, line.doc)
			if line.when:
				self.record(steps, [line.when["path"]], None, "condition")

	def report(self, inventory: Inventory | None) -> CoverageReport:
		if self.binding.at is not None:
			self.record(None, documentPaths(self.binding.at), None, "condition")
		for scope in self.binding.scopes:
			self.scope(scope)
		keys = [key for decl in self.elements.instanceTypes() for key in self.elements.declared(decl.path)]
		keys += [f"{decl.path}.{decl.arrow.verb}" for decl in self.elements.model.ontology.decls if decl.kind == "relation" and decl.arrow and f"{decl.participants[0].type}.{decl.arrow.verb}" not in keys]
		unassigned = sorted(self.elements.display(key) for key in dict.fromkeys(keys)
			if key not in self.assigned and not any(key.startswith(item + ".") for item in self.assigned))
		if inventory is None:
			return CoverageReport([], unassigned, [])
		types = inventory.types()
		excluded: dict[str, tuple[str, str | None]] = {}
		for exclusion in self.binding.exclusions:
			prefix = pathText(absolute(None, exclusion.path["path"]))
			for path in types:
				if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
					excluded.setdefault(path, (exclusion.reason, exclusion.doc))
		# NOTE: Containers (objects, lists) are reported only when read or excluded themselves; their fields carry the rest.
		fields = [path for path, kind in types.items() if kind not in CONTAINER_TYPES or path in self.reads or path in excluded]
		rows: list[CoverageRow] = coverageRows(fields, self.reads, excluded)
		return CoverageReport(rows, unassigned, sorted(path for path in self.reads if path not in types and path != "$"))


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def bindingCoverage(ontology: Ontology, binding: Binding, inventory: Inventory | None = None) -> CoverageReport:
	"""Both sides of a binding's coverage.

	`unassigned` is the ontology side: elements no line assigns, needing no data. With an
	`inventory`, `rows` give each document field's status and `uninventoried` the paths
	the binding reads that the inventory does not list.
	"""
	return BindingCoverage(ontology, binding).report(inventory)


__all__ = ["bindingCoverage", "absolute", "documentPaths"]

# EOF
