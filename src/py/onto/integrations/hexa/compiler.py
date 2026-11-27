"""Module: integrations.hexa.compiler — ontology → slots; binding scope lines → selectors, shapes and record templates (spec-06)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Any as AnyValue

from hexa.core import NAME_RE
from hexa.shape import Slot, compileShape, validateShape
from hexa.shapes import Any, Bool, DateOnly, DatePattern, DateTime, Decimal, DecimalText, Location, Null, Origin, Text, Timed, Tuple, derive, either, gather, loose, optional, parsed, rest, slot, tolerant, via

from ...binding.model import Binding, BindingLine, BindingScope
from ...binding.operations import enclosingPath, enclosingScope, rootSteps
from ...conditions import conditionPaths, mapConditionPaths, testValues
from ...expressions import Expression, keyedSteps, printExpression
from ...formats.model import Formats
from ...functions.model import BUILTIN_RESULTS, FunctionLibrary
from ...functions.operations import resolveSignature
from ...functions.runtime import FunctionEvaluator
from ...inventory.operations import pascalCase
from ...ontology.model import Attr, Model, Ontology, ResolvedType, TypeExpr
from ...mapping.model import MappingScope, lookupOf
from ...mapping.operations import acceptedTypes, contextModel, correspondenceScopes, correspondenceTarget, namedCorrespondenceScope
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
	# NOTE: An element key (`Phones[Mobile]`) is a segment of its own, `Phones.KeyMobile`: hexa names are dotted names.
	return ".".join(segment for part in parts for segment in part.replace("[", ".Key").replace("]", "").replace("/", ".").split(".") if segment)


def localSlot(name: str, shape: AnyValue) -> Slot:
	"""Keep slots with revision-dependent shapes out of hexa's process-wide registry."""
	if not NAME_RE.fullmatch(name):
		raise ValueError("invalid slot name")
	compiled = compileShape(shape)
	validateShape(compiled)
	return Slot(name, compiled)


def isIndex(step: AnyValue) -> bool:
	return isinstance(step, dict) and "index" in step


def relativeStep(step: AnyValue) -> AnyValue:
	"""A path step in a relative key: a field name, `*` for `[*]`, the position for `[n]`."""
	if step == EACH:
		return "*"
	return step["index"] if isIndex(step) else step


def keyStep(step: AnyValue) -> AnyValue:
	"""The path step of a relative key's step (the inverse of `relativeStep`)."""
	return EACH if step == "*" else {"index": step} if isinstance(step, int) else step


def fieldName(steps: list[AnyValue]) -> str:
	"""`bond.couponRate` → `BondCouponRate`; `[*]` adds `All`, `[0]` adds `At0`."""
	return "".join("All" if step == EACH else f"At{step}" if isinstance(step, int) else pascalCase(step) for step in steps) or "Value"


def isLevel(step: AnyValue) -> bool:
	"""A selector level boundary: `[*]`, or an index step before one (selected as `*`, then picked)."""
	return step == EACH or isIndex(step)


def selectorSegment(step: AnyValue) -> str:
	if isLevel(step):
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


def conditionValue(condition: dict, pathValue) -> AnyValue:
	"""A condition as a template boolean (spec-04 Conditions): `pathValue(steps)` reads a test's path.

	A single value keeps `Onto.TextEquals`, so that programs with simple conditions compile as before."""
	for key, combine in (("all", V.AllOf), ("any", V.AnyOf)):
		if key in condition:
			return derive(combine, *[conditionValue(item, pathValue) for item in condition[key]])
	value = pathValue(condition["path"])
	if "value" in condition:
		return derive(V.TextEquals, value, condition["value"])
	return derive(V.TextIn, value, list(condition["values"])) if "values" in condition else derive(V.HasValue, value)


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
		"""Resolve a built-in or declared transform and record its use."""
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
		# A selector has no index form (hexa spec-004). Index steps after the last `[*]` are read by the
		# record's shape (`rows[*][0]` selects `rows/*`, and every line reads below position 0); an index
		# before a `[*]` is a selector level of its own, `*`, keeping only that position (`levelPicks`).
		steps = rootSteps(scope.path)
		self.recordSteps = steps
		last = max((index for index, step in enumerate(steps) if step == EACH), default=-1)
		first = next((index for index, step in enumerate(steps) if isIndex(step) and index > last), len(steps))
		if first < len(steps):
			try:
				first = max(first, len(enclosingPath(steps, 1, owner.binding.scopes)))
			except ValueError:
				pass
		self.steps = steps[:first]
		self.prefix = tuple(relativeStep(step) for step in steps[first:])
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
		"""The key of a path read from the record: `*` for `[*]`, an integer for `[n]`, below the scope's index prefix."""
		return self.prefix + tuple(relativeStep(step) for step in steps)

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
		"""Resolve the line's target attribute, or raise a type mismatch."""
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
		"""Render a relative position as a binding document path."""
		steps = list(self.steps) + [keyStep(step) for step in key]
		if steps and isLevel(steps[0]):
			steps.insert(0, {"root": True})
		return printExpression({"path": steps}, binding=True)

	def plan(self) -> None:
		"""Count reads, choose direct attribute positions, then declare field positions."""
		scope = self.scope
		for expr in (scope.id, scope.valid, scope.ctx):
			self.countReads(expr)
		for path in conditionPaths(scope.deleted):
			self.countReads({"path": path})
		for line in scope.lines:
			if line.expr is not None and not self.isEnclosing(line.expr):
				self.countReads(line.expr)
			for path in conditionPaths(line.when):
				self.countReads({"path": path})
			if self.nullPolicy(line) and line.expr is not None and len(paths := self.linePaths(line.expr)) == 1:
				self.nullPolicies[paths[0]] = self.nullPolicy(line)
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
			capture = localSlot(slotName("Bind", self.short, "Fields", fieldName([EACH if step == "*" else step for step in key])), [Any] if collection else Any)
			codecs = self.patterns(key, self.formatted[key]) if key in self.formatted else []
			self.positions[key] = Position(capture, codecs, collection)
		for key, kind in self.nullPolicies.items():
			if key in self.positions:
				self.positions[key].nulls = slot(slotName("Bind", self.short, "Nulls", fieldName([EACH if step == "*" else step for step in key])), Null)

	def linePaths(self, expr: Expression) -> list[tuple]:
		"""Collect the record-relative paths read by an expression."""
		if "path" in expr:
			first = expr["path"][0]
			return [] if isinstance(first, dict) and "each" not in first else [self.relative(expr["path"])]
		if "call" in expr:
			return [path for index, arg in enumerate(expr["args"]) if not (expr["call"] == "ref" and index == 0) for path in self.linePaths(arg)]
		if "coalesce" in expr:
			return [path for item in expr["coalesce"] for path in self.linePaths(item)]
		return []

	def nullPolicy(self, line: BindingLine) -> str | None:
		return line.null or self.owner.binding.header.get("null")

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
			positions = [name for name in node if isinstance(name, int)]
			if not positions:
				return loose({name + "?": value(child, inList) for name, child in node.items()})
			if len(positions) < len(node):
				raise CompileError(V.BindingCodes.PathUnsupported, "A value is read both as a list position and as a field")
			# hexa has no index access: positions are matched by a tuple, positions not read by `Any`
			# and further items by `rest(Any)`. A list too short fails the tuple: a hole where it is
			# a field, a gap for the record where it is the record (`rows[*][1]`).
			return Tuple(*[value(node[index], inList) if index in node else Any for index in range(max(positions) + 1)], rest(Any))

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
		levels: list[list[str]] = [[blockText(self.blocks[0])] if 0 in self.blocks else []]
		for offset, step in enumerate(steps, 1):
			levels[-1].append(selectorSegment(step))
			if offset in self.blocks:
				levels[-1].append(blockText(self.blocks[offset]))
			if isLevel(step):
				levels.append([])
		if not levels[-1] and len(levels) > 1:
			levels.pop()
		return ["/".join(level) for level in levels]

	def levelPicks(self) -> list[int | None]:
		"""Per selector level, the position its `*` keeps (an index step), or None to keep every element."""
		picks = [step["index"] if isIndex(step) else None for step in self.steps if isLevel(step)]
		return picks + [None] * (len(self.levels()) - len(picks))

	def selector(self) -> str:
		"""The scope's whole selector, as spec-06 writes it."""
		return "/".join(level for level in self.levels() if level)

	# --- templates --------------------------------------------------------------

	def capture(self, offset: int, up: int, name: str) -> AnyValue:
		"""A field captured at a prefix of the selector path."""
		fields = self.blocks.setdefault(offset, {})
		if name not in fields:
			if offset == 0:
				owner = "Root"
			else:
				owner = "Outer" if up == 1 else f"Outer{up}"
			# Textual selectors resolve these fixed-shape captures through hexa's slot registry.
			fields[name] = slot(slotName("Bind", self.short, "Fields", owner, pascalCase(name)), Any)
			self.outer.append(fields[name])
			self.outer.sort(key=lambda item: item.name)
		return fields[name]

	def pathValue(self, steps: list[AnyValue]) -> AnyValue:
		"""Compile a path into a captured or derived template value."""
		first = steps[0]
		if isinstance(first, dict) and ("root" in first or "up" in first):
			up = first.get("up", 0)
			try:
				offset = len(enclosingPath(self.recordSteps, up, self.owner.binding.scopes)) if up else 0
			except ValueError as error:
				raise CompileError(V.BindingCodes.PathUnsupported, str(error)) from error
			rest = [relativeStep(step) for step in steps[1:]]
			if not rest or not isinstance(rest[0], str) or rest[0] == "*":
				raise CompileError(V.BindingCodes.PathUnsupported, "An enclosing path must name a field")
			if offset == 0 and self.owner.atSlot is not None and rest == [self.owner.atField]:
				self.registerAt()
				return derive(V.Present, optional(self.owner.atSlot))
			# Captured and navigated values are raw JSON, where a record's positions match `null` first.
			captured = optional(self.capture(offset, up, rest[0]))
			return derive(V.Present, derive(V.Field, captured, rest[1:]) if len(rest) > 1 else captured)
		key = self.relative(steps)
		for index in range(1, len(key)):
			if key[:index] in self.positions:
				return derive(V.Present, derive(V.Field, optional(self.positions[key[:index]].slot), list(key[index:])))
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
		return derive(V.When, conditionValue(when, self.pathValue), value)

	def lineValue(self, line: BindingLine) -> AnyValue:
		"""Compile a binding line, including null policy and condition."""
		expr = line.expr
		if line.facet:
			value = True
		elif line.target is not None and not self.isEnclosing(expr) and (key := next((key for key, (item, _) in self.direct.items() if item is line), None)) is not None:
			position = self.positions[key]
			value = optional(position.slot)
			if position.nulls is not None:
				value = derive(V.Nullable, value, optional(position.nulls), self.nullPolicy(line))
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
				if position.nulls is not None and (policy := self.nullPolicy(line)):
					value = derive(V.Nullable, value, optional(position.nulls), policy)
				if len(position.codecs) > 1:
					self.formats[self.fieldPath(paths[0])] = derive(V.FormatName, parsed(position.slot))
		if line.unset is not None:
			# Compared with the read value's text: numbers as the canonical decimals reading gives
			spec = typeSpec(self.model, self.attribute(line))
			value = derive(V.Unset, value, V.decimalText(line.unset) if spec in ("Integer", "Decimal", "Duration:unit") else line.unset)
		if line.when:
			value = self.condition(line.when, value)
		return value

	def template(self) -> dict[str, AnyValue]:
		"""Build the scope's record template from its lines and metadata."""
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
		if self.owner.binding.valid is not None:
			record["documentValid?"] = derive(V.Valid, self.expression(rootExpression(self.owner.binding.valid)))
		if scope.ctx is not None:
			record["ctx?"] = self.expression(scope.ctx)
		if scope.deleted:
			record["deleted?"] = conditionValue(scope.deleted, self.pathValue)
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
		if at is not None and "path" in at and len(steps := rootSteps(at)) == 1 and isinstance(steps[0], str):
			self.atField = steps[0]
			self.atSlot = slot("Bind.At", Any)

	def attributeSlot(self, typePath: str, attrPath: str) -> AnyValue:
		"""Return the cached attribute slot, declaring it on first use."""
		name = slotName(typePath, attrPath)
		if name not in self.slots:
			attr = self.model.lookup(typePath, attrPath)
			self.slots[name] = localSlot(name, valueShape(self.model, attr))
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
		"""Expand a structure member into leaf paths, stopping at cycles."""
		attr = self.model.lookup(owner, member)
		structure = self.model.structOf(attr.type) if attr else None
		if not structure or not structure.fields or structure.path in seen:
			return [member]
		return [leaf for item in structure.fields for leaf in self.leaves(owner, f"{member}.{item.name}", seen | {structure.path})]

	def scopes(self) -> list[BindingScope]:
		"""Return binding scopes in type and document-path order."""
		return sorted(self.binding.scopes, key=lambda item: (item.type, printExpression(item.path, binding=True)))

	def enclosing(self, scope: BindingScope, up: int) -> BindingScope | None:
		"""Find the scope enclosing `scope` by `up` levels, if any."""
		try:
			path = enclosingPath(rootSteps(scope.path), up, self.binding.scopes)
		except ValueError:
			return None
		return enclosingScope(path, self.binding.scopes)

	def atValue(self, scope: ScopeCompiler) -> AnyValue:
		at = self.binding.at
		if self.atSlot is not None:
			scope.registerAt()
			return derive(V.Present, optional(self.atSlot))
		return scope.expression(rootExpression(at))

	def compile(self) -> list[ScopeCompiler]:
		"""Declare slots and plan uniquely named scopes in normal-form order."""
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
	context: str | None = None
	lookup: AnyValue = None  # a `lookup` step: the `@lookup` declaration it reads through


@dataclass(slots=True)
class LineInfo:
	"""A compiled mapping line: its record key, the paths it reads (`when` included) and its source input."""

	section: str
	key: str
	inputs: list[list[str]]
	source: int = 0
	also: str | None = None
	contextual: bool = False
	contextType: str | None = None
	qualifiers: tuple[str, ...] = ()
	slot: str = ""  # the record key, when exclusive lines share the target `key`
	when: dict | None = None  # the line's condition (spec-04 Conditions), paths with keyed steps
	unless: dict | None = None  # a default's: `{path, values}` of its exclusive siblings

	@property
	def record(self) -> str:
		return self.slot or self.key

	def sourcePath(self, paths: list[list[str]]) -> list[str]:
		"""The pointers of the source input's path; none for literals and facets."""
		return paths[self.source] if 0 <= self.source < len(paths) else []


ROOT_KEYS = ("@handle", "@type", "@scope", "@target", "@self", "@valid", "@at", "@src")
SELF = [{"root": True}]


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
		self.when = self.compiledCondition(scope.when)
		if ["@self"] in conditionPaths(self.when):
			self.root("@self")
		self.sourceRefs: dict[str, tuple[str, list[str]]] = {}  # `@ref<n>` -> (source type, key path): `ref(S, Key)`

	# --- paths ---------------------------------------------------------------

	def segments(self, steps: list[str]) -> list[Segment]:
		"""Walk attribute `steps` from the scope's source type, through facets, structures and references."""
		if steps == ["@self"]:
			return [Segment("@self", "self")]
		steps = keyedSteps(steps)
		result: list[Segment] = []
		current, index = self.scope.source, 0
		if lookup := lookupOf(self.owner.mapping.lookups, steps[0], current, self.source):
			# The scope instance's lookup: the instance it finds, read on as a reference (spec-04 Lookups)
			result.append(Segment(steps[0], "lookup", None, current, False, lookup.type, None, lookup))
			current, index = lookup.type, 1
		while index < len(steps):
			if current is None:
				raise CompileError(V.MappingCodes.ReferenceUnmapped, f"Path '{'.'.join(steps)}' reads through a value")
			name = steps[index]
			facet = self.source.facetOf(current, name)
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
			result.append(Segment(member, "ref" if reference else "attr", attr, current, isMulti(self.source, attr), resolved.path if reference else None,
				annotation(facet.ann, "ctx") if facet else None))
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
		"""Compile a source path and return its value and resolved segments."""
		segments = self.segments(steps)
		if steps == ["@self"]:
			return optional(self.root("@self")), segments
		value = optional(self.position(segments[0]))
		if segments[0].kind == "lookup":
			# The one instance found; several, or a compared value in conflict, are ambiguous, never the first
			value = derive(V.Single, value)
		if len(segments) > 1:
			navigation: list[str] = []
			for previous, segment in zip(segments, segments[1:]):
				navigation += (["set", "*", "of"] if previous.multi else ["of"]) + [segment.key]
			value = derive(V.Field, value, navigation)
		return value, segments

	# --- typing --------------------------------------------------------------

	def exprType(self, expr: Expression) -> AnyValue:
		"""The resolved type of an expression, for conversions; None when unknown."""
		if expr.get("path") == SELF:
			return self.source.resolveType(TypeExpr(path=self.scope.source))
		if "path" in expr:
			segments = self.segments(expr["path"])
			last = segments[-1]
			if last.kind == "verb":
				return ResolvedType("entity", path=last.next)
			if last.kind == "lookup":
				return self.source.resolveType(TypeExpr(path=last.next))
			return self.source.resolveType(last.attr.type, last.attr.ann)
		if "call" in expr:
			name = expr["call"]
			if self.isSourceRef(expr):
				return self.source.resolveType(TypeExpr(path=expr["args"][0]["path"][0]))
			if name == "ref":
				path = expr["args"][0]["path"][0]
				return self.target.resolveType(TypeExpr(path=path)) if self.owner.mapping.isTargetType(path) else None
			if name in BUILTIN_RESULTS:
				return ResolvedType("builtin", builtin=BUILTIN_RESULTS[name])
			evaluator = self.owner.calls.evaluator
			if (function := evaluator.functions.get(name)) is not None:
				return resolveSignature(evaluator.model, function.result)
			if (mapping := evaluator.maps.get(name)) is not None:
				return evaluator.mapTargetModel(name).resolveType(TypeExpr(path=mapping.mapTo))
			return None
		if "coalesce" in expr:
			return next((kind for item in expr["coalesce"] if (kind := self.exprType(item)) is not None), None)
		if "meta" in expr:
			return ResolvedType("builtin", builtin="DateTime" if expr["meta"] == "at" else "Text")
		return None

	def convert(self, value: AnyValue, actual: AnyValue, attr: Attr) -> AnyValue:
		"""spec-04 typing conversions that a compile-time check cannot settle."""
		expected = self.target.resolveType(attr.type, attr.ann)
		if expected.kind in ("entity", "relation"):
			return self.owner.correspond(value, actual.path, [expected.path]) if actual is not None and actual.kind in ("entity", "relation") else value
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
		"""Compile a mapping expression into a template value."""
		if expr.get("path") == SELF:
			# `$`: the scope instance, as a reference with its target instances
			return optional(self.root("@self"))
		if "path" in expr:
			return self.pathValue(expr["path"])[0]
		if "call" in expr:
			name, args = expr["call"], expr["args"]
			if self.isSourceRef(expr):
				# Resolved while unfolding: the source instance's handle from its key, as a reference read from the state.
				key = next((name for name, item in self.sourceRefs.items() if item == (args[0]["path"][0], args[1]["path"])), f"@ref{len(self.sourceRefs)}")
				self.sourceRefs[key] = (args[0]["path"][0], args[1]["path"])
				return optional(self.root(key))
			if name == "ref":
				return self.reference(args[0]["path"][0], self.expression(args[1]))
			return derive(self.owner.calls.transform(name), *[self.expression(arg) for arg in args])
		if "coalesce" in expr:
			return derive(V.Coalesce, *[self.expression(item) for item in expr["coalesce"]])
		if "meta" in expr:
			return optional(self.root(f"@{expr['meta']}"))
		return literal(expr)

	def isSourceRef(self, expr: Expression) -> bool:
		"""`ref(S, Key)` written in a mapping names a source type; generated reverses name target types."""
		if expr.get("call") != "ref" or len(expr["args"]) != 2 or "path" not in expr["args"][1]:
			return False
		mapping = self.owner.mapping
		typePath = expr["args"][0]["path"][0]
		return mapping.fromNamespace != mapping.toNamespace and typePath.startswith(mapping.fromNamespace + "/") and self.source.get(typePath) is not None

	def reference(self, typePath: str, key: AnyValue) -> AnyValue:
		"""A generated `ref(T, Key)`: the handle from `T`'s policy key, else source-qualified with the key."""
		policy = self.owner.policy(typePath)
		if policy is not None:
			return derive(V.Ref, typePath, key)
		return derive(V.Ref, typePath, derive(V.builtin("concat"), optional(self.root("@scope")), "/", key))

	def paths(self, expr: Expression | None) -> list[list[str]]:
		"""Collect source paths read by a mapping expression."""
		if expr is None:
			return []
		if "path" in expr:
			return [] if expr["path"] == SELF else [keyedSteps(expr["path"])]
		if "call" in expr:
			return [path for index, arg in enumerate(expr["args"]) if not (expr["call"] == "ref" and index == 0) for path in self.paths(arg)]
		if "coalesce" in expr:
			return [path for item in expr["coalesce"] for path in self.paths(item)]
		return []

	def condition(self, when: dict, value: AnyValue) -> AnyValue:
		return derive(V.When, conditionValue(when, lambda steps: self.pathValue(steps)[0]), value)

	def compiledCondition(self, condition: dict | None) -> dict | None:
		"""Use occurrence-tree keys for `$` and the same keyed steps as expressions for member paths."""
		return mapConditionPaths(condition, lambda path: ["@self"] if path == SELF else keyedSteps(path)) if condition else None

	def lineValue(self, line: AnyValue, exclusive: dict | None = None) -> tuple[AnyValue, LineInfo]:
		"""`exclusive`, for the default of exclusive lines: the `{path, values}` of its siblings' conditions."""
		read = self.paths(line.expr)
		when, exclusive = self.compiledCondition(line.when), self.compiledCondition(exclusive)
		inputs = read + [path for expr in line.qualifiers.values() for path in self.paths(expr)] + conditionPaths(when)
		inputs += [exclusive["path"]] if exclusive else []
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
			if line.name and actual is not None and actual.kind in ("entity", "relation"):
				# `{name=N}`: the target of the scope line named N, which that scope must have emitted
				accepted = acceptedTypes(self.target, self.scope.target, key, attr)
				value = derive(V.CorrespondNamed, value, *self.owner.namedTarget(actual.path, line.name, accepted))
			elif line.asType and actual is not None and actual.kind in ("entity", "relation"):
				# `{as=T}`: the instance's target of type T, which its scope line must have emitted
				value = derive(V.CorrespondEmitted, value, line.asType)
			elif attr is not None:
				value = self.convert(value, actual, attr)
			elif line.verb:
				accepted = [relation.participants[0 if inverse else 1].type for relation, inverse in self.target.verbs(self.scope.target, line.verb)]
				value = self.owner.correspond(value, actual.path if actual is not None and actual.kind in ("entity", "relation") else None, accepted)
			info = LineInfo("links" if line.verb else "values", key, inputs, source, also)
		info.qualifiers = tuple(line.qualifiers)
		info.when, info.unless = when, exclusive
		if when:
			value = self.condition(when, value)
		elif exclusive:
			value = derive(V.WhenNone, self.pathValue(exclusive["path"])[0], exclusive["values"], value)
		info.contextual = any(segment.context for path in inputs for segment in self.segments(path))
		facet = self.target.facets(self.scope.target).get(line.facet) if line.facet else self.target.facetOf(self.scope.target, info.key)
		info.contextType = annotation(facet.ann, "ctx") if facet else None
		return value, info

	def template(self) -> dict[str, AnyValue]:
		"""Build the target record template and collect its line metadata."""
		candidates = self.owner.mapping.header.get("candidates") is True
		sections: dict[str, dict] = {"values": {}, "facets": {}, "links": {}}
		qualifiers = {}
		active = [line for line in self.scope.lines if not line.candidate or candidates]
		groups: dict[str, list] = {}
		for line in active:
			groups.setdefault(f"[{line.facet}]" if line.facet else line.target or line.verb, []).append(line)
		for line in active:
			# Exclusive lines of one target (spec-04): one record key each; the default applies when no condition matches.
			group = groups[f"[{line.facet}]" if line.facet else line.target or line.verb]
			conditions = [item.when for item in group if item.when]
			exclusive = {"path": conditions[0]["path"], "values": [value for when in conditions for value in testValues(when)]} if len(group) > 1 and not line.when else None
			value, info = self.lineValue(line, exclusive)
			if len(group) > 1:
				info.slot = f"{info.key}#{group.index(line)}"
			sections[info.section][info.record + "?"] = value
			self.lines.append(info)
			if line.qualifiers:
				qualifiers[info.record] = {key + "?": self.expression(expr) for key, expr in line.qualifiers.items()}
		record: dict[str, AnyValue] = {"type": self.scope.target, "scope": self.name, "handle": optional(self.root("@target"))}
		if self.scope.valid is not None:
			record["valid?"] = derive(V.Valid, self.expression(self.scope.valid))
		if self.scope.ctx is not None:
			actual = self.exprType(self.scope.ctx)
			record["ctx?"] = self.owner.correspond(self.expression(self.scope.ctx), actual.path if actual else None)
		if self.scope.present is not None:
			record["present?"] = self.expression(self.scope.present)
		return record | sections | ({"qualifiers": qualifiers} if qualifiers else {}) | {"source": Location}

	def handleTemplate(self) -> dict[str, AnyValue]:
		"""`{handle}`: derived from a single key line of `T`'s policy, else source-qualified."""
		if self.scope.into is not None:
			actual = self.exprType(self.scope.into)
			value = self.owner.correspond(self.expression(self.scope.into), actual.path, [self.scope.target])
			if any(segment.multi for path in self.paths(self.scope.into) for segment in self.segments(path)):
				# A multi-valued selector names its one member; several are ambiguous, never the first.
				value = derive(V.Single, value)
			record = {"handle?": derive(V.Field, value, ["ref"])}
			if self.scope.present is not None:
				record["present?"] = self.expression(self.scope.present)
			return record
		policy = self.owner.policy(self.scope.target)
		short = lastSegment(self.scope.target)
		if policy is None:
			scope = optional(self.root("@scope"))
			if self.scope.name:
				scope = derive(V.builtin("concat"), scope, "/@", self.scope.name)
			return {"handle": derive(V.SourceHandle, short, scope, optional(self.root("@handle")), self.scope.source)}
		if self.scope.name:
			raise CompileError(V.MappingCodes.PolicyUnsupported, "Named scopes currently require source-qualified identities")
		key = policy.keys[0]
		candidates = self.owner.mapping.header.get("candidates") is True
		lines = [line for line in self.scope.lines if line.target == key and (not line.candidate or candidates)]
		if not lines:
			raise CompileError(V.MappingCodes.PolicyUnsupported, f"No line of '{self.scope.source} -> {self.scope.target}' assigns key '{key}'")
		if len(lines) > 1:
			# Handle projection precedes body emission and its transforms evaluate arguments eagerly:
			# coalescing the branches would run inactive expressions and treat a conflicting condition as absent.
			raise CompileError(V.MappingCodes.PolicyUnsupported, f"Exclusive assignments to referential key '{key}' are not supported")
		line = lines[0]
		actual = self.exprType(line.expr)
		if actual is not None and actual.kind in ("entity", "relation"):
			raise CompileError(V.MappingCodes.KeyReference, f"Key '{key}' reads a reference's target")
		value = self.expression(line.expr)
		attr = self.target.lookup(self.scope.target, key)
		value = self.convert(value, actual, attr)
		if line.when:
			value = self.condition(self.compiledCondition(line.when), value)
		# spec-05: a record without its key keeps a source-qualified handle; it never becomes a gap
		return {"handle": derive(V.KeyedHandle, short, value, optional(self.root("@scope")), optional(self.root("@handle")), self.scope.source)}

	def shape(self) -> AnyValue:
		"""Build the loose input shape from registered root and field slots."""
		fields = {f"{key}?": slotValue for key, slotValue in self.roots.items()}
		fields |= {f"{key}?": tolerant(position) for key, position in self.positions.items()}
		return loose(fields)

	def reach(self) -> dict:
		"""Every path the scope reads: `{key: {segment, children}}`, references continuing under their type."""
		tree: dict = {}
		paths = [path for line in self.scope.lines for path in self.paths(line.expr) + conditionPaths(self.compiledCondition(line.when))]
		paths += [path for line in self.scope.lines for expr in line.qualifiers.values() for path in self.paths(expr)]
		paths += self.paths(self.scope.valid) + self.paths(self.scope.ctx) + self.paths(self.scope.present) + self.paths(self.scope.into) + conditionPaths(self.when)
		for steps in paths:
			if steps == ["@self"]:
				continue  # the occurrence supplies this root separately from the attribute subtree
			node = tree
			for segment in self.segments(steps):
				node = node.setdefault(segment.key, {"segment": segment, "children": {}})["children"]
		return tree


def scopeProgramIds(scopes: list[MappingScope]) -> dict[tuple[str, str, str], str]:
	"""Keep existing readable IDs where unique; otherwise append an unambiguous encoding of the full scope key."""
	short = {scope.key: lastSegment(scope.source) + lastSegment(scope.target) + ("_" + scope.name if scope.name else "") for scope in scopes}
	counts = Counter(short.values())
	return {key: name if counts[name] == 1 else name + "." + ".".join(V.encodeKey(part) for part in key if part)
		for key, name in short.items()}


class MappingCompiler:
	"""Compile every scope of a mapping, using the same attribute slot definitions as bindings."""

	def __init__(self, fromOntology: Ontology, toOntology: Ontology, mapping: AnyValue, referential: AnyValue, libraries: list[FunctionLibrary] | None,
		implementations: dict | None, ontologies: list[Ontology] | None = None):
		self.model = Model(fromOntology)
		self.targetModel = Model(toOntology)
		self.mapping = mapping
		self.scopeIds = scopeProgramIds(mapping.scopes)
		self.referential = referential
		self.slots: dict[str, AnyValue] = {}
		self.used: set[str] = set()
		contexts = [fromOntology, toOntology] + list(ontologies or [])
		context = contextModel(fromOntology, contexts).ontology
		target = contextModel(toOntology, contexts) if mapping.maps else None
		self.calls = Calls(FunctionEvaluator([context], libraries or [], mapping.functions, mapping.maps, implementations or {},
			mapTargetModel=target), self.used)

	def attributeSlot(self, typePath: str, attrPath: str, owner: str | None = None) -> AnyValue:
		name = slotName(typePath, attrPath)
		if name not in self.slots:
			attr = self.model.lookup(owner or typePath, attrPath)
			self.slots[name] = localSlot(name, valueShape(self.model, attr))
		return self.slots[name]

	def correspond(self, value: AnyValue, source: str | None, accepted: list[str] | None = None) -> AnyValue:
		"""Translate a source reference to the accepted target; an already-target reference needs no translation."""
		if self.mapping.isTargetType(source):
			return value
		if source is None or len(correspondenceScopes(self.model, self.mapping, source)) < 2:
			return derive(V.Correspond, value)
		try:
			target = correspondenceTarget(self.model, self.targetModel, self.mapping, source, accepted)
		except ValueError as error:
			raise CompileError(V.MappingCodes.ReferenceUnmapped, str(error)) from error
		return derive(V.CorrespondAs, value, target)

	def namedTarget(self, source: str, name: str, accepted: list[str]) -> tuple[str, str]:
		"""The program scope and target type of the scope line named `name` that a reference to `source` translates through."""
		scope = namedCorrespondenceScope(self.model, self.targetModel, self.mapping, source, name, accepted)
		return self.scopeIds[scope.key], scope.target

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
		return [MappingScopeCompiler(self, scope, self.scopeIds[scope.key]) for scope in sorted(self.mapping.scopes, key=lambda item: item.key)]


__all__ = ["CompileError", "BindingCompiler", "MappingCompiler", "MappingScopeCompiler", "LineInfo", "Segment", "ROOT_KEYS", "ScopeCompiler", "typeSpec", "scalarShape", "valueShape", "slotName", "fieldName", "Calls", "literal", "isMulti"]

# EOF
