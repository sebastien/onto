"""Module: store.formatter — the normal form of store files and their detached JSON."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..ontology.formatter import Namer
from ..text import printAnnotations, printArguments, withDoc
from .model import HEADER_KEYS, POLICY_KEYS, POPULATION_KEYS, STORE_FORMAT, Store, StorePopulation

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def keysText(keys: dict[str, str]) -> str:
	"""` {k=v, ...}` in the order of the policy keys, or nothing."""
	text = printAnnotations(list(keys.items()), list(POPULATION_KEYS))
	return f" {text}" if text else ""


def compact(item: dict[str, Any]) -> dict[str, Any]:
	return {key: value for key, value in item.items() if value is not None}


def populationToJson(population: StorePopulation, root: bool) -> dict[str, Any]:
	if root:
		return {"name": population.name, "type": population.type}
	return compact({"name": population.name, "type": population.type, "parent": population.parent, "via": population.via,
		"reverse": True if population.reverse else None, "through": population.through or None,
		**{key: population.keys[key] for key in POPULATION_KEYS if key in population.keys}, "doc": population.doc})


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printStore(store: Store) -> str:
	"""Print the normal form: header, aliases and systems, then partitions, exclusions and indexes, each sorted."""
	short = Namer(None, sorted(store.uses.items()))
	header = [(key, store.header[key]) for key in HEADER_KEYS if key in store.header]
	lines = [f"@store {store.name}" + (f" {printArguments(header)}" if header else "")]
	lines += [f"@use {path} as {alias}" for alias, path in sorted(store.uses.items())]
	for system in sorted(store.systems, key=lambda item: item.header):
		scope = f" {{scope={system.scope}}}" if system.scope else ""
		lines.append(withDoc(f"@system {system.header}{scope}", system.doc))
	blocks: list[list[str]] = []
	for partition in sorted(store.partitions, key=lambda item: item.kind):
		root = partition.root
		block = [withDoc(f"@partition {partition.kind}({root.name}: {short(root.type)}){keysText(partition.keys)}", partition.doc)]
		for population in partition.populations:
			arrow = "<-" if population.reverse else "->"
			through = f" through {population.through}" if population.through else ""
			block.append(withDoc(f"  {population.name}: {short(population.type)} = {population.parent} {arrow} {population.via}{through}"
				f"{keysText(population.keys)}", population.doc))
		blocks.append(block)
	if store.exclusions:
		blocks.append([withDoc(f"- {short(item.type)}.{item.path}" + (f" {{reason={item.reason}}}" if item.reason else ""), item.doc)
			for item in sorted(store.exclusions, key=lambda item: (item.type, item.path))])
	for index in sorted(store.indexes, key=lambda item: item.name):
		blocks.append([withDoc(f"@index {index.name} {index.kind}", index.doc),
			*(withDoc(f"  {column.population}.{column.path}", column.doc) for column in index.columns)])
	for block in blocks:
		lines += ["", *block]
	return "\n".join(lines) + "\n"


def storeToJson(store: Store) -> dict[str, Any]:
	"""Encode the store as independent JSON, in normal-form order."""
	data: dict[str, Any] = {"format": STORE_FORMAT, "name": store.name}
	if store.header:
		data["header"] = {key: store.header[key] for key in HEADER_KEYS if key in store.header}
	if store.uses:
		data["uses"] = dict(sorted(store.uses.items()))
	if store.systems:
		data["systems"] = [compact({"from": item.fromNamespace, "to": item.toNamespace, "scope": item.scope, "doc": item.doc})
			for item in sorted(store.systems, key=lambda item: item.header)]
	data["partitions"] = [compact({"kind": item.kind, "root": populationToJson(item.root, True),
		"populations": [populationToJson(population, False) for population in item.populations] or None,
		**{key: item.keys[key] for key in POLICY_KEYS if key in item.keys}, "doc": item.doc})
		for item in sorted(store.partitions, key=lambda item: item.kind)]
	if store.exclusions:
		data["exclusions"] = [compact({"type": item.type, "path": item.path, "reason": item.reason, "doc": item.doc})
			for item in sorted(store.exclusions, key=lambda item: (item.type, item.path))]
	if store.indexes:
		data["indexes"] = [compact({"name": item.name, "kind": item.kind,
			"columns": [compact({"population": column.population, "path": column.path, "doc": column.doc}) for column in item.columns],
			"doc": item.doc}) for item in sorted(store.indexes, key=lambda item: item.name)]
	return deepcopy(data)


__all__ = ["printStore", "storeToJson"]

# EOF
