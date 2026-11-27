"""Module: coverage — observation coverage of views (spec-02) and the static coverage of bindings and mappings (spec-04)."""

from __future__ import annotations

from dataclasses import dataclass

from .observations import Observations, reconcileObservations
from .observations.model import activeHandles, observationStatus
from .ontology import Decl, Model, Ontology, viewRelations
from .ontology.model import unkeyed
from .ontology.rooted import RootedView
from .text import Diagnostics, annotation, lastSegment

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


STATUSES = ("supplied", "unknown", "absent", "missing")
# NOTE: Static (spec-04) statuses, strongest first: a source read several ways reports its strongest reads.
LINE_STATUSES = ("direct", "transformed", "condition", "ambiguous")
TABLE_HEADER = "source\ttarget\tstatus\tnote"


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
class CoverageRow:
	"""One line of a coverage table: a source element or field, what it feeds and how (spec-04)."""

	source: str
	target: str | None
	status: str
	note: str | None = None


@dataclass(slots=True)
class CoverageReport:
	"""Static coverage: `rows` by source, the elements no line assigns, and paths read but not inventoried."""

	rows: list[CoverageRow]
	unassigned: list[str]
	uninventoried: list[str]


@dataclass(slots=True, frozen=True)
class ViewSelection:
	owner: str
	member: str = ""
	facet: bool = False
	contextType: str | None = None


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def viewSelections(model: Model, view: Decl) -> set[ViewSelection]:
	"""Collect schema selections, not instances. A rooted view contributes its projected fields."""
	selected: set[ViewSelection] = set()
	visited: set[str] = set()

	def attribute(owner: str, member: str, seen: frozenset[str] = frozenset()) -> None:
		selected.add(ViewSelection(owner))
		attr = model.lookup(owner, member)
		struct = model.structOf(attr.type) if attr else None
		if struct and struct.fields and struct.path not in seen:
			for field in struct.fields:
				attribute(owner, f"{member}.{field.name}", seen | {struct.path})
		else:
			facet = model.facetOf(owner, member)
			context = annotation(facet.ann, "ctx") if facet else None
			selected.add(ViewSelection(owner, member, contextType=context))
			if facet:
				selected.add(ViewSelection(owner, lastSegment(facet.path), True, context))
				if context:
					selected.add(ViewSelection(context))

	def whole(decl: Decl) -> None:
		selected.add(ViewSelection(decl.path))
		attrs = model.entityAttrs(decl.path).values() if decl.kind == "entity" else decl.attrs
		for attr in attrs:
			attribute(decl.path, attr.name)
		if decl.kind == "relation":
			for participant in decl.participants:
				selected.add(ViewSelection(participant.type))
				if not decl.arrow:
					attribute(decl.path, participant.role)

	def include(current: Decl) -> None:
		if current.path in visited:
			return
		visited.add(current.path)
		if current.viewInput:
			rooted = RootedView(model, current)
			for projection in rooted.selections.values():
				f = projection.field
				if f.relation:
					whole(model.get(f.relation))
				else:
					attribute(f.owner, f.member)
			return
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
					selected.add(ViewSelection(decl.path, name, True, context))
					if context:
						selected.add(ViewSelection(context))
					for attr in facet.attrs:
						attribute(decl.path, f"{name}.{attr.name}")

	include(view)
	return selected


class Elements:
	"""Ontology elements of instance types, keyed by declaring path: `T.Attr`, `T.F.Attr`, `T[F]`, `T.verb`, `R.Role`."""

	def __init__(self, model: Model, namespace: str | None):
		self.model = model
		self.namespace = namespace

	def display(self, key: str) -> str:
		"""A key without its ontology's namespace prefix."""
		prefix = f"{self.namespace}/"
		return key[len(prefix):] if self.namespace and key.startswith(prefix) else key

	def instanceTypes(self) -> list[Decl]:
		"""Entities and identity-bearing relations, in declaration order."""
		return [decl for decl in self.model.ontology.decls if decl.kind == "entity" or decl.kind == "relation" and decl.arrow is None]

	def leaves(self, owner: str, member: str, seen: frozenset[str] = frozenset()) -> list[str]:
		attr = self.model.lookup(owner, member)
		structure = self.model.structOf(attr.type) if attr else None
		if not structure or not structure.fields or structure.path in seen:
			return [member]
		return [leaf for field in structure.fields for leaf in self.leaves(owner, f"{member}.{field.name}", seen | {structure.path})]

	def declared(self, path: str) -> list[str]:
		"""Elements declared on `path` itself (not inherited), structures as their leaves."""
		decl = self.model.get(path)
		keys = [f"{path}.{leaf}" for attr in decl.attrs if not attr.derived for leaf in self.leaves(path, attr.name)]
		if decl.kind == "relation":
			keys += [f"{path}.{participant.role}" for participant in decl.participants]
		for facet in self.model.facetsOf(path):
			name = lastSegment(facet.path)
			keys.append(f"{path}[{name}]")
			keys += [f"{path}.{leaf}" for attr in facet.attrs if not attr.derived for leaf in self.leaves(path, f"{name}.{attr.name}")]
		for relation in self.model.ontology.decls:
			if relation.kind == "relation" and relation.arrow and relation.participants[0].type == path:
				keys.append(f"{path}.{relation.arrow.verb}")
		return keys

	def owner(self, path: str, name: str) -> str:
		"""The type in `path`'s lineage declaring attribute or facet `name`."""
		for entity in self.model.lineage(path):
			decl = self.model.get(entity)
			if any(attr.name == name for attr in decl.attrs) or any(lastSegment(facet.path) == name for facet in self.model.facetsOf(entity)):
				return entity
		return path

	def verb(self, path: str, verb: str) -> tuple[str, str] | None:
		"""The element key of a binary verb read from `path`, and the type it leads to."""
		for relation, inverse in self.model.verbs(path, verb):
			subject, other = relation.participants[0].type, relation.participants[1].type
			return f"{subject}.{relation.arrow.verb}", subject if inverse else other
		return None

	def read(self, path: str, steps: list[str]) -> list[str]:
		"""Elements read by attribute `steps` from an instance of `path`, through references."""
		keys: list[str] = []
		current, index = path, 0
		while index < len(steps) and current:
			name = steps[index]
			facet = self.model.facetOf(current, name)
			if facet is not None and index + 1 < len(steps):
				member, index = f"{name}.{steps[index + 1]}", index + 2
			elif self.model.lookup(current, name):
				member, index = name, index + 1
			elif found := self.verb(current, name):
				keys.append(found[0])
				current, index = found[1], index + 1
				continue
			else:
				break
			attr = self.model.lookup(current, member)
			while index < len(steps) and self.model.structOf(attr.type if attr else None):
				member, index = f"{member}.{steps[index]}", index + 1
				attr = self.model.lookup(current, member)
			keys.append(f"{self.owner(current, member.split('.')[0])}.{member}")
			resolved = self.model.resolveType(attr.type, attr.ann) if attr else None
			current = resolved.path if resolved and resolved.kind in ("entity", "relation") else None
		return keys

	def assigned(self, path: str, target: str | None = None, facet: str | None = None, verb: str | None = None) -> str | None:
		"""The element a line of a scope of type `path` assigns."""
		if facet:
			return f"{self.owner(path, facet)}[{facet}]"
		if verb:
			found = self.verb(path, verb)
			return found[0] if found else None
		if target:
			target = unkeyed(target)  # `Phones[Mobile].Number` assigns the field `Phones.Number`
			return f"{self.owner(path, target.split('.')[0])}.{target}"
		return None


def impliedKeyFields(model: Model, path: str, target: str) -> list[str]:
	"""The key fields named by `target`, e.g. `Phones[Mobile].Number` implies `Phones.Use`."""
	result = []
	parts = target.split(".")
	for index, part in enumerate(parts):
		if "[" not in part:
			continue
		prefix = unkeyed(".".join(parts[:index + 1]))
		field = model.elementKey(model.lookup(path, prefix))
		if field is not None:
			result.append(f"{prefix}.{field.name}")
	return result


def impliedKeys(elements: Elements, path: str, target: str | None) -> list[str]:
	"""The declaring elements of the key fields a keyed target assigns."""
	return [f"{elements.owner(path, member.split('.')[0])}.{member}"
		for member in impliedKeyFields(elements.model, path, target or "")]


def coverageRows(keys: list[str], reads: dict[str, list[tuple[str | None, str, str | None]]], excluded: dict[str, tuple[str, str | None]]) -> list[CoverageRow]:
	"""One status per source: its strongest reads, else its exclusion, else `unmapped`."""
	rows: list[CoverageRow] = []
	for key in keys:
		found = reads.get(key, [])
		strongest = min((LINE_STATUSES.index(status) for _, status, _ in found), default=None)
		if strongest is None:
			reason, doc = excluded.get(key, ("unmapped", None))
			rows.append(CoverageRow(key, None, reason, doc))
			continue
		chosen = [item for item in found if item[1] in LINE_STATUSES[:2]] if strongest < 2 else [item for item in found if LINE_STATUSES.index(item[1]) == strongest]
		if LINE_STATUSES[strongest] == "condition":
			chosen = [(None, "condition", None)]
		seen: set[tuple[str | None, str]] = set()
		for target, status, note in sorted(chosen, key=lambda item: (item[0] or "", LINE_STATUSES.index(item[1]))):
			if (target, status) not in seen:
				seen.add((target, status))
				rows.append(CoverageRow(key, target, status, note))
	return rows


def printCoverageTable(rows: list[CoverageRow]) -> str:
	"""The tab-separated coverage table of spec-04, sorted by source path."""
	lines = [TABLE_HEADER] + [
		"\t".join([row.source, row.target or "", row.status] + ([row.note] if row.note else []))
		for row in sorted(rows, key=lambda item: (item.source, item.target or ""))
	]
	return "\n".join(lines) + "\n"


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def observationsCoverage(ontology: Ontology, observations: Observations, view: str, mode: str = "strict") -> list[CoverageItem]:
	"""Report reconciled per-instance coverage of a flat `view` (full or namespace-relative path)."""
	model = Model(ontology)
	target = model.get(view) or model.get(f"{ontology.namespace}/{view}")
	diag = Diagnostics()
	if target is None or target.kind != "view":
		diag.error("reference", f"Unknown view '{view}'")
	elif target.viewInput:
		diag.error("view", f"Rooted view '{target.path}' requires a seed; use HexaViewOperator.report for rooted coverage")
	diag.check()
	state = reconcileObservations(ontology, observations, mode)
	handles = activeHandles(state.claims)
	claims = []
	for claim in state.claims:
		member = claim.get("p", "")
		keyFields = impliedKeyFields(model, state.instances[claim["s"]]["type"], member) if "[" in member else []
		claims.append((claim, unkeyed(member), keyFields))

	def compatible(handle: str, path: str) -> bool:
		actual = state.instances[handle]["type"]
		return actual == path or model.isA(actual, path)

	items: list[CoverageItem] = []
	# ponytail: scan claims per requested slot; index subject/context pairs if coverage on large logs is slow.
	for selection in viewSelections(model, target):
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
				implied = False
				for claim, member, keyFields in claims:
					if binary:
						if claim.get("rel") == selection.owner:
							matches.append(claim)
						continue
					if subject is None or claim.get("s") != subject or claim.get("ctx") != ctx:
						continue
					if selection.facet:
						if claim.get("facet") == selection.member or member.startswith(selection.member + "."):
							matches.append(claim)
					elif selection.member:
						if selection.member in keyFields:
							implied = True
							continue
						selectedMember = (
							member == selection.member
							or structure and member.startswith(selection.member + ".")
							or member and selection.member.startswith(member + ".") and observationStatus(claim.get("v")) != "supplied"
						)
						if selectedMember:
							matches.append(claim)
					elif claim.get("exists") or claim.get("rel") == selection.owner:
						matches.append(claim)
				statuses = {observationStatus(claim["v"]) if selection.member and not selection.facet else "supplied" for claim in matches}
				if implied:
					statuses.add("supplied")
				items.append(CoverageItem(
					path=path,
					subject=subject,
					ctx=ctx,
					statuses=tuple(status for status in STATUSES if status in (statuses or {"missing"})),
					conflict=any(claim.get("conflict", False) for claim in matches if not selection.facet or claim.get("facet") == selection.member),
					partial=not selection.facet and any(isinstance(claim.get("v"), dict) and claim["v"].get("partial", False) for claim in matches),
				))
	return sorted(items, key=lambda item: (item.path, item.subject or "", item.ctx or ""))


# EOF
