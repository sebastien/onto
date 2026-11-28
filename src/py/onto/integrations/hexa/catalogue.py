"""Module: integrations.hexa.catalogue — declared reads and the prerequisite graph a rooted view can use."""

from __future__ import annotations

from dataclasses import dataclass, field

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


# NOTE: A list read's parameters (spec-09 "List reads"), each filling one `{name}` placeholder of its request.

LIST_OPERATORS = ("eq", "in", "exists", "contains")


@dataclass(slots=True, frozen=True)
class ListFilter:
	"""A filter on a source attribute of the rows, with the operator the endpoint applies (`contains`: in part)."""

	attr: str
	operator: str


@dataclass(slots=True, frozen=True)
class ListKeys:
	"""The rows' keys to `include` or to `exclude`, at most `limit` of them."""

	mode: str
	limit: int


@dataclass(slots=True, frozen=True)
class ListSort:
	"""The source attributes the endpoint sorts by, with its spelling of each; `default`, the attribute it sorts by,
	ascending, when a query gives no sort, for an endpoint that requires one (DEC0038)."""

	spellings: dict[str, str]
	default: str | None = None


@dataclass(slots=True, frozen=True)
class ListDirection:
	"""The values the endpoint takes for an ascending and a descending sort (DEC0038)."""

	asc: object
	desc: object


@dataclass(slots=True, frozen=True)
class ListSearch:
	"""A text the endpoint matches across its rows, as it does: their names, numbers or any field (DEC0038)."""


@dataclass(slots=True, frozen=True)
class ListPage:
	"""The page `size`, or the page `number`, counted from `first`."""

	part: str
	first: int = 0


@dataclass(slots=True)
class ListRead:
	"""A system's list endpoint (spec-09 "List reads"): the source type of its rows, the bindings that read them, a
	request template with a placeholder per parameter, and where the response gives the number of matching rows.
	`absent` is how a request carries a parameter a query leaves out: its members are left out (`omit`), or are `null`
	(`null`) for an endpoint that requires every member (DEC0038).

	A view operator sets `input`, the rows' key, which a list view's parameter names."""

	rows: str
	bindings: list[Binding]
	request: dict
	parameters: dict[str, ListFilter | ListKeys | ListSort | ListDirection | ListPage | ListSearch]
	total: str | None = None
	absent: str = "omit"
	input: ViewInput | None = field(default=None, init=False)
	provides: ViewInput | None = field(default=None, init=False)
	source: str | None = field(default=None, init=False)
	selects: dict | None = field(default=None, init=False)
	via: str | None = field(default=None, init=False)

	@property
	def key(self) -> str:
		return self.input.key

	def bound(self, model: Model) -> ListRead:
		"""A copy whose `input` is the rows' key, after checking its parameters against the rows' type."""
		keys = [name for name, attr in model.entityAttrs(self.rows).items() if annotation(attr.ann, "key") is True] if model.get(self.rows) else []
		if len(keys) != 1:
			raise ValueError(f"the rows of a list read are of a source type with one {{key}} attribute, not {self.rows}")
		kinds: dict[type, list[str]] = {}
		for name, parameter in self.parameters.items():
			kinds.setdefault(type(parameter), []).append(name)
			attrs = [parameter.attr] if isinstance(parameter, ListFilter) else list(parameter.spellings) if isinstance(parameter, ListSort) else []
			if isinstance(parameter, ListSort) and parameter.default is not None and parameter.default not in parameter.spellings:
				raise ValueError(f"{name}: a list sort's default is one of its attributes")
			if isinstance(parameter, ListFilter) and parameter.operator not in LIST_OPERATORS:
				raise ValueError(f"{name}: a list filter's operator is one of {', '.join(LIST_OPERATORS)}")
			if isinstance(parameter, ListPage) and parameter.part not in ("number", "size"):
				raise ValueError(f"{name}: a list page parameter is its number or its size")
			for attr in attrs:
				if model.lookup(self.rows, attr) is None:
					raise ValueError(f"{name}: no attribute {attr} on {self.rows}")
		if len(kinds.get(ListSort, [])) > 1 or len(kinds.get(ListDirection, [])) > 1 or kinds.get(ListDirection) and not kinds.get(ListSort):
			raise ValueError("a list read has at most one sort parameter, and a direction only with it")
		if len(kinds.get(ListSearch, [])) > 1:
			raise ValueError("a list read has at most one search parameter")
		if self.absent not in ("omit", "null"):
			raise ValueError("a list read's absent parameters are left out (omit) or null")
		parts = [parameter.part for parameter in self.parameters.values() if isinstance(parameter, ListPage)]
		if len(parts) != len(set(parts)):
			raise ValueError("a list read has at most one page number and one page size")
		read = ListRead(self.rows, self.bindings, self.request, self.parameters, self.total, self.absent)
		read.input = ViewInput("query", self.rows, keys[0], many=True)
		return read


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

	lists = {name for name, read in reads.items() if isinstance(read, ListRead)}
	# NOTE: A list view's list read is its first read, and provides the keys its rows' reads take (DEC0038).
	first = [name for name in lists if reads[name].key == seedKey] if view.many else []
	if len(first) > 1:
		raise ValueError(f"several list reads of {view.input.path}: {', '.join(sorted(first))}")
	providers, steps = {seedKey: first[0] if first else None}, {name: {"requires": [], "capability": name} for name in first}
	while ready := [(name, read) for name, read in reads.items() if name not in steps and name not in lists and read.key in providers]:
		for name, read in ready:
			parent = providers[read.key]
			steps[name] = {"requires": [parent] if parent else [], "capability": name}
			if read.provides and (key := read.provides.key) != seedKey and admits(links.get(name)):
				if key in providers:
					raise ValueError(f"ambiguous providers of {key}: {providers[key]}, {name}")
				providers[key] = name
	return steps


__all__ = ["LIST_OPERATORS", "ListDirection", "ListFilter", "ListKeys", "ListPage", "ListRead", "ListSearch", "ListSort", "ViewRead", "planReadSteps", "readLink",
	"readSelection"]

# EOF
