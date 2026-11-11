"""Module: functions.operations — ontology-backed library validation and interchange."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..observations.model import ObservationsDocument, Statement
from ..observations.parser import _Resolver
from ..ontology.model import Attr, Model, Ontology, ResolvedType, TypeExpr, isAssociation
from ..text import Diagnostics, FormatError, Loc, Source, annotation
from .formatter import functionsToJson, printFunctions
from .model import Function, FunctionExample, FunctionLibrary, FunctionsDocument, SignatureType
from .parser import _readFunctionsJson, parseFunctions

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def _resolveSignature(model: Model, signature: SignatureType) -> ResolvedType:
	if signature.path:
		decl = model.get(signature.path)
		if not decl or decl.kind not in ("entity", "type") and not isAssociation(decl):
			raise ValueError(f"Unknown signature type '{signature.path}'")
	return model.resolveType(TypeExpr(builtin=signature.builtin, path=signature.path))


def _exampleValue(resolver: _Resolver, signature: SignatureType, raw: str, loc: Loc) -> Any:
	attr = Attr("Example", card="*" if signature.collection else "?", type=TypeExpr(builtin=signature.builtin, path=signature.path))
	return resolver.value(raw, attr, Statement(1, "value", "", None, loc, {}))


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Operator:
	"""Library operations sharing the ontologies used by function signatures."""

	def __init__(self, ontologies: list[Ontology]):
		self.ontologies = list(ontologies)

	def parse(self, sources: list[Source]) -> FunctionsDocument:
		"""Parse source declarations without typing their examples."""
		return parseFunctions(sources)

	def resolve(self, doc: FunctionsDocument) -> FunctionLibrary:
		"""Validate signatures and type source examples against this context."""
		return resolveFunctions(self.ontologies, doc)

	def load(self, sources: list[Source]) -> FunctionLibrary:
		"""Parse and resolve one library's files."""
		return loadFunctions(self.ontologies, sources)

	def print(self, library: FunctionLibrary) -> str:
		"""Print a typed library in normal form."""
		return printFunctions(library)

	def format(self, sources: list[Source]) -> str:
		"""Load and print source files with this ontology context."""
		return formatFunctions(self.ontologies, sources)

	def toJson(self, library: FunctionLibrary) -> dict[str, Any]:
		"""Export independent JSON data from a typed library."""
		return functionsToJson(library)

	def fromJson(self, data: Any, name: str = "functions.json") -> FunctionLibrary:
		"""Validate library JSON through its text and signatures."""
		return functionsFromJson(self.ontologies, data, name)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def resolveFunctions(ontologies: list[Ontology], doc: FunctionsDocument) -> FunctionLibrary:
	"""Validate types and inverse signatures and type examples, without executing any function."""
	diag = Diagnostics(list(doc.diagnostics))
	namespaces = {ontology.namespace for ontology in ontologies}
	if len(namespaces) != len(ontologies):
		diag.error("reference", "Loaded ontologies must have distinct namespaces")
	ontology = Ontology(namespace=doc.namespace, uses=list(doc.uses.items()), decls=[decl for ontology in ontologies for decl in ontology.decls])
	model = Model(ontology)
	namespaces |= set().union(*(Model(item).namespaces() for item in ontologies))
	for namespace in doc.uses.values():
		if namespace not in namespaces:
			diag.error("reference", f"Unknown ontology '{namespace}'")
	resolved: dict[str, tuple[list[ResolvedType], ResolvedType]] = {}
	for function in doc.functions:
		try:
			resolved[function.name] = ([_resolveSignature(model, arg) for arg in function.args], _resolveSignature(model, function.result))
		except ValueError as error:
			diag.error("signature", str(error), function.loc)
	for function in doc.functions:
		inverse = annotation(function.ann, "inverse")
		if inverse is None:
			continue
		if inverse not in resolved:
			diag.error("inverse", f"Unknown inverse '{inverse}' of '{function.name}'", function.loc)
		elif function.name in resolved:
			args, result = resolved[function.name]
			otherArgs, otherResult = resolved[inverse]
			other = next(item for item in doc.functions if item.name == inverse)
			if len(args) != 1 or len(otherArgs) != 1 or args[0] != otherResult or result != otherArgs[0] or function.args[0].collection != other.result.collection or function.result.collection != other.args[0].collection:
				diag.error("inverse", f"Inverse '{inverse}' does not have the reversed signature of '{function.name}'", function.loc)
	diag.check()
	functions = []
	for function in doc.functions:
		examples = []
		for source in function.examples:
			# Examples are independent fixtures, not one shared observation document/handle registry.
			resolver = _Resolver(ontology, ObservationsDocument())
			try:
				if len(source.args) != len(function.args):
					raise ValueError(f"Function '{function.name}' expects {len(function.args)} arguments")
				args = [_exampleValue(resolver, signature, value, source.loc) for signature, value in zip(function.args, source.args)]
				result = _exampleValue(resolver, function.result, source.result, source.loc)
				examples.append(FunctionExample(args, result, source.loc))
			except ValueError as error:
				diag.error("example", str(error), source.loc)
			for handle, expected, loc in resolver.references:
				actual = resolver.instances.get(handle, {}).get("type")
				if actual and not model.isA(actual, expected):
					diag.error("example", f"Reference '{handle}' has incompatible type '{actual}', expected '{expected}'", loc)
			diag.items.extend(resolver.diag.items)
		functions.append(Function(function.name, deepcopy(function.args), deepcopy(function.result), examples, list(function.ann), function.doc, function.loc))
	return FunctionLibrary(doc.namespace, dict(doc.header), dict(doc.uses), functions, diag.check())


def loadFunctions(ontologies: list[Ontology], sources: list[Source]) -> FunctionLibrary:
	"""Parse and validate a function library against loaded ontologies."""
	return resolveFunctions(ontologies, parseFunctions(sources))


def formatFunctions(ontologies: list[Ontology], sources: list[Source]) -> str:
	"""Load one library's files and print their normal form."""
	return printFunctions(loadFunctions(ontologies, sources))


def functionsFromJson(ontologies: list[Ontology], data: Any, name: str = "functions.json") -> FunctionLibrary:
	"""Validate exact JSON members, signature types and lossless text replay."""
	try:
		read = _readFunctionsJson(data)
		loaded = loadFunctions(ontologies, [Source(name, printFunctions(read))])
		if functionsToJson(read) != functionsToJson(loaded):
			raise ValueError("Function-library JSON does not survive its text round trip")
	except (ValueError, KeyError, TypeError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	return loaded


# EOF
