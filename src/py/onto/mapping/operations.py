"""Module: mapping.operations — static mapping resolution, reference reach and interchange."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..binding.operations import ExpressionResolver, Inferred, checkAssignment, checkScalarTarget, compatible
from ..binding.parser import qualifyPath
from ..conditions import conditionPaths, testValues
from ..expressions import keyedSteps
from ..ontology.model import unkeyed
from ..coverage import ViewSelection, viewSelections
from ..functions.model import Function, FunctionLibrary, FunctionsDocument
from ..functions.operations import resolveFunctions
from ..observations.model import ObservationsDocument
from ..observations.parser import ObservationResolver
from ..ontology.model import Model, Ontology, ResolvedType, TypeExpr, isAssociation, isSetValued
from ..ontology.operations import checkAnnotations, validateMap
from ..referential.model import Referential
from ..referential.operations import policyFor, validateReferential
from ..text import Diagnostics, FormatError, Loc, Source, annotation
from .formatter import mappingToJson, printMapping
from .model import Mapping, MappingDocument, MappingLine, MappingScope
from .parser import parseMapping, readMappingJson

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def contextModel(primary: Ontology, contexts: list[Ontology]) -> Model:
	"""Build the ontology model for the mapping context."""
	decls = {}
	for ontology in [primary] + contexts:
		for decl in ontology.decls:
			decls.setdefault(decl.path, decl)
	return Model(Ontology(namespace=primary.namespace, header=primary.header, decls=list(decls.values())))


def selected(model: Model, selections: set[ViewSelection] | None, owner: str, member: str = "") -> bool:
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


def correspondenceScopes(model: Model, mapping: Mapping, source: str) -> list[MappingScope]:
	"""The scope lines giving instances of `source` (or a type it specialises) their target instances."""
	return [scope for scope in mapping.scopes if scope.into is None and (source == scope.source or model.isA(source, scope.source))]


def correspondenceTarget(model: Model, targetModel: Model, mapping: Mapping, source: str, accepted: list[str] | None) -> str | None:
	"""The target type a reference to `source` translates to (spec-04 Instances).

	With one scope line for `source`, its target. With several, the one whose target type the
	receiving attribute, role or verb accepts (`accepted`, a type or one it specialises). None
	without a scope line; ValueError when several fit, or none does.
	"""
	scopes = correspondenceScopes(model, mapping, source)
	if len(scopes) > 1:
		# Scope lines, not types: two lines to the same target type are still ambiguous
		fitting = [scope.target for scope in scopes if accepted and any(scope.target == item or targetModel.isA(scope.target, item) for item in accepted)]
		if len(fitting) != 1:
			targets = ", ".join(sorted({scope.target for scope in scopes}))
			raise ValueError(f"Ambiguous instance correspondence for '{source}': {'several' if fitting else 'none'} of {targets} {'fit' if fitting else 'fits'} the target")
		return fitting[0]
	return scopes[0].target if scopes else None


def acceptedTypes(targetModel: Model, owner: str, name: str, attr: Any) -> list[str]:
	"""The instance types a target attribute, role or verb `name` of `owner` accepts."""
	if attr is not None:
		resolved = targetModel.resolveType(attr.type, attr.ann)
		return [resolved.path] if resolved.kind in ("entity", "relation") else []
	return [relation.participants[0 if inverse else 1].type for relation, inverse in targetModel.verbs(owner, name)]


def checkExclusive(name: str, lines: list[MappingLine], facet: bool) -> None:
	"""Lines assigning one target must be exclusive: `when` tests of one path sharing no value, and at most one default."""
	if len(lines) < 2:
		return
	conditional = [line.when for line in lines if line.when]
	# A test of having a value overlaps any value: exclusive lines test values.
	values = [value for when in conditional for value in testValues(when)] if all("path" in when and testValues(when) for when in conditional) else []
	if facet or len(lines) - len(conditional) > 1 or not values or any(when["path"] != conditional[0]["path"] for when in conditional[1:]) \
		or len(set(values)) != len(values):
		raise ValueError(f"Target '{name}' is assigned twice in one scope; repeated lines need exclusive conditions"
			" (`when` tests of one path sharing no value) and at most one line without `when`")


def chosenTarget(model: Model, targetModel: Model, mapping: Mapping, inferred: Inferred, asType: str, accepted: list[str]) -> Inferred:
	"""`{as=T}`: a reference translated through the unique scope line targeting type `T`."""
	kind, plural = inferred
	if kind is None or kind.kind not in ("entity", "relation"):
		raise ValueError("as requires a reference expression")
	matches = [scope for scope in correspondenceScopes(model, mapping, kind.path) if scope.target == asType]
	if not matches:
		raise ValueError(f"as={asType}: no scope line maps '{kind.path}' to it")
	if len(matches) > 1:
		raise ValueError(f"Ambiguous instance correspondence for '{kind.path}': as={asType} matches several scope lines")
	if not any(asType == item or targetModel.isA(asType, item) for item in accepted):
		raise ValueError(f"as={asType}: the target does not accept it")
	return targetModel.resolveType(TypeExpr(path=asType)), plural


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

	def __init__(self, model: Model, targetModel: Model, mapping: Mapping, scope: MappingScope, functions: dict[str, Function], diag: Diagnostics, selections: set[ViewSelection] | None = None):
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
		if expr.get("path") == [{"root": True}]:
			# `$`: a reference to the scope instance, translated like any reference
			return self.model.resolveType(TypeExpr(path=self.owner)), False
		if "path" in expr:
			return self.path(expr["path"])
		if expr.get("call") == "ref":
			return self.sourceReference(expr)
		if "meta" in expr:
			return (ResolvedType("builtin", builtin="Text") if expr["meta"] == "src" else None), False
		return super().resolve(expr)

	def path(self, steps: list[str]) -> Inferred:
		steps = keyedSteps(steps)
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
				if error := self.model.elementPathError(owner, member):
					raise ValueError(error)
				if not all(selected(self.model, self.selections, owner, unkeyed(leaf)) for leaf in leafMembers(self.model, owner, member)):
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

	def sourceReference(self, expr: dict[str, Any]) -> Inferred:
		"""`ref(S, Key)`: the source instance of `S` whose key (the binding's `id`) is the value of path `Key`."""
		args = expr["args"]
		if self.mapping.fromNamespace == self.mapping.toNamespace:
			raise ValueError("ref(Type, key) needs distinct source and target ontologies")
		if len(args) != 2 or set(args[0]) != {"path"} or len(args[0]["path"]) != 1 or not isinstance(args[0]["path"][0], str) or set(args[1]) != {"path"}:
			raise ValueError("ref requires a source instance type and a key path: ref(Type, Path)")
		path = qualifyPath(args[0]["path"][0], self.mapping.fromNamespace, self.mapping.uses)
		if not path.startswith(self.mapping.fromNamespace + "/") or not instanceType(self.model, path):
			raise ValueError(f"Unknown source reference type '{path}'")
		args[0] = {"path": [path]}
		kind, plural = self.resolve(args[1])
		if plural:
			raise ValueError("ref requires a single key")
		if kind is not None and not (kind.kind == "vocab" or kind.kind == "builtin" and kind.builtin in ("Text", "Integer", "Number")):
			raise ValueError("ref requires a text or integer key")
		return self.model.resolveType(TypeExpr(path=path)), False

	def call(self, expr: dict[str, Any]) -> Inferred:
		decl = self.localMaps.get(expr["call"])
		if decl is None:
			return super().call(expr)
		if len(expr["args"]) != 1:
			raise ValueError(f"Invalid argument count for local map '{decl.path}'")
		actual, plural = self.resolve(expr["args"][0])
		checkAssignment(self.model, (actual, False), self.model.resolveType(TypeExpr(path=decl.mapFrom)), True, decl.path)
		return self.targetModel.resolveType(TypeExpr(path=decl.mapTo)), plural or isSetValued(decl)

	def translate(self, inferred: Inferred, accepted: list[str] | None = None) -> Inferred:
		"""A source reference's type as the target sees it, through the instance correspondence.

		`accepted` are the target types the receiving attribute, role or verb accepts, which choose
		among several scope lines for the source type.
		"""
		kind, plural = inferred
		if kind is None or kind.kind not in ("entity", "relation"):
			return inferred
		target = correspondenceTarget(self.model, self.targetModel, self.mapping, kind.path, accepted)
		if target is not None:
			return self.targetModel.resolveType(TypeExpr(path=target)), plural
		if kind.path.startswith(self.mapping.toNamespace + "/") and self.mapping.toNamespace != self.mapping.fromNamespace:
			return inferred
		self.diag.warn("reference", f"No instance correspondence for '{kind.path}'; these references produce run-time gaps", self.loc)
		return None, plural


class Operator:
	"""Mapping declarations sharing two ontologies, imported declarations and loaded referentials."""

	def __init__(self, fromOntology: Ontology, toOntology: Ontology, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: list[Referential] | None = None):
		self.fromOntology = fromOntology
		self.toOntology = toOntology
		self.libraries = list(libraries or [])
		self.ontologies = list(ontologies or [])
		self.referentials = list(referentials or [])

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


def resolveMapping(fromOntology: Ontology, toOntology: Ontology, doc: MappingDocument, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: list[Referential] | None = None) -> Mapping:
	"""Validate declarations, static reach and effective referential key assignments, without executing them."""
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
	references: dict[str, Referential] = {}
	for ref in referentials or []:
		if not isinstance(ref, Referential):
			diag.error("reference", "Mappings require loaded Referential models, not referential names", doc.loc)
		elif ref.namespace in references:
			diag.error("reference", f"Duplicate loaded referential '{ref.namespace}'", doc.loc)
		else:
			references[ref.namespace] = ref
	if "referential" in doc.header and doc.header["referential"] not in references:
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
			selections = viewSelections(model, view)
	for decl in mapping.maps:
		validateMap(model, decl, diag, targetModel)
		checkAnnotations(model, decl.ann, {"map"}, decl.loc, diag)
	diag.check()
	referential = references.get(str(doc.header.get("referential", "")))
	if referential is not None:
		# Policies describe the actual target revision, even for same-namespace migrations.
		refContexts = [toOntology] + [context for context in contexts if context.namespace != toOntology.namespace]
		referential = validateReferential(refContexts, referential)
		diag.items.extend(referential.diagnostics)
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
	scopeNames = set()
	for scope in mapping.scopes:
		key = (scope.source, scope.target, scope.name)
		repeated = [item for item in mapping.scopes if item.into is None and item.source == scope.source and item.target == scope.target]
		if key in scopeNames or len(repeated) > 1 and scope.into is None and not scope.name:
			diag.error("mapping", "Repeated source/target scopes require distinct names", scope.loc)
		scopeNames.add(key)
		if not instanceType(model, scope.source) or not instanceType(targetModel, scope.target):
			diag.error("reference", f"Unknown entity or association mapping scope '{scope.source}' -> '{scope.target}'", scope.loc)
			continue
		if not selected(model, selections, scope.source):
			diag.error("view", f"Scope '{scope.source}' is outside the mapping view", scope.loc)
		resolver = MappingExpressionResolver(model, targetModel, mapping, scope, functions, diag, selections)
		context: Inferred = None, False
		try:
			if scope.into is not None:
				intoType, multi = resolver.resolve(scope.into)
				if intoType is None or intoType.kind not in ("entity", "relation"):
					raise ValueError("into requires a source instance reference")
				if resolver.contexts:
					raise ValueError("into currently requires a non-contextual reference")
				destination = resolver.translate((intoType, False), [scope.target])
				checkAssignment(targetModel, destination, targetModel.resolveType(TypeExpr(path=scope.target)), False, "into target")
			for path in conditionPaths(scope.when):
				resolver.resolve({"path": path})
			if scope.valid:
				resolver.resolve(scope.valid)
			if scope.present:
				resolver.resolve(scope.present)
			if scope.ctx:
				context = resolver.translate(resolver.resolve(scope.ctx))
		except ValueError as error:
			diag.error("expression", str(error), scope.loc)
		targets: dict[str, list[MappingLine]] = {}
		for line in scope.lines:
			resolver = MappingExpressionResolver(model, targetModel, mapping, scope, functions, diag, selections)
			resolver.loc = line.loc
			try:
				name = line.facet or line.target or line.verb
				key = f"[{name}]" if line.facet else name
				siblings = targets.setdefault(key, [])
				siblings.append(line)
				checkExclusive(name, siblings, bool(line.facet))
				if len(siblings) > 1:
					# A collection can hold two exclusive values at once: exclusive lines test a single value.
					shared = next(item.when["path"] for item in siblings if item.when)
					if MappingExpressionResolver(model, targetModel, mapping, scope, functions, Diagnostics(), selections).resolve({"path": shared})[1]:
						raise ValueError(f"Target '{name}': exclusive lines test a single-valued path")
				inferred: Inferred = None, False
				if line.expr is not None:
					inferred = resolver.resolve(line.expr)
				if line.src is not None and line.src not in resolver.paths:
					raise ValueError(f"src='{line.src}' names a path the expression does not read")
				if line.reverse and not resolver.throughReference:
					raise ValueError("reverse requires a path through a reference")
				for path in conditionPaths(line.when):
					resolver.resolve({"path": path})
				qualifierTypes = {key: resolver.resolve(expr) for key, expr in line.qualifiers.items()}
				contextsRead = set(resolver.contexts)
				facet = targetModel.facets(scope.target).get(line.facet) if line.facet else targetModel.facetOf(scope.target, name)
				if facet and (expectedContext := annotation(facet.ann, "ctx")):
					if scope.ctx is None and not contextsRead:
						raise ValueError("A contextual target requires ctx or a contextual input claim")
					values = [context] if scope.ctx is not None else [resolver.translate((model.resolveType(TypeExpr(path=path)), False), [expectedContext]) for path in contextsRead]
					for value in values:
						checkAssignment(targetModel, value, targetModel.resolveType(TypeExpr(path=expectedContext)), False, "target context")
				if line.facet:
					if facet is None:
						raise ValueError(f"Unknown target facet '{name}'")
					continue
				attr = targetModel.lookup(scope.target, name)
				if line.qualifiers:
					if attr is None:
						raise ValueError("Measurement qualifiers require a scalar attribute target")
					expected = targetModel.resolveType(attr.type, attr.ann)
					for qualifier, (kind, multi) in qualifierTypes.items():
						if expected.qualifiers.get(qualifier) != "?":
							raise ValueError(f"{name}: qualifier '{qualifier}' requires a variable target qualifier")
						if inferred[0] is not None and inferred[0].qualifiers.get(qualifier, "?") != "?":
							raise ValueError(f"{name}: qualifier '{qualifier}' is already fixed on the source expression")
						if multi or kind is not None and not (kind.kind == "vocab" or kind.kind == "builtin" and kind.builtin == "Text"):
							raise ValueError(f"{name}: qualifier '{qualifier}' requires a single text or vocabulary value")
				if attr and inferred[0] is not None and inferred[0].kind in ("entity", "relation") and targetModel.resolveType(attr.type).kind not in ("entity", "relation"):
					raise ValueError(f"{name}: incompatible reference expression for a scalar target")
				accepted = acceptedTypes(targetModel, scope.target, name, attr)
				if line.asType:
					inferred = chosenTarget(model, targetModel, mapping, inferred, line.asType, accepted)
				else:
					inferred = resolver.translate(inferred, accepted)
				if attr:
					if error := targetModel.elementPathError(scope.target, name):
						raise ValueError(error)
					checkScalarTarget(targetModel, attr, name)
					expected = targetModel.resolveType(attr.type, attr.ann)
					if expected.kind == "range" and line.expr is not None and "text" in line.expr:
						line.expr["text"] = ObservationResolver(toOntology, ObservationsDocument()).scalar(line.expr["text"], expected, line.loc or Loc("mapping", 0))
						inferred = expected, False
					checkAssignment(targetModel, inferred, expected, (attr.card or targetModel.defaultCard) in ("*", "+"), name)
				else:
					verbs = targetModel.verbs(scope.target, name)
					if inferred[0] is not None:
						verbs = [(relation, inverse) for relation, inverse in verbs if compatible(targetModel, inferred[0], targetModel.resolveType(TypeExpr(path=relation.participants[0 if inverse else 1].type)))]
					if len(verbs) != 1:
						raise ValueError(f"Unknown or ambiguous target/verb '{name}'")
					line.target, line.verb = None, name
			except ValueError as error:
				diag.error("mapping", str(error), line.loc)
		if referential is not None and scope.into is None:
			policy = policyFor(targetModel, referential, scope.target)
			if policy is not None and not policy.minted:
				assigned = {line.target for line in scope.lines if not line.candidate or mapping.header.get("candidates", False)}
				if not assigned.intersection(policy.keys):
					diag.error("key", f"Scope '{scope.target}' must assign a policy key: {', '.join(policy.keys)}", scope.loc)
	mapping.diagnostics = diag.check()
	return mapping


def parseMappings(sources: list[Source]) -> MappingDocument:
	"""Parse the files of one mapping (the same `@mapping From -> To` header) into one document.

	Each file resolves its own `@use` aliases; their declarations are then merged: header keys and aliases
	must agree, local functions, maps and exclusions must not repeat, and scopes are checked when resolved.
	"""
	docs = [parseMapping(source) for source in sources]
	if not docs:
		raise ValueError("A mapping needs at least one file")
	merged = MappingDocument(docs[0].fromNamespace, docs[0].toNamespace, loc=docs[0].loc)
	diag = Diagnostics()
	functions: set[str] = set()
	maps: set[str] = set()
	exclusions: set[str] = set()
	for doc in docs:
		merged.diagnostics += doc.diagnostics
		if (doc.fromNamespace, doc.toNamespace) != (merged.fromNamespace, merged.toNamespace):
			diag.error("header", f"Files of one mapping name {merged.fromNamespace} -> {merged.toNamespace}, not {doc.fromNamespace} -> {doc.toNamespace}", doc.loc)
			continue
		for key, value in doc.header.items():
			if merged.header.setdefault(key, value) != value:
				diag.error("header", f"Mapping header '{key}' differs between files: {merged.header[key]} and {value}", doc.loc)
		for alias, namespace in doc.uses.items():
			if merged.uses.setdefault(alias, namespace) != namespace:
				diag.error("mapping", f"Alias '{alias}' names {merged.uses[alias]} and {namespace} in files of one mapping", doc.loc)
		for function in doc.functions:
			if function.name in functions or function.name in maps:
				diag.error("mapping", f"Duplicate local function/map '{function.name}' across the mapping's files", function.loc)
			functions.add(function.name)
			merged.functions.append(function)
		for decl in doc.maps:
			if decl.path in maps or decl.path in functions:
				diag.error("mapping", f"Duplicate local function/map '{decl.path}' across the mapping's files", decl.loc)
			maps.add(decl.path)
			merged.maps.append(decl)
		for exclusion in doc.exclusions:
			if exclusion.path in exclusions:
				diag.error("mapping", f"'{exclusion.path}' is excluded twice", exclusion.loc)
			exclusions.add(exclusion.path)
			merged.exclusions.append(exclusion)
		merged.scopes += doc.scopes
	merged.diagnostics += diag.check()
	return merged


def loadMapping(fromOntology: Ontology, toOntology: Ontology, source: Source | list[Source], libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: list[Referential] | None = None) -> Mapping:
	"""Parse and statically resolve a mapping, from one file or all the files of one mapping; this does not execute it.

	The whole mapping is parsed before anything is resolved: a reference translates through the scope lines
	of every file, wherever they are declared.
	"""
	doc = parseMappings(source if isinstance(source, list) else [source])
	return resolveMapping(fromOntology, toOntology, doc, libraries, ontologies, referentials)


def formatMapping(fromOntology: Ontology, toOntology: Ontology, source: Source, libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: list[Referential] | None = None) -> str:
	"""Load and canonically print a mapping source."""
	return printMapping(loadMapping(fromOntology, toOntology, source, libraries, ontologies, referentials))


def mappingFromJson(fromOntology: Ontology, toOntology: Ontology, data: Any, name: str = "mapping.json", libraries: list[FunctionLibrary] | None = None, ontologies: list[Ontology] | None = None, referentials: list[Referential] | None = None) -> Mapping:
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


__all__ = ["Operator", "parseMappings", "resolveMapping", "loadMapping", "formatMapping", "mappingFromJson", "contextModel", "correspondenceScopes", "correspondenceTarget", "acceptedTypes"]

# EOF
