"""Module: store.bundle — compile a checked store file into its `onto.store-bundle/1` (spec-08 "Store bundle")."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..mapping.model import Mapping
from ..ontology.facts import modelJson
from ..ontology.model import Model, Ontology, isAssociation
from ..referential.model import Referential
from ..referential.operations import modelFor, policyFor
from .model import POLICY_KEYS, Store, StorePopulation
from .operations import resolvePopulation

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


STORE_BUNDLE_FORMAT = "onto.store-bundle/1"
DEFAULT_POLICIES = {"orphaned": "never", "archived": "never", "grace": "P30D"}
# Spec-08 "Limits".
LIMITS = {
	"requestBytes": 8 * 1024 * 1024, "statementsPerBatch": 1024, "statementBytes": 1024 * 1024, "handleBytes": 256,
	"logPage": 1000, "retries": "P7D", "indexes": 16, "columns": 8, "inValues": 64, "indexPage": 1000,
}


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def related(model: Model, left: str, right: str) -> bool:
	return model.isA(left, right) or model.isA(right, left)


def instanceTypes(model: Model) -> list[str]:
	"""The entity and association types of the model, sorted."""
	return sorted(decl.path for decl in model.ontology.decls if decl.kind == "entity" or isAssociation(decl))


def populationsJson(model: Model, populations: list[StorePopulation], root: StorePopulation, policies: dict[str, str]) -> list[dict[str, Any]]:
	"""Member populations with the claim that makes a subject a member; `through` adds its witness population."""
	types = {root.name: root.type}
	result: list[dict[str, Any]] = []

	def add(name: str, type: str, parent: str, link: dict[str, Any], population: StorePopulation) -> None:
		keys = {key: population.keys[key] for key in POLICY_KEYS if key in population.keys}
		result.append({"name": name, "type": type, "parent": parent, "link": link, "policies": policies | keys,
			**({"privacy": "kept"} if population.keys.get("privacy") == "kept" else {})})
		types[name] = type

	for population in populations:
		field = resolvePopulation(model, population, types)
		if population.through:
			context, start, end = field.association
			if population.reverse:
				start, end = end, start
			add(population.through, context, population.parent, {"slot": start, "on": "member"}, population)
			add(population.name, population.type, population.through, {"slot": end, "on": "parent"}, population)
		elif field.relation:
			parentRole, memberRole = field.roles[::-1] if population.reverse else field.roles
			add(population.name, population.type, population.parent, {"rel": field.relation, "parentRole": parentRole, "memberRole": memberRole}, population)
		else:
			add(population.name, population.type, population.parent, {"slot": field.member, "on": "member" if population.reverse else "parent"}, population)
	return result


def systemJson(model: Model, name: str, scope: str, mapping: Mapping) -> dict[str, Any]:
	"""The slots a system's mapping fills, per target type: attributes and roles, facets, relations and existence."""
	types: dict[str, dict[str, set[str]]] = {}
	for item in mapping.scopes:
		filled = types.setdefault(item.target, {"attrs": set(), "facets": set(), "relations": set()})
		for line in item.lines:
			if line.target:
				filled["attrs"].add(line.target)
			if line.facet:
				filled["facets"].add(line.facet)
			if line.verb:
				filled["relations"].update(decl.path for decl, _ in model.verbs(item.target, line.verb))
	return {"name": name, "scope": scope, "types": {type: {key: sorted(values) for key, values in filled.items()} for type, filled in sorted(types.items())}}


def originsJson(model: Model, systems: list[tuple[dict[str, Any], Referential | None]]) -> dict[str, Any]:
	"""Per instance type that a system produces, or that is related to one: the producing systems and the key policy."""
	origins: dict[str, Any] = {}
	for type in instanceTypes(model):
		producers = [system["name"] for system, _ in systems if any(related(model, type, target) for target in system["types"])]
		if not producers:
			continue
		entry: dict[str, Any] = {"systems": producers}
		for system, referential in systems:
			policy = policyFor(model, referential, type) if referential is not None and system["name"] in producers else None
			if policy is not None and policy.keys and not policy.minted:
				entry["policy"] = {"keys": list(policy.keys), **({"from": policy.fromNamespace} if policy.fromNamespace else {})}
				break
		origins[type] = entry
	return origins


def revisionOf(bundle: dict[str, Any]) -> str:
	"""A digest of the bundle's content, which stamps the batches it validates."""
	return "sha256:" + hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def storeBundle(ontologies: list[Ontology], store: Store, mappings: list[Mapping] | None = None, referentials: list[Referential] | None = None) -> dict[str, Any]:
	"""Compile a checked store: model facts, kinds, held slots, origins, policies, indexes and limits."""
	model = modelFor(ontologies)
	byHeader = {f"{mapping.fromNamespace} -> {mapping.toNamespace}": mapping for mapping in mappings or []}
	byName = {referential.namespace: referential for referential in referentials or []}
	systems: list[tuple[dict[str, Any], Referential | None]] = []
	for system in sorted(store.systems, key=lambda item: item.header):
		mapping = byHeader[system.header]
		referential = byName.get(str(mapping.header.get("referential", "")))
		systems.append((systemJson(model, system.fromNamespace, system.scopeToken, mapping), referential))
	kinds = []
	for partition in sorted(store.partitions, key=lambda item: item.kind):
		policies = DEFAULT_POLICIES | {key: partition.keys[key] for key in POLICY_KEYS if key in partition.keys}
		kinds.append({"kind": partition.kind, "root": {"name": partition.root.name, "type": partition.root.type}, "policies": policies,
			"populations": populationsJson(model, partition.populations, partition.root, policies)})
	indexes = []
	for index in sorted(store.indexes, key=lambda item: item.name):
		partition = store.partition(index.kind)
		types = {population.name: population.type for population in partition.all} if partition else {}
		indexes.append({"name": index.name, "kind": index.kind, "columns": [{"name": f"{column.population}.{column.path}", "population": column.population,
			"type": types.get(column.population, ""), "path": column.path} for column in index.columns]})
	bundle = {
		"format": STORE_BUNDLE_FORMAT, "store": store.name, **({"rev": store.header["rev"]} if "rev" in store.header else {}),
		**({"edit": store.header["edit"]} if "edit" in store.header else {}), "ontology": ontologies[0].namespace,
		"model": modelJson(Model(ontologies[0])), "kinds": kinds, "systems": [system for system, _ in systems],
		"origins": originsJson(model, systems),
		"exclusions": [{"type": item.type, "path": item.path} for item in sorted(store.exclusions, key=lambda item: (item.type, item.path))],
		"indexes": indexes, "limits": dict(LIMITS),
	}
	return {**bundle, "revision": revisionOf(bundle)}


__all__ = ["STORE_BUNDLE_FORMAT", "DEFAULT_POLICIES", "LIMITS", "storeBundle", "revisionOf"]

# EOF
