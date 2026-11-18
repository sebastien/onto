"""Module: observations.rooted — walk typed view paths and collect witnesses from reconciled claims."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..ontology.model import Model, isSymmetric
from ..ontology.rooted import Field, Hop, RootedView, memberMatches
from .model import Claim, Observations, observationStatus, referenceHandles

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type BoundPath = tuple[dict[str, str], list[Witness]]


@dataclass(frozen=True, slots=True)
class Witness:
	"""The original claim and the specific hop, subject and value it proved."""

	claim: Claim
	hop: Hop
	subject: str
	value: Any


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Evidence:
	"""A per-run index of the reconciled claims usable in a rooted view."""

	def __init__(self, model: Model, state: Observations):
		self.model, self.state = model, state
		self.index: dict[Field, list[tuple[str, Any, Claim]]] = {}

	def rows(self, field: Field) -> list[tuple[str, Any, Claim]]:
		"""The subjects, values and claims that address `field`."""
		if field not in self.index:
			rows = []
			for claim in self.state.claims:
				if claim.get("ctx") is not None:  # These views request unqualified facts.
					continue
				if field.relation and claim.get("rel") == field.relation:
					subject, other = (claim["roles"][role] for role in field.roles)
					if self.isA(subject, field.owner) and (other == "?" or self.isA(other, field.other)):
						rows.append((subject, {"unknown": True} if other == "?" else {"ref": other}, claim))
					if subject != other and isSymmetric(self.model.get(field.relation)) and self.isA(other, field.owner):
						rows.append((other, {"ref": subject}, claim))
				elif not field.relation and "p" in claim and memberMatches(claim["p"], field.member) and self.isA(claim["s"], field.owner):
					rows.append((claim["s"], claim["v"], claim))
			self.index[field] = rows
		return self.index[field]

	def isA(self, handle: str, kind: str) -> bool:
		return self.model.isA(self.state.instances.get(handle, {}).get("type", ""), kind)

	def test(self, hop: Hop, bindings: dict[str, str]) -> tuple[list[Witness], str]:
		"""Retain every matching filter claim, or explain why none proves the filter."""
		subject = bindings[hop.population]
		checks = [(v, c) for h, v, c in self.rows(hop.field) if h == subject]
		if any(c.get("conflict") for _, c in checks):
			return [], "conflict"
		witnesses = []
		for value, claim in checks:
			ok = bindings[hop.ancestor] in referenceHandles(value) if hop.ancestor else value == hop.test
			if ok:
				witnesses.append(Witness(claim, hop, subject, value))
		states = {observationStatus(v) for v, _ in checks}
		status = "unknown" if "unknown" in states else "absent" if states == {"absent"} else "notMatched" if states == {"supplied"} else "missing"
		return witnesses, status

	def walk(self, view: RootedView, population: str, root: str,
		blocked: Callable[[Hop, dict[str, str]], str | None]) -> tuple[list[BoundPath], list[dict[str, Any]]]:
		"""Return reached bindings and first stops; `blocked` can rule out a hop before inspection."""
		paths: list[BoundPath] = [({view.root: root}, [])]
		stops = []
		chain = view.paths[population]
		for i, hop in enumerate(chain):
			if hop.test is not None:  # Applied with the edge that bound its candidate.
				continue
			guard = chain[i + 1] if i + 1 < len(chain) and chain[i + 1].test is not None else None
			reached = []
			for bindings, trail in paths:
				handle = bindings[hop.parent]
				if status := blocked(hop, bindings):
					stops.append({"subject": handle, "stoppedAt": hop.field.path, "statuses": [status], "path": trail})
					continue
				status, branches, rejected = "missing", [], []
				for subject, value, claim in self.rows(hop.field):
					if not hop.reverse and subject == handle and (found := observationStatus(value)) != "supplied":
						status = "conflict" if claim.get("conflict") else found
						continue
					for other in referenceHandles(value):
						start, end = (other, subject) if hop.reverse else (subject, other)
						if start != handle or not self.isA(end, view.populations[hop.population].type):
							continue
						if claim.get("conflict"):
							status = "conflict"
							continue
						bound = {**bindings, hop.population: end}
						witness = Witness(claim, hop, handle, end)
						if guard:
							why = blocked(guard, bound)
							proofs, why = self.test(guard, bound) if why is None else ([], why)
							if not proofs:
								rejected.append({"subject": end, "stoppedAt": guard.field.path,
									"statuses": [why], "path": [*trail, witness]})
								continue
							branches.extend((bound, [*trail, witness, proof]) for proof in proofs)
						else:
							branches.append((bound, [*trail, witness]))
				reached.extend(branches)
				stops.extend(r for r in rejected if not branches or r["statuses"] != ["notMatched"])
				if not branches and not rejected:
					stops.append({"subject": handle, "stoppedAt": hop.field.path, "statuses": [status], "path": trail})
			paths = reached
			if not paths:
				break
		return paths, stops


__all__ = ["Evidence", "Witness"]

# EOF
