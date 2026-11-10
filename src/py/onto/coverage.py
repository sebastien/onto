"""Module: coverage — report observation coverage of ontology views (spec-02)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .observations import Claim, Observations, reconcileObservations
from .ontology import Decl, Model, Ontology, viewRelations
from .text import Diagnostics, annotation, lastSegment

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class CoverageItem:
	"""Coverage of `path` for a subject/context; multiple statuses retain differing sources."""

	path: str
	subject: str | None
	ctx: str | None
	statuses: tuple[str, ...]
	conflict: bool = False
	partial: bool = False


@dataclass(slots=True, frozen=True)
class _Selection:
	owner: str
	member: str = ""
	facet: bool = False
	contextType: str | None = None


STATUSES = ("supplied", "unknown", "absent", "missing")

# -----------------------------------------------------------------------------
#
# SELECTION
#
# -----------------------------------------------------------------------------


def _selections(model: Model, view: Decl) -> set[_Selection]:
	selected: set[_Selection] = set()
	visited: set[str] = set()

	def attribute(owner: str, member: str, seen: frozenset[str] = frozenset()) -> None:
		selected.add(_Selection(owner))
		attr = model.lookup(owner, member)
		struct = model.structOf(attr.type) if attr else None
		if struct and struct.fields and struct.path not in seen:
			for field in struct.fields:
				attribute(owner, f"{member}.{field.name}", seen | {struct.path})
		else:
			facet = model.facetOf(owner, member)
			context = annotation(facet.ann, "ctx") if facet else None
			selected.add(_Selection(owner, member, contextType=context))
			if facet:
				selected.add(_Selection(owner, lastSegment(facet.path), True, context))
				if context:
					selected.add(_Selection(context))

	def whole(decl: Decl) -> None:
		selected.add(_Selection(decl.path))
		attrs = model.entityAttrs(decl.path).values() if decl.kind == "entity" else decl.attrs
		for attr in attrs:
			attribute(decl.path, attr.name)
		if decl.kind == "relation":
			for participant in decl.participants:
				selected.add(_Selection(participant.type))
				if not decl.arrow:
					attribute(decl.path, participant.role)

	def include(current: Decl) -> None:
		if current.path in visited:
			return
		visited.add(current.path)
		for line in current.viewLines:
			relations = viewRelations(model, line)
			if relations is not None:
				for relation in relations:
					whole(relation)
				continue
			decl = model.get(line.path)
			if decl.kind == "view":
				include(decl)
				continue
			if line.member:
				attribute(decl.path, line.member)
			else:
				whole(decl)
			if line.facets:
				facets = model.facets(decl.path)
				for name in facets if line.facets == "*" else line.facets:
					facet = facets[name]
					context = annotation(facet.ann, "ctx")
					selected.add(_Selection(decl.path, name, True, context))
					if context:
						selected.add(_Selection(context))
					for attr in facet.attrs:
						attribute(decl.path, f"{name}.{attr.name}")

	include(view)
	return selected


def _activeHandles(claims: list[Claim]) -> set[str]:
	handles: set[str] = set()
	for claim in claims:
		if "s" in claim:
			handles.add(claim["s"])
		if "ctx" in claim:
			handles.add(claim["ctx"])
		handles.update(handle for handle in claim.get("roles", {}).values() if handle != "?")
		value = claim.get("v")
		members = value.get("set", []) if isinstance(value, dict) and "set" in value else [value]
		handles.update(member["ref"] for member in members if isinstance(member, dict) and "ref" in member)
	return handles


def _status(value: Any) -> str:
	if value is None:
		return "absent"
	if isinstance(value, dict):
		if "unknown" in value:
			return "unknown"
		if "set" in value and not value["set"]:
			return "unknown" if value.get("partial") else "absent"
	return "supplied"

# -----------------------------------------------------------------------------
#
# API
#
# -----------------------------------------------------------------------------


def observationsCoverage(ontology: Ontology, observations: Observations, view: str, mode: str = "strict") -> list[CoverageItem]:
	"""Report reconciled per-instance coverage of `view` (full or namespace-relative path)."""
	model = Model(ontology)
	target = model.get(view) or model.get(f"{ontology.namespace}/{view}")
	if target is None or target.kind != "view":
		diag = Diagnostics()
		diag.error("reference", f"Unknown view '{view}'")
		diag.check()
	state = reconcileObservations(ontology, observations, mode)
	handles = _activeHandles(state.claims)

	def compatible(handle: str, path: str) -> bool:
		actual = state.instances[handle]["type"]
		return actual == path or model.isA(actual, path)

	items: list[CoverageItem] = []
	# ponytail: scan claims per requested slot; index subject/context pairs if coverage on large logs is slow.
	for selection in _selections(model, target):
		owner = model.get(selection.owner)
		path = selection.owner + (f"[{selection.member}]" if selection.facet else f".{selection.member}" if selection.member else "")
		# Binary existence is one profile-level request, including anonymous instances.
		binary = owner.arrow is not None and not selection.member
		attr = model.lookup(selection.owner, selection.member) if selection.member and not selection.facet else None
		structure = model.structOf(attr.type) is not None if attr else False
		subjects = [None] if binary else sorted(handle for handle in handles if compatible(handle, selection.owner)) or [None]
		contexts = sorted(handle for handle in handles if compatible(handle, selection.contextType)) if selection.contextType else []
		for subject in subjects:
			for ctx in contexts or [None]:
				matches = []
				for claim in state.claims:
					if binary:
						if claim.get("rel") == selection.owner:
							matches.append(claim)
						continue
					if subject is None or claim.get("s") != subject or claim.get("ctx") != ctx:
						continue
					if selection.facet:
						if claim.get("facet") == selection.member or claim.get("p", "").startswith(selection.member + "."):
							matches.append(claim)
					elif selection.member:
						member = claim.get("p", "")
						if (
							member == selection.member
							or structure and member.startswith(selection.member + ".")
							or member and selection.member.startswith(member + ".") and claim.get("v") in (None, {"unknown": True})
						):
							matches.append(claim)
					elif claim.get("exists") or claim.get("rel") == selection.owner:
						matches.append(claim)
				statuses = {_status(claim["v"]) if selection.member and not selection.facet else "supplied" for claim in matches}
				items.append(CoverageItem(path, subject, ctx, tuple(status for status in STATUSES if status in (statuses or {"missing"})),
					any(claim.get("conflict", False) for claim in matches if not selection.facet or claim.get("facet") == selection.member),
					not selection.facet and any(isinstance(claim.get("v"), dict) and claim["v"].get("partial", False) for claim in matches)))
	return sorted(items, key=lambda item: (item.path, item.subject or "", item.ctx or ""))


# EOF
