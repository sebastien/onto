"""Module: ontology.operations — semantic validation, loading and ontology interchange."""

from __future__ import annotations

from collections.abc import Callable
from typing import (
	Any,
)
from ..text import (
	Annotations,
	Diagnostics,
	FormatError,
	Loc,
	Source,
	annotation,
	isName,
	isPath,
	lastSegment,
)
from .formatter import (
	_toJson,
	normaliseOntology,
	printOntology,
)
from .model import (
	ANNOTATION_PLACES,
	Arrow,
	Participant,
	arrowPath,
	LAYERINGS,
	Attr,
	Decl,
	IDENTIFIERS,
	MULTI,
	Model,
	Ontology,
	STATUSES,
	TypeExpr,
	ViewLine,
	_typeKey,
	isAssociation,
	isSymmetric,
)
from .parser import (
	_fromJson,
	parseOntology,
)

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def _checkAnnotations(model: Model, ann: Annotations, places: set[str], loc: Loc | None, diag: Diagnostics) -> None:
	for key, value in ann:
		allowed = ANNOTATION_PLACES.get(key, set())
		if key not in ANNOTATION_PLACES:
			diag.error("annotation", f"Unknown annotation '{key}'", loc)
		elif allowed is not None and not allowed & places:
			diag.error("annotation", f"'{key}' applies to {' or '.join(sorted(allowed))}, not here", loc)
		elif key == "kind" and value not in ("event", "state"):
			diag.error("annotation", "kind must be event or state", loc)
		elif key in ("status", "cards") and value not in STATUSES:
			diag.error("annotation", f"{key} must be stated, inferred or assumed", loc)
		elif key == "scale" and value not in ("1", "100", "?"):
			diag.error("annotation", "scale must be 1, 100 or ?", loc)
		elif key == "deps" and value != "candidate":
			diag.error("annotation", "deps must be candidate", loc)
		elif key == "elided" and not (isinstance(value, str) and value.isdigit()):
			diag.error("annotation", "elided must be a count", loc)
		elif key in ("key", "ordered", "hierarchical", "history") and value is not True:
			diag.error("annotation", f"{key} is a flag", loc)
		elif key == "id" and value not in IDENTIFIERS:
			diag.error("annotation", f"id must be {', '.join(IDENTIFIERS)}", loc)
		elif key in ("subjectRole", "objectRole") and not (isinstance(value, str) and isName(value)):
			diag.error("annotation", f"{key} must name a role", loc)
		elif key == "layer" and not (isinstance(value, str) and isName(value)):
			diag.error("annotation", "layer must be a name", loc)
		elif key == "default" and not isinstance(value, str):
			diag.error("annotation", "default needs a value", loc)
		elif key == "privacy":
			names = value.split("+") if isinstance(value, str) else []
			if not names or not all(isName(name) for name in names) or len(set(names)) != len(names):
				diag.error("annotation", "privacy must be distinct audience names joined with +", loc)
		elif key == "context" and not isAssociation(model.get(value if isinstance(value, str) else None)):
			diag.error("reference", f"context must name an n-ary relation: '{value}'", loc)
		elif key == "ctx":
			target = model.get(value if isinstance(value, str) else None)
			if not target or (target.kind != "entity" and not isAssociation(target)):
				diag.error("reference", f"ctx must name an entity or an n-ary relation: '{value}'", loc)


def _typeCycle(model: Model, type: TypeExpr | None) -> bool:
	"""True when following aliases and attribute reuse from `type` comes back to a visited type."""
	seen: set[str] = set()
	while type and type.path:
		key = _typeKey(type)
		if key in seen:
			return True
		seen.add(key)
		if type.attr:
			attr = model.lookup(type.path, type.attr)
			type = attr.type if attr else None
		else:
			decl = model.get(type.path)
			type = decl.definition if decl and decl.kind == "type" else None
	return False


def _checkType(model: Model, type: TypeExpr | None, ann: Annotations, loc: Loc | None, what: str, diag: Diagnostics) -> None:
	if type and type.values is not None:
		valid = isPath if annotation(ann, "hierarchical") is True else isName
		if not type.values or not all(valid(value) for value in type.values):
			diag.error("vocabulary", f"{what}: invalid vocabulary values", loc)
		if len(set(type.values)) != len(type.values):
			diag.error("vocabulary", f"{what}: duplicate vocabulary values", loc)
	for conflict in model.resolveType(type, ann).conflicts:
		diag.error("qualifier", f"{what}: {conflict}", loc)
	if not type or type.builtin or type.values is not None or type.unknown:
		return
	if _typeCycle(model, type):
		diag.error("cycle", f"{what}: type alias or attribute reuse cycle through '{_typeKey(type)}'", loc)
		return
	decl = model.get(type.path)
	if not decl:
		diag.error("reference", f"{what}: unknown '{type.path}'", loc)
	elif type.attr:
		if not model.lookup(type.path, type.attr):
			diag.error("reference", f"{what}: unknown attribute '{type.path}.{type.attr}'", loc)
	elif decl.kind not in ("type", "entity") and not isAssociation(decl):
		kind = "binary relation" if decl.arrow else decl.kind
		diag.error("reference", f"{what}: '{type.path}' is a {kind}, not a type, entity or association", loc)


def _checkDefault(model: Model, attr: Attr, what: str, diag: Diagnostics) -> None:
	"""A default on a closed vocabulary must be one of its values; other types are not checked."""
	default = next((value for key, value in attr.ann if key == "default"), None)
	if not isinstance(default, str):
		return
	if attr.derived:
		diag.error("annotation", f"{what}: a derived attribute has no default", attr.loc)
		return
	resolved = model.resolveType(attr.type, attr.ann)
	if resolved.kind == "vocab" and not resolved.open and default not in (resolved.values or []):
		diag.error("annotation", f"{what}: default '{default}' is not a value of its vocabulary", attr.loc)


def _checkAttrs(model: Model, owner: Decl, attrs: list[Attr], localNames: Callable[[], set[str]], diag: Diagnostics) -> None:
	names: set[str] = set()
	for attr in attrs:
		if attr.name in names:
			diag.error("duplicate", f"Duplicate attribute '{owner.path}.{attr.name}'", attr.loc)
		names.add(attr.name)
		_checkType(model, attr.type, attr.ann, attr.loc, f"{owner.path}.{attr.name}", diag)
		_checkAnnotations(model, attr.ann, placesOf(attr), attr.loc, diag)
		_checkDefault(model, attr, f"{owner.path}.{attr.name}", diag)
		for dep in attr.deps or []:
			if dep.local and dep.local not in localNames():
				diag.error("reference", f"Unknown dependency '{dep.local}' of '{owner.path}.{attr.name}'", attr.loc)
			if dep.path and not model.lookup(dep.path, dep.attr):
				diag.error("reference", f"Unknown dependency '{dep.path}.{dep.attr}'", attr.loc)


def _validateMap(model: Model, decl: Decl, diag: Diagnostics, targetModel: Model | None = None) -> None:
	def vocabulary(path: str, using: Model) -> set[str] | None:
		target = using.get(path)
		resolved = using.resolveType(TypeExpr(path=path)) if target and target.kind == "type" else None
		if not resolved or resolved.kind != "vocab":
			diag.error("reference", f"Map '{decl.path}': '{path}' is not a vocabulary type", decl.loc)
			return None
		return set(resolved.values or [])

	fromValues, toValues = vocabulary(decl.mapFrom, model), vocabulary(decl.mapTo, targetModel or model)
	pairs: set[tuple[str, str]] = set()
	for line in decl.mapLines:
		if fromValues is not None and line.fromValue not in fromValues:
			diag.error("reference", f"Unknown value '{line.fromValue}' of '{decl.mapFrom}'", line.loc)
		if toValues is not None and line.toValue not in toValues:
			diag.error("reference", f"Unknown value '{line.toValue}' of '{decl.mapTo}'", line.loc)
		pair = (line.fromValue, line.toValue)
		if pair in pairs:
			diag.error("duplicate", f"Duplicate map line '{line.fromValue} {line.toValue}'", line.loc)
		pairs.add(pair)


def _validateViewLine(model: Model, line: ViewLine, diag: Diagnostics) -> None:
	relations = viewRelations(model, line)
	if relations is not None:
		if not relations or line.facets is not None:
			name = line.path + (f".{line.member}" if line.member else "")
			diag.error("reference", f"View selects unknown binary relation '{name}'", line.loc)
		return
	decl = model.get(line.path)
	if not decl:
		diag.error("reference", f"View selects unknown '{line.path}'", line.loc)
		return
	if decl.kind == "view" and (line.facets is not None or line.member):
		diag.error("reference", f"View '{line.path}' is selected whole: no facets or members", line.loc)
		return
	if line.facets:
		if decl.kind != "entity" and not isAssociation(decl):
			diag.error("reference", f"Facets selected on '{line.path}', which is not an entity or association", line.loc)
			return
		if line.facets != "*":
			facets = model.facets(line.path)
			for name in line.facets:
				if name not in facets:
					diag.error("reference", f"Unknown facet '{name}' on '{line.path}'", line.loc)
	if line.member and not model.lookup(line.path, line.member):
		diag.error("reference", f"View selects unknown '{line.path}.{line.member}'", line.loc)
	if decl.kind not in ("entity", "relation", "view"):
		diag.error("reference", f"View cannot select {decl.kind} '{line.path}'", line.loc)


def _validateRelation(model: Model, decl: Decl, diag: Diagnostics) -> None:
	if len(decl.participants) < 2:
		diag.error("relation", f"Relation '{decl.path}' needs at least two participants", decl.loc)
	roles: set[str] = set()
	for participant in decl.participants:
		target = model.get(participant.type)
		if not target or (target.kind != "entity" and not isAssociation(target)):
			diag.error("reference", f"Participant of '{decl.path}' is not an entity or association: '{participant.type}'", decl.loc)
		if participant.role in roles:
			diag.error("duplicate", f"Duplicate role '{participant.role}' in '{decl.path}'", decl.loc)
		roles.add(participant.role)
	for attr in decl.attrs:
		if attr.name in roles:
			diag.error("collision", f"Attribute '{attr.name}' collides with a role of '{decl.path}'", attr.loc)
	context = model.get(annotation(decl.ann, "context"))
	contextRoles = {item.role: item for item in context.participants} if context else {}
	for index, key in enumerate(("subjectRole", "objectRole")):
		role = annotation(decl.ann, key)
		if role is None:
			continue
		participant = contextRoles.get(role)
		if not decl.arrow or not participant or not model.isA(decl.participants[index].type, participant.type):
			diag.error("reference", f"{key} '{role}' must select a compatible role on the relation context", decl.loc)
	subjectRole, objectRole = annotation(decl.ann, "subjectRole"), annotation(decl.ann, "objectRole")
	if subjectRole is not None and subjectRole == objectRole:
		shared = contextRoles.get(subjectRole)
		if not shared or shared.card not in MULTI:
			diag.error("reference", "A role selected for both subject and object must be multi-valued", decl.loc)
	_checkAttrs(model, decl, decl.attrs, lambda: roles | {attr.name for attr in decl.attrs}, diag)


def _checkViewCycles(model: Model, diag: Diagnostics) -> None:
	# NOTE: A view including itself, directly or through other views, selects nothing definite: an error.
	def includes(view: Decl) -> list[str]:
		return [line.path for line in view.viewLines if (target := model.get(line.path)) and target.kind == "view"]

	for view in (decl for decl in model.ontology.decls if decl.kind == "view"):
		pending, seen = includes(view), set()
		while pending:
			path = pending.pop()
			if path == view.path:
				diag.error("cycle", f"View '{view.path}' includes itself", view.loc)
				break
			if path not in seen:
				seen.add(path)
				pending += includes(model.index[path])


def _typeRefs(type: TypeExpr | None) -> list[str]:
	"""Declaration paths a type expression refers to: a named type, or the owner of a reused attribute."""
	return [type.path] if type and type.path else []


def _attrRefs(attrs: list[Attr] | None) -> list[tuple[str, Loc | None]]:
	"""Declaration paths attributes refer to, through their types and derived inputs."""
	refs: list[tuple[str, Loc | None]] = []
	for attr in attrs or []:
		refs += [(path, attr.loc) for path in _typeRefs(attr.type)]
		refs += [(dep.path, attr.loc) for dep in attr.deps or [] if dep.path]
	return refs


def _declRefs(decl: Decl) -> list[tuple[str, Loc | None]]:
	"""Declaration paths `decl` refers to. Vocabulary values, map line values and docs are not references."""
	refs: list[tuple[str, Loc | None]] = []
	if decl.kind == "type":
		refs += [(path, decl.loc) for path in _typeRefs(decl.definition)]
		refs += _attrRefs(decl.fields)
	elif decl.kind == "map":
		refs += [(path, decl.loc) for path in (decl.mapFrom, decl.mapTo) if path]
	else:
		refs += [(path, decl.loc) for path in (decl.base, decl.subject) if path]
		refs += [(participant.type, decl.loc) for participant in decl.participants]
		refs += [(value, decl.loc) for key, value in decl.ann if key in ("ctx", "context") and isinstance(value, str)]
		refs += _attrRefs(decl.attrs)
	return refs


def _checkLayering(model: Model, diag: Diagnostics) -> None:
	"""Under `layering=declared`, an element refers only to its own domain and the domains declared before it."""
	ontology = model.ontology
	layering = dict(ontology.header).get("layering")
	if layering is None:
		return
	if layering not in LAYERINGS:
		diag.error("header", f"Invalid layering '{layering}'", None)
		return
	# NOTE: The Meta domain (spec-01) is generated, refers to no other domain, and ranks first wherever it is declared.
	meta = f"{ontology.namespace}/Meta"
	domains = [decl for decl in ontology.decls if decl.kind == "domain" and decl.path != meta]
	files = {decl.loc.file for decl in domains if decl.loc}
	if len(files) > 1:
		diag.error("layering", "Under layering=declared, all @domain lines must be in one file: " + ", ".join(sorted(str(name) for name in files)), domains[-1].loc)
		return
	rank = {decl.path: index for index, decl in enumerate(domains)}
	if model.get(meta):
		rank[meta] = -1
	prefix = f"{ontology.namespace}/"

	def domainOf(path: str | None) -> str | None:
		if not path or not path.startswith(prefix):
			return None
		head = f"{prefix}{path[len(prefix):].split('/')[0].split('.')[0]}"
		return head if head in rank else None

	def later(*paths: str | None) -> str | None:
		known = [domain for domain in map(domainOf, paths) if domain]
		return max(known, key=rank.__getitem__) if known else None

	for decl in ontology.decls:
		if decl.kind in ("domain", "view"):
			continue
		# NOTE: A binary relation is contributed by the latest of its two ends and its context, whatever its `S.verb.T` path starts with.
		context = annotation(decl.ann, "context")
		ends = [item.type for item in decl.participants] + ([context] if isinstance(context, str) else [])
		own = later(*ends) if decl.kind == "relation" and decl.arrow else domainOf(decl.path)
		if not own:
			continue
		for path, loc in _declRefs(decl):
			target = domainOf(path)
			if target and rank[target] > rank[own]:
				diag.error(
					"layering",
					f"'{lastSegment(own)}' is declared before '{lastSegment(target)}': '{decl.path}' cannot refer to '{path}'",
					loc or decl.loc,
				)


def _validate(model: Model, diag: Diagnostics) -> None:
	ontology = model.ontology
	for decl in ontology.decls:
		_checkAnnotations(model, decl.ann, placesOf(decl), decl.loc, diag)
		if decl.kind == "type":
			_checkType(model, decl.definition, decl.ann, decl.loc, decl.path, diag)
			if decl.fields is not None:
				fieldNames = {item.name for item in decl.fields}
				_checkAttrs(model, decl, decl.fields, lambda names=fieldNames: names, diag)
		elif decl.kind == "entity":
			if decl.base:
				base = model.get(decl.base)
				if not base or base.kind != "entity":
					diag.error("reference", f"Base of '{decl.path}' is not an entity: '{decl.base}'", decl.loc)
				elif decl.path in model.lineage(decl.base):
					diag.error("cycle", f"Specialisation cycle through '{decl.path}'", decl.loc)
				else:
					inherited = model.entityAttrs(decl.base)
					for attr in decl.attrs:
						if attr.name in inherited:
							diag.error("duplicate", f"'{decl.path}.{attr.name}' redeclares an inherited attribute", attr.loc)
			_checkAttrs(model, decl, decl.attrs, lambda path=decl.path: set(model.entityAttrs(path)), diag)
			# NOTE: Facets of a base apply here too, so their names must not equal this entity's attributes.
			for attr in decl.attrs:
				facet = model.facets(decl.path).get(attr.name)
				if facet and facet.subject != decl.path:
					diag.error("collision", f"'{decl.path}.{attr.name}' collides with inherited facet '{facet.path}'", attr.loc)
		elif decl.kind == "facet":
			subject = model.get(decl.subject)
			if not subject or (subject.kind != "entity" and not isAssociation(subject)):
				diag.error("reference", f"Facet subject is not an entity or association: '{decl.subject}'", decl.loc)
				continue
			name = lastSegment(decl.path)
			if name in model.ownNames(decl.subject):
				diag.error("collision", f"Facet '{name}' collides with an attribute or role of '{decl.subject}'", decl.loc)
			clash = [
				other
				for path in model.lineage(decl.subject)
				for other in model.facetsOf(path)
				if other is not decl and lastSegment(other.path) == name
			]
			if clash:
				diag.error("collision", f"Facet name '{name}' is used twice on '{decl.subject}'", decl.loc)
			_checkAttrs(
				model, decl, decl.attrs,
				lambda facet=decl: {attr.name for attr in facet.attrs} | model.ownNames(facet.subject), diag,
			)
		elif decl.kind == "relation":
			_validateRelation(model, decl, diag)
		elif decl.kind == "view":
			for line in decl.viewLines:
				_validateViewLine(model, line, diag)
		elif decl.kind == "map":
			_validateMap(model, decl, diag)
	_checkViewCycles(model, diag)
	_checkLayering(model, diag)
	# NOTE: A verb read from an entity must identify one relation for any compatible object type.
	uses: list[tuple[str, str, str, Decl]] = []
	for decl in ontology.decls:
		if decl.kind != "relation" or not decl.arrow:
			continue
		subject, obj = decl.participants[0].type, decl.participants[1].type
		uses.append((subject, decl.arrow.verb, obj, decl))
		if decl.arrow.inverse and not isSymmetric(decl):
			uses.append((obj, decl.arrow.inverse, subject, decl))

	def related(a: str, b: str) -> bool:
		return model.isA(a, b) or model.isA(b, a)

	for i, (fromA, verbA, toA, declA) in enumerate(uses):
		for fromB, verbB, toB, declB in uses[i + 1 :]:
			if verbA == verbB and related(fromA, fromB) and related(toA, toB):
				diag.error(
					"collision",
					f"Verb '{verbA}' is ambiguous from '{fromA}' to '{toA}' ('{declA.path}', '{declB.path}')",
					declB.loc,
				)


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Operator:
	"""Operations sharing an ontology; functions remain available for one-off calls."""

	def __init__(self, ontology: Ontology):
		self.ontology = ontology

	def validate(self) -> Ontology:
		"""Validate the current ontology, rebuilding lookups if the AST changed."""
		return validateOntology(self.ontology)

	def normalise(self) -> Ontology:
		"""Return the canonical AST without replacing the context's ontology."""
		return normaliseOntology(self.ontology)

	def print(self) -> str:
		"""Normalize the current ontology and render canonical text."""
		return printOntology(self.normalise())

	def toJson(self, ids: dict[str, str] | None = None) -> dict[str, Any]:
		"""Export the ontology with its optional identity sidecar."""
		return ontologyToJson(self.ontology, ids)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def viewRelations(model: Model, line: ViewLine) -> list[Decl] | None:
	"""Find binary relations selected by `line`, or None for a non-binary selection."""
	if "." in line.path:
		decl = model.get(line.path)
		return [decl] if decl and decl.arrow else []
	if not line.member or not line.member[0].islower():
		return None
	return [decl for decl, _ in model.verbs(line.path, line.member)]


def placesOf(item: Decl | Attr) -> set[str]:
	"""Return annotation placement categories for declaration or attribute `item`."""
	if isinstance(item, Attr):
		places = {"attribute"}
		if item.derived:
			places.add("derived")
		if item.type and item.type.values is not None:
			places.add("vocabulary")
		return places
	places = {item.kind}
	if item.kind == "type" and item.definition and item.definition.values is not None:
		places.add("vocabulary")
	if item.arrow:
		places.add("binary")
	return places


def _expandHistory(ontology: Ontology, diag: Diagnostics) -> None:
	"""Add the change concept and relation of each `{history}` attribute to `ontology` (spec-01 "History")."""
	ontology.decls = [decl for decl in ontology.decls if not decl.generated]
	declared = {decl.path for decl in ontology.decls}
	defaultCard = dict(ontology.header).get("card", "?")
	generated: list[Decl] = []
	for owner in ontology.decls:
		if owner.kind not in ("entity", "facet", "relation") or (owner.kind == "relation" and owner.arrow):
			continue
		for attr in owner.attrs:
			if annotation(attr.ann, "history") is not True:
				continue
			if attr.derived or (attr.card or defaultCard) in MULTI:
				diag.error("history", f"'{owner.path}.{attr.name}' cannot keep a history: it is derived or multi-valued", attr.loc)
				continue
			path = f"{owner.path}/{attr.name}Change"
			if path in declared:
				diag.error("collision", f"'{path}' is generated by '{owner.path}.{attr.name} {{history}}' and cannot be declared", attr.loc)
				continue
			# NOTE: Relations do not start from facets: a facet's history hangs off its subject.
			subject = owner.subject if owner.kind == "facet" and owner.subject else owner.path
			layer = annotation(owner.ann, "layer")
			if layer is None and owner.kind == "facet":
				layer = next((annotation(item.ann, "layer") for item in ontology.decls if item.path == owner.subject), None)
			name = lastSegment(owner.path)
			generated.append(Decl(
				kind="entity", path=path, ann=[("layer", layer)] if isinstance(layer, str) else [],
				doc=f"{name} reaching a value of {attr.name}", loc=attr.loc, generated=True,
				attrs=[
					Attr(name=attr.name, card="1", type=attr.type, loc=attr.loc),
					Attr(name="OccurredDate", card="?", type=TypeExpr(builtin="Date"), doc="When the value was reached", loc=attr.loc),
					Attr(name="Reason", card="?", type=TypeExpr(builtin="Text"), doc="Why, as stated", loc=attr.loc),
				],
			))
			generated.append(Decl(
				kind="relation", path=arrowPath(subject, "hasChange", path), loc=attr.loc, generated=True,
				participants=[Participant(lastSegment(subject), None, subject), Participant(lastSegment(path), None, path)],
				arrow=Arrow("hasChange", "isChangeOf", "1:*"), doc=f"Values {name}.{attr.name} reached, with when and why",
			))
	ontology.decls += generated


def validateOntology(ontology: Ontology) -> Ontology:
	"""Validate references and structure of `ontology`, updating diagnostics or raising `FormatError`."""
	diag = Diagnostics(list(ontology.diagnostics))
	_expandHistory(ontology, diag)
	_validate(Model(ontology), diag)
	ontology.diagnostics = diag.check()
	return ontology


def loadOntology(sources: list[Source]) -> Ontology:
	"""Parse and validate `sources` as one ontology."""
	return validateOntology(parseOntology(sources))


def formatOntology(sources: list[Source]) -> str:
	"""Parse, validate and render `sources` in normal form."""
	return printOntology(normaliseOntology(loadOntology(sources)))


def ontologyToJson(ontology: Ontology, ids: dict[str, str] | None = None) -> dict[str, Any]:
	"""Export normalized `ontology`, overriding its identity sidecar with `ids` when supplied."""
	return _toJson(normaliseOntology(ontology), ids if ids is not None else ontology.ids)


def ontologyFromJson(data: Any, name: str = "ontology.json") -> Ontology:
	"""Load `data` through validated normal-form text, rejecting lossy JSON with location `name`."""
	loc = Loc(name, 0)

	def fail(message: str) -> FormatError:
		diag = Diagnostics()
		diag.error("json", message, loc)
		return FormatError(diag.items)

	try:
		read = _fromJson(data)
		validateOntology(read)
		normal = normaliseOntology(read)
		text = printOntology(normal)
		expected = _toJson(normal, None)
	except ValueError as error:
		raise fail(f"Invalid ontology JSON: {error}") from error
	ontology = loadOntology([Source(name, text)])
	if _toJson(normaliseOntology(ontology), None) != expected:
		raise fail("Ontology JSON does not round-trip through its text form")
	ontology.ids = read.ids
	return ontology


# EOF
