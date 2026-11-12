"""Module: inventory.model — spec-04 document-format inventories: field paths and JSON types."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..text import Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


FIELD_TYPES = ("text", "number", "boolean", "object", "list")
CONTAINER_TYPES = ("object", "list")


@dataclass(slots=True)
class InventoryField:
	"""One field path, in binding path syntax, and the JSON type of its values."""

	path: str
	type: str
	loc: Loc | None = None


@dataclass(slots=True)
class Inventory:
	"""The field paths a document format can contain, sorted by path."""

	fields: list[InventoryField] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)

	def types(self) -> dict[str, str]:
		"""Field path → JSON type."""
		return {item.path: item.type for item in self.fields}


__all__ = ["FIELD_TYPES", "CONTAINER_TYPES", "InventoryField", "Inventory"]

# EOF
