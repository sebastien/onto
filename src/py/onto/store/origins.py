"""Module: store.origins — an instance's origin from its handle, and the slots a store holds for it, read from a store bundle.

Spec-09 "Origins" and spec-08 "Held slots": only the compiled bundle is consulted, as the JavaScript store does.
"""

from __future__ import annotations

import re
from typing import Any

from ..handles import handleKey, sourceParts

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


ORIGIN_STORE = "@store"
ORIGIN_SHARED = "@shared"
RE_ELEMENT_KEY = re.compile(r"\[[^\]]*\]")


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def lineage(bundle: dict[str, Any], type: str) -> list[str]:
	"""`type` and its bases, from the bundle's model facts."""
	types = bundle["model"]["types"]
	result: list[str] = []
	while type and type not in result:
		result.append(type)
		type = types.get(type, {}).get("base", "")
	return result


def isA(bundle: dict[str, Any], type: str, ancestor: str) -> bool:
	return ancestor in lineage(bundle, type)


def related(bundle: dict[str, Any], left: str, right: str) -> bool:
	return isA(bundle, left, right) or isA(bundle, right, left)


def slotOf(claim: dict[str, Any]) -> tuple[str, str] | None:
	"""A statement's slot kind and name; None for identity links, which no instance holds."""
	if "same" in claim or "distinct" in claim:
		return None
	if "rel" in claim:
		return "rel", claim["rel"]
	if "facet" in claim:
		return "facet", claim["facet"]
	if "p" in claim:
		return "attr", RE_ELEMENT_KEY.sub("", claim["p"])
	return "exists", ""


def fills(system: dict[str, Any], bundle: dict[str, Any], type: str, kind: str, name: str) -> bool:
	"""Whether `system`'s mapping fills the slot on `type` or a type compatible with it (spec-09 "Holders")."""
	for target, filled in system["types"].items():
		if kind == "rel" and name in filled["relations"]:
			return True
		if not related(bundle, type, target):
			continue
		if kind == "attr" and name in {RE_ELEMENT_KEY.sub("", item) for item in filled["attrs"]} or kind == "facet" and name in filled["facets"]:
			return True
	return False


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def originOf(bundle: dict[str, Any], handle: str, type: str, scope: str) -> str | None:
	"""The system an instance of `type` comes from: a system's name, `ORIGIN_STORE`, `ORIGIN_SHARED`, or None when its handle
	tells none. `scope` is the store's scope, which its source-qualified handles carry."""
	entry = bundle["origins"].get(type)
	if entry is None:
		return ORIGIN_STORE
	for prefix in lineage(bundle, type):
		key = handleKey(handle, prefix)
		if key is None:
			continue
		if parts := sourceParts(key):
			if parts[0] == scope:
				return ORIGIN_STORE
			if system := next((item for item in bundle["systems"] if item["scope"] == parts[0]), None):
				return system["name"]
		if policy := entry.get("policy"):
			return policy.get("from", ORIGIN_SHARED)
	return None


def holds(bundle: dict[str, Any], origin: str, type: str, claim: dict[str, Any]) -> bool:
	"""Whether the store holds the slot `claim` states about a subject of `type` and `origin`."""
	slot = slotOf(claim)
	if slot is None:
		return True
	kind, name = slot
	if origin != ORIGIN_STORE:
		if kind == "exists":
			# NOTE: A system holds the existence of its instances, so the store never states it.
			return False
		producers = bundle["origins"].get(type, {}).get("systems", []) if origin == ORIGIN_SHARED else [origin]
		if any(fills(system, bundle, type, kind, name) for system in bundle["systems"] if system["name"] in producers):
			return False
	return not (kind == "attr" and any(item["path"] == name and isA(bundle, type, item["type"]) for item in bundle["exclusions"]))


__all__ = ["ORIGIN_STORE", "ORIGIN_SHARED", "originOf", "holds", "slotOf", "lineage", "isA", "related"]

# EOF
