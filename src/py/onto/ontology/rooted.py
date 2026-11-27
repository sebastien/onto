"""Module: ontology.rooted — resolve rooted view declarations to typed populations and projection paths."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..text import annotation, isName, isPath
from .model import Decl, Model, RE_ATTR_PATH, ViewPopulation, isAssociation, unkeyed

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Field:
	"""A typed projection, filter member or traversable link."""

	owner: str
	member: str
	path: str
	other: str = ""  # Type of the referenced handle (binary links and association roles).
	relation: str = ""
	roles: tuple[str, ...] = ()
	# A link whose relation has a context: the association and its roles holding the owner and the other end.
	association: tuple[str, str, str] | None = None
	contextType: str = ""  # A contextual facet's member: the type of the instance its values hold within.


@dataclass(frozen=True, slots=True)
class Hop:
	"""Bind a population from its parent, or test a filter on a bound population."""

	parent: str
	population: str
	field: Field
	reverse: bool = False
	test: str | bool | None = None
	proves: str = ""
	contextPopulation: str = ""  # The population whose instance a contextual member's claims hold within.

	@property
	def ancestor(self) -> str | None:
		return self.test[1:] if isinstance(self.test, str) and self.test.startswith("@") else None

	@property
	def key(self) -> str:
		return self.population + ("?" if self.test is not None else "")


@dataclass(frozen=True, slots=True)
class Projection:
	"""A view field on a bound population, with its context population when required."""

	population: str
	field: Field
	contextPopulation: str = ""


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def memberMatches(member: str, asked: str) -> bool:
	member = unkeyed(member)
	return member == asked or member.startswith(asked + ".")


def linkContext(relation: Decl, roles: tuple[str, str]) -> tuple[str, str, str] | None:
	"""The association a relation's `context` names and its roles holding `roles`' participants, in order; none
	without both role selectors."""
	ann = dict(relation.ann)
	if not {"context", "subjectRole", "objectRole"} <= ann.keys():
		return None
	selectors = {p.role: ann[k] for p, k in zip(relation.participants, ("subjectRole", "objectRole"))}
	return ann["context"], selectors[roles[0]], selectors[roles[1]]


def fieldFor(model: Model, owner: str, member: str, *, target: str | None = None, endpoint: str = "") -> Field:
	"""Resolve a member, respecting a selected binary endpoint or a traversal's narrowed destination."""
	short = lambda p: p.removeprefix(f"{model.ontology.namespace}/")
	path = f"{short(owner)}.{member}" + (f".{short(target)}" if target else "")
	if not RE_ATTR_PATH.fullmatch(member):
		raise ValueError(f"invalid field {path}")
	if member and member[0].islower():
		found = [(r, inv) for r, inv in model.verbs(owner, member)
			if (not target or r.participants[int(not inv)].type == target)
			and (not endpoint or model.isA(endpoint, r.participants[int(not inv)].type))]
		if len(found) != 1:
			raise ValueError(f"expected one directed relation at {path}")
		r, inverse = found[0]
		a, b = r.participants[::-1] if inverse else r.participants
		if not target and len(model.verbs(owner, member)) > 1:
			path += "." + short(b.type)
		return Field(owner, member, path, b.type, r.path, (a.role, b.role), linkContext(r, (a.role, b.role)))
	attr = model.lookup(owner, member)
	if not attr or target:
		raise ValueError(f"unknown view field {path}")
	kind = model.resolveType(attr.type, attr.ann)
	facet = model.facetOf(owner, member)
	return Field(owner, member, path, kind.path if kind.kind in ("entity", "relation") else "",
		contextType=(annotation(facet.ann, "ctx") or "") if facet else "")


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class RootedView:
	"""Resolve one declaration to typed hops, filters and explicitly selected leaves."""

	def __init__(self, model: Model, decl: Decl):
		param = decl.viewInput
		if not param or not (isName(param.name) and isPath(param.path) and isName(param.attr)) or not decl.viewPopulations or not decl.viewLines:
			raise ValueError("a rooted view needs a named source key, a root population and projected fields")
		self.input, self.root = param, decl.viewPopulations[0].name
		self.populations: dict[str, ViewPopulation] = {}
		self.paths: dict[str, tuple[Hop, ...]] = {}
		self.guardedLinks = {}
		dependencies = set()

		def resolveField(owner, member, **options):
			f = fieldFor(model, owner, member, **options)
			if relation := model.get(f.relation):
				dependencies.update(p.type for p in relation.participants)
				dependencies.add(annotation(relation.ann, "context"))
			else:
				facet = model.facetOf(owner, member)
				if facet:
					dependencies.update((facet.path, annotation(facet.ann, "ctx")))
				else:
					first = member.partition(".")[0]
					dependencies.update(p for p in model.lineage(owner) if any(a.name == first for a in model.get(p).attrs))
				# Each component may introduce a value type from another domain (e.g. Person.Name.Given).
				parts = member.split(".")
				for end in range(1, len(parts) + 1):
					attr = model.lookup(owner, ".".join(parts[:end]))
					if attr and attr.type and attr.type.path:
						dependencies.add(attr.type.path)
			return f

		def bound(path: tuple[Hop, ...]) -> list[str]:
			"""The populations a path binds, from the root."""
			return [self.root, *(h.population for h in path if h.test is None)]

		def contextIn(f: Field, before: list[str]) -> str:
			"""The population whose instance a contextual member holds within: the nearest of its type bound before its subject."""
			if not f.contextType:
				return ""
			found = next((alias for alias in reversed(before) if model.isA(self.populations[alias].type, f.contextType)), None)
			if found is None:
				raise ValueError(f"{f.path} holds within a {f.contextType.removeprefix(model.ontology.namespace + '/')}: expected a population of that type before it")
			return found

		def bind(population: ViewPopulation, path: tuple[Hop, ...]) -> None:
			t = model.get(population.type)
			if not t or not (t.kind == "entity" or isAssociation(t)):
				raise ValueError(f"population {population.name} needs an entity or association type: {population.type}")
			if not isName(population.name) or population.name in self.populations:
				raise ValueError(f"invalid or repeated population {population.name}")
			self.populations[population.name], self.paths[population.name] = population, path
			dependencies.add(population.type)

		for i, population in enumerate(decl.viewPopulations):
			alias, kind, parent = population.name, population.type, population.parent
			if i == 0 and not parent:
				bind(population, ())
				continue
			if parent not in self.populations:
				raise ValueError(f"{alias}: expected a previously bound parent, got '{parent}'")
			parentType = self.populations[parent].type
			a, b = (kind, parentType) if population.reverse else (parentType, kind)
			field = resolveField(a, population.via, endpoint=b)
			if not field.other or not model.isA(b, field.other):
				raise ValueError(f"{alias}: {field.path} cannot reach {b}")
			path = self.paths[parent]
			if population.through:
				if not field.association:
					raise ValueError(f"{alias}: {field.path} needs a context with both role selectors")
				context, start, end = field.association
				if population.reverse:
					start, end = end, start
				if start == end:
					raise ValueError(f"{alias}: through requires distinct context roles")
				witness = ViewPopulation(population.through, context, parent, start, reverse=True)
				path += (Hop(parent, witness.name, replace(fieldFor(model, context, start), other=parentType), True),)
				bind(witness, path)
				path += (Hop(witness.name, alias, replace(fieldFor(model, context, end), other=kind), proves=field.path),)
			else:
				# The subject of a forward link is the parent, of a backward one the population it binds.
				before = bound(self.paths[parent]) if population.reverse else bound(self.paths[parent])[:-1]
				path += (Hop(parent, alias, replace(field, other=b), population.reverse, contextPopulation=contextIn(field, before)),)
			if population.where:
				f = resolveField(kind, population.where)
				test = population.equals
				guard = Hop(alias, alias, f, test=test, contextPopulation=contextIn(f, bound(path)[:-1]))
				if ancestor := guard.ancestor:
					if ancestor not in {h.parent for h in path} or not model.isA(self.populations[ancestor].type, f.other):
						raise ValueError(f"{alias}: expected a compatible ancestor for {test}")
				else:
					attr = model.lookup(kind, f.member)
					t = model.resolveType(attr.type, attr.ann) if attr else None
					if not t or not ((t.builtin == "Boolean" and type(test) is bool) or
						(isinstance(test, str) and (t.builtin == "Text" or t.kind == "vocab" and (t.open or test in t.values)))):
						raise ValueError(f"{alias}: incompatible filter {f.path}={test}")
				path += (guard,)
				if not population.reverse and field.relation:
					key = (parent, field.relation, field.roles)
					if key in self.guardedLinks:
						raise ValueError(f"ambiguous object filter on {field.path}")
					self.guardedLinks[key] = alias
			bind(population, path)
		self.selections: dict[str, Projection] = {}
		self.typeSelections: dict[str, list[str]] = {}
		defaultKeys = []
		for line in decl.viewLines:
			if line.path not in self.populations or not line.member:
				raise ValueError(f"unknown projected population or missing field: {line.path}")
			f = resolveField(self.populations[line.path].type, line.member, target=line.target)
			key = f"{line.path}.{f.member}"
			if key in self.selections:
				raise ValueError(f"duplicate or ambiguous projected field {key}")
			self.selections[key] = Projection(line.path, f, contextIn(f, bound(self.paths[line.path])[:-1]))
			self.typeSelections.setdefault(f.path, []).append(key)
			if not line.optional:
				defaultKeys.append(key)
		if not defaultKeys:
			raise ValueError("a rooted view needs at least one default projection")
		self.defaults = {}
		for key in defaultKeys:
			path = self.selections[key].field.path
			# NOTE: Preserve a type-based display name only if it resolves to this projection.
			spelling = path if path not in self.selections and self.typeSelections[path] == [key] else key
			self.defaults[spelling] = key
		self.targetModules = sorted({model.moduleOf(p) for p in dependencies if isinstance(p, str)})

	def select(self, fields: list[str] | None) -> dict[str, str]:
		"""Resolve selectors to declared projections, preferring exact population names."""
		if fields is None:
			return dict(self.defaults)
		if not fields:
			raise ValueError("select at least one field declared by this view")
		result = {}
		for spelling in fields:
			if spelling in self.selections:
				result[spelling] = spelling
				continue
			keys = self.typeSelections.get(spelling, [])
			if not keys:
				raise ValueError(f"unknown view field '{spelling}'")
			if len(keys) > 1:
				raise ValueError(f"ambiguous view field '{spelling}'; select one of {', '.join(keys)}")
			result[spelling] = keys[0]
		return result


__all__ = ["RootedView", "Field", "Hop", "Projection", "memberMatches"]

# EOF
