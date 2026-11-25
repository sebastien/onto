"""Module: observations.rooted — walk typed view paths and collect witnesses from reconciled claims."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..ontology.model import Model, isSymmetric
from ..ontology.rooted import Field, Hop, RootedView, memberMatches
from .model import Claim, Observations, intersectIntervals, observationStatus, referenceHandles

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type BoundPath = tuple[dict[str, str], list[Witness]]
# Subject, value, the claim reaching it, and (for an association link) its subject role claim.
type Row = tuple[str, Any, Claim, Claim | None]


@dataclass(frozen=True, slots=True)
class Witness:
	"""The original claim and the specific hop, subject and value it proved. A link its relation's context
	association states is proved by two role claims of one instance: `claim` reaches the value,
	`subjectRoleClaim` holds the field's subject (irrespective of traversal direction)."""

	claim: Claim
	hop: Hop
	subject: str
	value: Any
	subjectRoleClaim: Claim | None = None


def conflicted(claim: Claim, subjectRoleClaim: Claim | None = None) -> bool:
	"""Whether a row's claims include a conflicting one."""
	return bool(claim.get("conflict") or subjectRoleClaim is not None and subjectRoleClaim.get("conflict"))


def roleValidity(claim: Claim, subjectRoleClaim: Claim) -> str | Literal[False] | None:
	"""The link's shared validity; False for disjoint role claims, None for an unbounded link."""
	valids = [item["valid"] for item in (subjectRoleClaim, claim) if "valid" in item]
	return (intersectIntervals(valids) or False) if valids else None


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Evidence:
	"""A per-run index of the reconciled claims usable in a rooted view."""

	def __init__(self, model: Model, state: Observations):
		self.model, self.state = model, state
		self.index: dict[Field, list[Row]] = {}

	def rows(self, field: Field) -> list[Row]:
		"""The subjects, values and claims that address `field`. A link is stated by its relation's claims and, when
		the relation has a context, by each instance of that association with both of its selected roles."""
		if field not in self.index:
			rows = []
			symmetric = bool(field.relation) and isSymmetric(self.model.get(field.relation))
			context, startRole, endRole = field.context or ("", "", "")
			roles = defaultdict(list) if startRole != endRole else None
			for claim in self.state.claims:
				if claim.get("ctx") is not None:  # These views request unqualified facts.
					continue
				if field.relation and claim.get("rel") == field.relation:
					subject, other = (claim["roles"][role] for role in field.roles)
					if self.isA(subject, field.owner) and (other == "?" or self.isA(other, field.other)):
						rows.append((subject, {"unknown": True} if other == "?" else {"ref": other}, claim, None))
					if subject != other and symmetric and self.isA(other, field.owner):
						rows.append((other, {"ref": subject}, claim, None))
				elif not field.relation and "p" in claim and memberMatches(claim["p"], field.member) and self.isA(claim["s"], field.owner):
					rows.append((claim["s"], claim["v"], claim, None))
				elif roles is not None and claim.get("p") in (startRole, endRole) and self.isA(claim["s"], context):
					roles[claim["s"], claim["p"]].append(claim)
			for (handle, role), held in (roles or {}).items():
				if role != startRole:
					continue
				for subjectRoleClaim in held:
					for claim in roles.get((handle, endRole), ()):
						if roleValidity(claim, subjectRoleClaim) is False:
							continue
						rows.extend(self.associationRows(field, subjectRoleClaim, claim))
						if symmetric:
							rows.extend(self.associationRows(field, claim, subjectRoleClaim, reverse=True))
			self.index[field] = rows
		return self.index[field]

	def associationRows(self, field: Field, subjectRoleClaim: Claim, claim: Claim, *, reverse: bool = False) -> list[Row]:
		"""The links for one orientation of a role pair; skip self-links in the mirrored orientation."""
		rows = []
		others = [h for h in referenceHandles(claim["v"]) if self.isA(h, field.other)]
		for subject in referenceHandles(subjectRoleClaim["v"]):
			if not self.isA(subject, field.owner):
				continue
			if observationStatus(claim["v"]) == "unknown":
				rows.append((subject, {"unknown": True}, claim, subjectRoleClaim))
			for other in others:
				if not reverse or subject != other:
					rows.append((subject, {"ref": other}, claim, subjectRoleClaim))
		return rows

	def isA(self, handle: str, kind: str) -> bool:
		return self.model.isA(self.state.instances.get(handle, {}).get("type", ""), kind)

	def test(self, hop: Hop, bindings: dict[str, str]) -> tuple[list[Witness], str]:
		"""Retain every matching filter claim, or explain why none proves the filter."""
		subject = bindings[hop.population]
		checks = [(v, c, roleClaim) for h, v, c, roleClaim in self.rows(hop.field) if h == subject]
		if any(conflicted(c, roleClaim) for _, c, roleClaim in checks):
			return [], "conflict"
		witnesses = []
		for value, claim, roleClaim in checks:
			ok = bindings[hop.ancestor] in referenceHandles(value) if hop.ancestor else value == hop.test
			if ok:
				witnesses.append(Witness(claim, hop, subject, value, roleClaim))
		states = {observationStatus(v) for v, _, _ in checks}
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
				for subject, value, claim, roleClaim in self.rows(hop.field):
					# An explicit `through` finishes with the second role; the previous hop proved the first.
					if hop.proves:
						roleClaim = trail[-1].claim
						if subject != handle or roleValidity(claim, roleClaim) is False:
							continue
					if not hop.reverse and subject == handle and (found := observationStatus(value)) != "supplied":
						status = "conflict" if conflicted(claim, roleClaim) else found
						continue
					for other in referenceHandles(value):
						start, end = (other, subject) if hop.reverse else (subject, other)
						if start != handle or not self.isA(end, view.populations[hop.population].type):
							continue
						if conflicted(claim, roleClaim):
							status = "conflict"
							continue
						bound = {**bindings, hop.population: end}
						witness = Witness(claim, hop, handle, end, roleClaim)
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


__all__ = ["Evidence", "Witness", "conflicted", "roleValidity"]

# EOF
