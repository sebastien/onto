"""Module: referential.operations — policy validation and inherited metadata lookup, without registries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..ontology.model import Model, Ontology, isAssociation
from ..text import Diagnostics, FormatError, Loc, Source, annotation
from .formatter import printReferential, referentialToJson
from .model import Policy, Referential
from .parser import checkPolicyShape, parseReferential, readReferentialJson

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def modelFor(ontologies: list[Ontology]) -> Model:
	# Earlier contexts win when imported declarations are also physically carried by another ontology.
	return Model(Ontology(decls=[decl for ontology in reversed(ontologies) for decl in ontology.decls]))


def hasIdentity(policy: Policy) -> bool:
	return policy.minted or bool(policy.keys)


def policyFor(model: Model, ref: Referential, typePath: str) -> Policy | None:
	for ancestor in model.lineage(typePath):
		for policy in ref.policies:
			if policy.type == ancestor and hasIdentity(policy):
				return policy
	return None


def implicitFor(model: Model, ref: Referential, typePath: str) -> str | None:
	for ancestor in model.lineage(typePath):
		for policy in ref.policies:
			if policy.type == ancestor and policy.implicit is not None:
				return policy.implicit
	return None


def knownInstanceType(model: Model, typePath: str) -> None:
	decl = model.get(typePath)
	if decl is None or decl.kind != "entity" and not isAssociation(decl):
		diag = Diagnostics()
		diag.error("reference", f"Unknown entity or association type '{typePath}'")
		diag.check()


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Operator:
	"""Referential declarations and policy queries sharing their loaded ontology context."""

	def __init__(self, ontologies: list[Ontology]):
		self.ontologies = list(ontologies)

	def parse(self, sources: list[Source]) -> Referential:
		"""Parse one referential's files and file-local aliases."""
		return parseReferential(sources)

	def validate(self, ref: Referential) -> Referential:
		"""Validate and independently copy parsed policy declarations."""
		return validateReferential(self.ontologies, ref)

	def load(self, sources: list[Source]) -> Referential:
		"""Parse and validate a referential without reading a registry."""
		return self.validate(self.parse(sources))

	def print(self, ref: Referential) -> str:
		"""Print an already validated referential."""
		return printReferential(ref)

	def format(self, sources: list[Source]) -> str:
		"""Load and canonically print one referential's files."""
		return self.print(self.load(sources))

	def toJson(self, ref: Referential) -> dict[str, Any]:
		"""Export detached policy metadata."""
		return referentialToJson(ref)

	def fromJson(self, data: Any, name: str = "referential.json") -> Referential:
		"""Validate exact JSON members and ontology-backed text replay."""
		return referentialFromJson(self.ontologies, data, name)

	def policy(self, ref: Referential, typePath: str) -> Policy | None:
		"""Return a detached effective identity policy for a fully qualified instance type."""
		return referentialPolicy(self.ontologies, ref, typePath)

	def implicit(self, ref: Referential, typePath: str) -> str | None:
		"""Return the nearest declared implicit age, without measuring elapsed time."""
		return referentialImplicit(self.ontologies, ref, typePath)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def validateReferential(ontologies: list[Ontology], ref: Referential) -> Referential:
	"""Check policy types, key annotations, source ontologies, duplicates and inherited identity rules."""
	diag = Diagnostics([item for item in ref.diagnostics if item.code != "revision"])
	if len({ontology.namespace for ontology in ontologies}) != len(ontologies):
		diag.error("reference", "Loaded ontologies must have distinct namespaces", ref.loc)
	model = modelFor(ontologies)
	namespaces = model.namespaces() | {ontology.namespace for ontology in ontologies}
	for namespace in ref.uses.values():
		if namespace not in namespaces:
			diag.error("reference", f"Unknown ontology '{namespace}'", ref.loc)
	identities: dict[str, Policy] = {}
	ages: set[str] = set()
	covered: set[int] = set()
	for policy in ref.policies:
		try:
			checkPolicyShape(policy)
		except ValueError as error:
			diag.error("policy", str(error), policy.loc)
			continue
		decl = model.get(policy.type)
		if decl is None or decl.kind != "entity" and not isAssociation(decl):
			diag.error("reference", f"Unknown entity or association policy type '{policy.type}'", policy.loc)
			continue
		for index, ontology in enumerate(ontologies):
			if any(item.path == policy.type for item in ontology.decls):
				covered.add(index)
				break
		if policy.fromNamespace is not None and policy.fromNamespace not in namespaces:
			diag.error("reference", f"Unknown from ontology '{policy.fromNamespace}'", policy.loc)
		for key in policy.keys:
			attr = model.lookup(policy.type, key)
			if attr is None or annotation(attr.ann, "key") is not True:
				diag.error("key", f"Policy key '{policy.type}.{key}' must name an attribute declared {{key}}", policy.loc)
		if hasIdentity(policy):
			if policy.type in identities:
				diag.error("duplicate", f"Two identity policies for '{policy.type}'", policy.loc)
			identities[policy.type] = policy
		if policy.implicit is not None:
			if policy.type in ages:
				diag.error("duplicate", f"Two implicit ages for '{policy.type}'", policy.loc)
			ages.add(policy.type)
	for path, policy in identities.items():
		if any(base in identities for base in model.lineage(path)[1:]):
			diag.error("policy", f"Policy on '{path}' conflicts with an inherited identity policy", policy.loc)
	if "rev" in ref.header:
		for index in sorted(covered):
			ontology = ontologies[index]
			if ref.header["rev"] != dict(ontology.header).get("rev"):
				diag.warn("revision", f"Referential revision differs from loaded ontology '{ontology.namespace}'", ref.loc)
	result = deepcopy(ref)
	result.diagnostics = diag.check()
	return result


def loadReferential(ontologies: list[Ontology], sources: list[Source]) -> Referential:
	"""Parse and validate policies against loaded ontologies; no registry or handle allocation is used."""
	return validateReferential(ontologies, parseReferential(sources))


def formatReferential(ontologies: list[Ontology], sources: list[Source]) -> str:
	"""Load and print a referential's normal form."""
	return printReferential(loadReferential(ontologies, sources))


def referentialFromJson(ontologies: list[Ontology], data: Any, name: str = "referential.json") -> Referential:
	"""Validate policy JSON through exact structural checks and lossless text replay."""
	try:
		read = readReferentialJson(data)
		loaded = loadReferential(ontologies, [Source(name, printReferential(read))])
		if referentialToJson(read) != referentialToJson(loaded):
			raise ValueError("Referential JSON does not survive its text round trip")
	except (ValueError, TypeError, KeyError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	return loaded


def referentialPolicy(ontologies: list[Ontology], ref: Referential, typePath: str) -> Policy | None:
	"""Return a detached inherited identity policy from a loaded referential; age-only rows do not mask it."""
	model = modelFor(ontologies)
	knownInstanceType(model, typePath)
	return deepcopy(policyFor(model, ref, typePath))


def referentialImplicit(ontologies: list[Ontology], ref: Referential, typePath: str) -> str | None:
	"""Return the nearest declared implicit age, or None to leave the run's fallback setting in force."""
	model = modelFor(ontologies)
	knownInstanceType(model, typePath)
	return implicitFor(model, ref, typePath)


__all__ = ["Operator", "validateReferential", "loadReferential", "formatReferential", "referentialFromJson", "referentialPolicy", "referentialImplicit"]

# EOF
