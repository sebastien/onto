"""Module: inventory.parser — read tab-separated inventories, checking paths and types."""

from __future__ import annotations

from ..expressions import parseExpression, printExpression
from ..text import Diagnostics, Loc, Source
from .model import FIELD_TYPES, Inventory, InventoryField

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def canonicalPath(text: str) -> str:
	"""Return a document field path in canonical binding syntax, rejecting other expressions."""
	expr = parseExpression(text, binding=True)
	if "path" not in expr or any(isinstance(step, dict) and ("up" in step or "index" in step) for step in expr["path"]):
		raise ValueError(f"Invalid inventory path '{text}'")
	return printExpression(expr, binding=True)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseInventory(source: Source) -> Inventory:
	"""Parse `path<TAB>type` lines; paths are unique and canonical, types one of `FIELD_TYPES`."""
	diag = Diagnostics()
	fields: dict[str, InventoryField] = {}
	for number, text in enumerate(source.text.replace("\r\n", "\n").split("\n"), 1):
		if not text.strip():
			continue
		loc = Loc(source.name, number)
		parts = text.split("\t")
		if len(parts) != 2:
			diag.error("inventory", "Expected 'path<TAB>type'", loc)
			continue
		path, kind = parts
		try:
			path = canonicalPath(path)
		except ValueError as error:
			diag.error("inventory", str(error), loc)
			continue
		if kind not in FIELD_TYPES:
			diag.error("inventory", f"Unknown field type '{kind}'", loc)
		elif path in fields:
			diag.error("inventory", f"Duplicate field '{path}'", loc)
		else:
			fields[path] = InventoryField(path, kind, loc)
	return Inventory(sorted(fields.values(), key=lambda item: item.path), diag.check())


__all__ = ["canonicalPath", "parseInventory"]

# EOF
