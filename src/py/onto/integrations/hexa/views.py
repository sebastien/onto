"""Module: integrations.hexa.views — plan and retrieve a declared rooted view over a host read catalogue."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import cached_property
from hashlib import sha256
import json
from math import isfinite

from hexa.combinators import pipe, plan, validate
from hexa.runtime import run
from hexa.shapes import Failure, SelectionRequest, profile
from ...binding.model import Binding
from ...mapping.model import Mapping, MappingLine, MappingScope
from ...mapping.operations import acceptedTypes, correspondenceScopes, correspondenceTarget
from ...observations.model import Observations, activeHandles, observationStatus
from ...observations.operations import mergeObservationLogs, observationsFromJson, observationsToJson, reconcileObservations, sourceToken
from ...observations.rooted import Evidence, Witness
from ...ontology.model import Model, ViewInput, unkeyed
from ...ontology.rooted import Field, Hop, RootedView, memberMatches
from ...text import FormatError, isName, isPath
from .compiler import MappingCompiler
from .operations import HexaBindingOperator, HexaMappingOperator

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class ViewRead:
	"""A catalogue step: typed input key, admitted bindings, and any key discovered in their output."""

	input: ViewInput
	bindings: list[Binding]
	provides: ViewInput | None = None

	@property
	def key(self) -> str:
		return self.input.key


@dataclass(slots=True)
class ViewDocument:
	"""One fetched document, its provenance, and collections/keys the source establishes as empty."""

	document: dict
	source: str
	emptyTypes: tuple[str, ...] = ()
	emptyInputs: tuple[str, ...] = ()


class ViewReadError(ValueError):
	"""A source-specific read outcome to record in the report."""

	reason = "UnreadableResponse"


@dataclass(slots=True)
class ReadOutcome:
	"""Scope a read's status and empty collections to the concrete input that was fetched."""

	handles: set[str]
	status: str
	emptyTypes: tuple[str, ...] = ()


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


def describeHop(hop: Hop) -> dict:
	"""Render a planned traversal or filter for the diagnostic path."""
	if hop.test is not None:
		return {"on": hop.population, "where": hop.field.path, "equals": hop.test}
	return {"from": hop.parent, "bind": hop.population, "via": hop.field.path, "reverse": hop.reverse,
		**({"proves": hop.proves} if hop.proves else {})}


def describeWitness(state: Observations, witness: Witness) -> dict:
	"""Render observed path evidence without exposing its internal claim object."""
	hop = witness.hop
	data = {"from": witness.subject, "source": sourceToken(state, witness.claim)}
	if hop.test is not None:
		return {**data, "where": hop.field.path, "value": witness.value}
	return {**data, "via": hop.field.path, "to": witness.value,
		**({"reverse": True} if hop.reverse else {}), **({"proves": hop.proves} if hop.proves else {})}


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class HexaViewOperator:
	"""Discover rooted views in the mapping target. `access` supplies only source-wide I/O and identity."""

	def __init__(self, mapper: HexaMappingOperator, mapping: Mapping, reads: dict[str, ViewRead], access):
		self.source, self.target = mapper.fromOntology, mapper.toOntology
		self.sourceModel, self.targetModel = Model(self.source), Model(self.target)
		self.mapper, self.mapping, self.reads, self.access = mapper, mapping, reads, access
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

	@cached_property
	def mapProgram(self):
		return self.mapper.compile(self.mapping)

	def readSteps(self, seedKey: str) -> dict:
		"""Discover the catalogue reachable from the seed, in prerequisite order with ties in catalogue order."""
		providers, steps = {seedKey: None}, {}
		while ready := [(s, r) for s, r in self.reads.items() if s not in steps and r.key in providers]:
			for name, read in ready:
				parent = providers[read.key]
				steps[name] = {"requires": [parent] if parent else [], "capability": name}
				if read.provides and (key := read.provides.key) != seedKey:
					if key in providers:
						raise ValueError(f"ambiguous providers of {key}: {providers[key]}, {name}")
					providers[key] = name
		return steps

	def correspondences(self, view: RootedView, steps: dict) -> dict:
		"""Follow mapping correspondences from the seed to select a read for each population field."""
		fields = {f for _, f in view.selections.values()} | {h.field for path in view.paths.values() for h in path}
		inputs = defaultdict(list)
		for reader in self.scopes:
			scope = reader.scope
			guards = [scope.when, scope.into, scope.present, scope.ctx, scope.valid]
			# An update scope supplies claims on the referenced instance, not on the update row itself.
			subjectType = reader.exprType(scope.into).path if scope.into else scope.source
			for line in scope.lines:
				if line.candidate:
					continue
				matches = [f for f in fields if writesViewField(self.targetModel, scope, line, f)]
				if not matches:
					continue
				objectType = None
				if any(f.other for f in matches):
					kind = reader.exprType(line.expr)
					objectType = kind.path if kind and kind.kind in ("entity", "relation") else None
					dest = line.asType
					if not dest and objectType:
						attr = self.targetModel.lookup(scope.target, line.target) if line.target else None
						dest = correspondenceTarget(reader.source, self.targetModel, self.mapping, objectType,
							acceptedTypes(self.targetModel, scope.target, line.target or line.verb, attr))
					matches = [f for f in matches if dest and self.targetModel.isA(dest, f.owner if line.verb and line.verb != f.member else f.other)]
				required = {(scope.source, "")} | {(part.owner, unkeyed(part.key)) for expr in [*guards, line.expr, line.when, *line.qualifiers.values()]
					for path in reader.paths(expr) for part in reader.segments(path)}
				for f in matches:
					a, b = (objectType, subjectType) if line.verb and line.verb != f.member else (subjectType, objectType)
					inputs[f].append((a, b, required))

		matches = {}
		def register(key, candidates):
			supplier = next((s for s in steps if any(deps <= self.footprints[s] for _, _, deps in candidates)), None)
			matches[key] = [{"resolved": True, "supplier": supplier}] if candidates else []

		# A shared target type need not have the same source rows in two populations.
		rowTypes = {view.root: set(self.sourceModel.lineage(view.input.path))}
		for alias, path in view.paths.items():
			for hop in (h for h in path if h.population == alias):
				candidates = inputs[hop.field]
				if hop.test is None:
					candidates = [c for c in candidates if c[int(hop.reverse)] in rowTypes[hop.parent]]
					rowTypes[alias] = {c[int(not hop.reverse)] for c in candidates}
				else:
					candidates = [c for c in candidates if c[0] in rowTypes[alias] and (
						not hop.ancestor or c[1] in rowTypes[hop.ancestor])]
				register(hop.key, candidates)
		for key, (alias, f) in view.selections.items():
			register(key, [c for c in inputs[f] if c[0] in rowTypes[alias]])
		return matches

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
		self.checkValue(param, value)
		kind = rooted.populations[rooted.root].type
		handle = self.access.rootHandle(param, value, self.rootTargets[view])
		wanted = rooted.select(fields)
		steps = self.readSteps(param.key)
		matches = self.correspondences(rooted, steps)
		supplier = {key: entries[0]["supplier"] if entries else None for key, entries in matches.items()}
		dependents, paths, outputs = defaultdict(list), {}, {}
		for spelling, key in wanted.items():
			alias, f = rooted.selections[key]
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
			description = {"step": name, "input": read.input.name, "requires": steps[name]["requires"], "bindings": [b.header.get("name", b.ontology) for b in read.bindings],
				**self.access.describe(name, value if read.key == param.key else "{" + read.input.name + "}")}
			reads.append(description)
		gaps = []
		for gap in compiled["gaps"]:
			index = gap["path"][-1]
			for spelling, at in dependents[obligations[index]]:
				gaps.append({"field": spelling, "reason": gap["code"], "stoppedAt": at})
				outputs[spelling] = None
		return {"format": "onto.view-plan/1", "view": view, "seed": dict(seed),
			"root": {"role": rooted.root, "type": kind.removeprefix(self.target.namespace + "/"), "handle": handle},
			"fields": outputs, "paths": paths, "steps": reads, "gaps": gaps}

	async def report(self, view: str, seed: dict, fields: list[str] | None = None) -> dict:
		"""Explain the reads, proven answers and missing links as a diagnostic report."""
		result, state, outcomes = await self.runReads(view, seed, fields)
		result["format"] = "onto.view-report/1"
		result["facts"], result["coverage"] = self.project(state, result, outcomes)
		return result

	async def retrieve(self, view: str, seed: dict, fields: list[str] | None = None) -> Observations:
		"""Return native observations: selected claims and the evidence that connects them to the seed."""
		result, state, outcomes = await self.runReads(view, seed, fields)
		selected = set()
		self.project(state, result, outcomes, selected)
		claims = [c for c in state.claims if id(c) in selected]
		handles = activeHandles(claims)
		sources = {c.get("src") for c in claims}
		header = {k: v for k, v in state.obs.items() if k in ("ontology", "rev", "scope")}
		header.update({k: str(claims[0][k]) for k in ("at", "by", "src", "conf") if claims and k in claims[0] and all(c.get(k) == claims[0][k] for c in claims)})
		return Observations(header, {k: v for k, v in state.sources.items() if k in sources},
			{h: {"type": item["type"]} for h, item in state.instances.items() if h in handles}, claims, [])

	async def runReads(self, view: str, seed: dict, fields: list[str] | None = None):
		"""Return the plan/receipts, reconciled state and read outcomes before rooted projection."""
		result = await self.plan(view, seed, fields)
		param = self.views[view].input
		keys = {param.key: [seed[param.name]]}
		emptyInputs = set()
		calls, logs, outcomes = [], [], defaultdict(list)
		now = datetime.now(timezone.utc).isoformat(timespec="seconds")
		env = {"ClockRead": lambda context: now}
		for step in result["steps"]:
			name = step["step"]
			read = self.reads[name]
			values = keys.get(read.key, [])
			if not values:
				outcomes[name].append(ReadOutcome(set(), "empty" if read.key in emptyInputs else "unavailable"))
				if read.key not in emptyInputs:
					result["gaps"].append({"step": name, "reason": "MissingInput", "input": read.input.name})
			for value in values:
				receipt = {"step": name, "input": {read.input.name: value}, **self.access.describe(name, value)}
				calls.append(receipt)
				try:
					response = self.access.fetch(name, value)
					batch = []
					for i, b in enumerate(read.bindings):
						key = (name, i)
						if key not in self.programs:
							self.programs[key] = self.binder.compile(b)
						program = self.programs[key]
						raw = await run(env, program.stages.BindingRead, [{"src": response.source, "document": response.document}])
						log, report = self.binder.result(program, raw)
						batch.append(log)
						result["gaps"].extend({"step": name, **asdict(g)} for g in report.gaps)
					state = self.sourceState(batch)
					discovered = self.access.discover(state, read.provides)
					if read.provides:
						for item in discovered:
							self.checkValue(read.provides, item)
				except (OSError, ValueError, KeyError, IndexError, TypeError, FormatError, Failure) as exc:
					if isinstance(exc, Failure) and exc.kind is Failure.Defect:
						raise
					receipt["status"] = "unavailable"
					reason = exc.reason if isinstance(exc, ViewReadError) else "UnreadableResponse"
					result["gaps"].append({"step": name, "input": receipt["input"], "reason": reason, "detail": str(exc)})
				else:
					receipt["status"] = "ok"
					logs.extend(batch)
					emptyInputs.update(response.emptyInputs)
					if read.provides:
						key = read.provides.key
						if key != param.key:
							keys[key] = list(dict.fromkeys([*keys.get(key, ()), *discovered]))
						receipt["discovered"] = {read.provides.name: discovered}
				handles = {self.access.rootHandle(read.input, value, kind) for kind in self.inputTargets[read.key]}
				outcomes[name].append(ReadOutcome(handles, receipt["status"], response.emptyTypes if receipt["status"] == "ok" else ()))
		state = Observations({"ontology": self.target.namespace, "scope": None}, {}, {}, [], [])
		if logs:
			program = self.mapProgram
			raw = await run(env, program.stages.MappingRead, self.sourceState(logs))
			log, report = self.mapper.result(program, raw)
			result["gaps"].extend(asdict(g) for g in report.gaps)
			state = reconcileObservations(self.target, log, mode=self.mapper.mode)
		result["calls"] = calls
		return result, state, outcomes

	def sourceState(self, logs: list) -> dict:
		mode = self.mapper.mode
		data = mergeObservationLogs(self.source, logs)
		return observationsToJson(reconcileObservations(self.source, observationsFromJson(self.source, data, mode=mode), mode=mode))

	def project(self, state: Observations, result: dict, outcomes: dict, selected: set[int] | None = None) -> tuple[list, list]:
		"""Only emit leaves reached from this seed, with the claims that established each path."""
		facts, coverage = [], []
		view = self.views[result["view"]]
		graph = Evidence(self.targetModel, state)
		root = result["root"]["handle"]
		gaps = {g["field"]: g["reason"] for g in result["gaps"] if "field" in g}
		for spelling, key in view.select(list(result["fields"])).items():
			alias, f = view.selections[key]
			supplier = result["fields"][spelling]
			path = result["paths"][spelling]
			child = path.get("objectPopulation")
			hopSuppliers = {h.key: route["supplier"] for h, route in zip(view.paths[child or alias], path["hops"], strict=True)}

			def blocked(step: str | None, population: str, bindings: dict[str, str], other: str = "") -> str | None:
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

			reached, stops = graph.walk(view, child or alias, root, lambda h, bound: blocked(hopSuppliers[h.key], h.population, bound))
			if selected is None:
				coverage.extend({"field": spelling, "population": alias, **stop,
					"path": [describeWitness(state, w) for w in stop["path"]]} for stop in stops)
			incoming = next((h for h in view.paths[alias] if h.population == alias and h.test is None), None)
			returnsToParent = (f.relation and incoming and incoming.field.relation == f.relation
				and f.roles == (incoming.field.roles if incoming.reverse else incoming.field.roles[::-1]))
			for bindings, trail in reached:
				h = bindings[alias]
				seen = set()
				reason = blocked(supplier, alias, bindings, f.other)
				for subject, value, c in graph.rows(f) if reason is None else ():
					if subject != h:
						continue
					if returnsToParent and value.get("ref") != bindings[incoming.parent]:
						continue  # Returning a filing/review link back to the root must preserve that root.
					if child:
						edge = trail[-2].claim  # The last witness is the object filter, immediately after its incoming edge.
						if value.get("ref") != bindings[child] or "rel" in edge and edge is not c:
							continue
					if selected is not None:
						selected.add(id(c))
						selected.update(id(w.claim) for w in trail)
						continue
					member = c.get("p", f.member)
					facts.append({"field": spelling, "population": alias, "subject": h, "value": value,
						"source": sourceToken(state, c), "path": [describeWitness(state, w) for w in trail],
						**({"member": member} if member != f.member else {}),
						**{k: c[k] for k in ("cur", "unit", "period", "scale", "valid", "at", "ctx", "conflict") if k in c}})
					seen.add("conflict" if c.get("conflict") else "partial" if isinstance(value, dict) and value.get("partial") else observationStatus(value))
				if selected is None:
					coverage.append({"field": spelling, "population": alias, "subject": h,
						"statuses": sorted(seen or {reason or "missing"}),
						**({} if "supplied" in seen else {"stoppedAt": f.path, "path": [describeWitness(state, w) for w in trail]})})
		return facts, coverage


__all__ = ["HexaViewOperator", "ViewDocument", "ViewRead", "ViewReadError"]

# EOF
