"""Module: ontology.changes — model-first semantic comparison and change rendering."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

from .formatter import Printer, normaliseOntology
from .model import HEADER_DEFAULTS, Ontology
from .operations import ontologyToJson

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class Element:
	"""A declaration or owned member, addressed independently of its source file."""

	data: dict[str, Any]
	line: str
	owner: str | None = None
	name: str | None = None


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def ontologyElements(ontology: Ontology) -> dict[str, Element]:
	"""Index normalized declarations, attributes, roles and vocabulary values."""
	normal = normaliseOntology(ontology)
	printer = Printer(normal)
	# NOTE: Diff paths and rendered references are independent of file-local aliases.
	printer.short = lambda path: path
	elements: dict[str, Element] = {}

	def vocabulary(path: str, data: dict[str, Any]) -> None:
		if "values" not in data:
			return
		values = data.pop("values")
		if elements[path].data.get("ann", {}).get("ordered"):
			data["order"] = values
		for value in values:
			elements[f"{path}:{value}"] = Element({"kind": "value"}, value, path, value)

	for decl, encoded in zip(normal.decls, ontologyToJson(normal)["decls"]):
		path = decl.path
		data = {key: value for key, value in encoded.items() if key not in ("path", "attrs", "fields", "participants")}
		if "def" in data:
			data["type"] = data.pop("def")
		if "arrow" in data:
			data.update(data.pop("arrow"))
		elements[path] = Element(data, printer.head(decl).strip())
		if "type" in data:
			vocabulary(path, data["type"])
		for role in encoded.get("participants", []):
			member = f"{path}.{role['role']}"
			elements[member] = Element(
				{"kind": "role", "type": role["type"], "card": role["card"]},
				f"{member} {role['card']} {role['type']}", path, role["role"],
			)
		# NOTE: Facet attributes use their public Subject.Facet.Attr address (spec-01).
		attrOwner = f"{decl.subject}.{path.rsplit('/', 1)[-1]}" if decl.kind == "facet" else path
		for attr, encodedAttr in zip(decl.fields or [] if decl.kind == "type" else decl.attrs, encoded.get("fields", encoded.get("attrs", []))):
			member = f"{attrOwner}.{attr.name}"
			attrData = {"kind": "attribute", **{key: value for key, value in encodedAttr.items() if key != "name"}}
			elements[member] = Element(attrData, printer.attr(replace(attr, name=member)).strip(), path, attr.name)
			if "type" in attrData:
				vocabulary(member, attrData["type"])
	return elements


def changeValue(value: Any) -> str:
	"""Compact text for a changed property."""
	if value is None:
		return "-"
	if isinstance(value, str):
		return value
	if isinstance(value, dict):
		if "builtin" in value:
			return value["builtin"]
		if set(value) == {"name", "path", "attr"}:
			return f"{value['name']}: {value['path']}.{value['attr']}"
		if "path" in value:
			return value["path"] + (f".{value['attr']}" if "attr" in value else "")
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def ontologyDiff(before: Ontology, after: Ontology) -> list[dict[str, Any]]:
	"""Compare normalized models, matching unique stable IDs before paths."""
	old, new = ontologyElements(before), ontologyElements(after)
	oldIds, newIds = before.ids or {}, after.ids or {}
	oldCounts, newCounts = Counter(oldIds.values()), Counter(newIds.values())
	byId = {identifier: path for path, identifier in newIds.items() if path in new and newCounts[identifier] == 1 and identifier not in ("(overlay)", "(authored)")}
	pairs: dict[str, str] = {}
	used: set[str] = set()
	for path in old:
		identifier = oldIds.get(path)
		target = byId.get(identifier) if oldCounts[identifier] == 1 else None
		if target is not None:
			pairs[path] = target
			used.add(target)
	for path, element in old.items():
		if element.owner is None and path not in pairs and path in new and path not in used:
			pairs[path] = path
			used.add(path)
	# NOTE: A renamed owner carries unchanged member names with it; no similarity heuristics.
	members = {(element.owner, element.name): path for path, element in new.items() if element.owner is not None}
	for path, element in old.items():
		if path in pairs or element.owner not in pairs:
			continue
		target = members.get((pairs[element.owner], element.name))
		if target is not None and target not in used:
			pairs[path] = target
			used.add(target)
	changes: list[dict[str, Any]] = []
	oldHeader: dict[str, str | list[str] | None] = {"namespace": before.namespace, **HEADER_DEFAULTS, **dict(before.header)}
	newHeader: dict[str, str | list[str] | None] = {"namespace": after.namespace, **HEADER_DEFAULTS, **dict(after.header)}
	for header, ontology in ((oldHeader, before), (newHeader, after)):
		if header.get("layering") == "declared":
			# NOTE: Meta ranks first regardless of its position in the source.
			meta = f"{ontology.namespace}/Meta"
			header["domainOrder"] = [
				decl.path for decl in ontology.decls if decl.kind == "domain" and decl.path != meta
			]
	for field in sorted(oldHeader.keys() | newHeader.keys()):
		if oldHeader.get(field) != newHeader.get(field):
			changes.append({"op": "change", "path": "@ontology", "field": field, "before": oldHeader.get(field), "after": newHeader.get(field)})
	for path, element in old.items():
		target = pairs.get(path)
		if target is None:
			changes.append({"op": "remove", "path": path, "before": element.data})
			continue
		if target != path:
			inherited = element.owner is not None and pairs.get(element.owner) == new[target].owner and element.name == new[target].name
			if not inherited:
				changes.append({"op": "move", "path": path, "to": target})
		right = new[target].data
		for field in sorted(element.data.keys() | right.keys()):
			if element.data.get(field) != right.get(field):
				changes.append({"op": "change", "path": target, "field": field, "before": element.data.get(field), "after": right.get(field)})
	for path, element in new.items():
		if path not in used:
			changes.append({"op": "add", "path": path, "after": element.data, "line": element.line})
	return sorted(changes, key=lambda change: (change["path"], change["op"], change.get("field", "")))


def printOntologyDiff(changes: list[dict[str, Any]]) -> str:
	"""Render semantic changes using spec-01's +, -, > and ~ notation."""
	lines = []
	for change in changes:
		path, op = change["path"], change["op"]
		if op == "move":
			lines.append(f"> {path} => {change['to']}")
		elif op in ("add", "remove"):
			data = change.get("after", change.get("before"))
			if data["kind"] == "value":
				owner, value = path.rsplit(":", 1)
				lines.append(f"~ {owner} {'+' if op == 'add' else '-'}{value}")
			else:
				lines.append(f"+ {change['line']}" if op == "add" else f"- {path}")
		else:
			field = change["field"]
			if field == "ann":
				before, after = change["before"] or {}, change["after"] or {}
				removed = ["-" + key + ("" if value is True else "=" + str(value)) for key, value in before.items() if after.get(key) != value]
				added = ["+" + key + ("" if value is True else "=" + str(value)) for key, value in after.items() if before.get(key) != value]
				tail = " " + " ".join(removed + added)
			else:
				tail = "" if field == "doc" else f" {changeValue(change['before'])} => {changeValue(change['after'])}"
			lines.append(f"~ {path} {field}{tail}")
	return "".join(line + "\n" for line in lines)


__all__ = ["ontologyDiff", "printOntologyDiff"]

# EOF
