"""Module: integrations.hexa.sessions — page views over a system's reads and an observation store, and changes routed to
each slot's holder (spec-09 Sessions).

A `SessionViewOperator` plans a view as `HexaViewOperator` does for its system, then gives the obligations on slots the
store holds to store reads of the partition kinds that reach them. A `Session` keeps the state of the view it opened and
routes a change set: the store's slots to their home partitions, the system's to its operations (spec-10; read-only here).
"""

from __future__ import annotations

import copy
import json
import uuid
from collections import defaultdict
from typing import Any

from ...handles import sourceQualifiedHandle
from ...observations.model import Observations, claimSlot, referenceHandles
from ...observations.rooted import Evidence
from ...ontology.rooted import Field, RootedView
from ...store.origins import ORIGIN_SHARED, ORIGIN_STORE, RE_ELEMENT_KEY, elementPath, holds, isA, originOf, related
from ...store.runtime import StoreError
from .bundle import viewBundle
from .views import HexaViewOperator, ReadOutcome, readWaves

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Json = dict[str, Any]
SLOT_KEYS = ("s", "p", "facet", "exists", "rel", "roles", "ctx")


def slotKey(item: Json) -> str:
	"""A slot's identity: subject, member and context (spec-02)."""
	return json.dumps(list(claimSlot({key: item[key] for key in SLOT_KEYS if key in item})))


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class SessionViewOperator(HexaViewOperator):
	"""Plan and retrieve page views over one system's reads and a store (spec-09 "Page views").

	`bundle` is the store's bundle (spec-08) and `scope` its scope. `access` adds two host operations to the view
	operator's: `storeRead(body)`, a batch read of partitions, and `storeAppend(partition, body)`, an append.
	"""

	def __init__(self, mapper, mapping, reads, access, bundle: Json, scope: str, operations: dict | None = None):
		super().__init__(mapper, mapping, reads, access, operations)
		self.bundle, self.scope = bundle, scope
		self.system = mapping.fromNamespace
		self.storeName = bundle["store"]
		self.kinds = {kind["kind"]: kind for kind in bundle["kinds"]}

	# -- Holders -----------------------------------------------------------------

	def typeOrigin(self, type: str) -> str:
		"""The origin of the instances of `type` a view reaches: the system when it produces the type, else the store."""
		return self.system if self.system in self.bundle["origins"].get(type, {}).get("systems", []) else ORIGIN_STORE

	def fieldHolder(self, subjectType: str, field: Field) -> str:
		"""Who holds a field of instances of `subjectType` (spec-09 "Holders")."""
		claim = {"rel": field.relation} if field.relation else {"p": field.member}
		return self.storeName if holds(self.bundle, self.typeOrigin(subjectType), subjectType, claim) else self.system

	def keyedHolders(self, subjectType: str, field: Field) -> dict[str, str]:
		"""The keyed elements of a field the system fills for its instances, such as `Phones[Mobile].Number`, when the
		store holds the field's other elements (spec-09 "Keyed elements")."""
		if field.relation or self.typeOrigin(subjectType) != self.system:
			return {}
		found: dict[str, str] = {}
		for system in self.bundle["systems"]:
			if system["name"] != self.system:
				continue
			for target, filled in system["types"].items():
				if related(self.bundle, subjectType, target):
					found.update({path: self.system for path in map(elementPath, filled["attrs"])
						if "[" in path and RE_ELEMENT_KEY.sub("", path) == field.member})
		return dict(sorted(found.items()))

	def claimHolder(self, claim: Json, instances: dict) -> str | None:
		"""Who holds the slot a claim states, by its subject's origin; None when the subject has no origin."""
		subject = self.subjectOf(claim)
		type = instances.get(subject, {}).get("type")
		origin = originOf(self.bundle, subject, type, self.scope) if type else None
		if origin is None:
			return None
		return self.storeName if holds(self.bundle, origin, type, claim) else self.system if origin in (ORIGIN_SHARED, self.system) else origin

	def subjectOf(self, claim: Json) -> str:
		"""A statement's subject: its `s`, a binary relation's first participant, an identity link's first handle."""
		if "s" in claim:
			return claim["s"]
		if "rel" in claim:
			return claim["roles"][self.targetModel.get(claim["rel"]).participants[0].role]
		return (claim.get("same") or claim.get("distinct"))[0]

	# -- Planning ----------------------------------------------------------------

	def matched(self, rooted: RootedView) -> dict[str, tuple[str, str, str]]:
		"""The view's populations a store's partitions hold: alias -> (kind, the kind's population, the anchor's alias).

		A population of a kind's key entity anchors its partitions; a hop matches a kind's population by its link
		(owner, member and direction), not by its alias (spec-09 "Planning")."""
		found: dict[str, tuple[str, str, str]] = {}
		for alias, population in rooted.populations.items():
			kind = next((item for item in self.bundle["kinds"] if isA(self.bundle, population.type, item["root"]["type"])), None)
			if kind is not None:
				found[alias] = (kind["kind"], kind["root"]["name"], alias)
		changed = True
		while changed:
			changed = False
			for alias, path in rooted.paths.items():
				hop = next((item for item in path if item.population == alias and item.test is None), None)
				if alias in found or hop is None or hop.parent not in found:
					continue
				kindName, parentName, anchor = found[hop.parent]
				type = rooted.populations[alias].type
				for population in self.kinds[kindName]["populations"]:
					link = population["link"]
					follows = link.get("rel") == hop.field.relation if hop.field.relation else (
						link.get("slot") == hop.field.member and link.get("on") == ("member" if hop.reverse else "parent"))
					if population["parent"] == parentName and follows and (isA(self.bundle, type, population["type"]) or isA(self.bundle, population["type"], type)):
						found[alias] = (kindName, population["name"], anchor)
						changed = True
						break
		return found

	def storePlan(self, view: str, fields: list[str] | None, result: Json) -> Json:
		"""Give the store the obligations on slots it holds: store reads, holders and writability (spec-09 "Results")."""
		rooted = self.views[view]
		matched = self.matched(rooted)
		providers = {step["step"]: step["requires"][0] if step["requires"] else None for step in result["steps"]}
		later = max(readWaves(list(providers), providers).values(), default=-1) + 1
		steps: dict[str, Json] = {}
		selections: dict[tuple[str, str], set[str]] = defaultdict(set)
		populations: dict[str, dict[str, str]] = defaultdict(dict)

		def storeStep(alias: str) -> str:
			kindName, populationName, anchor = matched[alias]
			name = f"store:{kindName}" if anchor == rooted.root else f"store:{kindName}:{anchor}"
			steps.setdefault(name, {"step": name, "kind": "store", "partitionKind": kindName, "anchor": anchor, "wave": 0 if anchor == rooted.root else later})
			populations[name][populationName] = alias
			return name

		def select(alias: str, member: str) -> str | None:
			if alias not in matched:
				return None
			name = storeStep(alias)
			selections[name, matched[alias][1]].add(member)
			return name

		holders, writable, unhomed, keyedHolders = {}, {}, set(), {}
		for spelling, key in rooted.select(fields).items():
			projection = rooted.selections[key]
			alias, field = projection.population, projection.field
			holder = holders[spelling] = self.fieldHolder(rooted.populations[alias].type, field)
			attr = None if field.relation else self.targetModel.lookup(field.owner, field.member)
			writable[spelling] = holder == self.storeName and not (attr is not None and attr.derived)
			if holder != self.storeName:
				continue
			if keyed := self.keyedHolders(rooted.populations[alias].type, field):
				keyedHolders[spelling] = keyed
			supplier = select(alias, field.member)
			path = result["paths"][spelling]
			for hop, route in zip(rooted.paths[path.get("objectPopulation") or alias], path["hops"], strict=True):
				if route["supplier"] is not None or hop.test is not None:
					continue
				# NOTE: A member's own link is selected with it; a parent's link, with the parent.
				owner = hop.population if hop.reverse else hop.parent
				if self.fieldHolder(rooted.populations[owner].type, hop.field) == self.storeName:
					route["supplier"] = select(owner, hop.field.member if not hop.field.relation else hop.field.relation)
					if hop.population in matched:
						select(hop.population, "exists")
			# NOTE: A field whose keyed elements a system fills keeps that system's supplier beside the store's.
			systemSupplier = result["fields"][spelling] if spelling in keyedHolders else None
			result["fields"][spelling] = ([systemSupplier, supplier] if supplier else systemSupplier) if systemSupplier else supplier
			if supplier is None:
				unhomed.add(spelling)
		stored = {spelling for spelling, holder in holders.items() if holder == self.storeName and spelling not in keyedHolders}
		result["gaps"] = [gap for gap in result["gaps"] if gap.get("field") not in stored] + [
			{"field": spelling, "reason": "Store.Unhomed", "stoppedAt": rooted.selections[rooted.select(fields)[spelling]].field.path} for spelling in sorted(unhomed)]
		for (name, populationName), members in selections.items():
			step, alias = steps[name], populations[name][populationName]
			kind = self.kinds[step["partitionKind"]]
			slots = sorted(member for member in members if member != "exists")
			if populationName == kind["root"]["name"]:
				entry = {"s": "{anchor}", "slots": slots}
			else:
				entry = {"population": populationName, "slots": slots, **({"page": {"size": rooted.pages[alias]}} if alias in rooted.pages else {})}
			step.setdefault("select", []).append(entry)
		result["storeSteps"] = list(steps.values())
		result["holders"], result["writable"], result["keyedHolders"] = holders, writable, keyedHolders
		return result

	async def plan(self, view: str, seed: dict, fields: list[str] | None = None) -> dict:
		"""Plan a view's system reads and store reads, with each field's holder and writability."""
		result = self.storePlan(view, fields, await super().plan(view, seed, fields))
		result["steps"] = result["steps"] + result.pop("storeSteps")
		return result

	# -- Retrieval ---------------------------------------------------------------

	@staticmethod
	def storeRequests(steps: list[Json], anchorsOf) -> tuple[list[Json], list[tuple[Json, str]]]:
		"""One wave's store reads, one per partition of each step's anchors, with the step and anchor of each."""
		reads, owners = [], []
		for step in steps:
			for anchor in anchorsOf(step):
				reads.append({"partition": f"{step['partitionKind']}/{anchor}",
					"select": [{**entry, "s": anchor} if entry.get("s") == "{anchor}" else entry for entry in step["select"]]})
				owners.append((step, anchor))
		return reads, owners

	async def runReads(self, view: str, seed: dict, fields: list[str] | None = None, now: str | None = None, **options):
		"""Run the store reads of the first wave, the system's reads, then the later store reads, and keep each claim
		from its slot's holder (spec-09 "Reads and waves")."""
		rooted = self.views[view]
		planned = await HexaViewOperator.plan(self, view, seed, fields)
		# NOTE: When `rootHandle` gives the root's handle from the seed, the root's store read needs no system read.
		early = planned["root"]["handle"]
		first = [step for step in self.storePlan(view, fields, copy.deepcopy(planned))["storeSteps"] if step["wave"] == 0] if early else []
		reads, owners = self.storeRequests(first, lambda step: [early])
		answers = self.access.storeRead({"reads": reads})["results"] if reads else []
		result, state, outcomes = await super().runReads(view, seed, fields, now, planned=planned, **options)
		result = self.storePlan(view, fields, result)
		root = result["root"]["handle"]
		graph: Evidence | None = None

		def anchorsOf(step: Json) -> list[str]:
			nonlocal graph
			if step["anchor"] == rooted.root:
				return [root] if root else []
			graph = graph or Evidence(self.targetModel, state)
			reached, _ = graph.walk(rooted, step["anchor"], root, lambda hop, bound: None)
			return list(dict.fromkeys(bindings[step["anchor"]] for bindings, _ in reached))

		done = {step["step"] for step in first}
		later, laterOwners = self.storeRequests([step for step in result["storeSteps"] if step["step"] not in done], anchorsOf)
		answers += self.access.storeRead({"reads": later})["results"] if later else []
		reads, owners = reads + later, owners + laterOwners
		claims = [claim for claim in state.claims if self.claimHolder(claim, state.instances) in (self.system, None)]
		offAuthority = [claim for claim in state.claims if self.claimHolder(claim, state.instances) not in (self.system, None)]
		instances = dict(state.instances)
		ordinal = max((claim["n"] for claim in state.claims), default=0)
		versions, homes, pages = {}, {}, {}
		for (step, anchor), read, answer in zip(owners, reads, answers):
			call = {"step": step["step"], "partition": read["partition"]}
			if "error" in answer:
				status = "empty" if answer.get("status") == 404 else "unavailable"
				outcomes[step["step"]].append(ReadOutcome({anchor}, status))
				result["calls"].append({**call, "status": status})
				if status == "unavailable":
					result["gaps"].append({**call, "reason": f"Store.{answer['error']}"})
				continue
			outcomes[step["step"]].append(ReadOutcome({anchor}, "ok"))
			result["calls"].append({**call, "status": "ok", "head": answer["head"]})
			data = answer["observations"]
			for handle, item in data["instances"].items():
				instances.setdefault(handle, {"type": item["type"]})
			for claim in data["claims"]:
				ordinal += 1
				claim = {**claim, "n": ordinal}
				homes[self.subjectOf(claim)] = read["partition"]
				(claims if self.claimHolder(claim, instances) == self.storeName else offAuthority).append(claim)
			versions.update({slotKey(slot): slot["version"] for slot in answer["versions"]})
			for population, cursor in answer.get("pages", {}).items():
				alias = next(alias for alias, (kind, name, _) in self.matched(rooted).items() if kind == step["partitionKind"] and name == population)
				pages.setdefault(alias, {})[step["step"]] = cursor
		result["steps"] = result["steps"] + result.pop("storeSteps")
		result["store"] = {"versions": versions, "homes": homes}
		result["pages"] = pages
		result["offAuthority"] = offAuthority
		return result, Observations(state.obs, state.sources, instances, claims, [], state.diagnostics), outcomes

	async def open(self, view: str, seed: dict, fields: list[str] | None = None, now: str | None = None, **options) -> tuple[dict, Observations]:
		"""A view's report, with each fact's holder, partition and version, and the state it was projected from."""
		result, state, outcomes = await self.runReads(view, seed, fields, now, **options)
		result["format"] = "onto.view-report/1"
		result["facts"], result["coverage"] = self.project(state, result, outcomes)
		rooted = self.views[view]
		store = result.pop("store")
		for fact in result["facts"]:
			field = rooted.selections[rooted.select([fact["field"]])[fact["field"]]].field
			member = fact.get("member", field.member)
			# NOTE: A fact's holder is its own slot's: a keyed field's elements may have different holders.
			fact["holder"] = result["holders"][fact["field"]] if field.relation else \
				self.claimHolder({"s": fact["subject"], "p": member}, state.instances) or result["holders"][fact["field"]]
			fact["writable"] = fact["holder"] == self.storeName and result["writable"][fact["field"]]
			if fact["holder"] == self.storeName:
				slot = {"s": fact["subject"], "p": member, **({"ctx": fact["ctx"]} if "ctx" in fact else {})}
				fact["partition"] = store["homes"].get(fact["subject"])
				fact["version"] = store["versions"].get(slotKey(slot), 0)
		return result, state

	async def report(self, view: str, seed: dict, fields: list[str] | None = None, now: str | None = None, **options) -> dict:
		"""Explain the reads and facts of a view, each fact with its holder, and the store's with partition and version."""
		return (await self.open(view, seed, fields, now, **options))[0]


SESSION_BUNDLE_FORMAT = "onto.view-bundle/3"


def sessionBundle(operator: SessionViewOperator) -> Json:
	"""A session's bundle (spec-09 "Bundles and runtimes"): the view bundle, with the store bundle it reads and appends to."""
	return viewBundle(operator) | {"format": SESSION_BUNDLE_FORMAT, "store": operator.bundle}


class Session:
	"""A client's session: the state of the view it opened, and changes routed to each slot's holder (spec-09 "Changes")."""

	def __init__(self, operator: SessionViewOperator):
		self.operator = operator
		self.report: dict | None = None
		self.state: Observations | None = None
		self.opened: tuple | None = None

	def newHandle(self, type: str) -> str:
		"""A handle for a new instance of `type`, source-qualified in the store's scope with a new UUID as its key, so
		that its origin is the store even when a system produces the type (spec-09 "Origins")."""
		return sourceQualifiedHandle(type, self.operator.scope, type, str(uuid.uuid7()))

	async def open(self, view: str, seed: dict, fields: list[str] | None = None, **options) -> dict:
		"""Read a view and keep its state."""
		self.opened = (view, seed, fields, options)
		self.report, self.state = await self.operator.open(view, seed, fields, **options)
		return self.report

	def homes(self, statements: list[Json], types: dict[str, str]) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, Json | None]]]:
		"""Each handle's home partition and population, from the change set's links and the state's; and for each handle
		homed by a link, its parent and the link when a system holds it, which an append must send (spec-08 "Homes")."""
		operator, bundle = self.operator, self.operator.bundle
		homes: dict[str, tuple[str, str]] = {}
		for handle, type in types.items():
			kind = next((item for item in bundle["kinds"] if isA(bundle, type, item["root"]["type"])), None)
			if kind is not None:
				homes[handle] = (f"{kind['kind']}/{handle}", kind["root"]["name"])
		state = list(self.state.claims) if self.state else []
		claims = [(item, False) for item in statements if not item.get("retract")] + [(item, True) for item in state]
		via: dict[str, tuple[str, Json | None]] = {}
		changed = True
		while changed:
			changed = False
			for handle, type in types.items():
				if handle in homes:
					continue
				for kind in bundle["kinds"]:
					for population in kind["populations"]:
						if not isA(bundle, type, population["type"]):
							continue
						for claim, fromState in claims:
							parent = self.linkParent(claim, handle, population)
							if parent is None or parent not in homes or homes[parent][1] != population["parent"] or not homes[parent][0].startswith(kind["kind"] + "/"):
								continue
							homes[handle] = (homes[parent][0], population["name"])
							held = fromState and operator.claimHolder(claim, {item: {"type": kind} for item, kind in types.items()}) != operator.storeName
							via[handle] = (parent, {key: claim[key] for key in ("s", "p", "v", "rel", "roles") if key in claim} if held else None)
							changed = True
							break
						if handle in homes:
							break
					if handle in homes:
						break
		return homes, via

	@staticmethod
	def homeLinks(subjects: list[str], via: dict[str, tuple[str, Json | None]]) -> list[Json]:
		"""The links a system holds that home `subjects`, and their parents up to the anchor, each once."""
		links: list[Json] = []
		for subject in subjects:
			handle, seen = subject, set()
			while handle in via and handle not in seen:
				seen.add(handle)
				parent, link = via[handle]
				if link is not None and link not in links:
					links.append(link)
				handle = parent
		return links

	@staticmethod
	def linkParent(claim: Json, handle: str, population: Json) -> str | None:
		"""The parent a claim links `handle` to along `population`'s link, if it states that link."""
		link = population["link"]
		if "rel" in link:
			roles = claim.get("roles", {})
			return roles.get(link["parentRole"]) if claim.get("rel") == link["rel"] and roles.get(link["memberRole"]) == handle else None
		if claim.get("p") != link["slot"]:
			return None
		targets = referenceHandles(claim.get("v"))
		if link["on"] == "member":
			return targets[0] if claim.get("s") == handle and targets else None
		return claim.get("s") if handle in targets else None

	def batch(self, statements: list[Json], types: dict[str, str], links: list[Json]) -> Json:
		"""An append of statements with the store file's edit source, their slots' versions and the home links."""
		bundle = self.operator.bundle
		claims, retractions, expect, mentioned = [], [], [], set()
		for n, statement in enumerate(statements, 1):
			entry = {key: value for key, value in statement.items() if key not in ("version", "was", "retract")}
			if "version" in statement:
				expect.append({key: entry[key] for key in SLOT_KEYS if key in entry} | {"version": statement["version"]})
			(retractions if statement.get("retract") else claims).append(entry | {"n": n, "src": "e"})
			mentioned.update(item for item in [entry.get("s"), *entry.get("roles", {}).values(), *referenceHandles(entry.get("v"))] if item)
		for link in links:
			mentioned.update(item for item in [link.get("s"), *link.get("roles", {}).values(), *referenceHandles(link.get("v"))] if item)
		return {"requestId": str(uuid.uuid4()), "expect": expect, **({"links": links} if links else {}),
			"observations": {"format": "onto.observations/1", "obs": {"ontology": self.operator.target.namespace, "scope": self.operator.scope},
				"sources": {"e": bundle["edit"]}, "instances": {handle: {"type": types[handle]} for handle in sorted(mentioned) if handle in types},
				"claims": claims, "retractions": retractions}}

	def append(self, partition: str, body: Json) -> Json:
		"""Append a batch; an append without an answer is retried once with the same request ID (spec-08 "Retries"),
		and is `uncertain` if that fails too."""
		access = self.operator.access
		try:
			access.storeAppend(partition, body)
		except OSError:
			try:
				access.storeAppend(partition, body)
			except OSError:
				return {"result": "uncertain", "partition": partition, "requestId": body["requestId"]}
		return {"result": "applied", "partition": partition}

	def moved(self, partition: str, expect: list[Json], versions: list[Json]) -> list[Json]:
		"""The slots that moved since a batch was prepared, each with its current version and value (`v`, none when the
		slot has no value now), read from the partition (spec-09 "Atomic per partition")."""
		moved = [current for wanted, current in zip(expect, versions) if wanted["version"] != current["version"]]
		subjects: dict[str, set[str]] = defaultdict(set)
		for slot in moved:
			subjects[self.operator.subjectOf(slot)].add(slot.get("p") or slot.get("rel") or (f"[{slot['facet']}]" if "facet" in slot else "exists"))
		answer, = self.operator.access.storeRead({"reads": [{"partition": partition,
			"select": [{"s": subject, "slots": sorted(slots)} for subject, slots in subjects.items()]}]})["results"]
		claims = answer.get("observations", {}).get("claims", [])
		values = {slotKey(claim): claim["v"] for claim in claims if "v" in claim}
		return [slot | ({"v": values[slotKey(slot)]} if slotKey(slot) in values else {}) for slot in moved]

	async def change(self, changes: Json) -> Json:
		"""Route a change set (spec-09 "Changes"): store-held statements to their home partitions, one batch per partition;
		system-held ones are read-only until the system declares operations (spec-10). After applying, the session
		reads its view again."""
		operator, bundle = self.operator, self.operator.bundle
		state = self.state.instances if self.state else {}
		types = {handle: item["type"] for handle, item in state.items()} | {handle: item["type"] for handle, item in changes.get("instances", {}).items()}
		statements = [dict(item) for item in changes.get("claims", [])] + [dict(item, retract=True) for item in changes.get("retractions", [])]
		homes, via = self.homes(statements, types)
		results: list[Json] = [{} for _ in statements]
		groups: dict[str, list[int]] = defaultdict(list)
		for index, statement in enumerate(statements):
			subject = operator.subjectOf(statement)
			type = types.get(subject)
			origin = originOf(bundle, subject, type, operator.scope) if type else None
			if origin is None:
				results[index] = {"result": "rejected", "reason": "origin.unknown" if type else "type"}
			elif not holds(bundle, origin, type, statement):
				results[index] = {"result": "readonly"}
			elif subject not in homes:
				results[index] = {"result": "unhomed"}
			else:
				groups[homes[subject][0]].append(index)
		for partition, indexes in groups.items():
			subjects = list(dict.fromkeys(operator.subjectOf(statements[index]) for index in indexes))
			body = self.batch([statements[index] for index in indexes], types, self.homeLinks(subjects, via))
			try:
				outcome = self.append(partition, body)
			except StoreError as error:
				if error.error == "precondition":
					outcome = {"result": "conflict", "partition": partition, "moved": self.moved(partition, body["expect"], error.details["versions"])}
				else:
					outcome = {"result": "rejected", "partition": partition, "reason": error.details.get("check", error.error)}
			for index in indexes:
				results[index] = outcome
		if self.opened and any(result.get("result") == "applied" for result in results):
			view, seed, fields, options = self.opened
			await self.open(view, seed, fields, **options)
		return {"statements": [{key: statement[key] for key in SLOT_KEYS if key in statement} | result for statement, result in zip(statements, results)]}


__all__ = ["SESSION_BUNDLE_FORMAT", "Session", "SessionViewOperator", "sessionBundle"]

# EOF
