"""Module: mapping.operations — static mapping resolution, reference reach and interchange."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..binding.operations import ExpressionResolver, Inferred, checkAssignment, compatible
from ..binding.parser import qualifyPath
from ..coverage import _Selection, _selections
from ..functions.model import Function, FunctionLibrary, FunctionsDocument
from ..functions.operations import resolveFunctions
from ..ontology.model import Model, Ontology, ResolvedType, TypeExpr, isAssociation
from ..ontology.operations import _checkAnnotations, _validateMap
from ..text import Diagnostics, FormatError, Loc, Source, annotation
from .formatter import mappingToJson, printMapping
from .model import Mapping, MappingDocument, MappingScope
from .parser import parseMapping, readMappingJson

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def contextModel(primary: Ontology, contexts: list[Ontology]) -> Model:
	decls = {}
	for ontology in [primary] + contexts:
		for decl in ontology.decls:
			decls.setdefault(decl.path, decl)
	return Model(Ontology(namespace=primary.namespace, header=primary.header, decls=list(decls.values())))


def selected(model: Model, selections: set[_Selection] | None, owner: str, member: str = "") -> bool:
	if selections is None:
		return True
	return any((owner == item.owner or model.isA(owner, item.owner)) and item.member == member and not item.facet for item in selections)


def leafMembers(model: Model, owner: str, member: str, seen: frozenset[str] = frozenset()) -> list[str]:
	attr = model.lookup(owner, member)
	structure = model.structOf(attr.type) if attr else None
	if not structure or not structure.fields or structure.path in seen:
		return [member]
	return [leaf for field in structure.fields for leaf in leafMembers(model, owner, f"{member}.{field.name}", seen | {structure.path})]


def instanceType(model: Model, path: str) -> bool:
	decl = model.get(path)
	return decl is not None and (decl.kind == "entity" or isAssociation(decl))


def checkElement(model: Model, path: str) -> None:
	if model.get(path):
		return
	if path.endswith("]"):
		owner, facet = path[:-1].split("[", 1)
		if facet in model.facets(owner):
			return
	else:
		owner, dot, member = path.partition(".")
		if dot and model.lookup(owner, member):
			return
	raise ValueError(f"Unknown excluded source element '{path}'")


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class MappingExpressionResolver(ExpressionResolver):
	"""Shared call typing over ontology paths, tracking read paths and contextual/reference reach."""

	def __init__(self, model: Model, targetModel: Model, mapping: Mapping, scope: MappingScope, functions: dict[str, Function], diag: Diagnostics, selections: set[_Selection] | None = None):
		super().__init__(model, mapping.fromNamespace, mapping.uses, functions)
		self.targetModel = targetModel
		self.mapping = mapping
		self.owner = scope.source
		self.loc = scope.loc
		self.diag = diag
		self.selections = selections
		self.paths: set[str] = set()
		self.throughReference = False
		self.contexts: set[str] = set()
		self.localMaps = {decl.path: decl for decl in mapping.maps}

	def resolve(self, expr: dict[str, Any]) -> Inferred:
		if "path" in expr:
			return self.path(expr["path"])
		if expr.get("call") == "ref":
			raise ValueError("ref(Type, key) is binding-only; mappings translate existing references")
		if "meta" in expr:
			return (ResolvedType("builtin", builtin="Text") if expr["meta"] == "src" else None), False
		return super().resolve(expr)

	def path(self, steps: list[str]) -> Inferred:
		self.paths.add(".".join(steps))
		owner, segments, plural = self.owner, list(steps), False
		while segments:
			traversed = False
			for end in range(1, len(segments) + 1):
				member = ".".join(segments[:end])
				attr = self.model.lookup(owner, member)
				if attr is None:
					continue
				kind = self.model.resolveType(attr.type, attr.ann)
				if end < len(segments) and kind.kind not in ("entity", "relation"):
					continue
				if not all(selected(self.model, self.selections, owner, leaf) for leaf in leafMembers(self.model, owner, member)):
					raise ValueError(f"Path '{owner}.{member}' reads outside the mapping view")
				facet = self.model.facetOf(owner, member)
				if facet and (context := annotation(facet.ann, "ctx")):
					self.contexts.add(context)
				plural |= (attr.card or self.model.defaultCard) in ("*", "+")
				if end == len(segments):
					return kind, plural
				self.throughReference = True
				owner, segments, traversed = kind.path, segments[end:], True
				break
			if traversed:
				continue
			verbs = self.model.verbs(owner, segments[0])
			if len(verbs) != 1:
				raise ValueError(f"Unknown or ambiguous source path '{owner}.{'.'.join(segments)}'")
			relation, inverse = verbs[0]
			if not selected(self.model, self.selections, relation.path):
				raise ValueError(f"Relation '{relation.path}' reads outside the mapping view")
			counts = (relation.arrow.counts or self.model.defaultCounts).split(":")
			plural |= counts[0 if inverse else 1] in ("*", "+")
			owner = relation.participants[0 if inverse else 1].type
			segments = segments[1:]
			if not segments:
				return self.model.resolveType(TypeExpr(path=owner)), plural
			self.throughReference = True
		raise ValueError("Empty mapping path")

	def call(self, expr: dict[str, Any]) -> Inferred:
		decl = self.localMaps.get(expr["call"])
		if decl is None:
			return super().call(expr)
		if len(expr["args"]) != 1:
			raise ValueError(f"Invalid argument count for local map '{decl.path}'")
		actual, plural = self.resolve(expr["args"][0])
		checkAssignment(self.model, (actual, False), self.model.resolveType(TypeExpr(path=decl.mapFrom)), True, decl.path)
		return self.targetModel.resolveType(TypeExpr(path=decl.mapTo)), plural

	def translate(self, inferred: Inferred) -> Inferred:
		kind, plural = inferred
		if kind is None or kind.kind not in ("entity", "relation"):
			return inferred
		scopes = [scope for scope in self.mapping.scopes if kind.path == scope.source or self.model.isA(kind.path, scope.source)]
		if len(scopes) > 1:
			raise ValueError(f"Ambiguous instance correspondence for '{kind.path}'")
		if scopes:
			return self.targetModel.resolveType(TypeExpr(path=scopes[0].target)), plural
		if kind.path.startswith(self.mapping.toNamespace + "/") and self.mapping.toNamespace != self.mapping.fromNamespace:
			return inferred
		self.diag.warn("reference", f"No instance correspondence for '{kind.path}'; these references produce run-time gaps", self.loc)
		return None, plural


class Operator:
	"""Mapping declarations sharing two ontologies, imported declarations and known referential names."""

	def __init__(self, fromOntology: Ontology, toOntology: Ontology, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: set[str] | None = None):
		self.fromOntology = fromOntology
		self.toOntology = toOntology
		self.libraries = list(libraries or [])
		self.ontologies = list(ontologies or [])
		self.referentials = set(referentials or ())

	def parse(self, source: Source) -> MappingDocument:
		"""Parse one source file without typing its assignments."""
		return parseMapping(source)

	def resolve(self, doc: MappingDocument) -> Mapping:
		"""Validate parsed declarations using this context."""
		return resolveMapping(self.fromOntology, self.toOntology, doc, self.libraries, self.ontologies, self.referentials)

	def load(self, source: Source) -> Mapping:
		"""Parse and statically resolve one mapping."""
		return self.resolve(self.parse(source))

	def print(self, mapping: Mapping) -> str:
		"""Print a resolved mapping, not its output observations."""
		return printMapping(mapping)

	def format(self, source: Source) -> str:
		"""Load and canonically print one mapping file."""
		return self.print(self.load(source))

	def toJson(self, mapping: Mapping) -> dict[str, Any]:
		"""Export detached declaration data."""
		return mappingToJson(mapping)

	def fromJson(self, data: Any, name: str = "mapping.json") -> Mapping:
		"""Validate JSON through its text and ontology-backed static checks."""
		return mappingFromJson(self.fromOntology, self.toOntology, data, name, self.libraries, self.ontologies, self.referentials)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def resolveMapping(fromOntology: Ontology, toOntology: Ontology, doc: MappingDocument, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: set[str] | None = None) -> Mapping:
	"""Validate declarations and static reach; referential names do not establish identity policies."""
	diag = Diagnostics(list(doc.diagnostics))
	if (doc.fromNamespace, doc.toNamespace) != (fromOntology.namespace, toOntology.namespace):
		diag.error("header", "Mapping namespaces do not match the loaded ontologies", doc.loc)
	contexts = [fromOntology] + ([toOntology] if toOntology.namespace != fromOntology.namespace else []) + list(ontologies or [])
	if len({item.namespace for item in contexts}) != len(contexts):
		diag.error("reference", "Loaded ontologies must have distinct namespaces", doc.loc)
	model = contextModel(fromOntology, [toOntology] + contexts)
	targetModel = contextModel(toOntology, contexts)
	known = model.namespaces() | {item.namespace for item in contexts} | {library.namespace for library in libraries or []}
	for namespace in doc.uses.values():
		if namespace not in known:
			diag.error("reference", f"Unknown ontology or function library '{namespace}'", doc.loc)
	for key, ontology in (("from", fromOntology), ("to", toOntology)):
		if key in doc.header and doc.header[key] != dict(ontology.header).get("rev"):
			diag.warn("revision", f"Mapping {key} revision differs from the loaded ontology", doc.loc)
	if "referential" in doc.header and doc.header["referential"] not in (referentials or set()):
		diag.error("reference", f"Unknown referential '{doc.header['referential']}'", doc.loc)
	mapping = Mapping(doc.fromNamespace, doc.toNamespace, dict(doc.header), dict(doc.uses), maps=deepcopy(doc.maps), scopes=deepcopy(doc.scopes), exclusions=deepcopy(doc.exclusions), loc=doc.loc)
	selections = None
	if "view" in doc.header:
		path = qualifyPath(str(doc.header["view"]), doc.fromNamespace, doc.uses)
		view = model.get(path)
		if view is None or view.kind != "view":
			diag.error("reference", f"Unknown mapping view '{path}'", doc.loc)
		else:
			mapping.header["view"] = path
			selections = _selections(model, view)
	for decl in mapping.maps:
		_validateMap(model, decl, diag, targetModel)
		_checkAnnotations(model, decl.ann, {"map"}, decl.loc, diag)
	diag.check()
	if doc.functions:
		uses = {alias: namespace for alias, namespace in doc.uses.items() if namespace in model.namespaces()}
		mapping.functions = resolveFunctions(contexts, FunctionsDocument(doc.fromNamespace, uses=uses, functions=doc.functions)).functions
	functions = {item.name: item for item in mapping.functions}
	for library in libraries or []:
		for function in library.functions:
			path = f"{library.namespace}/{function.name}"
			if path in functions:
				diag.error("function", f"Ambiguous library function '{path}'", doc.loc)
			functions[path] = function
	for exclusion in mapping.exclusions:
		try:
			checkElement(model, exclusion.path)
		except ValueError as error:
			diag.error("reference", str(error), exclusion.loc)
	for scope in mapping.scopes:
		if not instanceType(model, scope.source) or not instanceType(targetModel, scope.target):
			diag.error("reference", f"Unknown entity or association mapping scope '{scope.source}' -> '{scope.target}'", scope.loc)
			continue
		if not selected(model, selections, scope.source):
			diag.error("view", f"Scope '{scope.source}' is outside the mapping view", scope.loc)
		resolver = MappingExpressionResolver(model, targetModel, mapping, scope, functions, diag, selections)
		context: Inferred = None, False
		try:
			if scope.when:
				resolver.resolve({"path": scope.when["path"]})
			if scope.valid:
				resolver.resolve(scope.valid)
			if scope.ctx:
				context = resolver.translate(resolver.resolve(scope.ctx))
		except ValueError as error:
			diag.error("expression", str(error), scope.loc)
		targets: set[str] = set()
		for line in scope.lines:
			resolver = MappingExpressionResolver(model, targetModel, mapping, scope, functions, diag, selections)
			resolver.loc = line.loc
			try:
				name = line.facet or line.target or line.verb
				key = f"[{name}]" if line.facet else name
				if key in targets:
					raise ValueError(f"Target '{name}' is assigned twice in one scope")
				targets.add(key)
				inferred: Inferred = None, False
				if line.expr is not None:
					inferred = resolver.resolve(line.expr)
				if line.src is not None and line.src not in resolver.paths:
					raise ValueError(f"src='{line.src}' names a path the expression does not read")
				if line.reverse and not resolver.throughReference:
					raise ValueError("reverse requires a path through a reference")
				if line.when:
					resolver.resolve({"path": line.when["path"]})
				contextsRead = set(resolver.contexts)
				facet = targetModel.facets(scope.target).get(line.facet) if line.facet else targetModel.facetOf(scope.target, name)
				if facet and (expectedContext := annotation(facet.ann, "ctx")):
					if scope.ctx is None and not contextsRead:
						raise ValueError("A contextual target requires ctx or a contextual input claim")
					values = [context] if scope.ctx is not None else [resolver.translate((model.resolveType(TypeExpr(path=path)), False)) for path in contextsRead]
					for value in values:
						checkAssignment(model, value, targetModel.resolveType(TypeExpr(path=expectedContext)), False, "target context")
				if line.facet:
					if facet is None:
						raise ValueError(f"Unknown target facet '{name}'")
					continue
				attr = targetModel.lookup(scope.target, name)
				if attr and inferred[0] is not None and inferred[0].kind in ("entity", "relation") and targetModel.resolveType(attr.type).kind not in ("entity", "relation"):
					raise ValueError(f"{name}: incompatible reference expression for a scalar target")
				inferred = resolver.translate(inferred)
				if attr:
					checkAssignment(model, inferred, targetModel.resolveType(attr.type, attr.ann), (attr.card or targetModel.defaultCard) in ("*", "+"), name)
				else:
					verbs = targetModel.verbs(scope.target, name)
					if inferred[0] is not None:
						verbs = [(relation, inverse) for relation, inverse in verbs if compatible(model, inferred[0], targetModel.resolveType(TypeExpr(path=relation.participants[0 if inverse else 1].type)))]
					if len(verbs) != 1:
						raise ValueError(f"Unknown or ambiguous target/verb '{name}'")
					line.target, line.verb = None, name
			except ValueError as error:
				diag.error("mapping", str(error), line.loc)
	mapping.diagnostics = diag.check()
	return mapping


def loadMapping(fromOntology: Ontology, toOntology: Ontology, source: Source, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: set[str] | None = None) -> Mapping:
	"""Parse and statically resolve a mapping; this does not execute its declarations."""
	return resolveMapping(fromOntology, toOntology, parseMapping(source), libraries, ontologies, referentials)


def formatMapping(fromOntology: Ontology, toOntology: Ontology, source: Source, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: set[str] | None = None) -> str:
	"""Load and canonically print a mapping source."""
	return printMapping(loadMapping(fromOntology, toOntology, source, libraries, ontologies, referentials))


def mappingFromJson(fromOntology: Ontology, toOntology: Ontology, data: Any, name: str = "mapping.json", libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: set[str] | None = None) -> Mapping:
	"""Validate exact JSON members and lossless ontology-backed text replay."""
	try:
		read = readMappingJson(data)
		loaded = loadMapping(fromOntology, toOntology, Source(name, printMapping(read)), libraries, ontologies, referentials)
		if mappingToJson(read) != mappingToJson(loaded):
			raise ValueError("Mapping JSON does not survive its text round trip")
	except (ValueError, TypeError, KeyError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	return loaded


__all__ = ["Operator", "resolveMapping", "loadMapping", "formatMapping", "mappingFromJson"]

# EOF
