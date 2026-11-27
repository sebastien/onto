"""Module: store.operations — store files against their ontology and their @system mappings (spec-08 "Checks")."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..mapping.model import Mapping
from ..ontology.model import Model, Ontology, isAssociation
from ..ontology.rooted import Field, fieldFor
from ..referential.model import Referential
from ..referential.operations import modelFor
from ..text import Diagnostics, Source, annotation
from .formatter import printStore, storeToJson
from .model import Store, StorePartition, StorePopulation
from .parser import parseStore, storeFromJson

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def isInstanceType(model: Model, path: str) -> bool:
	"""Whether `path` names an entity or an association, whose instances a partition can hold."""
	decl = model.get(path)
	return decl is not None and (decl.kind == "entity" or isAssociation(decl))


def resolvePopulation(model: Model, population: StorePopulation, types: dict[str, str]) -> Field:
	"""The link a member population follows from its parent, as a rooted view resolves it."""
	if not isInstanceType(model, population.type):
		raise ValueError(f"expected an entity or association type, not '{population.type}'")
	parentType = types.get(population.parent)
	if parentType is None:
		raise ValueError(f"its parent '{population.parent}' did not resolve")
	owner, endpoint = (population.type, parentType) if population.reverse else (parentType, population.type)
	field = fieldFor(model, owner, population.via, endpoint=endpoint)
	if not field.other or not model.isA(endpoint, field.other):
		raise ValueError(f"{field.path} cannot reach {endpoint}")
	if population.through and not field.association:
		raise ValueError(f"{field.path} needs a context with both role selectors")
	return field


def personalAttributes(model: Model, path: str) -> list[str]:
	"""The attributes of `path`, inherited and of its facets, that carry a `privacy` annotation (spec-01)."""
	lineage = set(model.lineage(path))
	decls = [model.get(item) for item in lineage]
	decls += [decl for decl in model.ontology.decls if decl.kind == "facet" and decl.subject in lineage]
	return sorted({attr.name for decl in decls if decl for attr in decl.attrs if annotation(attr.ann, "privacy") is not None})


def referencedTypes(model: Model, path: str) -> set[str]:
	"""The types that `path`'s roles and reference attributes, inherited included, refer to."""
	types: set[str] = set()
	for item in model.lineage(path):
		decl = model.get(item)
		if decl is None:
			continue
		types.update(participant.type for participant in decl.participants)
		for attr in decl.attrs:
			resolved = model.resolveType(attr.type, attr.ann)
			if resolved.kind == "entity" and resolved.path:
				types.add(resolved.path)
	return types


# -----------------------------------------------------------------------------
#
# CHECKS
#
# -----------------------------------------------------------------------------


class StoreChecker:
	"""Spec-08's checks of one store against its ontology (the first of `ontologies`) and mappings."""

	def __init__(self, ontologies: list[Ontology], mappings: list[Mapping], store: Store):
		self.store = store
		self.mappings = mappings
		self.namespace = ontologies[0].namespace if ontologies else ""
		self.model = modelFor(ontologies)
		self.diag = Diagnostics(list(store.diagnostics))
		# Resolved populations per kind: alias -> type; roots of the kinds whose key entity resolved.
		self.types: dict[str, dict[str, str]] = {}
		self.roots: list[StorePartition] = []

	def short(self, path: str) -> str:
		return path.removeprefix(f"{self.namespace}/")

	def related(self, left: str, right: str) -> bool:
		return self.model.isA(left, right) or self.model.isA(right, left)

	def members(self) -> list[tuple[StorePartition, StorePopulation]]:
		"""Resolved member populations, with their kind."""
		return [(partition, population) for partition in self.roots for population in partition.populations
			if self.types[partition.kind].get(population.name) == population.type]

	def checkUses(self) -> None:
		if not self.namespace:
			self.diag.error("store", "A store is checked against its ontology", self.store.loc)
		for alias, path in sorted(self.store.uses.items()):
			if path != self.namespace and not path.startswith(f"{self.namespace}/"):
				self.diag.error("store", f"@use {path} as {alias}: a store holds the observations of one ontology, {self.namespace}", self.store.loc)

	def checkSystems(self) -> None:
		headers = {f"{mapping.fromNamespace} -> {mapping.toNamespace}" for mapping in self.mappings}
		for system in self.store.systems:
			if system.toNamespace != self.namespace:
				self.diag.error("system", f"@system {system.header}: the mapping must fill the store's ontology, {self.namespace}", system.loc)
			elif system.header not in headers:
				self.diag.error("system", f"@system {system.header}: no such mapping is loaded", system.loc)

	def checkPartitions(self) -> None:
		for partition in self.store.partitions:
			root = self.model.get(partition.root.type)
			if root is None or root.kind != "entity":
				self.diag.error("partition", f"'{partition.kind}' needs an entity type as its key entity, not '{self.short(partition.root.type)}'", partition.loc)
				continue
			types = self.types[partition.kind] = {partition.root.name: partition.root.type}
			self.roots.append(partition)
			for population in partition.populations:
				try:
					resolvePopulation(self.model, population, types)
				except ValueError as error:
					self.diag.error("population", f"{partition.kind}.{population.name}: {error}", population.loc)
					continue
				types[population.name] = population.type

	def checkKinds(self) -> None:
		"""One kind per type: an instance has one home."""
		for index, partition in enumerate(self.roots):
			for other in self.roots[:index]:
				if self.related(partition.root.type, other.root.type):
					self.diag.error("kind", f"'{partition.kind}' and '{other.kind}' have related key entities, so an anchor would have two kinds", partition.loc)
		seen: list[tuple[StorePartition, StorePopulation]] = []
		for partition, population in self.members():
			for other in self.roots:
				if other.kind != partition.kind and self.related(population.type, other.root.type):
					self.diag.error("kind", f"{partition.kind}.{population.name}: {self.short(population.type)} is the key entity of '{other.kind}', "
						"which gives it its own partitions", population.loc)
			for otherPartition, otherPopulation in seen:
				if otherPartition.kind != partition.kind and self.related(population.type, otherPopulation.type):
					self.diag.error("kind", f"{partition.kind}.{population.name}: {self.short(population.type)} is already a member of "
						f"'{otherPartition.kind}'; a member type appears in one kind", population.loc)
			seen.append((partition, population))

	def checkPrivacy(self) -> None:
		"""Personal values about another kind's key entity must be accepted, so that its erasure redacts them."""
		for partition, population in self.members():
			if population.keys.get("privacy") == "kept" or not (personal := personalAttributes(self.model, population.type)):
				continue
			references = referencedTypes(self.model, population.type)
			others = [other.kind for other in self.roots if other.kind != partition.kind and any(self.related(item, other.root.type) for item in references)]
			if others:
				self.diag.error("privacy", f"{partition.kind}.{population.name}: {self.short(population.type)} keeps personal values "
					f"({', '.join(personal)}) and refers to the key entities of '{others[0]}'; accept them with {{privacy=kept}}", population.loc)

	def checkSlots(self) -> None:
		"""Exclusions name slots, and index columns name held slots of their populations."""
		excluded: list[tuple[str, str]] = []
		for exclusion in self.store.exclusions:
			if not isInstanceType(self.model, exclusion.type) or self.model.lookup(exclusion.type, exclusion.path) is None:
				self.diag.error("exclusion", f"Unknown slot {self.short(exclusion.type)}.{exclusion.path}", exclusion.loc)
			excluded.append((exclusion.type, exclusion.path))
		for index in self.store.indexes:
			types = self.types.get(index.kind, {})
			for column in index.columns:
				if (type := types.get(column.population)) is None:
					continue
				if self.model.lookup(type, column.path) is None:
					self.diag.error("index", f"Unknown slot {self.short(type)}.{column.path} in index '{index.name}'", column.loc)
				elif any(path == column.path and self.model.isA(type, owner) for owner, path in excluded):
					self.diag.error("index", f"{column.population}.{column.path} is excluded, so the store never holds it", column.loc)

	def check(self) -> Store:
		self.checkUses()
		self.checkSystems()
		self.checkPartitions()
		self.checkKinds()
		self.checkPrivacy()
		self.checkSlots()
		result = deepcopy(self.store)
		result.diagnostics = self.diag.check()
		return result


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Operator:
	"""Store files, their checks and bundles, sharing the store's ontology (the first of `ontologies`), its @system
	mappings and their referentials."""

	def __init__(self, ontologies: list[Ontology], mappings: list[Mapping] | None = None, referentials: list[Referential] | None = None):
		self.ontologies = list(ontologies)
		self.mappings = list(mappings or [])
		self.referentials = list(referentials or [])

	def parse(self, sources: list[Source]) -> Store:
		"""Parse one store's files and aliases."""
		return parseStore(sources)

	def validate(self, store: Store) -> Store:
		"""Check a parsed store against the ontology and mappings, returning a detached copy."""
		return validateStore(self.ontologies, store, self.mappings)

	def load(self, sources: list[Source]) -> Store:
		"""Parse and check one store's files."""
		return self.validate(self.parse(sources))

	def print(self, store: Store) -> str:
		"""Print the normal form."""
		return printStore(store)

	def format(self, sources: list[Source]) -> str:
		"""Load and print one store's files in normal form."""
		return self.print(self.load(sources))

	def toJson(self, store: Store) -> dict[str, Any]:
		"""Export the JSON form."""
		return storeToJson(store)

	def fromJson(self, data: Any, name: str = "store.json") -> Store:
		"""Decode and check the JSON form."""
		return self.validate(storeFromJson(data, name))

	def bundle(self, store: Store) -> dict[str, Any]:
		"""Compile a checked store into its `onto.store-bundle/1`."""
		# NOTE: Imported here: the bundle compiler resolves populations with this module.
		from .bundle import storeBundle

		return storeBundle(self.ontologies, store, self.mappings, self.referentials)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def validateStore(ontologies: list[Ontology], store: Store, mappings: list[Mapping] | None = None) -> Store:
	"""Check `store` against its ontology (the first of `ontologies`) and its @system mappings."""
	return StoreChecker(list(ontologies), list(mappings or []), store).check()


def loadStore(ontologies: list[Ontology], sources: list[Source], mappings: list[Mapping] | None = None) -> Store:
	"""Parse and check one store's files."""
	return validateStore(ontologies, parseStore(sources), mappings)


def formatStore(ontologies: list[Ontology], sources: list[Source], mappings: list[Mapping] | None = None) -> str:
	"""Load and print one store's files in normal form."""
	return printStore(loadStore(ontologies, sources, mappings))


__all__ = ["Operator", "validateStore", "loadStore", "formatStore", "resolvePopulation", "personalAttributes", "referencedTypes"]

# EOF
