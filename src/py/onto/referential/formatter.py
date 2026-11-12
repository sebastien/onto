"""Module: referential.formatter — canonical policy declarations and detached JSON."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..ontology.formatter import Namer
from ..text import withDoc
from .model import REFERENTIAL_FORMAT, Policy, Referential

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def policyKey(policy: Policy) -> tuple[str, bool]:
	return policy.type, not (policy.minted or bool(policy.keys))


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printReferential(ref: Referential) -> str:
	"""Print policies in normal form without allocating or resolving any instance handles."""
	short = Namer(ref.namespace, sorted(ref.uses.items()))
	lines = [f"@referential {ref.namespace}" + (f" rev={ref.header['rev']}" if "rev" in ref.header else "")]
	lines += [f"@use {namespace} as {alias}" for alias, namespace in sorted(ref.uses.items())]
	if ref.policies:
		lines.append("")
	for policy in sorted(ref.policies, key=policyKey):
		parts = [short(policy.type)]
		if policy.minted:
			parts.append("minted")
		if policy.keys:
			parts.append("key=" + ",".join(policy.keys))
		if policy.fromNamespace is not None:
			parts.append("from=" + policy.fromNamespace)
		if policy.implicit is not None:
			parts.append("implicit=" + policy.implicit)
		lines.append(withDoc(" ".join(parts), policy.doc))
	return "\n".join(lines) + "\n"


def referentialToJson(ref: Referential) -> dict[str, Any]:
	"""Encode policy metadata as independent JSON, retaining primary/alternate key order."""
	policies = []
	for policy in sorted(ref.policies, key=policyKey):
		item: dict[str, Any] = {"type": policy.type}
		if policy.keys:
			item["keys"] = policy.keys
		if policy.minted:
			item["minted"] = True
		for key, value in (("from", policy.fromNamespace), ("implicit", policy.implicit), ("doc", policy.doc)):
			if value is not None:
				item[key] = value
		policies.append(item)
	return deepcopy({"format": REFERENTIAL_FORMAT, "namespace": ref.namespace, **({"header": ref.header} if ref.header else {}),
		**({"uses": ref.uses} if ref.uses else {}), "policies": policies})


__all__ = ["printReferential", "referentialToJson"]

# EOF
