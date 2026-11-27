"""Module: integrations.hexa.catalogue — declared reads and the prerequisite graph a rooted view can use."""

from __future__ import annotations

from dataclasses import dataclass

from ...binding.model import Binding
from ...conditions import conditionFromJson, parseCondition, testValues
from ...ontology.model import Model, ViewInput
from ...ontology.rooted import Field, RootedView, fieldFor
from ...text import annotation, isPath
from .compiler import isMulti

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class ViewRead:
	"""A catalogue read with a source key, bindings and an optional key its output discovers.

	`request` is the effect template and `source` its provenance template; without a request the host fetches it.
	`selects` records the source rows' known attribute values, e.g. `{"Exchange/Listing": "Venue:XNYS"}`.
	`via` restricts key discovery to views that follow the named link or when that link is a composition.
	"""

	input: ViewInput
	bindings: list[Binding]
	provides: ViewInput | None = None
	request: dict | None = None
	source: str | None = None
	selects: dict[str, str | dict] | None = None
	via: str | None = None

	@property
	def key(self) -> str:
		return self.input.key


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


def readSelection(model: Model, selects: dict[str, str | dict]) -> dict[tuple[str, str], frozenset[str]]:
	"""What a read selects as `{(source type, member): allowed values}`."""
	fixed = {}
	for kind, condition in selects.items():
		decl = model.get(kind)
		if decl is None or decl.kind != "entity":
			raise ValueError(f"a read selects the rows of a source entity, not {kind}")
		parsed = parseCondition(condition, binding=False) if isinstance(condition, str) else conditionFromJson(condition, binding=False)
		for test in parsed["all"] if "all" in parsed else [parsed]:
			steps = test.get("path", [])
			member = ".".join(steps) if steps and all(isinstance(step, str) for step in steps) else ""
			if not member or not testValues(test) or model.lookup(kind, member) is None:
				raise ValueError(f"{kind}: a read selects rows by values of their own attributes, joined by &")
			if any((attr := model.lookup(kind, ".".join(steps[:end]))) and isMulti(model, attr) for end in range(1, len(steps) + 1)):
				raise ValueError(f"{kind}: a read selects by single-valued attributes, not {member}")
			if (kind, member) in fixed:
				raise ValueError(f"{kind}: a read selects {member} once")
			fixed[kind, member] = frozenset(testValues(test))
	return fixed


def readLink(model: Model, inputTargets: dict[str, set[str]], step: str, read: ViewRead) -> Field:
	"""Resolve the binary link from the read's input to the key it discovers."""
	owner, _, spelling = read.via.partition(".")
	member, colon, target = (part.strip() for part in spelling.partition(":"))

	def endMatches(key: str, end: str) -> bool:
		return any(model.isA(kind, end) or model.isA(end, kind) for kind in inputTargets[key])

	try:
		if read.provides is None:
			raise ValueError("a link discovers a provided key")
		if colon and not isPath(target):
			raise ValueError("a link qualifier must be a target type path")
		verbs = model.verbs(owner, member)
		if not colon and len(verbs) > 1:
			ends = {relation.participants[int(not inverse)].type for relation, inverse in verbs}
			fitting = [end for end in ends if endMatches(read.provides.key, end)]
			if len(fitting) == 1:
				target, = fitting
			elif len(fitting) > 1:
				raise ValueError("expected one directed relation; qualify the link with ': Target/Type'")
		link = fieldFor(model, owner, member, target=target or None)
		if not link.relation or not model.get(link.relation).arrow:
			raise ValueError("a link is a binary relation")
		for key, end in ((read.key, link.owner), (read.provides.key, link.other)):
			if not endMatches(key, end):
				raise ValueError(f"does not lead from {read.input.path} to {read.provides.path}")
	except ValueError as error:
		raise ValueError(f"{step}: via {read.via}: {error}") from None
	return link


def planReadSteps(model: Model, view: RootedView, reads: dict[str, ViewRead], links: dict[str, Field]) -> dict:
	"""Order the catalogue reachable along the view's links and compositions, or from unrestricted providers."""
	seedKey = view.input.key
	hops = {hop for path in view.paths.values() for hop in path if hop.test is None}
	followedRelations = {hop.field.relation for hop in hops if hop.field.relation}
	# An association can prove a link when the view follows both selected roles.
	followedRoles = {(a.field.owner, a.field.member, b.field.member) for a in hops for b in hops
		if a.reverse and not b.reverse and b.parent == a.population and a.field.owner == b.field.owner}

	def admits(link: Field | None) -> bool:
		if link is None or link.relation in followedRelations or annotation(model.get(link.relation).ann, "part"):
			return True
		if link.association:
			association, start, end = link.association
			return link.association in followedRoles or (association, end, start) in followedRoles
		return False

	providers, steps = {seedKey: None}, {}
	while ready := [(name, read) for name, read in reads.items() if name not in steps and read.key in providers]:
		for name, read in ready:
			parent = providers[read.key]
			steps[name] = {"requires": [parent] if parent else [], "capability": name}
			if read.provides and (key := read.provides.key) != seedKey and admits(links.get(name)):
				if key in providers:
					raise ValueError(f"ambiguous providers of {key}: {providers[key]}, {name}")
				providers[key] = name
	return steps


__all__ = ["ViewRead", "readSelection", "readLink", "planReadSteps"]

# EOF
