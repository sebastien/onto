"""Module: functions.operations — ontology-backed library validation and interchange."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from ..observations.model import ObservationsDocument, Statement
from ..observations.parser import ObservationResolver
from ..ontology.model import Attr, Decl, Model, Ontology, ResolvedType, TypeExpr, isAssociation
from ..text import Diagnostics, FormatError, Loc, Source, annotation
from .formatter import functionsToJson, printFunctions
from .model import Function, FunctionExample, FunctionLibrary, FunctionsDocument, SignatureType
from .parser import readFunctionsJson, parseFunctions

if TYPE_CHECKING:
	from .runtime import FunctionEvaluator

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def resolveSignature(model: Model, signature: SignatureType) -> ResolvedType:
	"""Resolve and validate a function signature type against `model`."""
	if signature.path:
		decl = model.get(signature.path)
		if not decl or decl.kind not in ("entity", "type") and not isAssociation(decl):
			raise ValueError(f"Unknown signature type '{signature.path}'")
	return model.resolveType(signature.typeExpr())


def exampleValue(resolver: ObservationResolver, signature: SignatureType, raw: str, loc: Loc) -> Any:
	attr = Attr("Example", card="*" if signature.collection else "?", type=signature.typeExpr())
	return resolver.value(raw, attr, Statement(1, "value", "", None, loc, {}))


NUMERIC = ("Integer", "Number", "Amount", "Percent")


def ruleTypesCompatible(model: Model, expected: ResolvedType, actual: ResolvedType) -> bool:
	"""Whether a value of `actual` type is accepted where `expected` is: same type, a specialisation, or numbers."""
	if "unspecified" in (expected.kind, actual.kind):
		return True
	if expected.kind == actual.kind == "builtin":
		return expected.builtin == actual.builtin or (expected.builtin in NUMERIC and actual.builtin in NUMERIC)
	if expected.kind == actual.kind == "entity":
		return bool(actual.path and expected.path and model.isA(actual.path, expected.path))
	if expected.kind == actual.kind == "vocab" and not (expected.path and actual.path):
		return expected.values == actual.values
	if expected.kind == actual.kind == "range":
		return expected.element is not None and actual.element is not None and ruleTypesCompatible(model, expected.element, actual.element)
	return expected.kind == actual.kind and expected.path == actual.path


def checkRules(ontologies: list[Ontology], doc: FunctionsDocument, model: Model, resolved: dict[str, tuple[list[ResolvedType], ResolvedType]], diag: Diagnostics) -> None:
	"""Check derived attributes whose `rule` names a function of this library (spec-01 "Attributes", `rule`).

	The function must exist, take one argument per input (at least as many when the inputs end with `...`),
	and its argument and result types must match the inputs' and the attribute's types."""
	declarations = {function.name: function for function in doc.functions}
	for ontology in ontologies:
		defaultCard = dict(ontology.header).get("card", "?")
		aliases = dict(ontology.uses)
		owners = [decl for decl in ontology.decls if decl.kind in ("entity", "facet", "relation", "type")]
		for owner in owners:
			for attr in (owner.fields or []) if owner.kind == "type" else owner.attrs:
				rule = annotation(attr.ann, "rule")
				if not attr.derived or not isinstance(rule, str) or "/" not in rule:
					continue
				head, _, name = rule.partition("/")
				if aliases.get(head, head) != doc.namespace:
					continue
				where = f"'{owner.path}.{attr.name}'"
				if name not in resolved:
					diag.error("rule", f"{where} names unknown function '{doc.namespace}/{name}'", attr.loc)
					continue
				args, result = resolved[name]
				declaration = declarations[name]
				deps = [dep for dep in attr.deps or [] if not dep.ellipsis]
				incomplete = any(dep.ellipsis for dep in attr.deps or [])
				if len(args) < len(deps) or (len(args) > len(deps) and not incomplete):
					diag.error("rule", f"{where} has {len(deps)} inputs but '{doc.namespace}/{name}' takes {len(args)}", attr.loc)
					continue
				for index, dep in enumerate(deps):
					if dep.input:
						continue
					source = model.lookup(owner.path, dep.local) if dep.local else model.lookup(dep.path, dep.attr) if dep.path and dep.attr else Attr("Input", type=TypeExpr(path=dep.path))
					if source and (
						declaration.args[index].collection != ((source.card or defaultCard) in ("*", "+"))
						or not ruleTypesCompatible(model, args[index], model.resolveType(source.type, source.ann))
					):
						diag.error("rule", f"{where}: input {index + 1} does not match the argument type of '{doc.namespace}/{name}'", attr.loc)
				if declaration.result.collection != ((attr.card or defaultCard) in ("*", "+")) or not ruleTypesCompatible(model, model.resolveType(attr.type, attr.ann), result):
					diag.error("rule", f"{where}: the result of '{doc.namespace}/{name}' does not match its type", attr.loc)


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

	def evaluator(self, libraries: list[FunctionLibrary] | None = None, functions: list[Function] | None = None,
		maps: list[Decl] | None = None, implementations: dict[str, Callable[..., Any]] | None = None) -> FunctionEvaluator:
		"""Create a pure evaluator sharing the signature ontologies, without executing examples implicitly."""
		from .runtime import FunctionEvaluator
		return FunctionEvaluator(self.ontologies, libraries, functions, maps, implementations)

	def conformance(self, library: FunctionLibrary, implementations: dict[str, Callable[..., Any]]) -> int:
		"""Check all library examples and executable inverse round trips; return the example count."""
		return self.evaluator(libraries=[library], implementations=implementations).conformance(library)


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
			resolved[function.name] = ([resolveSignature(model, arg) for arg in function.args], resolveSignature(model, function.result))
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
	checkRules(ontologies, doc, model, resolved, diag)
	diag.check()
	functions = []
	for function in doc.functions:
		examples = []
		for source in function.examples:
			# Examples are independent fixtures, not one shared observation document/handle registry.
			resolver = ObservationResolver(ontology, ObservationsDocument())
			try:
				if len(source.args) != len(function.args):
					raise ValueError(f"Function '{function.name}' expects {len(function.args)} arguments")
				args = [exampleValue(resolver, signature, value, source.loc) for signature, value in zip(function.args, source.args)]
				result = exampleValue(resolver, function.result, source.result, source.loc)
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
		read = readFunctionsJson(data)
		loaded = loadFunctions(ontologies, [Source(name, printFunctions(read))])
		if functionsToJson(read) != functionsToJson(loaded):
			raise ValueError("Function-library JSON does not survive its text round trip")
	except (ValueError, KeyError, TypeError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	return loaded


__all__ = [
	"resolveSignature", "exampleValue", "NUMERIC", "ruleTypesCompatible", "checkRules",
	"Operator", "resolveFunctions", "loadFunctions", "formatFunctions", "functionsFromJson",
]


# EOF
