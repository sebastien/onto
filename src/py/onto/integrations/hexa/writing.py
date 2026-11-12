"""Module: integrations.hexa.writing — documents written by bindings: fragments, originals, materializing (spec-06 Writing).

BindingWrite: DocumentPreviousRetrieve → RecordsPreviousProject → InstancesUnfold → <Type>FragmentsProject
              → OriginalsRestore → DocumentMaterialize
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any as AnyValue

from hexa.combinators import Policy, collect, each, lift, project, stage
from hexa.shapes import Any, Bool, DatePattern, Location, derive, loose, optional, slot, tolerant, via

from ...binding.model import Binding, BindingLine, BindingScope
from ...expressions import Expression, printExpression
from ...formats.model import Formats
from ...inventory.model import Inventory
from ...inventory.operations import documentFields
from ...ontology.model import Model
from ...text import lastSegment
from .compiler import BindingCompiler, CompileError, isMulti, scalarShape, slotName, typeSpec
from .stages import namedStage
from .unfold import StateIndex
from . import vocabulary as V

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


EACH = {"each": True}
SPELLING = ("trim", "lower", "upper")


@dataclass(slots=True)
class WriteLeaf:
	"""One written field: its path below the record, the line's record key and how it is spelled."""

	steps: list[str]
	key: str | None
	kind: str = "value"
	numeric: bool = False
	null: str | None = None


@dataclass(slots=True)
class WriteScope:
	"""A scope line used for writing: its document path, fragment template and leaves."""

	name: str
	type: str
	steps: list[AnyValue]
	parent: str | None
	shape: AnyValue
	template: dict
	leaves: list[WriteLeaf] = field(default_factory=list)
	keys: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class BindingWriteProgram:
	"""A compiled binding in the writing direction, with the reading program re-reading previous documents."""

	binding: Binding
	scopes: list[WriteScope]
	lossy: list[dict]
	stages: AnyValue
	reading: AnyValue


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def documentPath(steps: list[AnyValue]) -> str:
	return printExpression({"path": steps}, binding=True) if steps else "$"


def navigate(value: AnyValue, steps: list[str]) -> AnyValue:
	for step in steps:
		if not isinstance(value, dict) or step not in value:
			return None
		value = value[step]
	return value


def pointerSteps(pointer: str) -> list[AnyValue]:
	return [int(part) if part.isdigit() else part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]] if pointer else []


def at(document: AnyValue, steps: list[AnyValue]) -> tuple[bool, AnyValue]:
	"""Whether `document` has a value at `steps`, and that value."""
	value = document
	for step in steps:
		if isinstance(value, list) and isinstance(step, int) and step < len(value):
			value = value[step]
		elif isinstance(value, dict) and step in value:
			value = value[step]
		else:
			return False, None
	return True, value


def setField(target: dict, steps: list[str], value: AnyValue) -> None:
	for step in steps[:-1]:
		target = target.setdefault(step, {})
	target[steps[-1]] = value


def comparable(value: AnyValue) -> str:
	"""A canonical value for comparison, without the reading program's reference types."""
	return json.dumps(V.documentValue(value) if not isinstance(value, dict) or "ref" not in value else {"ref": value["ref"]}, sort_keys=True)


def pruned(value: AnyValue) -> AnyValue:
	"""Drop empty objects left by fields nobody wrote."""
	if isinstance(value, dict):
		result = {key: pruned(item) for key, item in value.items()}
		return {key: item for key, item in result.items() if item != {}}
	return value


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class WriteCompiler:
	"""Reverse each scope line into a fragment template, reporting the lines that cannot be written."""

	def __init__(self, owner: BindingCompiler, inventory: Inventory | None, formats: Formats | None):
		self.owner = owner
		self.model: Model = owner.model
		self.binding = owner.binding
		self.types = inventory.types() if inventory else {}
		self.formats = formats
		self.csv = self.binding.header.get("format") == "csv"
		self.lossy: list[dict] = []

	def fieldPath(self, scope: BindingScope, steps: list[str]) -> str:
		return documentPath(list(scope.path["path"]) + steps)

	def chosen(self, path: str) -> str | None:
		entry = self.formats.entries.get(path) if self.formats else None
		return entry.format if entry and entry.format else None

	def plainCodec(self, scope: BindingScope, steps: list[str], spec: str, multi: bool) -> tuple[AnyValue, str]:
		"""The codec spelling a value with no line function, from the field's JSON type and formats entry."""
		path = self.fieldPath(scope, steps)
		chosen = self.chosen(path) or ""
		if multi:
			return (V.SplitText(chosen[4:]), "value") if chosen.startswith("sep:") else (None, "list")
		if spec in ("Decimal", "Integer", "Duration:unit"):
			if self.types.get(path) == "number" and not self.csv:
				return V.DecimalNumber, "value"
			if chosen.startswith("decimals:"):
				return V.DecimalPlaces(int(chosen[9:])), "value"
			return None, "value"
		if spec == "Date" and "YYYY" in chosen:
			return DatePattern(chosen), "value"
		if spec == "DateTime" and "YYYY" in chosen and "hh" in chosen:
			return V.DateTimePattern(chosen), "value"
		if spec == "Text" and chosen.startswith("case:"):
			return V.Case(chosen[5:]), "value"
		return None, "value"

	def reverse(self, scope: BindingScope, line: BindingLine, expr: Expression) -> tuple[list[str], AnyValue, str, str | None]:
		"""Solve a line's expression for the field it reads: (steps, codec, kind, referenced type)."""
		if "path" in expr:
			steps = expr["path"]
			if any(isinstance(step, dict) for step in steps):
				if len(steps) == 2 and steps[1] == EACH and isinstance(steps[0], str):
					return [steps[0]], None, "list", None
				if len(steps) == 3 and steps[1] == EACH and all(isinstance(step, str) for step in (steps[0], steps[2])):
					return [steps[0]], None, f"list:{steps[2]}", None
				raise CompileError(V.BindingCodes.PathUnsupported, "Only plain fields and lists of fields are written")
			attr = self.model.lookup(scope.type, line.target)
			codec, kind = self.plainCodec(scope, steps, typeSpec(self.model, attr), isMulti(self.model, attr))
			return list(steps), codec, kind, None
		if "coalesce" in expr:
			return self.reverse(scope, line, expr["coalesce"][0])
		if "call" not in expr:
			raise CompileError(V.BindingCodes.PathUnsupported, "Literals and metadata are not written")
		name, args = expr["call"], expr["args"]
		if name in SPELLING and len(args) == 1:
			return self.reverse(scope, line, args[0])
		if name == "ref" and len(args) == 2 and "path" in args[1]:
			steps, _, _, _ = self.reverse(scope, line, args[1])
			return steps, None, "key", args[0]["path"][0]
		if not args or "path" not in args[0] or any(isinstance(step, dict) for step in args[0]["path"]):
			raise CompileError(V.BindingCodes.PathUnsupported, f"'{name}' does not read a plain field")
		steps = list(args[0]["path"])
		text = args[1].get("text") if len(args) == 2 else None
		chosen = self.chosen(self.fieldPath(scope, steps))
		if name in ("date", "datetime") and len(args) == 2 and args[1] == {"meta": "format"}:
			pattern = chosen if chosen and "YYYY" in chosen else ("YYYY-MM-DD" if name == "date" else "YYYY-MM-DDThh:mm:ss")
			return steps, DatePattern(pattern) if name == "date" else V.DateTimePattern(pattern), "value", None
		if name == "date" and text is not None:
			return steps, DatePattern(text), "value", None
		if name == "datetime" and text is not None:
			return steps, V.DateTimePattern(text), "value", None
		if name == "date" and len(args) == 1:
			return steps, V.EpochDate, "value", None
		if name == "number" and len(args) == 1:
			return steps, None, "value", None
		if name == "split" and text is not None:
			return steps, V.SplitText(text), "value", None
		attr = self.model.lookup(scope.type, line.target)
		codec = self.owner.calls.codec(name, scalarShape(typeSpec(self.model, attr))) if len(args) == 1 else None
		if codec is None:
			raise CompileError(V.BindingCodes.PathUnsupported, f"'{name}' has no inverse")
		return steps, codec, "value", None

	def scope(self, scope: BindingScope, name: str) -> WriteScope:
		short = lastSegment(scope.type)
		handleSlot = slot("Write.Root.Handle", Any)
		positions: dict[str, AnyValue] = {"$handle": handleSlot}
		fields: dict = {}
		leaves: list[WriteLeaf] = []
		parent: str | None = None
		parentRef: str | None = None
		assigned: set[tuple] = set()
		pending: list[tuple[list[str], AnyValue, WriteLeaf]] = []
		for line in sorted(scope.lines, key=lambda item: (0 if item.facet else 1, item.target or item.verb or item.facet or "")):
			label = f"[{line.facet}]" if line.facet else line.target or line.verb or ""
			try:
				if line.facet:
					if not line.when:
						continue
					facetSlot = positions.setdefault(f"[{line.facet}]", slot(slotName("Write", short, "Facets", line.facet), Bool))
					pending.append((list(line.when["path"]), derive(V.When, optional(facetSlot), line.when["value"]), WriteLeaf(list(line.when["path"]), None, "condition")))
					continue
				if line.verb:
					raise CompileError(V.BindingCodes.PathUnsupported, "Relations are not written")
				expr = line.expr
				if "path" in expr and len(expr["path"]) == 1 and isinstance(expr["path"][0], dict) and "up" in expr["path"][0]:
					parent, parentRef = self.enclosingName(scope, expr["path"][0]["up"]), line.target
					positions.setdefault(line.target, self.owner.attributeSlot(scope.type, line.target))
					continue
				steps, codec, kind, referenced = self.reverse(scope, line, expr)
				attrSlot = positions.setdefault(line.target, self.owner.attributeSlot(scope.type, line.target))
				attr = self.model.lookup(scope.type, line.target)
				numeric = typeSpec(self.model, attr) in ("Decimal", "Integer", "Duration:unit")
				if kind == "key":
					value = derive(V.HandleKey, optional(attrSlot), referenced)
				elif kind.startswith("list"):
					value = derive(V.Members, optional(attrSlot), kind[5:])
				else:
					value = via(attrSlot, codec) if codec is not None else optional(attrSlot)
				setField(fields, steps[:-1] + [steps[-1] + "?"], value)
				assigned.add(tuple(steps))
				leaves.append(WriteLeaf(steps, line.target, kind, numeric, line.null or self.binding.header.get("null")))
				if line.when:
					pending.append((list(line.when["path"]), derive(V.Given, optional(attrSlot), line.when["value"]), WriteLeaf(list(line.when["path"]), None, "condition")))
			except CompileError as error:
				self.lossy.append({"type": scope.type, "line": label, "reason": str(error)})
		for steps, value, leaf in pending:
			if tuple(steps) in assigned:
				continue
			setField(fields, steps[:-1] + [steps[-1] + "?"], value)
			leaves.append(leaf)
		template = {"handle": optional(handleSlot), "fields": fields, "source": Location}
		if parentRef is not None:
			template["parent?"] = derive(V.Field, optional(positions[parentRef]), ["ref"])
		shape = loose({f"{key}?": tolerant(position) for key, position in positions.items()})
		return WriteScope(name, scope.type, list(scope.path["path"]), parent, shape, template, leaves)

	def enclosingName(self, scope: BindingScope, up: int) -> str | None:
		found = self.owner.enclosing(scope, up)
		return self.names.get(id(found)) if found is not None else None

	def compile(self) -> list[WriteScope]:
		ordered = self.owner.scopes()
		counts: dict[str, int] = {}
		for scope in ordered:
			counts[lastSegment(scope.type)] = counts.get(lastSegment(scope.type), 0) + 1
		seen: dict[str, int] = {}
		self.names: dict[int, str] = {}
		for scope in ordered:
			short = lastSegment(scope.type)
			seen[short] = seen.get(short, 0) + 1
			self.names[id(scope)] = short if counts[short] == 1 else f"{short}{seen[short]}"
		return [self.scope(scope, self.names[id(scope)]) for scope in ordered]


class Writer:
	"""The pure steps of writing: unfolding instances, restoring originals and materializing documents."""

	def __init__(self, program: BindingWriteProgram, model: Model, types: dict[str, str]):
		self.program = program
		self.model = model
		self.types = types
		self.csv = program.binding.header.get("format") == "csv"

	def unfold(self, item: dict) -> dict:
		"""`InstancesUnfold`: each scope's instances as trees of the values its lines write, in handle order."""
		index = StateIndex(item["state"], self.model)
		facets: dict[str, set[str]] = {}
		for claim in item["state"].get("claims", []):
			if "facet" in claim:
				facets.setdefault(claim["s"], set()).add(claim["facet"])
		occurrences: dict[str, list[dict]] = {}
		for scope in self.program.scopes:
			result = []
			for handle in index.handlesOf(scope.type):
				if index.existence(handle) is None:
					continue
				# Nulls and unknowns are not formatted; lines with a null policy write them when materializing.
				tree: dict = {"$handle": handle} | {f"[{name}]": True for name in facets.get(handle, ())}
				nulls: dict = {}
				for key, claims in index.values.get(handle, {}).items():
					value = claims[0]["v"]
					if value is None or value == V.UNKNOWN:
						nulls[key] = value
					else:
						tree[key] = value
				result.append({"value": tree, "location": f"/{scope.name}/{handle}", "nulls": nulls})
			occurrences[scope.name] = result
		return {**item, "occurrences": occurrences}

	def restore(self, item: dict) -> dict:
		"""`OriginalsRestore`: keep the previous raw value of a field whose previous reading equals the value written."""
		previous = item.get("previous")
		records = {(record.get("scope"), record.get("handle")): record for record in item.get("records", [])}
		originals: dict[str, int] = {}
		formatted: dict[str, int] = {}
		numbers = self.numberFields(previous) if previous is not None and not self.types else set()
		fragments: dict[str, list[dict]] = {}
		for scope in self.program.scopes:
			trees = {occurrence["value"]["$handle"]: occurrence for occurrence in item["occurrences"][scope.name]}
			result = []
			for fragment in item["fragments"][scope.name]:
				fragment = deepcopy(fragment)
				occurrence = trees.get(fragment.get("handle"), {})
				tree = occurrence.get("value", {})
				record = records.get((scope.name, fragment.get("handle")))
				for leaf in scope.leaves:
					path = documentPath(scope.steps + leaf.steps)
					if leaf.key and leaf.null and leaf.key in occurrence.get("nulls", {}) and (occurrence["nulls"][leaf.key] is None) == (leaf.null == "absent"):
						setField(fragment["fields"], leaf.steps, None)
					present, written = at(fragment["fields"], leaf.steps)
					if not present:
						continue
					if record is not None and leaf.key and comparable(record.get("values", {}).get(leaf.key)) == comparable(tree.get(leaf.key)):
						found, raw = at(previous, pointerSteps(record["source"]) + leaf.steps)
						if found:
							setField(fragment["fields"], leaf.steps, deepcopy(raw))
							originals[path] = originals.get(path, 0) + 1
							continue
					if leaf.numeric and path in numbers and isinstance(written, str):
						try:
							setField(fragment["fields"], leaf.steps, V.decimalNumberFormat(written))
						except V.Gap:
							pass
					formatted[path] = formatted.get(path, 0) + 1
				result.append(fragment)
			fragments[scope.name] = result
		return {**item, "fragments": fragments, "originals": originals, "formatted": formatted}

	def numberFields(self, document: AnyValue) -> set[str]:
		"""Fields whose values the previous document wrote as JSON numbers."""
		return {path for path, kinds in documentFields(document, self.csv).items() if kinds == ["number"]}

	def materialize(self, item: dict, runTime: str | None) -> dict:
		"""`DocumentMaterialize`: place fragments by scope path, nested ones under their parent, in handle order."""
		binding = self.program.binding
		parentless: list[str] = []
		elements: dict[tuple[str, str], dict] = {}
		document: AnyValue = [] if self.csv else {}
		if binding.at is not None and runTime is not None and "path" in binding.at and isinstance(binding.at["path"][0], str) and not self.csv:
			setField(document, binding.at["path"], runTime)
		for scope in sorted(self.program.scopes, key=lambda item: sum(1 for step in item.steps if step == EACH)):
			eaches = [index for index, step in enumerate(scope.steps) if step == EACH]
			for fragment in sorted(item["fragments"][scope.name], key=lambda value: value.get("handle", "")):
				fields = pruned(fragment["fields"])
				if self.csv:
					columns = binding.columns or list(fields)
					document.append({column: fields.get(column, "") for column in columns})
					continue
				if scope.parent is not None:
					container = elements.get((scope.parent, fragment.get("parent")))
					if container is None:
						parentless.append(fragment.get("handle"))
						continue
					parentScope = next(item for item in self.program.scopes if item.name == scope.parent)
					steps = [step for step in scope.steps[len(parentScope.steps):] if step != EACH]
				else:
					container, steps = document, [step for step in scope.steps[:eaches[-1] if eaches else len(scope.steps)] if isinstance(step, str)]
				node = container
				for step in steps[:-1]:
					node = node.setdefault(step, {})
				node.setdefault(steps[-1], []).append(fields)
				elements[(scope.name, fragment.get("handle"))] = fields
		return {"document": document, "parentless": parentless}


def writeStages(program: BindingWriteProgram, writer: Writer) -> dict[str, AnyValue]:
	"""`BindingWrite` and its stages: input `{src, state}`, output `{documents, report}`."""
	binding = program.binding
	members: dict[str, AnyValue] = {}
	projects = {scope.name: namedStage(f"{scope.name}FragmentsProject", each(project(scope.shape, scope.template), Policy.Drop)) for scope in program.scopes}
	members |= {stageValue.name: stageValue for stageValue in projects.values()}

	def DocumentPreviousRetrieve(env, item):
		"""{src, state} → with the previous version of the document, or null."""
		previous = yield env.DocumentPreviousRead({"binding": binding.ontology, "src": item["src"]})
		return {**item, "previous": previous}

	def RecordsPreviousProject(env, item):
		"""The previous document read by the reading program: records by handle, without claims."""
		if item["previous"] is None:
			return {**item, "records": []}
		documents = yield from program.reading.stages.DocumentsRead(env, [{"src": item["src"], "document": item["previous"]}])
		return {**item, "records": documents[0]["records"]}

	def FragmentsProject(env, item):
		fragments, gaps = {}, []
		for scope in program.scopes:
			occurrences = [{"value": occurrence["value"], "location": occurrence["location"]} for occurrence in item["occurrences"][scope.name]]
			result = yield from collect(projects[scope.name])(env, occurrences)
			fragments[scope.name] = result["value"]
			gaps += [{"target": f"{scope.type}", "reason": entry["reason"], "location": entry.get("source"), "path": entry.get("path")} for entry in result["ledger"]]
		return {**item, "fragments": fragments, "gaps": gaps}

	def DocumentMaterialize(env, item):
		"""Fragments → the document and the write report; `@at` writes the run's time."""
		runTime = (yield env.ClockRead()) if binding.at is not None else None
		built = writer.materialize(item, runTime)
		report = {"lossy": program.lossy, "gaps": item["gaps"] + [{"target": handle, "reason": str(V.BindingCodes.ParentMissing)} for handle in built["parentless"]],
			"parentless": built["parentless"], "originals": item["originals"], "formatted": item["formatted"]}
		return {"documents": [{"src": item["src"], "document": built["document"]}], "report": report}

	members["DocumentPreviousRetrieve"] = stage(DocumentPreviousRetrieve)
	members["RecordsPreviousProject"] = stage(RecordsPreviousProject)
	members["InstancesUnfold"] = namedStage("InstancesUnfold", lift(writer.unfold))
	members["FragmentsProject"] = stage(FragmentsProject)
	members["OriginalsRestore"] = namedStage("OriginalsRestore", lift(writer.restore))
	members["DocumentMaterialize"] = stage(DocumentMaterialize)

	def BindingWrite(env, item):
		value = yield from members["DocumentPreviousRetrieve"](env, item)
		value = yield from members["RecordsPreviousProject"](env, value)
		value = yield from members["InstancesUnfold"](env, value)
		value = yield from members["FragmentsProject"](env, value)
		value = yield from members["OriginalsRestore"](env, value)
		return (yield from members["DocumentMaterialize"](env, value))

	members["BindingWrite"] = stage(BindingWrite)
	return members


__all__ = ["BindingWriteProgram", "WriteCompiler", "WriteScope", "WriteLeaf", "Writer", "writeStages"]

# EOF
