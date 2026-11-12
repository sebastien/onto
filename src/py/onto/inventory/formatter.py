"""Module: inventory.formatter — print inventories in their tab-separated normal form."""

from __future__ import annotations

from .model import Inventory

# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printInventory(inventory: Inventory) -> str:
	"""One `path<TAB>type` line per field, sorted by path."""
	return "".join(f"{item.path}\t{item.type}\n" for item in sorted(inventory.fields, key=lambda item: item.path))


__all__ = ["printInventory"]

# EOF
