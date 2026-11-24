"""Module: binding.operations — ontology-backed declaration resolution and interchange."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..expressions import Expression
from ..functions.model import BUILTIN_ARITIES, BUILTIN_RESULTS, Function, FunctionLibrary, FunctionsDocument
from ..functions.operations import resolveSignature, resolveFunctions
from ..ontology.model import Model, Ontology, ResolvedType, TypeExpr, isAssociation
from ..text import Diagnostics, FormatError, Loc, Source, annotation
from .formatter import bindingToJson, printBinding
from .model import Binding, BindingDocument, BindingScope
from .parser import parseBinding, qualifyPath, readBindingJson

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Inferred = tuple[ResolvedType | None, bool]

NUMERIC = ("Integer", "Number", "Amount", "Percent")


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def rootSteps(path: Expression) -> list[Any]:
	"""Return `path` steps without an initial root marker."""
	steps = path["path"]
	return steps[1:] if steps[:1] == [{"root": True}] else steps


def enclosingPath(steps: list[Any], up: int, scopes: list[BindingScope]) -> list[Any]:
	"""Find an ancestor record, counting both list elements and explicit scope prefixes."""
	ancestors = [steps[:index + 1] for index, step in enumerate(steps[:-1]) if isinstance(step, dict) and ("each" in step or "index" in step)]
	# Explicit object scopes also introduce records, including a document-root object.
	for parent in scopes:
		path = rootSteps(parent.path)
		if len(path) < len(steps) and path == steps[:len(path)] and path not in ancestors:
			ancestors.append(path)
	ancestors.sort(key=len, reverse=True)
	if up > len(ancestors):
		raise ValueError("Ancestor path goes beyond the enclosing records")
	return ancestors[up - 1]


def enclosingScope(path: list[Any], scopes: list[BindingScope]) -> BindingScope | None:
	"""A bare `^` requires exactly one scope defining the enclosing instance."""
	parents = [scope for scope in scopes if rootSteps(scope.path) == path]
	return parents[0] if len(parents) == 1 else None


def compatible(model: Model, actual: ResolvedType, expected: ResolvedType) -> bool:
	"""Check whether the inferred value is compatible with the target type."""
	if actual.kind == expected.kind == "builtin":
		if actual.builtin != expected.builtin and {actual.builtin, expected.builtin} != {"Integer", "Number"}:
			return False
		for key in ("cur", "period"):
			left, right = actual.qualifiers.get(key, "?"), expected.qualifiers.get(key, "?")
			if "?" not in (left, right) and left != right:
				return False
		if actual.builtin == "Duration":
			left, right = actual.qualifiers.get("unit", "?"), expected.qualifiers.get("unit", "?")
			if left != right and "?" not in (left, right) and not any(left in group and right in group for group in (("Second", "Minute", "Hour", "Day", "Week"), ("Month", "Year"))):
				return False
		return True
	if actual.kind == expected.kind == "range":
		return actual.element is not None and expected.element is not None and compatible(model, actual.element, expected.element)
	if actual.kind == expected.kind == "vocab":
		return expected.open or not actual.open and set(actual.values or []) <= set(expected.values or [])
	if actual.kind == "vocab" and expected.builtin == "Text" or actual.builtin == "Text" and expected.kind == "vocab":
		return True
	return actual.kind == expected.kind and actual.path is not None and (actual.path == expected.path or model.isA(actual.path, expected.path))


def checkAssignment(model: Model, inferred: Inferred, expected: ResolvedType, collection: bool, what: str) -> None:
	"""Validate an inferred assignment against its target."""
	actual, plural = inferred
	if plural and not collection:
		raise ValueError(f"{what}: a collection cannot supply a single value")
	if actual is not None and not compatible(model, actual, expected):
		raise ValueError(f"{what}: incompatible expression type for the target")


def checkScalarTarget(model: Model, attr: Any, name: str) -> None:
	"""A structured attribute has no value of its own: its fields are assigned (`Attr.Field <- ...`)."""
	if model.resolveType(attr.type, attr.ann).kind == "struct":
		raise ValueError(f"{name}: a structure has no value of its own; assign its fields ({name}.<Field>)")


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class ExpressionResolver:
	"""Resolve binding function/type names and statically known expression shapes."""

	model: Model
	namespace: str
	uses: dict[str, str]
	functions: dict[str, Function]
	scopes: list[BindingScope] = field(default_factory=list)
	scope: BindingScope | None = None

	def resolve(self, expr: Expression) -> Inferred:
		if "path" in expr:
			steps = expr["path"]
			if isinstance(steps[0], dict) and "up" in steps[0]:
				if self.scope is None:
					raise ValueError("Ancestor paths require a record scope")
				path = enclosingPath(rootSteps(self.scope.path), steps[0]["up"], self.scopes)
				if len(steps) == 1:
					parent = enclosingScope(path, self.scopes)
					if parent is None:
						raise ValueError("An enclosing instance reference requires one defining parent scope")
					return self.model.resolveType(TypeExpr(path=parent.type)), False
			return None, any(step == {"each": True} for step in steps)
		if "coalesce" in expr:
			inferred = [self.resolve(item) for item in expr["coalesce"]]
			known = [kind for kind, _ in inferred if kind is not None]
			if known and any(not compatible(self.model, kind, known[0]) for kind in known[1:]):
				raise ValueError("Coalesce alternatives have incompatible types")
			return known[0] if known else None, any(plural for _, plural in inferred)
		if "call" in expr:
			return self.call(expr)
		for key, builtin in (("text", "Text"), ("number", "Number"), ("boolean", "Boolean")):
			if key in expr:
				return ResolvedType("builtin", builtin=builtin), False
		return None, False

	def call(self, expr: Expression) -> Inferred:
		name, args = expr["call"], expr["args"]
		if name in BUILTIN_ARITIES:
			minimum, maximum = BUILTIN_ARITIES[name]
			if len(args) < minimum or maximum is not None and len(args) > maximum:
				raise ValueError(f"Invalid argument count for '{name}'")
			if name == "ref":
				if set(args[0]) != {"path"} or len(args[0]["path"]) != 1 or not isinstance(args[0]["path"][0], str):
					raise ValueError("ref requires an instance type as its first argument")
				path = qualifyPath(args[0]["path"][0], self.namespace, self.uses)
				decl = self.model.get(path)
				if not decl or decl.kind != "entity" and not isAssociation(decl):
					raise ValueError(f"Unknown reference type '{path}'")
				args[0] = {"path": [path]}
				kind, plural = self.resolve(args[1])
				checkAssignment(self.model, (kind, False), ResolvedType("builtin", builtin="Text"), True, "ref key")
				return self.model.resolveType(TypeExpr(path=path)), plural
			inferred = [self.resolve(arg) for arg in args]
			if name in ("count", "join") and inferred[0][0] is not None and not inferred[0][1]:
				raise ValueError(f"'{name}' requires a collection argument")
			for index, (actual, plural) in enumerate(inferred):
				if name in ("text", "count") or actual is None:
					continue
				if name in ("sum", "multiply", "subtract", "divide"):
					if actual.builtin not in NUMERIC:
						raise ValueError(f"'{name}' requires numeric arguments")
				elif name == "date" and len(args) == 1:
					if actual.builtin != "Integer":
						# Number literals have one JSON number variant; integrality is checked on execution.
						if actual.builtin != "Number":
							raise ValueError("date(a) requires an integer epoch")
				elif name == "epoch" or name == "format" and index == 0:
					if actual.builtin not in (("Date",) if name == "epoch" else ("Date", "DateTime")):
						raise ValueError(f"'{name}' requires a date value")
				elif actual.builtin != "Text" and actual.kind != "vocab":
					raise ValueError(f"'{name}' requires text arguments")
			plural = name == "split" or name != "count" and any(plural for index, (_, plural) in enumerate(inferred) if not (name == "join" and index == 0))
			return ResolvedType("builtin", builtin=BUILTIN_RESULTS[name]), plural
		if "/" not in name and name in self.functions:
			function = self.functions[name]
		else:
			path = qualifyPath(name, self.namespace, self.uses)
			if path in self.functions:
				function = self.functions[path]
				expr["call"] = path
			else:
				decl = self.model.get(path)
				if not decl or decl.kind != "map" or len(args) != 1:
					raise ValueError(f"Unknown or ambiguous function '{name}'")
				expr["call"] = path
				actual = self.resolve(args[0])
				checkAssignment(self.model, (actual[0], False), self.model.resolveType(TypeExpr(path=decl.mapFrom)), True, name)
				return self.model.resolveType(TypeExpr(path=decl.mapTo)), actual[1]
		if len(args) != len(function.args):
			raise ValueError(f"Invalid argument count for '{name}'")
		lifted = False
		for arg, signature in zip(args, function.args):
			actual, plural = self.resolve(arg)
			checkAssignment(self.model, (actual, False), resolveSignature(self.model, signature), True, name)
			if signature.collection and actual is not None and not plural:
				raise ValueError(f"'{name}' requires a collection argument")
			lifted |= plural and not signature.collection
		return resolveSignature(self.model, function.result), function.result.collection or lifted


class Operator:
	"""Binding declaration operations sharing source ontology and optional libraries/types."""

	def __init__(self, ontology: Ontology, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None):
		self.ontology = ontology
		self.libraries = list(libraries or [])
		self.ontologies = list(ontologies or [])

	def parse(self, source: Source) -> BindingDocument:
		"""Parse one binding source without resolving its targets."""
		return parseBinding(source)

	def resolve(self, doc: BindingDocument) -> Binding:
		"""Resolve declarations using this operator's context."""
		return resolveBinding(self.ontology, doc, self.libraries, self.ontologies)

	def load(self, source: Source) -> Binding:
		"""Parse and resolve a binding file."""
		return self.resolve(self.parse(source))

	def print(self, binding: Binding) -> str:
		"""Print an already resolved binding."""
		return printBinding(binding)

	def format(self, source: Source) -> str:
		"""Load a source and print its normal form."""
		return self.print(self.load(source))

	def toJson(self, binding: Binding) -> dict[str, Any]:
		"""Export a detached JSON value."""
		return bindingToJson(binding)

	def fromJson(self, data: Any, name: str = "binding.json") -> Binding:
		"""Validate JSON using this operator's context."""
		return bindingFromJson(self.ontology, data, name, self.libraries, self.ontologies)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def resolveBinding(ontology: Ontology, doc: BindingDocument, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None) -> Binding:
	"""Resolve targets, functions, enclosing instances and statically known expression types."""
	diag = Diagnostics(list(doc.diagnostics))
	contexts = [ontology] + list(ontologies or [])
	if doc.ontology != ontology.namespace:
		diag.error("header", "Binding namespace does not match the source ontology", doc.loc)
	if len({item.namespace for item in contexts}) != len(contexts):
		diag.error("reference", "Loaded ontologies must have distinct namespaces", doc.loc)
	if "rev" in doc.header and doc.header["rev"] != dict(ontology.header).get("rev"):
		diag.warn("revision", "Binding revision differs from the loaded ontology", doc.loc)
	model = Model(Ontology(namespace=ontology.namespace, header=ontology.header, decls=[decl for item in contexts for decl in item.decls]))
	known = model.namespaces() | {item.namespace for item in contexts} | {item.namespace for item in libraries or []}
	for namespace in doc.uses.values():
		if namespace not in known:
			diag.error("reference", f"Unknown ontology or function library '{namespace}'", doc.loc)
	diag.check()
	binding = Binding(doc.ontology, dict(doc.header), dict(doc.uses), deepcopy(doc.at), deepcopy(doc.columns),
		scopes=deepcopy(doc.scopes), exclusions=deepcopy(doc.exclusions), loc=doc.loc)
	if doc.functions:
		uses = {alias: namespace for alias, namespace in doc.uses.items() if namespace in model.namespaces()}
		binding.functions = resolveFunctions(contexts, FunctionsDocument(doc.ontology, uses=uses, functions=doc.functions)).functions
	functions = {item.name: item for item in binding.functions}
	for library in libraries or []:
		for function in library.functions:
			path = f"{library.namespace}/{function.name}"
			if path in functions:
				diag.error("function", f"Ambiguous library function '{path}'", doc.loc)
			functions[path] = function
	resolver = ExpressionResolver(model, binding.ontology, binding.uses, functions, binding.scopes)
	if binding.at is not None:
		try:
			resolver.resolve(binding.at)
		except ValueError as error:
			diag.error("expression", str(error), doc.loc)
	for exclusion in binding.exclusions:
		try:
			resolver.resolve(exclusion.path)
		except ValueError as error:
			diag.error("expression", str(error), exclusion.loc)
	for scope in binding.scopes:
		decl = model.get(scope.type)
		if not decl or decl.kind != "entity" and not isAssociation(decl):
			diag.error("reference", f"Unknown entity or association scope type '{scope.type}'", scope.loc)
			continue
		resolver.scope = scope
		context: Inferred = None, False
		try:
			if isinstance(scope.path["path"][0], dict) and "up" in scope.path["path"][0]:
				raise ValueError("Scope paths are evaluated from the document root")
			if resolver.resolve(scope.id)[1]:
				raise ValueError("A scope id must supply one key, not a collection")
			if scope.valid is not None:
				resolver.resolve(scope.valid)
			if scope.ctx is not None:
				context = resolver.resolve(scope.ctx)
			if scope.deleted:
				resolver.resolve({"path": scope.deleted["path"]})
		except ValueError as error:
			diag.error("expression", str(error), scope.loc)
		targets: set[str] = set()
		for line in scope.lines:
			try:
				name = line.facet or line.target or line.verb
				key = f"[{name}]" if line.facet else name
				if key in targets:
					raise ValueError(f"Target '{name}' is assigned twice in one scope")
				targets.add(key)
				if line.when:
					resolver.resolve({"path": line.when["path"]})
				facet = model.facets(scope.type).get(line.facet) if line.facet else model.facetOf(scope.type, name)
				if facet and annotation(facet.ann, "ctx") and scope.ctx is None:
					raise ValueError(f"Contextual facet '{facet.path}' requires a scope ctx expression")
				if facet and (contextPath := annotation(facet.ann, "ctx")):
					# Text expressions may spell a context handle; a known reference must have its declared type.
					actual = None if context[0] is not None and context[0].builtin == "Text" else context[0]
					checkAssignment(model, (actual, context[1]), model.resolveType(TypeExpr(path=contextPath)), False, "scope ctx")
				if line.facet:
					if facet is None:
						raise ValueError(f"Unknown facet '{name}' on '{scope.type}'")
					continue
				inferred = resolver.resolve(line.expr)
				attr = model.lookup(scope.type, name)
				if attr:
					if error := model.elementPathError(scope.type, name):
						raise ValueError(error)
					checkScalarTarget(model, attr, name)
					checkAssignment(model, inferred, model.resolveType(attr.type, attr.ann), (attr.card or model.defaultCard) in ("*", "+"), name)
				else:
					verbs = model.verbs(scope.type, name)
					if inferred[0] is not None:
						verbs = [(relation, inverse) for relation, inverse in verbs if compatible(model, inferred[0], model.resolveType(TypeExpr(path=relation.participants[0 if inverse else 1].type)))]
					if len(verbs) != 1:
						raise ValueError(f"Unknown or ambiguous target/verb '{name}' on '{scope.type}'")
					line.target, line.verb = None, name
			except ValueError as error:
				diag.error("binding", str(error), line.loc)
	binding.diagnostics = diag.check()
	return binding


def loadBinding(ontology: Ontology, source: Source, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None) -> Binding:
	"""Parse and resolve a binding against its source ontology and imported declarations."""
	return resolveBinding(ontology, parseBinding(source), libraries, ontologies)


def formatBinding(ontology: Ontology, source: Source, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None) -> str:
	"""Load and canonically print a binding file."""
	return printBinding(loadBinding(ontology, source, libraries, ontologies))


def bindingFromJson(ontology: Ontology, data: Any, name: str = "binding.json", libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None) -> Binding:
	"""Validate exact JSON members and ontology-backed lossless text replay."""
	try:
		read = readBindingJson(data)
		loaded = loadBinding(ontology, Source(name, printBinding(read)), libraries, ontologies)
		if bindingToJson(read) != bindingToJson(loaded):
			raise ValueError("Binding JSON does not survive its text round trip")
	except (ValueError, KeyError, TypeError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	return loaded


__all__ = ["Operator", "resolveBinding", "loadBinding", "formatBinding", "bindingFromJson", "rootSteps", "enclosingPath", "enclosingScope", "compatible", "checkAssignment", "checkScalarTarget", "ExpressionResolver", "Inferred"]

# EOF
