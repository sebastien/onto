"""Module: integrations.hexa.compiler — ontology → slots; binding scope lines → selectors, shapes and record templates (spec-06)."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any as AnyValue

from hexa.shapes import Any, Bool, DateOnly, DatePattern, DateTime, Decimal, DecimalText, Location, Null, Origin, Text, Timed, derive, either, gather, loose, optional, parsed, slot, tolerant, via

from ...binding.model import Binding, BindingLine, BindingScope
from ...binding.operations import BUILTIN_RESULTS
from ...expressions import Expression, printExpression
from ...formats.model import Formats
from ...functions.model import FunctionLibrary
from ...functions.operations import _resolveSignature
from ...functions.runtime import FunctionEvaluator
from ...inventory.operations import pascalCase
from ...ontology.model import Attr, Model, Ontology, ResolvedType, TypeExpr
from ...referential.operations import policyFor
from ...text import annotation, lastSegment
from . import vocabulary as V

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


EACH = {"each": True}
NUMERIC = ("Integer", "Number", "Amount", "Percent")
RE_BLOCK_KEY = re.compile(r"[^,:/{}~]+")
# NOTE: spec-06 candidate patterns, after the chosen and seen formats.
DATE_CANDIDATES = ("YYYY-MM-DD", "YYYYMMDD", "DD/MM/YYYY", "MM/DD/YYYY", "DD.MM.YYYY", "YYYY/MM/DD")
DATETIME_CANDIDATES = tuple(base + suffix for suffix in ("Thh:mm:ss", "Thh:mm:ssZ", " hh:mm:ss") for base in DATE_CANDIDATES)


class CompileError(ValueError):
	"""A binding or mapping hexa cannot run; `code` is a `Binding.*` or `Mapping.*` code."""

	def __init__(self, code: AnyValue, message: str):
		super().__init__(f"{code}: {message}")
		self.code = code


@dataclass(slots=True)
class Position:
	"""How one relative document path is captured: an attribute slot read directly, or a field slot."""

	slot: AnyValue
	codecs: list[AnyValue] = field(default_factory=list)
	collection: bool = False
	nulls: AnyValue = None


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def typeSpec(model: Model, attr: Attr) -> str:
	"""The `Onto.Read` type of an attribute: `Text`, `Integer`, `Decimal`, `Vocab:A|B`, `Ref`, ..."""
	resolved = model.resolveType(attr.type, attr.ann)
	if resolved.kind in ("entity", "relation"):
		return "Ref"
	if resolved.kind == "vocab":
		return "Text" if resolved.open else "Vocab:" + "|".join(resolved.values or [])
	if resolved.kind == "builtin":
		if resolved.builtin == "Integer":
			return "Integer"
		if resolved.builtin in ("Number", "Amount", "Percent"):
			return "Decimal"
		if resolved.builtin == "Duration":
			return "Duration:iso" if resolved.qualifiers.get("unit", "?") == "?" else "Duration:unit"
		if resolved.builtin in ("Text", "Boolean", "Date", "DateTime"):
			return resolved.builtin
	raise CompileError(V.BindingCodes.TypeMismatch, f"Attribute '{attr.name}' has no scalar value type")


def scalarShape(spec: str) -> AnyValue:
	"""The canonical hexa shape of a spec-02 value of type `spec` (spec-06 Slots)."""
	kind, _, detail = spec.partition(":")
	if kind == "Integer":
		return Decimal & V.Integral
	if kind in ("Decimal",) or spec == "Duration:unit":
		return Decimal
	if spec == "Duration:iso":
		return Text & V.IsoDuration
	if kind == "Boolean":
		return Bool
	if kind == "Date":
		return DateTime & DateOnly
	if kind == "DateTime":
		return DateTime & Timed
	if kind == "Vocab":
		values = detail.split("|")
		return either(*values) if len(values) > 1 else values[0]
	if kind == "Ref":
		return {"ref": Text}
	return Text


def isMulti(model: Model, attr: Attr) -> bool:
	return (attr.card or model.defaultCard) in ("*", "+")


def valueShape(model: Model, attr: Attr) -> AnyValue:
	"""Canonical shape of an attribute slot; state values may also be `null` or `?`."""
	spec = typeSpec(model, attr)
	base = {"set": [scalarShape(spec)], "partial?": True} if isMulti(model, attr) else scalarShape(spec)
	return either(base, Null, {"unknown": True})


def slotName(*parts: str) -> str:
	return ".".join(segment for part in parts for segment in part.replace("/", ".").split(".") if segment)


def fieldName(steps: list[AnyValue]) -> str:
	"""`bond.couponRate` → `BondCouponRate`; `[*]` adds `All`."""
	return "".join("All" if step == EACH else pascalCase(step) for step in steps) or "Value"


def selectorSegment(step: AnyValue) -> str:
	if step == EACH:
		return "*"
	return step.replace("~", "~0").replace("/", "~1")


def blockText(fields: dict[str, AnyValue]) -> str:
	for key in fields:
		if not RE_BLOCK_KEY.fullmatch(key) or key.startswith("{"):
			raise CompileError(V.BindingCodes.PathUnsupported, f"Field '{key}' cannot be captured by a selector block")
	return "{" + ",".join(f"{key}?:${capture.name}" for key, capture in fields.items()) + "}"


def literal(expr: Expression) -> AnyValue:
	if "text" in expr:
		return expr["text"]
	if "number" in expr:
		return V.decimalText(expr["number"])
	if "boolean" in expr:
		return expr["boolean"]
	if "null" in expr:
		return None
	return dict(V.UNKNOWN)


def raisePath(expr: Expression) -> Expression:
	"""Rewrite an enclosing scope's expression to read from one record below it."""
	if "path" in expr:
		steps = expr["path"]
		first = steps[0]
		if isinstance(first, dict) and "root" in first:
			return expr
		if isinstance(first, dict) and "up" in first:
			return {"path": [{"up": first["up"] + 1}] + steps[1:]}
		return {"path": [{"up": 1}] + steps}
	if "call" in expr:
		return {"call": expr["call"], "args": [arg if index == 0 and expr["call"] == "ref" else raisePath(arg) for index, arg in enumerate(expr["args"])]}
	if "coalesce" in expr:
		return {"coalesce": [raisePath(item) for item in expr["coalesce"]]}
	return expr


def functionEvaluator(ontology: Ontology, libraries: list[FunctionLibrary], functions: list, maps: list, implementations: dict) -> FunctionEvaluator:
	return FunctionEvaluator([ontology], libraries, functions, maps, implementations)


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Calls:
	"""Resolve calls to `Onto` built-ins or to the transforms of declared functions and maps."""

	def __init__(self, evaluator: FunctionEvaluator, used: set[str]):
		self.evaluator = evaluator
		self.used = used

	def transform(self, name: str) -> AnyValue:
		if name in V.BUILTINS:
			result = V.builtin(name)
		else:
			if name not in self.evaluator.functions and name not in self.evaluator.maps:
				raise CompileError(V.BindingCodes.PathUnsupported, f"Unknown function '{name}'")
			result = V.functionTransform(name, self.evaluator)
		self.used.add(result.name)
		return result

	def codec(self, name: str, canonical: AnyValue) -> AnyValue | None:
		"""The codec of a declared function with an inverse, else None."""
		function = self.evaluator.functions.get(name)
		inverse = annotation(function.ann, "inverse") if function else None
		if not inverse or len(function.args) != 1:
			return None
		namespace = name.rpartition("/")[0]
		inverseName = f"{namespace}/{inverse}" if namespace else str(inverse)
		result = V.functionCodec(name, inverseName, canonical, self.evaluator)
		self.used.add(result.name)
		return result


class ScopeCompiler:
	"""Compile one binding scope line: positions, selector blocks and the record template."""

	def __init__(self, owner: "BindingCompiler", scope: BindingScope, name: str):
		self.owner = owner
		self.model = owner.model
		self.scope = scope
		self.name = name
		self.short = lastSegment(scope.type)
		self.steps = list(scope.path["path"])
		self.positions: dict[tuple, Position] = {}
		self.reads: dict[tuple, int] = {}
		self.direct: dict[tuple, tuple[BindingLine, AnyValue]] = {}
		self.formatted: dict[tuple, str] = {}
		self.blocks: dict[int, dict[str, AnyValue]] = {}
		self.outer: list[AnyValue] = []
		self.formats: dict[str, AnyValue] = {}
		self.nullPolicies: dict[tuple, str] = {}

	# --- paths -----------------------------------------------------------------

	def relative(self, steps: list[AnyValue]) -> tuple:
		for step in steps:
			if isinstance(step, dict) and "index" in step:
				raise CompileError(V.BindingCodes.PathUnsupported, "Index steps are not supported")
		return tuple("*" if step == EACH else step for step in steps)

	def countReads(self, expr: Expression | None) -> None:
		"""First pass: count relative path reads and note `$format` reads."""
		if expr is None:
			return
		if "path" in expr:
			first = expr["path"][0]
			if not isinstance(first, dict) or "each" in first:
				key = self.relative(expr["path"])
				self.reads[key] = self.reads.get(key, 0) + 1
			return
		if "call" in expr:
			args = expr["args"]
			if expr["call"] in ("date", "datetime") and len(args) == 2 and args[1] == {"meta": "format"} and "path" in args[0]:
				self.formatted[self.relative(args[0]["path"])] = expr["call"]
			for index, arg in enumerate(args):
				if not (expr["call"] == "ref" and index == 0) and arg != {"meta": "format"}:
					self.countReads(arg)
			return
		if "coalesce" in expr:
			for item in expr["coalesce"]:
				self.countReads(item)
		elif "meta" in expr:
			raise CompileError(V.BindingCodes.PathUnsupported, "'$format' is read only by date(x, $format) and datetime(x, $format)")

	def directCodec(self, line: BindingLine, attr: Attr) -> tuple[tuple, AnyValue] | None:
		"""A line reading one path into an attribute slot: the path and its read codec (None for none)."""
		expr = line.expr
		if line.target is None or expr is None:
			return None
		spec = typeSpec(self.model, attr)
		multi = isMulti(self.model, attr)
		if spec == "Ref":
			return None
		readCodec = V.IntegerText if spec == "Integer" else DecimalText if spec in ("Decimal", "Duration:unit") else None
		if "path" in expr and not multi:
			first = expr["path"][0]
			if isinstance(first, dict) or "*" in self.relative(expr["path"]):
				return None
			return self.relative(expr["path"]), readCodec
		if "call" not in expr or not expr["args"] or "path" not in expr["args"][0] or isinstance(expr["args"][0]["path"][0], dict):
			return None
		key = self.relative(expr["args"][0]["path"])
		if "*" in key:
			return None
		name, args = expr["call"], expr["args"]
		text = args[1].get("text") if len(args) == 2 else None
		if multi:
			if name == "split" and text is not None and spec == "Text":
				return key, V.SplitText(text)
			return None
		if name == "date" and len(args) == 2 and text is not None and spec == "Date":
			return key, DatePattern(text)
		if name == "datetime" and text is not None and spec == "DateTime":
			return key, V.DateTimePattern(text)
		if name in ("date", "datetime") and len(args) == 2 and args[1] == {"meta": "format"} and spec == ("Date" if name == "date" else "DateTime"):
			return key, "format"
		if name == "date" and len(args) == 1 and spec == "Date":
			return key, V.EpochDate
		if name == "number" and len(args) == 1 and spec in ("Decimal", "Integer"):
			return key, readCodec
		if len(args) == 1 and (codec := self.owner.calls.codec(name, scalarShape(spec))) is not None:
			return key, codec
		return None

	def attribute(self, line: BindingLine) -> Attr:
		attr = self.model.lookup(self.scope.type, line.target)
		if attr is None:
			raise CompileError(V.BindingCodes.TypeMismatch, f"Unknown attribute '{line.target}' of '{self.scope.type}'")
		return attr

	def patterns(self, key: tuple, kind: str) -> list[AnyValue]:
		"""`$format` codecs: the chosen format, the others seen, then the candidate patterns."""
		fieldPath = self.fieldPath(key)
		entry = self.owner.formats.entries.get(fieldPath) if self.owner.formats else None
		names = ([entry.format] if entry and entry.format else []) + [name for name, _ in entry.ordered()] if entry else []
		names += list(DATE_CANDIDATES if kind == "date" else DATETIME_CANDIDATES)
		timed = kind == "datetime"
		result = []
		for name in dict.fromkeys(names):
			if ("hh" in name) == timed and all(part in name for part in ("YYYY", "MM", "DD")):
				result.append(V.DateTimePattern(name) if timed else DatePattern(name))
		return result

	def fieldPath(self, key: tuple) -> str:
		steps = [step for step in self.steps] + [EACH if step == "*" else step for step in key]
		return printExpression({"path": steps}, binding=True)

	def plan(self) -> None:
		"""Count reads, choose direct attribute positions, then declare field positions."""
		scope = self.scope
		for expr in (scope.id, scope.valid, scope.ctx):
			self.countReads(expr)
		if scope.deleted:
			self.countReads({"path": scope.deleted["path"]})
		for line in scope.lines:
			if line.expr is not None and not self.isEnclosing(line.expr):
				self.countReads(line.expr)
			if line.when:
				self.countReads({"path": line.when["path"]})
			if line.null and line.expr is not None and len(paths := self.linePaths(line.expr)) == 1:
				self.nullPolicies[paths[0]] = line.null
		for line in scope.lines:
			if line.target is None or line.expr is None or self.isEnclosing(line.expr):
				continue
			found = self.directCodec(line, self.attribute(line))
			if found and self.reads.get(found[0]) == 1:
				self.direct[found[0]] = (line, found[1])
		for key in self.reads:
			if any(key[:index] in self.reads for index in range(1, len(key))):
				continue
			if key in self.direct:
				line, codec = self.direct[key]
				target = self.owner.attributeSlot(scope.type, line.target)
				codecs = self.patterns(key, self.formatted[key]) if codec == "format" else [codec] if codec else []
				self.positions[key] = Position(target, codecs)
				continue
			collection = "*" in key
			if key in self.formatted and collection:
				raise CompileError(V.BindingCodes.PathUnsupported, "'$format' cannot read a collection")
			capture = slot(slotName("Bind", self.short, "Fields", fieldName([EACH if step == "*" else step for step in key])), [Any] if collection else Any)
			codecs = self.patterns(key, self.formatted[key]) if key in self.formatted else []
			self.positions[key] = Position(capture, codecs, collection)
		for key, kind in self.nullPolicies.items():
			if key in self.positions:
				self.positions[key].nulls = slot(slotName("Bind", self.short, "Nulls", fieldName([EACH if step == "*" else step for step in key])), Null)

	def linePaths(self, expr: Expression) -> list[tuple]:
		if "path" in expr:
			first = expr["path"][0]
			return [] if isinstance(first, dict) and "each" not in first else [self.relative(expr["path"])]
		if "call" in expr:
			return [path for index, arg in enumerate(expr["args"]) if not (expr["call"] == "ref" and index == 0) for path in self.linePaths(arg)]
		if "coalesce" in expr:
			return [path for item in expr["coalesce"] for path in self.linePaths(item)]
		return []

	def isEnclosing(self, expr: Expression) -> bool:
		steps = expr.get("path")
		return bool(steps) and len(steps) == 1 and isinstance(steps[0], dict) and "up" in steps[0]

	# --- shapes ---------------------------------------------------------------

	def leafShape(self, position: Position) -> AnyValue:
		"""A position's slot, through its codec or, for `$format`, a union of pattern codecs."""
		if not position.codecs:
			return position.slot
		branches = [via(position.slot, codec) for codec in position.codecs]
		return branches[0] if len(branches) == 1 else either(*branches)

	def shape(self) -> AnyValue:
		"""A loose struct of every position, nested as in the document, every key optional.

		Positions are `either(Null, tolerant(P))` rather than spec-06's `tolerant(P | Null)`:
		hexa reports a union whose branches fail differently as `Issue.Mismatch`, which would
		hide a codec's reason (`DatePattern.Invalid`). A null still matches first and says
		nothing; a null policy's marker slot takes its place.
		"""
		tree: dict = {}
		for key, position in self.positions.items():
			node = tree
			for step in key[:-1]:
				node = node.setdefault(step, {})
			node[key[-1]] = position

		def build(node: dict, inList: bool) -> AnyValue:
			return loose({name + "?": value(child, inList) for name, child in node.items()})

		def value(child: AnyValue, inList: bool) -> AnyValue:
			nullBranch = child.nulls if isinstance(child, Position) and child.nulls is not None else Null
			if isinstance(child, Position):
				inner = gather(self.leafShape(child)) if child.collection and inList else self.leafShape(child)
			elif "*" in child and len(child) == 1:
				item = child["*"]
				inner = [either(Null, gather(self.leafShape(item)) if isinstance(item, Position) else build(item, True))]
			else:
				inner = build(child, inList)
			return either(nullBranch, inner if inList else tolerant(inner))

		return build(tree, False)

	def levels(self) -> list[str]:
		"""Selectors applied level by level: one per list, each starting below the previous level's element.

		Splitting at lists keeps a parent without the child list from hiding its siblings' children:
		hexa's selector fails as a whole on a missing path, which a nested scope reports per parent.
		"""
		steps = self.steps
		if steps and isinstance(steps[0], dict) and "root" in steps[0]:
			steps = steps[1:]
			if 0 in self.blocks:
				raise CompileError(V.BindingCodes.PathUnsupported, "A root list has no fields to capture")
		eaches = sum(1 for step in steps if step == EACH)
		levels: list[list[str]] = [[blockText(self.blocks[0])] if 0 in self.blocks else []]
		seen = 0
		for step in steps:
			if isinstance(step, dict) and "index" in step:
				raise CompileError(V.BindingCodes.PathUnsupported, "Index steps are not supported")
			levels[-1].append(selectorSegment(step))
			if step == EACH:
				seen += 1
				level = eaches - seen
				if level and level in self.blocks:
					levels[-1].append(blockText(self.blocks[level]))
				levels.append([])
		if not levels[-1] and len(levels) > 1:
			levels.pop()
		return ["/".join(level) for level in levels]

	def selector(self) -> str:
		"""The scope's whole selector, as spec-06 writes it."""
		return "/".join(level for level in self.levels() if level)

	# --- templates --------------------------------------------------------------

	def capture(self, level: int, name: str) -> AnyValue:
		"""A field captured by the selector block `level` records up (0: the document root)."""
		fields = self.blocks.setdefault(level, {})
		if name not in fields:
			if level == 0:
				owner = "Root"
			else:
				owner = "Outer" if level == 1 else f"Outer{level}"
			fields[name] = slot(slotName("Bind", self.short, "Fields", owner, pascalCase(name)), Any)
			self.outer.append(fields[name])
			self.outer.sort(key=lambda item: item.name)
		return fields[name]

	def pathValue(self, steps: list[AnyValue]) -> AnyValue:
		first = steps[0]
		if isinstance(first, dict) and ("root" in first or "up" in first):
			eaches = sum(1 for step in self.steps if step == EACH)
			level = 0 if "root" in first else first["up"]
			if level >= eaches and "up" in first:
				raise CompileError(V.BindingCodes.PathUnsupported, "'^' climbs above the document root")
			rest = [("*" if step == EACH else step) for step in steps[1:]]
			if not rest or not isinstance(rest[0], str) or rest[0] == "*":
				raise CompileError(V.BindingCodes.PathUnsupported, "An enclosing path must name a field")
			if level == 0 and self.owner.atSlot is not None and rest == [self.owner.atField]:
				self.registerAt()
				return optional(self.owner.atSlot)
			captured = optional(self.capture(level, rest[0]))
			return derive(V.Field, captured, rest[1:]) if len(rest) > 1 else captured
		key = self.relative(steps)
		for index in range(1, len(key)):
			if key[:index] in self.positions:
				return derive(V.Field, optional(self.positions[key[:index]].slot), list(key[index:]))
		return optional(self.positions[key].slot)

	def registerAt(self) -> None:
		"""Capture the `@at` field in the block opening the selector."""
		fields = self.blocks.setdefault(0, {})
		if self.owner.atField not in fields:
			fields[self.owner.atField] = self.owner.atSlot
			self.outer.append(self.owner.atSlot)
			self.outer.sort(key=lambda item: item.name)

	def expression(self, expr: Expression) -> AnyValue:
		"""A template value for `expr`; absent inputs give `ABSENT_VALUE`, failures holes."""
		if "path" in expr:
			if self.isEnclosing(expr):
				return self.enclosing(expr["path"][0]["up"])
			return self.pathValue(expr["path"])
		if "call" in expr:
			name, args = expr["call"], expr["args"]
			if name == "ref":
				return derive(V.Ref, args[0]["path"][0], self.expression(args[1]))
			if name in ("date", "datetime") and len(args) == 2 and args[1] == {"meta": "format"}:
				return self.pathValue(args[0]["path"])
			return derive(self.owner.calls.transform(name), *[self.expression(arg) for arg in args])
		if "coalesce" in expr:
			return derive(V.Coalesce, *[self.expression(item) for item in expr["coalesce"]])
		if "meta" in expr:
			raise CompileError(V.BindingCodes.PathUnsupported, "'$format' outside date(x, $format)")
		return literal(expr)

	def enclosing(self, up: int) -> AnyValue:
		"""`^`: a reference to the enclosing record's instance, keyed by its scope's `id`."""
		parent = self.owner.enclosing(self.scope, up)
		if parent is None:
			raise CompileError(V.BindingCodes.PathUnsupported, f"'^' in '{self.scope.type}' has no enclosing scope line")
		expr = parent.id
		for _ in range(up):
			expr = raisePath(expr)
		return derive(V.Ref, parent.type, self.expression(expr))

	def condition(self, when: dict, value: AnyValue) -> AnyValue:
		return derive(V.When, derive(V.TextEquals, self.pathValue(when["path"]), when["value"]), value)

	def lineValue(self, line: BindingLine) -> AnyValue:
		expr = line.expr
		if line.facet:
			value = True
		elif line.target is not None and not self.isEnclosing(expr) and (key := next((key for key, (item, _) in self.direct.items() if item is line), None)) is not None:
			position = self.positions[key]
			value = optional(position.slot)
			if position.nulls is not None:
				value = derive(V.Nullable, value, optional(position.nulls), line.null or self.owner.binding.header.get("null", "absent"))
			if position.codecs and len(position.codecs) > 1:
				self.formats[self.fieldPath(key)] = derive(V.FormatName, parsed(position.slot))
		else:
			value = self.expression(expr)
			if line.target is not None:
				attr = self.attribute(line)
				spec = typeSpec(self.model, attr)
				value = derive(V.Set if isMulti(self.model, attr) else V.Read, value, spec)
			else:
				value = derive(V.Set, value, "Ref")
			paths = self.linePaths(expr)
			if len(paths) == 1 and (position := self.positions.get(paths[0])) is not None:
				if position.nulls is not None and line.null:
					value = derive(V.Nullable, value, optional(position.nulls), line.null)
				if len(position.codecs) > 1:
					self.formats[self.fieldPath(paths[0])] = derive(V.FormatName, parsed(position.slot))
		if line.when:
			value = self.condition(line.when, value)
		return value

	def template(self) -> dict[str, AnyValue]:
		scope = self.scope
		values: dict[str, AnyValue] = {}
		facets: dict[str, AnyValue] = {}
		links: dict[str, AnyValue] = {}
		for line in scope.lines:
			value = self.lineValue(line)
			if line.facet:
				facets[line.facet + "?"] = value
			elif line.verb:
				links[line.verb + "?"] = value
			else:
				values[line.target + "?"] = value
		record: dict[str, AnyValue] = {"type": scope.type, "scope": self.name, "handle": derive(V.Handle, self.short, self.expression(scope.id))}
		if self.owner.binding.at is not None:
			record["at?"] = derive(V.At, self.owner.atValue(self))
		if scope.valid is not None:
			record["valid?"] = derive(V.Valid, self.expression(scope.valid))
		if scope.ctx is not None:
			record["ctx?"] = self.expression(scope.ctx)
		if scope.deleted:
			record["deleted?"] = derive(V.TextEquals, self.pathValue(scope.deleted["path"]), scope.deleted["value"])
		record |= {"values": values, "facets": facets, "links": links, "formats": {key + "?": value for key, value in self.formats.items()},
			"source": Location, "origin?": optional(Origin)}
		return record


class BindingCompiler:
	"""Declare attribute slots and compile every scope line, in normal-form order."""

	def __init__(self, ontology: Ontology, binding: Binding, formats: Formats | None, libraries: list[FunctionLibrary] | None,
		implementations: dict | None, ontologies: list[Ontology] | None = None):
		decls = {decl.path: decl for item in [ontology] + list(ontologies or []) for decl in item.decls}
		self.model = Model(ontology)
		self.functionsModel = Ontology(namespace=ontology.namespace, header=ontology.header, decls=list(decls.values()))
		self.binding = binding
		self.formats = formats
		self.slots: dict[str, AnyValue] = {}
		self.used: set[str] = set()
		self.calls = Calls(FunctionEvaluator([self.functionsModel], libraries or [], binding.functions, [], implementations or {}), self.used)
		self.atSlot = None
		self.atField = None
		at = binding.at
		if at is not None and "path" in at and len(at["path"]) == 1 and isinstance(at["path"][0], str):
			self.atField = at["path"][0]
			self.atSlot = slot("Bind.At", Any)

	def attributeSlot(self, typePath: str, attrPath: str) -> AnyValue:
		name = slotName(typePath, attrPath)
		if name not in self.slots:
			attr = self.model.lookup(typePath, attrPath)
			self.slots[name] = slot(name, valueShape(self.model, attr))
		return self.slots[name]

	def declareSlots(self) -> None:
		"""One attribute slot per scalar attribute (and structure leaf) of every instance type."""
		for decl in self.model.ontology.decls:
			if decl.kind != "entity" and not (decl.kind == "relation" and decl.arrow is None):
				continue
			attrs = self.model.entityAttrs(decl.path).values() if decl.kind == "entity" else decl.attrs
			members = [attr.name for attr in attrs if not attr.derived]
			members += [f"{lastSegment(facet.path)}.{attr.name}" for facet in self.model.facets(decl.path).values() for attr in facet.attrs if not attr.derived]
			for member in members:
				for leaf in self.leaves(decl.path, member):
					try:
						self.attributeSlot(decl.path, leaf)
					except CompileError:
						continue

	def leaves(self, owner: str, member: str, seen: frozenset[str] = frozenset()) -> list[str]:
		attr = self.model.lookup(owner, member)
		structure = self.model.structOf(attr.type) if attr else None
		if not structure or not structure.fields or structure.path in seen:
			return [member]
		return [leaf for item in structure.fields for leaf in self.leaves(owner, f"{member}.{item.name}", seen | {structure.path})]

	def scopes(self) -> list[BindingScope]:
		return sorted(self.binding.scopes, key=lambda item: (item.type, printExpression(item.path, binding=True)))

	def enclosing(self, scope: BindingScope, up: int) -> BindingScope | None:
		steps = scope.path["path"]
		eaches = [index for index, step in enumerate(steps) if step == EACH]
		if len(eaches) <= up:
			return None
		prefix = steps[:eaches[-1 - up] + 1]
		return next((item for item in self.binding.scopes if item.path["path"] == prefix), None)

	def atValue(self, scope: ScopeCompiler) -> AnyValue:
		at = self.binding.at
		if self.atSlot is not None:
			scope.registerAt()
			return optional(self.atSlot)
		return scope.expression(rootExpression(at))

	def compile(self) -> list[ScopeCompiler]:
		self.declareSlots()
		ordered = self.scopes()
		counts: dict[str, int] = {}
		for scope in ordered:
			counts[lastSegment(scope.type)] = counts.get(lastSegment(scope.type), 0) + 1
		seen: dict[str, int] = {}
		result = []
		for scope in ordered:
			short = lastSegment(scope.type)
			seen[short] = seen.get(short, 0) + 1
			name = short if counts[short] == 1 else f"{short}{seen[short]}"
			compiler = ScopeCompiler(self, scope, name)
			compiler.plan()
			result.append(compiler)
		return result


def rootExpression(expr: Expression) -> Expression:
	"""`@at` paths read from the document root."""
	if "path" in expr:
		return expr if isinstance(expr["path"][0], dict) else {"path": [{"root": True}] + expr["path"]}
	if "call" in expr:
		return {"call": expr["call"], "args": [rootExpression(arg) for arg in expr["args"]]}
	if "coalesce" in expr:
		return {"coalesce": [rootExpression(item) for item in expr["coalesce"]]}
	return expr


# -----------------------------------------------------------------------------
#
# MAPPINGS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class Segment:
	"""One step of a mapping path: a tree key, what it is, and the type it leads to."""

	key: str
	kind: str
	attr: Attr | None = None
	owner: str = ""
	multi: bool = False
	next: str | None = None


@dataclass(slots=True)
class LineInfo:
	"""A compiled mapping line: its record key, the paths it reads (`when` included) and its source input."""

	section: str
	key: str
	inputs: list[list[str]]
	source: int = 0
	also: str | None = None

	def sourcePath(self, paths: list[list[str]]) -> list[str]:
		"""The pointers of the source input's path; none for literals and facets."""
		return paths[self.source] if 0 <= self.source < len(paths) else []


ROOT_KEYS = ("$handle", "$type", "$scope", "$target", "$valid", "$at", "$src")


def qualifierPair(source: dict[str, str], target: dict[str, str]) -> tuple[dict, dict] | None:
	"""The `scale`/`unit` qualifiers to convert, when both are fixed and differ."""
	left, right = {}, {}
	for name in ("scale", "unit"):
		a, b = source.get(name, "?"), target.get(name, "?")
		if a != "?" and b != "?" and a != b:
			left[name], right[name] = a, b
	return (left, right) if left else None


class MappingScopeCompiler:
	"""Compile one `S -> T` scope: its reach, the tree shape, the record template and the handle template."""

	def __init__(self, owner: "MappingCompiler", scope: AnyValue, name: str):
		self.owner = owner
		self.scope = scope
		self.name = name
		self.source = owner.model
		self.target = owner.targetModel
		self.short = lastSegment(scope.source)
		self.positions: dict[str, AnyValue] = {}
		self.lines: list[LineInfo] = []
		self.roots: dict[str, AnyValue] = {}

	# --- paths ---------------------------------------------------------------

	def segments(self, steps: list[str]) -> list[Segment]:
		"""Walk attribute `steps` from the scope's source type, through facets, structures and references."""
		result: list[Segment] = []
		current, index = self.scope.source, 0
		while index < len(steps):
			if current is None:
				raise CompileError(V.MappingCodes.ReferenceUnmapped, f"Path '{'.'.join(steps)}' reads through a value")
			name = steps[index]
			facet = self.source.facetOf(current, name)
			if facet is not None and annotation(facet.ann, "ctx"):
				raise CompileError(V.MappingCodes.ContextUnsupported, f"Contextual facet '{name}' in a mapping")
			member = f"{name}.{steps[index + 1]}" if facet is not None and index + 1 < len(steps) else name
			index += 2 if facet is not None and index + 1 < len(steps) else 1
			attr = self.source.lookup(current, member)
			if attr is None:
				found = self.source.verbs(current, name)
				if not found:
					raise CompileError(V.BindingCodes.TypeMismatch, f"Unknown path '{'.'.join(steps)}' of '{self.scope.source}'")
				decl, inverse = found[0]
				other = decl.participants[0 if inverse else 1].type
				result.append(Segment(name, "verb", owner=current, multi=True, next=other))
				current = other
				continue
			while index < len(steps) and self.source.structOf(attr.type):
				member, index = f"{member}.{steps[index]}", index + 1
				attr = self.source.lookup(current, member)
			resolved = self.source.resolveType(attr.type, attr.ann)
			reference = resolved.kind in ("entity", "relation")
			result.append(Segment(member, "ref" if reference else "attr", attr, current, isMulti(self.source, attr), resolved.path if reference else None))
			current = resolved.path if reference else None
		return result

	def position(self, segment: Segment) -> AnyValue:
		"""The slot capturing a top-level tree key: the attribute slot of a value, a field slot for references."""
		if segment.key not in self.positions:
			if segment.kind == "attr":
				self.positions[segment.key] = self.owner.attributeSlot(self.scope.source, segment.key, segment.owner)
			else:
				self.positions[segment.key] = slot(slotName("Map", self.short, "Fields", fieldName(segment.key.split("."))), Any)
		return self.positions[segment.key]

	def root(self, key: str) -> AnyValue:
		if key not in self.roots:
			self.roots[key] = slot(slotName("Map", "Root", key[1:].capitalize()), Any)
		return self.roots[key]

	def pathValue(self, steps: list[str]) -> tuple[AnyValue, list[Segment]]:
		segments = self.segments(steps)
		value = optional(self.position(segments[0]))
		if len(segments) > 1:
			navigation: list[str] = []
			for previous, segment in zip(segments, segments[1:]):
				navigation += (["set", "*", "of"] if previous.multi else ["of"]) + [segment.key]
			value = derive(V.Field, value, navigation)
		return value, segments

	# --- typing --------------------------------------------------------------

	def exprType(self, expr: Expression) -> AnyValue:
		"""The resolved type of an expression, for conversions; None when unknown."""
		if "path" in expr:
			segments = self.segments(expr["path"])
			last = segments[-1]
			if last.kind == "verb":
				return ResolvedType("entity", path=last.next)
			return self.source.resolveType(last.attr.type, last.attr.ann)
		if "call" in expr:
			name = expr["call"]
			if name in BUILTIN_RESULTS:
				return ResolvedType("builtin", builtin=BUILTIN_RESULTS[name])
			evaluator = self.owner.calls.evaluator
			if (function := evaluator.functions.get(name)) is not None:
				return _resolveSignature(evaluator.model, function.result)
			if (mapping := evaluator.maps.get(name)) is not None:
				return evaluator.model.resolveType(TypeExpr(path=mapping.mapTo))
			return None
		if "coalesce" in expr:
			return self.exprType(expr["coalesce"][0])
		if "meta" in expr:
			return ResolvedType("builtin", builtin="DateTime" if expr["meta"] == "at" else "Text")
		return None

	def convert(self, value: AnyValue, actual: AnyValue, attr: Attr) -> AnyValue:
		"""spec-04 typing conversions that a compile-time check cannot settle."""
		expected = self.target.resolveType(attr.type, attr.ann)
		if expected.kind in ("entity", "relation"):
			return derive(V.Correspond, value) if actual is not None and actual.kind in ("entity", "relation") else value
		if actual is None:
			return value
		if expected.kind == "builtin" and expected.builtin in NUMERIC + ("Duration",):
			if actual.kind == "builtin" and actual.builtin in NUMERIC + ("Duration",):
				if pair := qualifierPair(actual.qualifiers, expected.qualifiers):
					value = derive(V.QualifierConvert, value, pair[0], pair[1])
				if expected.builtin == "Integer" and actual.builtin != "Integer":
					value = derive(V.ToInteger, value)
		elif expected.kind == "vocab" and not expected.open:
			if actual.kind == "builtin" and actual.builtin == "Text" or actual.kind == "vocab" and actual.open:
				value = derive(V.ToVocabulary, value, list(expected.values or []))
		return value

	# --- expressions -----------------------------------------------------------

	def expression(self, expr: Expression) -> AnyValue:
		if "path" in expr:
			return self.pathValue(expr["path"])[0]
		if "call" in expr:
			name, args = expr["call"], expr["args"]
			if name == "ref":
				return self.reference(args[0]["path"][0], self.expression(args[1]))
			return derive(self.owner.calls.transform(name), *[self.expression(arg) for arg in args])
		if "coalesce" in expr:
			return derive(V.Coalesce, *[self.expression(item) for item in expr["coalesce"]])
		if "meta" in expr:
			return optional(self.root(f"${expr['meta']}"))
		return literal(expr)

	def reference(self, typePath: str, key: AnyValue) -> AnyValue:
		"""A generated `ref(T, Key)`: the handle from `T`'s policy key, else source-qualified with the key."""
		policy = self.owner.policy(typePath)
		if policy is not None:
			return derive(V.Ref, typePath, key)
		return derive(V.Ref, typePath, derive(V.builtin("concat"), optional(self.root("$scope")), "/", key))

	def paths(self, expr: Expression | None) -> list[list[str]]:
		if expr is None:
			return []
		if "path" in expr:
			return [expr["path"]]
		if "call" in expr:
			return [path for index, arg in enumerate(expr["args"]) if not (expr["call"] == "ref" and index == 0) for path in self.paths(arg)]
		if "coalesce" in expr:
			return [path for item in expr["coalesce"] for path in self.paths(item)]
		return []

	def condition(self, when: dict, value: AnyValue) -> AnyValue:
		return derive(V.When, derive(V.TextEquals, self.pathValue(when["path"])[0], when["value"]), value)

	def lineValue(self, line: AnyValue) -> tuple[AnyValue, LineInfo]:
		read = self.paths(line.expr)
		inputs = read + ([line.when["path"]] if line.when else [])
		# The source input comes from the expression (`{src=Path}`, else its first path), never from `when`.
		source = 0 if read else -1
		if line.src:
			wanted = line.src.split(".")
			source = next((index for index, path in enumerate(inputs) if path == wanted), 0)
		if line.facet:
			value: AnyValue = True
			info = LineInfo("facets", line.facet, inputs, source)
		else:
			value = self.expression(line.expr)
			actual = self.exprType(line.expr)
			key = line.target or line.verb
			head = key.split(".")[0]
			headAttr = self.target.lookup(self.scope.target, head) if line.target else None
			also = None
			if line.target and "." in key and headAttr is not None and self.target.resolveType(headAttr.type, headAttr.ann).kind in ("entity", "relation"):
				# `Ref.Attr <- Path` (a `{reverse}` line reversed): claimed on the referenced instance.
				referenced = self.target.resolveType(headAttr.type, headAttr.ann).path
				attr = self.target.lookup(referenced, key.split(".", 1)[1])
				also = head
			elif line.target:
				attr = self.target.lookup(self.scope.target, key)
			else:
				attr = None
			if attr is not None:
				value = self.convert(value, actual, attr)
			elif line.verb:
				value = derive(V.Correspond, value)
			info = LineInfo("links" if line.verb else "values", key, inputs, source, also)
		if line.when:
			value = self.condition(line.when, value)
		return value, info

	def template(self) -> dict[str, AnyValue]:
		candidates = self.owner.mapping.header.get("candidates") is True
		sections: dict[str, dict] = {"values": {}, "facets": {}, "links": {}}
		for line in self.scope.lines:
			if line.candidate and not candidates:
				continue
			value, info = self.lineValue(line)
			sections[info.section][info.key + "?"] = value
			self.lines.append(info)
		record: dict[str, AnyValue] = {"type": self.scope.target, "scope": self.name, "handle": optional(self.root("$target"))}
		if self.scope.valid is not None:
			record["valid?"] = derive(V.Valid, self.expression(self.scope.valid))
		if self.scope.ctx is not None:
			raise CompileError(V.MappingCodes.ContextUnsupported, f"Scope '{self.scope.source} -> {self.scope.target}' sets a context")
		return record | sections | {"source": Location}

	def handleTemplate(self) -> dict[str, AnyValue]:
		"""`{handle}`: derived from the key line of `T`'s policy, else source-qualified."""
		policy = self.owner.policy(self.scope.target)
		short = lastSegment(self.scope.target)
		if policy is None:
			return {"handle": derive(V.SourceHandle, short, optional(self.root("$scope")), optional(self.root("$handle")), self.scope.source)}
		key = policy.keys[0]
		line = next((item for item in self.scope.lines if item.target == key and (not item.candidate or self.owner.mapping.header.get("candidates") is True)), None)
		if line is None:
			raise CompileError(V.MappingCodes.PolicyUnsupported, f"No line of '{self.scope.source} -> {self.scope.target}' assigns key '{key}'")
		actual = self.exprType(line.expr)
		if actual is not None and actual.kind in ("entity", "relation"):
			raise CompileError(V.MappingCodes.KeyReference, f"Key '{key}' reads a reference's target")
		value = self.expression(line.expr)
		attr = self.target.lookup(self.scope.target, key)
		value = self.convert(value, actual, attr)
		if line.when:
			value = self.condition(line.when, value)
		return {"handle": derive(V.Handle, short, value)}

	def shape(self) -> AnyValue:
		fields = {f"{key}?": slotValue for key, slotValue in self.roots.items()}
		fields |= {f"{key}?": tolerant(position) for key, position in self.positions.items()}
		return loose(fields)

	def reach(self) -> dict:
		"""Every path the scope reads: `{key: {segment, children}}`, references continuing under their type."""
		tree: dict = {}
		paths = [path for line in self.scope.lines for path in self.paths(line.expr) + ([line.when["path"]] if line.when else [])]
		paths += self.paths(self.scope.valid) + ([self.scope.when["path"]] if self.scope.when else [])
		for steps in paths:
			node = tree
			for segment in self.segments(steps):
				node = node.setdefault(segment.key, {"segment": segment, "children": {}})["children"]
		return tree


class MappingCompiler:
	"""Compile every scope of a mapping, sharing attribute slots with bindings of the same ontology."""

	def __init__(self, fromOntology: Ontology, toOntology: Ontology, mapping: AnyValue, referential: AnyValue, libraries: list[FunctionLibrary] | None,
		implementations: dict | None, ontologies: list[Ontology] | None = None):
		self.model = Model(fromOntology)
		self.targetModel = Model(toOntology)
		self.mapping = mapping
		self.referential = referential
		self.slots: dict[str, AnyValue] = {}
		self.used: set[str] = set()
		decls = {decl.path: decl for item in [fromOntology, toOntology] + list(ontologies or []) for decl in item.decls}
		context = Ontology(namespace=fromOntology.namespace, header=fromOntology.header, decls=list(decls.values()))
		self.calls = Calls(FunctionEvaluator([context], libraries or [], mapping.functions, mapping.maps, implementations or {}), self.used)

	def attributeSlot(self, typePath: str, attrPath: str, owner: str | None = None) -> AnyValue:
		name = slotName(typePath, attrPath)
		if name not in self.slots:
			attr = self.model.lookup(owner or typePath, attrPath)
			self.slots[name] = slot(name, valueShape(self.model, attr))
		return self.slots[name]

	def policy(self, typePath: str) -> AnyValue:
		"""`T`'s identity policy when it derives handles here; minted and alternate keys are deferred."""
		if self.referential is None:
			return None
		found = policyFor(self.targetModel, self.referential, typePath)
		if found is None:
			return None
		if found.minted or len(found.keys) != 1:
			raise CompileError(V.MappingCodes.PolicyUnsupported, f"Policy of '{typePath}' needs a registry")
		if found.fromNamespace and found.fromNamespace != self.mapping.fromNamespace:
			return None
		return found

	def compile(self) -> list[MappingScopeCompiler]:
		ordered = sorted(self.mapping.scopes, key=lambda item: (item.source, item.target))
		result = []
		for scope in ordered:
			name = lastSegment(scope.source) + lastSegment(scope.target)
			result.append(MappingScopeCompiler(self, scope, name))
		return result


__all__ = ["CompileError", "BindingCompiler", "MappingCompiler", "MappingScopeCompiler", "LineInfo", "Segment", "ROOT_KEYS", "ScopeCompiler", "typeSpec", "scalarShape", "valueShape", "slotName", "fieldName", "Calls", "literal", "isMulti"]

# EOF
