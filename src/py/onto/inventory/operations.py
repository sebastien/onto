"""Module: inventory.operations — inventories from sample documents and default bindings."""

from __future__ import annotations

import re
from typing import Any

from ..binding.model import Binding, BindingLine, BindingScope
from ..expressions import RESERVED, parseExpression, printExpression
from ..text import isPath
from .model import CONTAINER_TYPES, FIELD_TYPES, Inventory, InventoryField

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Steps = list[str | dict[str, Any]]

EACH = {"each": True}
ROOT = {"root": True}
RE_WORD = re.compile(r"[A-Za-z0-9]+")
# NOTE: Fields chosen as a scope's default `id`, by preference.
ID_NAMES = ("id", "key")


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def jsonType(value: Any) -> str | None:
	"""The inventory type of a JSON value; `null` has none."""
	if isinstance(value, bool):
		return "boolean"
	if isinstance(value, (int, float)):
		return "number"
	if isinstance(value, str):
		return "text"
	if isinstance(value, dict):
		return "object"
	if isinstance(value, list):
		return "list"
	return None


def pathText(steps: Steps) -> str:
	"""Print document path `steps` in binding syntax."""
	return printExpression({"path": steps}, binding=True)


def walk(value: Any, steps: Steps, found: dict[str, set[str]]) -> None:
	"""Record list items and scalars below `steps`; plain objects are traversed, not listed."""
	if isinstance(value, dict):
		for key, item in value.items():
			# NOTE: The binding path grammar does not represent empty field names.
			if key:
				walk(item, steps + [key], found)
	elif isinstance(value, list):
		for item in value:
			kind = jsonType(item)
			if kind is not None and kind != "list":
				found.setdefault(pathText(steps + [EACH]), set()).add(kind)
			walk(item, steps + [EACH], found)
	elif (kind := jsonType(value)) is not None and steps:
		found.setdefault(pathText(steps), set()).add(kind)


def pascalCase(text: str) -> str:
	"""`couponRate` → `CouponRate`, `"asset class"` → `AssetClass`; a leading digit gets `F`."""
	words = RE_WORD.findall(text)
	result = "".join(word[:1].upper() + word[1:] for word in words) or "Field"
	return "F" + result if result[0].isdigit() else result


def singular(name: str) -> str:
	"""A naive singular for list names: `instruments` → `Instrument`, `entries` → `Entry`."""
	if name.endswith("ies") and len(name) > 3:
		return name[:-3] + "y"
	if name.endswith("s") and not name.endswith("ss") and len(name) > 1:
		return name[:-1]
	return name


def fieldSteps(path: str) -> Steps:
	"""Parse an inventory path back into expression steps."""
	return parseExpression(path, binding=True)["path"]


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def documentFields(document: Any, csv: bool = False) -> dict[str, list[str]]:
	"""Field paths of one document, in inventory syntax, with the JSON types seen at each.

	A CSV document (a list of row objects) has its fields under `$[*]`; so has a JSON
	document whose root is a list.
	"""
	found: dict[str, set[str]] = {}
	walk(document, [ROOT] if csv or isinstance(document, list) else [], found)
	return {path: sorted(kinds, key=FIELD_TYPES.index) for path, kinds in sorted(found.items())}


def inventoryFromDocuments(documents: list[Any], csv: bool = False) -> Inventory:
	"""Derive an inventory from sample documents; fields absent from the samples are invisible.

	A field seen with several types gets the first in `FIELD_TYPES` order.
	"""
	found: dict[str, set[str]] = {}
	for document in documents:
		for path, kinds in documentFields(document, csv).items():
			found.setdefault(path, set()).update(kinds)
	return Inventory([InventoryField(path, min(kinds, key=FIELD_TYPES.index)) for path, kinds in sorted(found.items())])


def defaultBinding(inventory: Inventory, namespace: str, csv: bool = False) -> Binding:
	"""One scope line per list of objects, one body line per scalar field below it (spec-04).

	Attributes are the field names in PascalCase, types the singular list names (`Row`
	for CSV rows). The `id` is `id`, `key` or a field ending in `Id`, else the first scalar
	field; scopes without a scalar key candidate are omitted. People edit the exceptions.
	"""
	types = inventory.types()
	scopes: list[BindingScope] = []
	used: set[str] = set()
	for path, kind in types.items():
		steps = fieldSteps(path)
		if kind != "object" or steps[-1] != EACH:
			continue
		names = [step for step in steps if isinstance(step, str)]
		typeName = "Row" if not names else pascalCase(singular(names[-1]))
		name, index = typeName, 2
		while name in used:
			name, index = f"{typeName}{index}", index + 1
		fields: list[Steps] = []
		for other, otherKind in types.items():
			rest = fieldSteps(other)[len(steps):]
			if fieldSteps(other)[:len(steps)] != steps or not rest or otherKind in CONTAINER_TYPES:
				continue
			if EACH in rest[:-1] or rest[0] == EACH:
				continue
			fields.append(rest)
		# NOTE: A lone quoted string in an id expression is a literal, not a relative field.
		scalar = [rest for rest in fields if EACH not in rest and (len(rest) > 1 or isPath(rest[0]) and rest[0] not in RESERVED)]
		if not scalar:
			continue
		used.add(name)
		lines: list[BindingLine] = []
		short = [pascalCase(next(step for step in reversed(rest) if isinstance(step, str))) for rest in fields]
		targets: set[str] = set()
		for rest, attr in zip(fields, short):
			if short.count(attr) > 1:
				attr = "".join(pascalCase(step) for step in rest if isinstance(step, str))
			stem, index = attr, 2
			while attr in targets:
				attr, index = f"{stem}{index}", index + 1
			targets.add(attr)
			lines.append(BindingLine(target=attr, expr={"path": rest}))
		plain = [rest for rest in scalar if len(rest) == 1]
		key = next((rest for name in ID_NAMES for rest in plain if rest[0].lower() == name), None)
		key = key or next((rest for rest in plain if rest[0].endswith(("Id", "_id", "ID"))), None) or (plain or scalar)[0]
		scopes.append(BindingScope(type=f"{namespace}/{name}", path={"path": steps}, id={"path": key}, lines=lines))
	return Binding(ontology=namespace, header={"format": "csv"} if csv else {}, scopes=scopes)


__all__ = ["documentFields", "inventoryFromDocuments", "defaultBinding", "pascalCase"]

# EOF
