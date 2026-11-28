"""Module: integrations.hexa.views — plan and retrieve a declared rooted view over a host read catalogue.

A retrieval is one hexa run. A read with a request template is a `RequestSend` effect (an HTTP request, see
`hexa.http`); any other read is a `DocumentFetch` effect answered by the host. Effects are journaled and
replayable, and the reads whose input is known run concurrently.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import cached_property
from hashlib import sha256
import inspect
import json
from math import isfinite
import re

from hexa.combinators import parallel, pipe, plan, validate
from hexa.core import REGISTRY, member
from hexa.runtime import run
from hexa.shapes import Failure, SelectionRequest, codes, profile
from ...conditions import conditionOutcome, conditionPaths
from ...mapping.model import Mapping, MappingLine, MappingScope
from ...mapping.operations import acceptedTypes, correspondenceScopes, correspondenceTarget, namedCorrespondenceScope
from ...observations.model import Observations, activeHandles, observationStatus
from ...observations.operations import mergeObservationLogs, observationsFromJson, observationsToJson, reconcileObservations, sourceToken
from ...observations.rooted import Evidence, Witness, conflicted, inContext, roleValidity
from ...ontology.model import Model, ViewInput, isSymmetric, unkeyed
from ...ontology.rooted import Field, Hop, RootedView, fieldFor, memberMatches
from ...text import FormatError, isName, isPath
from ...mapping.reversal import Lossy, Reverser
from .catalogue import ListDirection, ListFilter, ListPage, ListRead, ListSearch, ListSort, ViewRead, planReadSteps, readLink, readSelection
from .compiler import SELF, MappingCompiler
from .operations import HexaBindingOperator, HexaMappingOperator
from .requests import checkListRequest, checkRequest, listRequestFor, requestFor, requestSource, requestTemplate

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class ViewDocument:
	"""One fetched document, its provenance, and collections/keys the source establishes as empty."""

	document: dict
	source: str
	emptyTypes: tuple[str, ...] = ()
	emptyInputs: tuple[str, ...] = ()


class ViewReadError(ValueError):
	"""A source-specific read outcome to record in the report: the read fails with the code `ViewRead.<reason>`."""

	reason = "UnreadableResponse"


RE_REASON = re.compile(r"[A-Za-z][A-Za-z0-9]*")
codes("ViewRead", "UnreadableResponse")


@dataclass(slots=True)
class ReadOutcome:
	"""Scope a read's status and empty collections to the concrete input that was fetched; `failure` says why it is unavailable."""

	handles: set[str]
	status: str
	emptyTypes: tuple[str, ...] = ()
	failure: BaseException | None = None


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def writesViewField(model: Model, scope: MappingScope, line: MappingLine, field: Field) -> bool:
	"""Whether this mapping line writes the directed relation or member of a view field."""
	if not field.relation:
		return bool(line.target and model.isA(scope.target, field.owner) and memberMatches(line.target, field.member))
	for relation, inverse in model.verbs(scope.target, line.verb) if line.verb else ():
		if relation.path == field.relation:
			role = relation.participants[int(inverse)].role
			return model.isA(scope.target, field.owner if role == field.roles[0] else field.other)
	return False


def segmentNeeds(segment) -> set[tuple[str, str]]:
	"""The source rows and members a read supplies for one path step: a lookup needs the rows it looks up and the compared
	attributes of both types (spec-04 Lookups)."""
	if segment.kind == "lookup":
		lookup = segment.lookup
		return {(lookup.type, "")} | {(lookup.type, unkeyed(line.attr)) for line in lookup.lines} | {(segment.owner, unkeyed(line.source)) for line in lookup.lines}
	return {(segment.owner, unkeyed(segment.key))}


def lineValues(reader, line) -> frozenset | None:
	"""The values a mapping line can give, as a filter compares them: a literal's own, a value map's targets; None for any."""
	expr = line.expr
	if expr is None:
		return None
	for kind in ("text", "number", "boolean"):
		if kind in expr:
			return frozenset([expr[kind]])
	if "call" in expr and len(expr["args"]) == 1 and (decl := reader.owner.calls.evaluator.maps.get(expr["call"])) is not None:
		return frozenset(item.toValue for item in decl.mapLines if item.toValue is not None)
	return None


def readCode(reason: object):
	"""The code of a read unavailable for `reason`: `ViewRead.<reason>`, or `ViewRead.UnreadableResponse`; declared on first use."""
	name = "ViewRead." + (reason if isinstance(reason, str) and RE_REASON.fullmatch(reason) else "UnreadableResponse")
	return REGISTRY[name] if name in REGISTRY else member(name)


def readReason(error: BaseException) -> str:
	"""How a report names a failed read: a `ViewReadError` or `ViewRead` code by its reason, another hexa code
	(a failed request, say) by its qualified name, anything else as `UnreadableResponse`."""
	if isinstance(error, ViewReadError):
		return error.reason if isinstance(error.reason, str) and RE_REASON.fullmatch(error.reason) else "UnreadableResponse"
	if not isinstance(error, Failure) or error.kind not in (Failure.Effect, Failure.Contract):
		return "UnreadableResponse"
	return str(error.code).removeprefix("ViewRead.")


def readDetail(error: BaseException) -> dict:
	"""The message of a failed read, as a report gives it to help resolve the failure: a hexa failure's host cause
	(spelled as its journal records it), or the error itself; none when there is no message."""
	cause = error.__cause__ if isinstance(error, Failure) else error
	return {} if cause is None else {"detail": str(cause) or type(cause).__name__}


def readClassify(error: BaseException) -> dict:
	"""`FailureClassify` for reads: a `ViewReadError` fails with its reason's code, any other error as unreadable."""
	return {"code": readCode(error.reason if isinstance(error, ViewReadError) else None), "transient": getattr(error, "transient", False) is True}


def documentDict(document: ViewDocument) -> dict:
	return {"document": document.document, "source": document.source, "emptyTypes": list(document.emptyTypes), "emptyInputs": list(document.emptyInputs)}


def documentFetch(fetch):
	"""The `DocumentFetch` operation over a host `fetch`; what it raises is classified by `readClassify`."""
	async def DocumentFetch(step, value, context):
		response = fetch(step, value)
		if inspect.isawaitable(response):
			response = await response
		return documentDict(response)
	return DocumentFetch


def keyValue(value: object, builtin: str | None) -> object:
	"""A claim value as a key value: canonical decimal text is a JSON number for numeric keys."""
	if isinstance(value, str) and builtin in ("Integer", "Number"):
		try:
			number = Decimal(value)
		except InvalidOperation:
			return value
		return int(number) if builtin == "Integer" or number == number.to_integral_value() else float(number)
	return value


def responseValue(data: object, path: str) -> object:
	"""The value at a dotted path of a response, or None."""
	for step in path.split("."):
		data = data.get(step) if isinstance(data, dict) else None
	return data


def readWaves(steps: list[str], providers: dict[str, str | None]) -> dict[str, int]:
	"""Each planned read's wave: 0 without a provider, one more than its provider's otherwise."""
	waves = {}
	for name in steps:
		provider = providers[name]
		waves[name] = waves[provider] + 1 if provider else 0
	return waves


def describeHop(hop: Hop) -> dict:
	"""Render a planned traversal or filter for the diagnostic path."""
	if hop.test is not None:
		return {"on": hop.population, "where": hop.field.path, "equals": hop.test}
	return {"from": hop.parent, "bind": hop.population, "via": hop.field.path, "reverse": hop.reverse,
		**({"proves": hop.proves} if hop.proves else {})}


def describeWitness(state: Observations, witness: Witness) -> dict:
	"""Render observed path evidence without exposing its internal claim object."""
	hop = witness.hop
	data = {"from": witness.subject, "source": sourceToken(state, witness.claim),
		**describeAssociation(witness.claim, witness.subjectRoleClaim)}
	if hop.test is not None:
		return {**data, "where": hop.field.path, "value": witness.value}
	return {**data, "via": hop.field.path, "to": witness.value,
		**({"reverse": True} if hop.reverse else {}), **({"proves": hop.proves} if hop.proves else {})}


def describeAssociation(claim: dict, subjectRoleClaim: dict | None) -> dict:
	"""The association witnessing a link and the validity both role claims support."""
	if subjectRoleClaim is None:
		return {}
	valid = roleValidity(claim, subjectRoleClaim)
	return {"through": claim["s"], **({"valid": valid} if valid else {})}


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class HexaViewOperator:
	"""Discover rooted views in the mapping target. `access` supplies only source-wide I/O and identity.

	`operations` are hexa host operations for every run: `RequestSend` for reads with a request template (e.g. from
	`hexa.http.http`), and optionally `FailureClassify`.
	"""

	def __init__(self, mapper: HexaMappingOperator, mapping: Mapping, reads: dict[str, ViewRead], access, operations: dict | None = None,
		lists: dict[str, ListRead] | None = None):
		self.source, self.target = mapper.fromOntology, mapper.toOntology
		self.sourceModel, self.targetModel = Model(self.source), Model(self.target)
		# NOTE: List reads join the catalogue, keyed by their rows' key, for the list views whose parameter names it.
		bound = {}
		for step, read in (lists or {}).items():
			if step in reads:
				raise ValueError(f"{step}: a list read and a read share the name")
			try:
				bound[step] = read.bound(self.sourceModel)
				checkListRequest(step, bound[step])
			except ValueError as error:
				raise ValueError(f"{step}: {error}") from None
		reads = {**reads, **bound}
		self.mapper, self.mapping, self.reads, self.access, self.operations = mapper, mapping, reads, access, dict(operations or {})
		self.rowValues = {}  # Per step, the values its request leaves the attributes it selects rows by.
		for step, read in reads.items():
			if not isinstance(read, ListRead):
				checkRequest(step, read)
			if read.request is None and not callable(getattr(access, "fetch", None)):
				raise ValueError(f"{step}: a read without a request template needs the host's fetch")
			try:
				self.rowValues[step] = readSelection(self.sourceModel, read.selects or {})
			except ValueError as error:
				raise ValueError(f"{step}: {error}") from None
		self.scopes = MappingCompiler(self.source, self.target, mapping, mapper.referential, mapper.libraries, mapper.implementations, mapper.ontologies).compile()
		self.binder = HexaBindingOperator(self.source, mode=mapper.mode, libraries=mapper.libraries, implementations=mapper.implementations, ontologies=mapper.ontologies)
		self.footprints, self.programs = {}, {}
		for step, read in reads.items():
			# NOTE: A binding on a specialisation also supplies inherited mapping slots.
			self.footprints[step] = {(kind, member)
				for binding in read.bindings for scope in binding.scopes
				for kind in self.sourceModel.lineage(scope.type)
				for member in ("", *(unkeyed(line.target or line.verb) for line in scope.lines if line.target or line.verb))}
		self.views = {d.path.removeprefix(self.target.namespace + "/"): RootedView(self.targetModel, d)
			for d in self.target.decls if d.viewInput}
		keys = {k for r in reads.values() for k in (r.input, r.provides) if k} | {view.input for view in self.views.values()}
		self.keyTypes = {k.key: k.resolve(self.sourceModel) for k in keys}
		self.inputTargets = {k.key: {s.target for s in correspondenceScopes(self.sourceModel, mapping, k.path)} for k in keys}
		self.rootTargets = {}
		for name, view in self.views.items():
			root = view.populations[view.root].type
			target = correspondenceTarget(self.sourceModel, self.targetModel, mapping, view.input.path, [root])
			if not target or not self.targetModel.isA(target, root):
				raise ValueError(f"{name}: no root correspondence from {view.input.key} to {root}")
			self.rootTargets[name] = target
		links = {step: readLink(self.targetModel, self.inputTargets, step, read) for step, read in reads.items() if read.via is not None}
		self.steps = {}
		for name, view in self.views.items():
			try:
				self.steps[name] = planReadSteps(self.targetModel, view, self.reads, links)
			except ValueError as error:
				raise ValueError(f"{name}: {error}") from None
		# Each list view's list read, and the query table compiled from it (DEC0038).
		self.listQueries = {name: self.listQuery(name, view, step) for name, view in self.views.items() if view.many
			for step in self.steps[name] if isinstance(self.reads[step], ListRead)}

	# -- List views ---------------------------------------------------------------

	def listQuery(self, name: str, view: RootedView, step: str) -> dict:
		"""What a list view's queries may use (spec-09 "Key queries"): its list read, each root field a filter of the list
		read takes, by operator, with the values a value map's line reverses; the fields it sorts by, with its spellings;
		and its sort, direction and page parameters."""
		read = self.reads[step]
		table = {"read": step, "filters": {}, "sorts": {}}
		spellings = {key: spelling for spelling, key in view.defaults.items()}
		page = {}
		for parameter, item in read.parameters.items():
			if isinstance(item, ListSort):
				table["sort"] = parameter
				if item.default is not None:
					table["sortDefault"] = item.spellings[item.default]
			elif isinstance(item, ListDirection):
				table["direction"] = parameter
			elif isinstance(item, ListSearch):
				table["search"] = parameter
			elif isinstance(item, ListPage):
				page[item.part] = parameter
				if item.part == "number":
					page["first"] = item.first
		if page:
			table["page"] = page
		reverser = Reverser(self.mapping, self.source, self.target, self.mapper.libraries)
		scopes = [scope for scope in correspondenceScopes(self.sourceModel, self.mapping, read.rows)
			if scope.target == self.rootTargets[name] or self.targetModel.isA(self.rootTargets[name], scope.target)]
		for key, projection in view.selections.items():
			field = projection.field
			if projection.population != view.root or field.relation:
				continue
			line = next((line for scope in scopes for line in scope.lines if line.target and unkeyed(line.target) == field.member and line.when is None), None)
			source, values = self.lineSource(reverser, line.expr if line else None)
			if source is None:
				continue
			spelling = spellings.get(key, key)
			for parameter, item in read.parameters.items():
				if isinstance(item, ListFilter) and item.attr == source and not (values is not None and item.operator == "contains"):
					table["filters"].setdefault(spelling, {})[item.operator] = {"parameter": parameter, **({"values": values} if values is not None else {})}
				elif isinstance(item, ListSort) and source in item.spellings and values is None:
					table["sorts"][spelling] = item.spellings[source]
		return table

	def lineSource(self, reverser: Reverser, expr: dict | None) -> tuple[str | None, dict | None]:
		"""The source attribute a mapping line reads, and for a value map's line, each target value's source value; none
		for a line that does not reverse so (spec-04 Reversal)."""
		values = None
		if expr is not None and "call" in expr and expr["call"] in reverser.maps and len(expr["args"]) == 1:
			try:
				reverser.reverseMap(expr["call"])
			except Lossy:
				return None, None
			values = {line.toValue: line.fromValue for line in reverser.maps[expr["call"]].mapLines}
			expr = expr["args"][0]
		steps = expr.get("path") if isinstance(expr, dict) else None
		if not steps or not all(isinstance(step, str) for step in steps):
			return None, None
		return ".".join(steps), values

	def compileQuery(self, view: str, query: object) -> dict:
		"""A list view's query as its list read's parameters, with the page it asks for (spec-09 "Key queries")."""
		rooted, table = self.views[view], self.listQueries.get(view)
		if table is None:
			raise ValueError(f"{view}: no list read of {rooted.input.path}")
		if not isinstance(query, dict) or set(query) - {"filter", "search", "sort", "page"}:
			raise ValueError(f"{view}: a query is {{filter?, search?, sort?, page?}}")
		parameters, stored, modes = {}, [], set()
		search = query.get("search")
		if search is not None and not isinstance(search, str):
			raise ValueError(f"{view}: a search is text")
		if search:
			if "search" not in table:
				raise ValueError(f"Session.Unsearchable: {view}'s list read takes no search")
			parameters[table["search"]] = search
		filter = query.get("filter")
		predicates = [] if filter is None else filter["and"] if isinstance(filter, dict) and set(filter) == {"and"} else [filter]
		for predicate in predicates:
			if isinstance(predicate, dict) and set(predicate) == {"not"}:
				# NOTE: A store-held predicate under `not` excludes the keys an index finds (spec-09 "Key queries").
				stored.append(self.storePredicate(view, table, predicate["not"]))
				modes.add("exclude")
				continue
			if isinstance(predicate, dict) and predicate.get("field") in table.get("stores", {}):
				stored.append(self.storePredicate(view, table, predicate))
				modes.add("include")
				continue
			operators = [key for key in predicate if key != "field"] if isinstance(predicate, dict) else []
			if len(operators) != 1 or not isinstance(predicate.get("field"), str):
				raise ValueError(f"{view}: a predicate is {{field, eq|in|exists|contains}}")
			operator, value = operators[0], predicate[operators[0]]
			entry = table["filters"].get(predicate["field"], {}).get(operator)
			if entry is None:
				raise ValueError(f"Session.Unfilterable: {view} cannot filter {predicate['field']} by {operator}")
			if "values" in entry:
				items = value if operator == "in" else [value]
				if any(not isinstance(item, str) or item not in entry["values"] for item in items):
					raise ValueError(f"Session.Unfilterable: {predicate['field']} has no source value for {value!r}")
				value = [entry["values"][item] for item in items] if operator == "in" else entry["values"][value]
			parameters[entry["parameter"]] = value
		sort = query.get("sort") or []
		if not isinstance(sort, list) or len(sort) > 1:
			raise ValueError(f"Session.Unsortable: {view} sorts by one field")
		if not sort and "sortDefault" in table:
			parameters[table["sort"]] = table["sortDefault"]
			if "direction" in table:
				parameters[table["direction"]] = self.reads[table["read"]].parameters[table["direction"]].asc
		for item in sort:
			spelling = table["sorts"].get(item.get("field")) if isinstance(item, dict) else None
			direction = item.get("direction", "asc") if isinstance(item, dict) else None
			if spelling is None or direction not in ("asc", "desc"):
				raise ValueError(f"Session.Unsortable: {view} cannot sort by {item!r}")
			parameters[table["sort"]] = spelling
			if "direction" in table:
				parameters[table["direction"]] = getattr(self.reads[table["read"]].parameters[table["direction"]], direction)
		page = query.get("page") or {}
		limit = rooted.max or 100
		size, number = page.get("size", rooted.page or limit), page.get("number", 1)
		if type(size) is not int or type(number) is not int or size < 1 or number < 1:
			raise ValueError(f"{view}: a page has a number from 1 and a positive size")
		if size > limit:
			raise ValueError(f"Session.PageTooLarge: {view} reads at most {limit} rows a page")
		if "number" in table.get("page", {}):
			parameters[table["page"]["number"]] = number - 1 + table["page"]["first"]
		if "size" in table.get("page", {}):
			parameters[table["page"]["size"]] = size
		compiled = {"parameters": parameters, "page": {"number": number, "size": size}}
		if stored:
			indexes = {index for index, _ in stored}
			keys = table.get("keys", {}).get(next(iter(modes))) if len(modes) == 1 else None
			if len(indexes) > 1 or keys is None:
				raise ValueError(f"Session.Unfilterable: {view} filters its store-held fields with one index, all included or all excluded")
			filters = [item for _, item in stored]
			compiled["keys"] = {"index": next(iter(indexes)), "filter": filters[0] if len(filters) == 1 else {"and": filters},
				"mode": next(iter(modes)), **keys}
		return compiled

	@staticmethod
	def storePredicate(view: str, table: dict, predicate: object) -> tuple[str, dict]:
		"""A predicate on a store-held field as its index's filter: `eq`, `in`, or `exists` (spec-08 "Indexes")."""
		entry = table.get("stores", {}).get(predicate.get("field")) if isinstance(predicate, dict) else None
		operators = [key for key in predicate if key != "field"] if isinstance(predicate, dict) else []
		if entry is None or len(operators) != 1 or operators[0] not in ("eq", "in", "exists") or operators[0] == "exists" and predicate["exists"] is not True:
			raise ValueError(f"Session.Unfilterable: {view} cannot filter {predicate!r} through an index")
		operator = operators[0]
		return entry["index"], {"exists": entry["column"]} if operator == "exists" else {operator: [entry["column"], predicate[operator]]}

	@cached_property
	def mapProgram(self):
		return self.mapper.compile(self.mapping)

	def refutes(self, step: str, conditions: tuple) -> bool:
		"""Whether the rows a read selects fail one of a mapping line's `(reader, condition)` conditions."""
		fixed = self.rowValues.get(step)
		if not fixed:
			return False
		for reader, condition in conditions:
			def known(steps: list, reader=reader) -> frozenset[str] | None:
				segments = [] if steps == SELF else reader.segments(steps)
				last = segments[-1] if segments else None
				if last is None or not last.owner:
					return None
				return next((values for (kind, member), values in fixed.items()
					if member == last.key and self.sourceModel.isA(last.owner, kind)), None)
			if conditionOutcome(condition, known) is False:
				return True
		return False

	def correspondences(self, view: RootedView, steps: dict) -> dict:
		"""Follow mapping correspondences from the seed to select a read for each population field."""
		fields = {projection.field for projection in view.selections.values()} | {h.field for path in view.paths.values() for h in path}
		# A link whose relation has a context can also be written by both roles of the same mapped association.
		roleFields = {f: tuple(fieldFor(self.targetModel, f.association[0], role) for role in f.association[1:])
			for f in fields if f.association and f.association[1] != f.association[2]}
		associationFields = {role for pair in roleFields.values() for role in pair}
		written = fields | associationFields
		inputs = defaultdict(list)
		# Per field, each line's subject row type and the values it can give (None: any), for population filters.
		produces = defaultdict(list)
		# Named scopes can mint separate association handles even when their source and target types match.
		rolesWritten = defaultdict(lambda: defaultdict(list))
		for reader in self.scopes:
			scope = reader.scope
			guards = [scope.into, scope.present, scope.ctx, scope.valid]
			# An update scope supplies claims on the referenced instance, not on the update row itself.
			subjectType = reader.exprType(scope.into).path if scope.into else scope.source
			origins = [scope]
			if scope.into and associationFields:
				origins = [origin for origin in correspondenceScopes(self.sourceModel, self.mapping, subjectType) if origin.target == scope.target]
			for line in scope.lines:
				if line.candidate:
					continue
				matches = [f for f in written if writesViewField(self.targetModel, scope, line, f)]
				if not matches:
					continue
				objectType, dest = None, None
				if any(f.other for f in matches):
					kind = reader.exprType(line.expr)
					objectType = kind.path if kind and kind.kind in ("entity", "relation") else None
					dest = line.asType
					if self.mapping.isTargetType(objectType):
						dest, objectType = objectType, None  # No source row stands behind an already-target reference.
					elif not dest and objectType:
						attr = self.targetModel.lookup(scope.target, line.target) if line.target else None
						accepted = acceptedTypes(self.targetModel, scope.target, line.target or line.verb, attr)
						# `{name=N}`: the target type of the scope it names, where several fit the receiver
						dest = (namedCorrespondenceScope(reader.source, self.targetModel, self.mapping, objectType, line.name, accepted).target if line.name
							else correspondenceTarget(reader.source, self.targetModel, self.mapping, objectType, accepted))
					matches = [f for f in matches if dest and self.targetModel.isA(dest, f.owner if line.verb and line.verb != f.member else f.other)]
				conditions = tuple((reader, condition) for condition in (scope.when, line.when) if condition)
				paths = [path for expr in [*guards, line.expr, *line.qualifiers.values()] for path in reader.paths(expr)]
				paths += [path for _, condition in conditions for path in conditionPaths(condition) if path != SELF]
				required = {(scope.source, "")} | {need for path in paths for part in reader.segments(path) for need in segmentNeeds(part)}
				for f in matches:
					a, b = (objectType, subjectType) if line.verb and line.verb != f.member else (subjectType, objectType)
					if f in fields:
						inputs[f].append((a, b, required, conditions))
						produces[f].append((subjectType, lineValues(reader, line)))
					if f in associationFields:
						for origin in origins:
							rolesWritten[id(origin)][f].append((objectType, dest, required | {(origin.source, "")}, conditions))
		for f, (owner, other) in roleFields.items():
			directions = [(owner, other)]
			if isSymmetric(self.targetModel.get(f.relation)):
				directions.append((other, owner))
			for roles in rolesWritten.values():
				for start, end in directions:
					inputs[f].extend((a, b, ra | rb, ca + cb)
						for a, ta, ra, ca in roles.get(start, ()) if self.targetModel.isA(ta, f.owner)
						for b, tb, rb, cb in roles.get(end, ()) if self.targetModel.isA(tb, f.other))

		matches = {}
		def supplies(step, candidates):
			return any(deps <= self.footprints[step] and not self.refutes(step, conditions) for _, _, deps, conditions in candidates)

		def keyedBy(step: str, type: str) -> bool:
			"""Whether a read's input corresponds to instances of `type`: the read of a group for a group's rows."""
			return any(self.targetModel.isA(target, type) or self.targetModel.isA(type, target) for target in self.inputTargets[self.reads[step].key])

		def register(key, candidates, rows=None, parent=None):
			"""Choose the first read supplying the obligation: the reads keyed as the read of its rows (`rows`) first, or
			for rows reached backwards, the reads keyed by their parent population's type (`parent`)."""
			order = sorted(steps, key=lambda s: rows is not None and self.reads[s].key != self.reads[rows].key
				or parent is not None and not keyedBy(s, parent))
			supplier = next((s for s in order if supplies(s, candidates)), None)
			matches[key] = [{"resolved": True, "supplier": supplier}] if candidates else []
			return supplier

		# A shared target type need not have the same source rows in two populations, nor the same read: rows reached
		# backwards are those of the read stating their link. A read keyed otherwise reads other rows (notes filed under
		# another key), and failing, would hide these rows' facts; among reads of their key, catalogue order decides.
		# A population's filters narrow its rows to the types a line can give the tested value (`passing`), before the read
		# of its link is chosen: rows that cannot pass the filter do not decide which read gives the population its rows.
		rowTypes = {view.root: set(self.sourceModel.lineage(view.input.path))}
		rowReads = {view.root: None}
		for alias, path in view.paths.items():
			filters = [h for h in path if h.population == alias and h.test is not None]
			for hop in (h for h in path if h.population == alias):
				candidates = inputs[hop.field]
				if hop.test is None:
					candidates = [c for c in candidates if c[int(hop.reverse)] in rowTypes[hop.parent]]
					passing = self.passing({c[int(not hop.reverse)] for c in candidates}, filters, produces)
					candidates = [c for c in candidates if c[int(not hop.reverse)] in passing]
					rowTypes[alias] = passing
					# NOTE: Rows reached backwards are filed under their parent: a read of another key states their link
					# only for the rows it happens to read (spec-06 Rooted retrieval).
					supplier = register(hop.key, candidates, None if hop.reverse else rowReads[hop.parent],
						view.populations[hop.parent].type if hop.reverse else None)
					rowReads[alias] = supplier if hop.reverse else None
				else:
					candidates = [c for c in candidates if c[0] in rowTypes[alias] and (
						not hop.ancestor or c[1] in rowTypes[hop.ancestor])]
					register(hop.key, candidates, rowReads[alias])
		for key, projection in view.selections.items():
			alias = projection.population
			register(key, [c for c in inputs[projection.field] if c[0] in rowTypes[alias]], rowReads[alias])
		return matches

	def passing(self, types: set, filters: list, produces: dict) -> set:
		"""The row types some line of which can give each value filter's tested value (spec-06 Rooted retrieval).

		A filter tests a value exactly, and missing evidence cannot satisfy it: a type no line writes the member for, or
		whose lines give only other values, cannot pass. Ancestor tests are not values."""
		for hop in filters:
			if hop.ancestor or not isinstance(hop.test, (str, bool)):
				continue
			lines = produces.get(hop.field, ())
			types = {t for t in types if t is None or any((t == a or self.sourceModel.isA(t, a)) and (values is None or hop.test in values)
				for a, values in lines)}
		return types

	def checkValue(self, param: ViewInput, value) -> None:
		"""Check the concrete JSON argument against its declared source key before using it for a read."""
		t = self.keyTypes[param.key]
		if t.builtin == "Integer":
			ok = type(value) is int
		elif t.builtin == "Number":
			ok = type(value) is int or type(value) is float and isfinite(value)
		elif t.kind == "vocab":
			ok = isinstance(value, str) and (isPath if t.hierarchical else isName)(value) and (t.open or value in t.values)
		else:
			ok = isinstance(value, str)
		if not ok:
			raise ValueError(f"{param.name} requires {t.builtin or t.path or 'a vocabulary value'} for {param.key}")

	async def plan(self, view: str, seed: dict, fields: list[str] | None = None) -> dict:
		"""Plan the required reads for a view without fetching documents."""
		rooted = self.views[view]
		param = rooted.input
		if set(seed) != {param.name}:
			raise ValueError(f"{view} requires {param.name}: {param.key}")
		value = seed[param.name]
		kind = rooted.populations[rooted.root].type
		if rooted.many:
			# NOTE: A list view's seed is its query; its roots are known once its list read answers (DEC0038).
			value, handle = self.compileQuery(view, value), None
		else:
			self.checkValue(param, value)
			handle = self.access.rootHandle(param, value, self.rootTargets[view])
		wanted = rooted.select(fields)
		steps = self.steps[view]
		matches = self.correspondences(rooted, steps)
		supplier = {key: entries[0]["supplier"] if entries else None for key, entries in matches.items()}
		dependents, paths, outputs = defaultdict(list), {}, {}
		for spelling, key in wanted.items():
			projection = rooted.selections[key]
			alias, f = projection.population, projection.field
			child = rooted.guardedLinks.get((alias, f.relation, f.roles))
			chain = rooted.paths[child or alias]
			paths[spelling] = {"population": alias, "hops": [{**describeHop(h), "supplier": supplier[h.key]} for h in chain], "leaf": f.path}
			if child:
				paths[spelling]["objectPopulation"] = child
			outputs[spelling] = supplier[key]
			# NOTE: Onto orders the proof. Hexa schedules each obligation up to and including the first static gap.
			for obligation, at in [*((h.key, h.field.path) for h in chain), (key, f.path)]:
				dependents[obligation].append((spelling, at))
				if supplier[obligation] is None:
					break
		obligations = list(dependents)
		attributes = {key: {"correspondences": entries} for key, entries in matches.items()}
		options = {"versions": [1], "entitySets": {"Proof": list(attributes)}, "relations": [], "maxSelections": 1, "maxRelations": 0}
		caller = profile("OntoView" + sha256(json.dumps(options, sort_keys=True).encode()).hexdigest(), requests={SelectionRequest: options})
		catalog = {"steps": steps, "entitySets": {"Proof": {"type": kind, "attributes": attributes}}}
		env = {"policy": {"profile": caller, "allow": list(steps)}, "vocabulary": {"SelectionRequest": catalog}}
		request = {"version": 1, "selections": {"Proof": {"from": "Proof", "attributes": obligations}}}
		compiled = await run(env, pipe(validate(SelectionRequest), plan(SelectionRequest)), request)
		reads = []
		for item in compiled["steps"]:
			name = item["step"]
			read = self.reads[name]
			own = isinstance(read, ListRead) or read.key == param.key and not rooted.many
			description = {"step": name, "input": read.input.name, "requires": steps[name]["requires"], "bindings": [b.header.get("name", b.ontology) for b in read.bindings],
				**self.describeRead(name, value if own else "{" + read.input.name + "}")}
			reads.append(description)
		gaps = []
		for gap in compiled["gaps"]:
			index = gap["path"][-1]
			for spelling, at in dependents[obligations[index]]:
				gaps.append({"field": spelling, "reason": gap["code"], "stoppedAt": at})
				outputs[spelling] = None
		return {"format": "onto.view-plan/1", "view": view, "seed": dict(seed),
			"root": {"role": rooted.root, "type": kind.removeprefix(self.target.namespace + "/"), "handle": handle},
			**({"query": value} if rooted.many else {}), "fields": outputs, "paths": paths, "steps": reads, "gaps": gaps}

	async def report(self, view: str, seed: dict, fields: list[str] | None = None, now: str | None = None, **options) -> dict:
		"""Explain the reads, proven answers and missing links as a diagnostic report; `options` as for `runReads`."""
		result, state, outcomes = await self.runReads(view, seed, fields, now, **options)
		result["format"] = "onto.view-report/1"
		result["facts"], result["coverage"] = self.project(state, result, outcomes)
		return result

	async def retrieve(self, view: str, seed: dict, fields: list[str] | None = None, now: str | None = None, **options) -> Observations:
		"""Return native observations: selected claims and the evidence that connects them to the seed; `options` as for `runReads`."""
		result, state, outcomes = await self.runReads(view, seed, fields, now, **options)
		selected = set()
		self.project(state, result, outcomes, selected)
		claims = [c for c in state.claims if id(c) in selected]
		handles = activeHandles(claims)
		sources = {c.get("src") for c in claims}
		header = {k: v for k, v in state.obs.items() if k in ("ontology", "rev", "scope")}
		header.update({k: str(claims[0][k]) for k in ("at", "by", "src", "conf") if claims and k in claims[0] and all(c.get(k) == claims[0][k] for c in claims)})
		return Observations(header, {k: v for k, v in state.sources.items() if k in sources},
			{h: {"type": item["type"]} for h, item in state.instances.items() if h in handles}, claims, [])

	async def runReads(self, view: str, seed: dict, fields: list[str] | None = None, now: str | None = None, *,
		fetch=None, operations: dict | None = None, record=None, replay: list | None = None, signal=None, policy: dict | None = None,
		planned: dict | None = None):
		"""Return the plan/receipts, reconciled state and read outcomes before rooted projection.

		One hexa run reads, binds and maps. A read with a request template is a `RequestSend` effect; another read is
		a `DocumentFetch(step, value)` effect answered by `fetch` (default `access.fetch`). Reads run in waves: a
		wave's effects are performed concurrently (`parallel`), each distinct request once, then its reads are
		checked, bound and accounted for in plan order. `now` fixes the clock; `operations` add to the operator's;
		`record` (a journal sink), `replay`, `signal` and `policy` (retry, concurrency) go to the run. A failed read
		is reported by reason and message; its outcome keeps the failure, and the journal a failed effect's details.
		`planned` is this view's plan when the caller has it, as a session does with its system's reads (spec-09).
		"""
		result = planned if planned is not None else await self.plan(view, seed, fields)
		param = self.views[view].input
		if "query" in result:
			seed = {param.name: result["query"]}
		steps = [step["step"] for step in result["steps"]]
		# NOTE: The view's provider of each key, not any earlier read discovering it: the view may not take it from that one.
		providers = {step["step"]: step["requires"][0] if step["requires"] else None for step in result["steps"]}
		waves = readWaves(steps, providers)
		# NOTE: A replayed journal may name host reasons this process has not declared yet.
		for entry in replay or ():
			code = entry.get("failure", {}).get("code") if isinstance(entry, dict) else None
			if isinstance(code, str) and code.startswith("ViewRead."):
				readCode(code.removeprefix("ViewRead."))
		now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
		env = {"FailureClassify": readClassify, **self.operations, **(operations or {}), "ClockRead": lambda context: now,
			"DocumentFetch": documentFetch(fetch or getattr(self.access, "fetch", None)), "policy": {"maxNodes": 500000, **(policy or {})},
			**{key: item for key, item in (("record", record), ("replay", replay), ("signal", signal)) if item is not None}}
		operator = self

		def ReadSend(env, effect):
			operation, *arguments = effect
			try:
				return {"status": "ok", "result": (yield getattr(env, operation)(*arguments))}
			except Failure as failure:
				if failure.kind is Failure.Defect:
					raise
				return {"status": "unavailable", "reason": readReason(failure), "failure": failure}
		send = parallel(ReadSend)

		def ViewRetrieve(env):
			values, outputs, sent = {}, {}, {}
			for wave in range(max(waves.values(), default=-1) + 1):
				names = [name for name in steps if waves[name] == wave]
				items, effects = [], {}
				for name in names:
					values[name] = operator.readValues(name, providers[name], param, seed, outputs)
					for value in values[name]:
						item = operator.readEffect(name, value)
						items.append((name, value, item))
						if "key" in item and item["key"] not in sent:
							effects.setdefault(item["key"], item["effect"])
				sent.update(zip(effects, (yield from send(env, list(effects.values()))) if effects else ()))
				for name in names:
					outputs[name] = []
				for name, value, item in items:
					outputs[name].append((yield from operator.readProcess(env, name, value, item, sent.get(item.get("key")))))
			logs = [log for name in steps for output in outputs[name] if output["status"] == "ok" for log in output["logs"]]
			mapped = (yield from operator.mapProgram.stages.MappingRead(env, operator.sourceState(logs))) if logs else None
			return values, outputs, mapped

		values, outputs, mapped = await run(env, ViewRetrieve)
		emptyInputs, calls, outcomes = set(), [], defaultdict(list)
		for name in steps:
			read = self.reads[name]
			if not values[name]:
				outcomes[name].append(ReadOutcome(set(), "empty" if read.key in emptyInputs else "unavailable"))
				if read.key not in emptyInputs:
					result["gaps"].append({"step": name, "reason": "MissingInput", "input": read.input.name})
			for value, output in zip(values[name], outputs[name]):
				if isinstance(read, ListRead):
					self.listRows(view, result, read, output)
				receipt = {"step": name, "input": {read.input.name: value}, **self.describeRead(name, value), "status": output["status"]}
				calls.append(receipt)
				result["gaps"].extend(output["gaps"])
				if output["status"] == "ok":
					emptyInputs.update(output["emptyInputs"])
					if read.provides:
						receipt["discovered"] = {read.provides.name: output["discovered"]}
				else:
					result["gaps"].append({"step": name, "input": receipt["input"], "reason": output["reason"], **readDetail(output["failure"])})
				keys = output.get("discovered", []) if isinstance(read, ListRead) else [value]
				handles = {self.access.rootHandle(read.input, key, kind) for key in keys for kind in self.inputTargets[read.key]}
				ok = output["status"] == "ok"
				outcomes[name].append(ReadOutcome(handles, output["status"], tuple(output["emptyTypes"]) if ok else (), None if ok else output["failure"]))
		state = Observations({"ontology": self.target.namespace, "scope": None}, {}, {}, [], [])
		if mapped is not None:
			log, report = self.mapper.result(self.mapProgram, mapped)
			result["gaps"].extend(asdict(g) for g in report.gaps)
			state = reconcileObservations(self.target, log, mode=self.mapper.mode)
		result["calls"] = calls
		if "query" in result and "rows" not in result:
			result.update(rows=[], total=None, page=result["query"]["page"], next=None)
		return result, state, outcomes

	def listRows(self, view: str, result: dict, read: ListRead, output: dict) -> None:
		"""A list page's rows in the list read's order, each with its key and root handle; the total the response gives;
		and the next page while more rows remain (spec-09 "Rows")."""
		page = result["query"]["page"]
		keys = output.get("discovered", []) if output["status"] == "ok" else []
		total = output.get("total") if output["status"] == "ok" else None
		more = page["number"] * page["size"] < total if isinstance(total, int) else len(keys) == page["size"]
		result.update(rows=[{"key": key, "handle": self.access.rootHandle(self.views[view].input, key, self.rootTargets[view])} for key in keys],
			total=total, page=page, next={"number": page["number"] + 1, "size": page["size"]} if more else None)

	def describeRead(self, name: str, value: object) -> dict:
		"""The host's description of a read, else its request (its template while the value is the placeholder `{name}`)."""
		if callable(describe := getattr(self.access, "describe", None)):
			return describe(name, value)
		read = self.reads[name]
		if read.request is None:
			return {}
		if isinstance(read, ListRead):
			return listRequestFor(read, value["parameters"])
		return requestTemplate(read) if value == "{" + read.input.name + "}" else requestFor(read, value)

	def readValues(self, name: str, provider: str | None, param: ViewInput, seed: dict, outputs: dict) -> list:
		"""A read's input values: the seed, or what its `provider` (an earlier wave) discovered, in order."""
		if self.reads[name].key == param.key and provider is None:
			return [seed[param.name]]
		return list(dict.fromkeys(item for output in outputs.get(provider, ()) if output["status"] == "ok" for item in output["discovered"]))

	def readEffect(self, name: str, value: object) -> dict:
		"""The effect a read needs, `[operation, ...arguments]`, keyed so that equal requests are sent once."""
		read = self.reads[name]
		try:
			if isinstance(read, ListRead) and "keys" in value:
				# NOTE: The host runs the index query and the list read, and answers only the list read (spec-09 "Key queries").
				effect = ["KeyQuery", {"read": name, "request": listRequestFor(read, value["parameters"]), "keys": value["keys"]}]
			else:
				effect = ["DocumentFetch", name, value] if read.request is None else ["RequestSend", listRequestFor(read, value["parameters"])
					if isinstance(read, ListRead) else requestFor(read, value)]
		except Failure as failure:
			return {"failure": failure}
		return {"effect": effect, "key": json.dumps(effect, sort_keys=True)}

	def readDocument(self, name: str, value: object, effect: list, result: dict) -> dict:
		"""The document of a read from its effect's result: a request's response, checked by the host's `check`."""
		if effect[0] == "DocumentFetch":
			return result
		read, request = self.reads[name], effect[1]["request"] if effect[0] == "KeyQuery" else effect[1]
		source = requestSource(read, request, value)
		if not callable(check := getattr(self.access, "check", None)):
			return {"document": result["data"], "source": source, "emptyTypes": [], "emptyInputs": []}
		# NOTE: Reads sharing a request share its response; each checks a copy of its own.
		return documentDict(check(name, value, {"request": request, "status": result["status"], "data": deepcopy(result["data"]), "source": source}))

	def discoverKeys(self, state: dict, provides: ViewInput | None) -> list:
		"""Without a host `discover`: the provided key's values on the bound instances of its type, in claim order."""
		if provides is None:
			return []
		builtin, found = getattr(self.keyTypes[provides.key], "builtin", None), []
		for claim in state["claims"]:
			instance = state["instances"].get(claim.get("s"))
			if (claim.get("p") == provides.attr and not claim.get("conflict") and instance and self.sourceModel.isA(instance["type"], provides.path)
				and isinstance(claim.get("v"), (str, int, float)) and not isinstance(claim["v"], bool)):
				found.append(keyValue(claim["v"], builtin))
		return list(dict.fromkeys(found))

	def readProcess(self, env, name: str, value: object, item: dict, sent: dict | None):
		"""One read after its effect: the document, its bindings and discovered keys. A failure makes it unavailable, with a reason."""
		read, gaps, logs = self.reads[name], [], []
		if "failure" in item:
			return {"status": "unavailable", "gaps": [], "reason": readReason(item["failure"]), "failure": item["failure"]}
		if sent["status"] != "ok":
			return {"status": "unavailable", "gaps": [], "reason": sent["reason"], "failure": sent["failure"]}
		if isinstance(read, ListRead) and sent["result"].get("empty"):
			# NOTE: An include no key matched: the host read nothing, and the page has no rows.
			return {"status": "ok", "logs": [], "gaps": [], "discovered": [], "emptyTypes": [], "emptyInputs": [], "total": 0}
		try:
			response = self.readDocument(name, value, item["effect"], sent["result"])
			for index, binding in enumerate(read.bindings):
				if (name, index) not in self.programs:
					self.programs[name, index] = self.binder.compile(binding)
				program = self.programs[name, index]
				raw = yield from program.stages.BindingRead(env, [{"src": response["source"], "document": response["document"]}])
				log, report = self.binder.result(program, raw)
				logs.append(log)
				gaps.extend({"step": name, **asdict(g)} for g in report.gaps)
			state = self.sourceState(logs)
			discover = getattr(self.access, "discover", None)
			total = None
			if isinstance(read, ListRead):
				# NOTE: A list read's rows are the keys on the instances its bindings state, in their order (spec-09).
				discovered = self.discoverKeys(state, read.input)
				total = responseValue(sent["result"].get("data"), read.total) if read.total else None
				if not any(isinstance(item, ListPage) for item in read.parameters.values()):
					# NOTE: A list read without page parameters is read whole; the session keeps the page asked for.
					page = value["page"]
					discovered = discovered[(page["number"] - 1) * page["size"]:][:page["size"]]
			else:
				discovered = list(discover(state, read.provides)) if callable(discover) else self.discoverKeys(state, read.provides)
			for key in discovered if read.provides or isinstance(read, ListRead) else ():
				self.checkValue(read.provides or read.input, key)
		except (OSError, ValueError, KeyError, IndexError, TypeError, FormatError, Failure) as exc:
			if isinstance(exc, Failure) and exc.kind is Failure.Defect:
				raise
			return {"status": "unavailable", "gaps": gaps, "reason": readReason(exc), "failure": exc}
		return {"status": "ok", "logs": logs, "gaps": gaps, "discovered": discovered, "emptyTypes": response["emptyTypes"], "emptyInputs": response["emptyInputs"],
			**({"total": total} if isinstance(total, int) and not isinstance(total, bool) else {})}

	def sourceState(self, logs: list) -> dict:
		"""Merge and reconcile bound source logs into a JSON state."""
		mode = self.mapper.mode
		data = mergeObservationLogs(self.source, logs)
		return observationsToJson(reconcileObservations(self.source, observationsFromJson(self.source, data, mode=mode), mode=mode))

	def project(self, state: Observations, result: dict, outcomes: dict, selected: set[int] | None = None) -> tuple[list, list]:
		"""Only emit leaves reached from this seed, with the claims that established each path."""
		facts, coverage = [], []
		view = self.views[result["view"]]
		graph = Evidence(self.targetModel, state)
		# NOTE: A list view's projection walks from each row's root, and its facts name their row (spec-09 "Rows").
		many = "rows" in result
		roots = [item["handle"] for item in result["rows"]] if many else [result["root"]["handle"]]
		gaps = {g["field"]: g["reason"] for g in result["gaps"] if "field" in g}
		for spelling, key in view.select(list(result["fields"])).items():
			projection = view.selections[key]
			alias, f = projection.population, projection.field
			supplier = result["fields"][spelling]
			path = result["paths"][spelling]
			child = path.get("objectPopulation")
			hopSuppliers = {h.key: route["supplier"] for h, route in zip(view.paths[child or alias], path["hops"], strict=True)}

			def blocked(step: str | list[str] | None, population: str, bindings: dict[str, str], other: str = "") -> str | None:
				if isinstance(step, list):
					# NOTE: A projection with a supplier in each holder (spec-09 "Keyed elements") is blocked when all are.
					reasons = [blocked(item, population, bindings, other) for item in step]
					return None if None in reasons else "unavailable" if "unavailable" in reasons else reasons[0]
				if step is None:
					return "notSupplied" if gaps.get(spelling) == "SelectionRequest.NotSupplied" else "unmapped"
				cases = outcomes.get(step, ())
				for handle in reversed(bindings.values()):
					if scoped := [case for case in cases if handle in case.handles]:
						cases = scoped
						break
				if cases and all(case.status == "unavailable" for case in cases):
					return "unavailable"
				if cases and all(case.status == "empty" or view.populations[population].type in case.emptyTypes or other in case.emptyTypes for case in cases):
					return "empty"
				return None

			for root in roots:
				row = {"row": root} if many else {}
				reached, stops = graph.walk(view, child or alias, root, lambda h, bound: blocked(hopSuppliers[h.key], h.population, bound))
				if selected is None:
					coverage.extend({"field": spelling, "population": alias, **row, **stop,
						"path": [describeWitness(state, w) for w in stop["path"]]} for stop in stops)
				incoming = next((h for h in view.paths[alias] if h.population == alias and h.test is None), None)
				returnsToParent = (f.relation and incoming and incoming.field.relation == f.relation
					and f.roles == (incoming.field.roles if incoming.reverse else incoming.field.roles[::-1]))
				for bindings, trail in reached:
					h = bindings[alias]
					seen = set()
					reason = blocked(supplier, alias, bindings, f.other)
					for subject, value, c, roleClaim in graph.rows(f) if reason is None else ():
						if subject != h or not inContext(c, projection.contextPopulation, bindings):
							continue  # Another subject's value, or one holding within another context.
						if returnsToParent and value.get("ref") != bindings[incoming.parent]:
							continue  # Returning a filing/review link back to the root must preserve that root.
						if child:
							edge = trail[-2]  # The last witness is the object filter, immediately after its incoming edge.
							if value.get("ref") != bindings[child] or edge.subjectRoleClaim is not roleClaim \
								or ("rel" in edge.claim or roleClaim is not None) and edge.claim is not c:
								continue
						if selected is not None:
							selected.update(id(claim) for claim in (c, roleClaim) if claim is not None)
							selected.update(id(claim) for w in trail for claim in (w.claim, w.subjectRoleClaim) if claim is not None)
							continue
						# An association's role claim states a link, not a member of the field.
						member = f.member if roleClaim is not None else c.get("p", f.member)
						facts.append({"field": spelling, "population": alias, "subject": h, "value": value, **row,
							"source": sourceToken(state, c), "path": [describeWitness(state, w) for w in trail],
							**({"member": member} if member != f.member else {}),
							**{k: c[k] for k in ("cur", "unit", "period", "scale", "valid", "at", "ctx", "conflict") if k in c},
							**describeAssociation(c, roleClaim), **({"conflict": True} if conflicted(c, roleClaim) else {})})
						seen.add("conflict" if conflicted(c, roleClaim) else "partial" if isinstance(value, dict) and value.get("partial") else observationStatus(value))
					if selected is None:
						coverage.append({"field": spelling, "population": alias, "subject": h, **row,
							"statuses": sorted(seen or {reason or "missing"}),
							**({} if "supplied" in seen else {"stoppedAt": f.path, "path": [describeWitness(state, w) for w in trail]})})
		return facts, coverage


__all__ = ["HexaViewOperator", "ViewDocument", "ViewRead", "ViewReadError"]

# EOF
