"""Module: integrations.hexa.unfold — mappings over a state: handles, unfolded trees, metadata, variants and claims (spec-06).

MappingRead: HandlesResolve → InstancesUnfold → <S><T>RecordsProject → <S><T>VariantsProject → ClaimsEmit

A state is a graph and hexa projects trees: each scope instance is unfolded into a
tree holding what the scope reads, with a metadata table from tree pointers to the
claims each value came from. Metadata and fan-out are computed here, not by hexa.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any as AnyValue

from hexa.combinators import Policy, collect, each, lift, pipe, project, stage

from ...observations.model import parseInterval
from ...ontology.model import Model
from .compiler import LineInfo
from .model import ScopeProgram
from .stages import ClaimsBuilder, cleanValue, namedStage
from .vocabulary import MappingCodes, isAbsent, reasonCode, textOf

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class MappingScopePlan:
	"""What unfolding and emission need from a compiled scope, beyond its hexa shapes."""

	name: str
	source: str
	target: str
	reach: dict
	lines: list[LineInfo]
	when: dict | None
	handleTemplate: dict
	program: ScopeProgram | None = None
	sectionLines: dict[tuple[str, str], LineInfo] = field(default_factory=dict)
	segmentKeys: dict[tuple, list[str]] = field(default_factory=dict)


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def escape(key: str) -> str:
	return key.replace("~", "~0").replace("/", "~1")


def metaOf(claim: dict, sources: dict[str, str]) -> dict:
	"""A claim's metadata in the table: `src` as its provenance token, `at`, `valid`, `conf`."""
	result = {"src": sources.get(claim.get("src"), claim.get("src")), "at": claim.get("at")}
	for key in ("valid", "conf"):
		if key in claim:
			result[key] = claim[key]
	return result


def intersect(valids: list[str]) -> str | None:
	"""The intersection of `valid` intervals, spelled with the bounds it keeps; None when unbounded or empty."""
	if not valids:
		return None
	if len(set(valids)) == 1:
		return valids[0]
	start, end = None, None
	startText, endText = "", ""
	for text in valids:
		left, _, right = text.partition("..") if ".." in text else (text, "", text)
		low, high = parseInterval(text)
		if low is not None and (start is None or low > start):
			start, startText = low, left
		if high is not None and (end is None or high < end):
			end, endText = high, right
	if start is not None and end is not None and start > end:
		return None
	return startText if startText == endText else f"{startText}..{endText}"


def valueAt(tree: dict, keys: list[str]) -> AnyValue:
	"""The value at segment `keys`, through references' `of` subtrees; None when absent or plural."""
	node: AnyValue = tree
	for index, key in enumerate(keys):
		if not isinstance(node, dict) or key not in node:
			return None
		node = node[key]
		if index + 1 < len(keys):
			node = node.get("of") if isinstance(node, dict) else None
	return node


def setAt(tree: dict, pointer: str, value: AnyValue) -> dict:
	"""A copy of `tree` with `value` at `pointer` (a conflicting slot taking one of its values)."""
	result = deepcopy(tree)
	parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]
	node = result
	for part in parts[:-1]:
		node = node[int(part)] if isinstance(node, list) else node.setdefault(part, {})
	node[parts[-1]] = value
	return result


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class StateIndex:
	"""Claims of a reconciled state by subject and slot, with conflicts kept together."""

	def __init__(self, state: dict, model: Model):
		self.model = model
		self.sources = state.get("sources", {})
		self.instances = state.get("instances", {})
		self.scope = (state.get("obs") or {}).get("scope") or (state.get("obs") or {}).get("ontology") or ""
		self.values: dict[str, dict[str, list[dict]]] = {}
		self.exists: dict[str, list[dict]] = {}
		self.relations: list[dict] = []
		for claim in state.get("claims", []):
			if claim.get("exists"):
				self.exists.setdefault(claim["s"], []).append(claim)
			elif "p" in claim:
				self.values.setdefault(claim["s"], {}).setdefault(claim["p"], []).append(claim)
			elif "rel" in claim:
				self.relations.append(claim)

	def typeOf(self, handle: str) -> str | None:
		return self.instances.get(handle, {}).get("type")

	def existence(self, handle: str) -> dict | None:
		claims = [claim for claim in self.exists.get(handle, []) if not claim.get("conflict")] or self.exists.get(handle, [])
		return claims[0] if claims else None

	def handlesOf(self, typePath: str) -> list[str]:
		"""Instances of `typePath` or its specialisations, in handle order."""
		return sorted(handle for handle, item in self.instances.items() if self.model.isA(item["type"], typePath))


class Unfolder:
	"""Turn scope instances into trees limited to the scope's reach, with metadata tables and conflicts."""

	def __init__(self, index: StateIndex, correspondence: dict[str, str] | None):
		self.index = index
		self.correspondence = correspondence

	def reference(self, handle: str, children: dict, pointer: str, meta: dict, conflicts: dict) -> dict:
		result: dict = {"ref": handle}
		if self.correspondence is not None and handle in self.correspondence:
			result["target"] = self.correspondence[handle]
		if children:
			result["of"] = self.subtree(handle, children, f"{pointer}/of", meta, conflicts)
		return result

	def value(self, value: AnyValue, segment: AnyValue, children: dict, pointer: str, meta: dict, conflicts: dict) -> AnyValue:
		if segment.kind != "ref" or not isinstance(value, dict):
			return value
		if "ref" in value:
			return self.reference(value["ref"], children, pointer, meta, conflicts)
		if "set" in value:
			members = [self.reference(item["ref"], children, f"{pointer}/set/{index}", meta, conflicts) if isinstance(item, dict) and "ref" in item else item
				for index, item in enumerate(value["set"])]
			return {**value, "set": members}
		return value

	def subtree(self, handle: str, reach: dict, base: str, meta: dict, conflicts: dict) -> dict:
		tree: dict = {}
		sources = self.index.sources
		for key, node in reach.items():
			segment, children = node["segment"], node["children"]
			pointer = f"{base}/{escape(key)}"
			if segment.kind == "verb":
				members = self.verb(handle, segment, children, pointer, meta, conflicts)
				if members is not None:
					tree[key] = members
				continue
			claims = self.index.values.get(handle, {}).get(key, [])
			if not claims:
				continue
			if any(claim.get("conflict") for claim in claims):
				conflicts[pointer] = [{"value": claim["v"], **metaOf(claim, sources)} for claim in claims]
				meta[pointer] = conflicts[pointer]
				continue
			value = claims[0]["v"]
			if len(claims) > 1 and all(isinstance(claim.get("v"), dict) and "set" in claim["v"] for claim in claims):
				# Rule 9 keeps a complete collection and later additions apart; their members together are the slot.
				members = {repr(item): item for claim in claims for item in claim["v"]["set"]}
				value = {"set": list(members.values()), **({"partial": True} if any(claim["v"].get("partial") for claim in claims) else {})}
			meta[pointer] = metaOf(claims[-1], sources)
			tree[key] = self.value(value, segment, children, pointer, meta, conflicts)
		return tree

	def verb(self, handle: str, segment: AnyValue, children: dict, pointer: str, meta: dict, conflicts: dict) -> dict | None:
		found = self.index.model.verbs(segment.owner, segment.key)
		if not found:
			return None
		decl, inverse = found[0]
		mine, other = (decl.participants[1].role, decl.participants[0].role) if inverse else (decl.participants[0].role, decl.participants[1].role)
		claims = sorted((claim for claim in self.index.relations if claim["rel"] == decl.path and claim["roles"].get(mine) == handle), key=lambda claim: claim["roles"][other])
		if not claims:
			return None
		members = []
		for index, claim in enumerate(claims):
			members.append(self.reference(claim["roles"][other], children, f"{pointer}/set/{index}", meta, conflicts))
			meta[f"{pointer}/set/{index}"] = metaOf(claim, self.index.sources)
		meta[pointer] = metaOf(claims[0], self.index.sources)
		return {"set": members}

	def occurrence(self, plan: MappingScopePlan, handle: str) -> dict | None:
		"""`{value: tree, location, meta, conflicts, exists}`, or None when the instance has no existence claim."""
		existence = self.index.existence(handle)
		if existence is None:
			return None
		meta: dict = {}
		conflicts: dict = {}
		tree = self.subtree(handle, plan.reach, "", meta, conflicts)
		existsMeta = metaOf(existence, self.index.sources)
		tree |= {"$handle": handle, "$type": self.index.typeOf(handle), "$scope": self.index.scope, "$at": existence.get("at"), "$src": existsMeta["src"]}
		if "valid" in existence:
			tree["$valid"] = existence["valid"]
		if self.correspondence is not None and handle in self.correspondence:
			tree["$target"] = self.correspondence[handle]
		return {"value": tree, "location": f"/{plan.name}/{escape(handle)}", "meta": meta, "conflicts": conflicts, "exists": existsMeta}


def pointersOf(tree: dict, steps: list[str]) -> list[str]:
	"""The tree pointers of the claims along a path, through references and their `of` subtrees."""
	result: list[str] = []
	frontier = [("", tree)]
	for index, key in enumerate(steps):
		following = []
		for base, node in frontier:
			pointer = f"{base}/{escape(key)}"
			result.append(pointer)
			value = node.get(key) if isinstance(node, dict) else None
			if index + 1 == len(steps) or not isinstance(value, dict):
				continue
			if "set" in value:
				following += [(f"{pointer}/set/{position}/of", item["of"]) for position, item in enumerate(value["set"]) if isinstance(item, dict) and "of" in item]
			elif "of" in value:
				following.append((f"{pointer}/of", value["of"]))
		frontier = following
	return result


class MappingEmitter:
	"""Turn records and variants into claims with spec-04 metadata, conflicts, gaps and stale slots."""

	def __init__(self, program: AnyValue, plans: list[MappingScopePlan], runTime: str):
		self.program = program
		self.plans = {plan.name: plan for plan in plans}
		self.runTime = runTime
		mapping = program.mapping
		self.by = f"map:{mapping.fromNamespace}->{mapping.toNamespace}"
		self.builder = ClaimsBuilder(program.targetModel, mapping.toNamespace, str(mapping.header.get("scope", mapping.toNamespace)), self.by)
		self.gaps: list[dict] = []
		self.stale: list[dict] = []
		self.mixed: list[dict] = []
		self.unidentified: list[dict] = []

	def inputs(self, occurrence: dict, info: LineInfo, variant: str | None = None) -> tuple[list[list[str]], list[str]]:
		"""Each input path's present pointers, and the conflicting pointers among them."""
		tree, conflicts = occurrence["value"], occurrence["conflicts"]
		paths = []
		for steps in info.inputs:
			segments = self.segmentKeys(occurrence, steps)
			paths.append(pointersOf(tree, segments))
		hits = sorted({pointer for pointers in paths for pointer in pointers if pointer in conflicts and pointer != variant})
		return paths, hits

	def segmentKeys(self, occurrence: dict, steps: list[str]) -> list[str]:
		return self.plans[occurrence["scope"]].segmentKeys[tuple(steps)]

	def metadata(self, occurrence: dict, info: LineInfo, paths: list[list[str]], variant: tuple[str, dict] | None) -> tuple[dict, list[str]]:
		"""`src` (shared, else the source input's), intersected `valid`, lowest `conf`; literals take the existence claim's."""
		table = occurrence["meta"]
		entries = []
		for pointers in paths:
			for pointer in pointers:
				if variant and pointer == variant[0]:
					entries.append(variant[1])
				elif isinstance(table.get(pointer), dict):
					entries.append(table[pointer])
		if not entries:
			entries = [occurrence["exists"]]
		sources = list(dict.fromkeys(entry["src"] for entry in entries))
		src = sources[0]
		if len(sources) > 1:
			chosen = info.sourcePath(paths)
			last = [pointer for pointer in chosen if (variant and pointer == variant[0]) or isinstance(table.get(pointer), dict)]
			if last:
				src = variant[1]["src"] if variant and last[-1] == variant[0] else table[last[-1]]["src"]
		meta = {"src": src, "at": self.runTime, "by": self.by}
		valid = intersect([entry["valid"] for entry in entries if "valid" in entry])
		if valid:
			meta["valid"] = valid
		confs = [entry["conf"] for entry in entries if "conf" in entry]
		if confs:
			meta["conf"] = min(confs)
		return meta, [item for item in sources if item != src]

	def record(self, plan: MappingScopePlan, occurrence: dict, record: dict, lines: list[LineInfo] | None, variant: tuple[str, dict] | None = None) -> None:
		handle = record.get("handle")
		if not isinstance(handle, str):
			return
		occurrence = {**occurrence, "scope": plan.name}
		if variant is None:
			exists = occurrence["exists"]
			meta = {"src": exists["src"], "at": self.runTime, "by": self.by}
			valid = record.get("valid") if isinstance(record.get("valid"), str) else exists.get("valid")
			if valid:
				meta["valid"] = valid
			if "conf" in exists:
				meta["conf"] = exists["conf"]
			self.builder.instance(handle, plan.target)
			self.builder.exists(handle, meta)
		for info in lines if lines is not None else plan.lines:
			value = record.get(info.section, {}).get(info.key)
			paths, conflicting = self.inputs(occurrence, info, variant[0] if variant else None)
			target = f"{plan.target}[{info.key}]" if info.section == "facets" else f"{plan.target}.{info.key}"
			if conflicting and variant is None and conflicting == info.sourcePath(paths)[-1:]:
				continue
			if conflicting:
				self.gap(target, str(MappingCodes.InputConflicting), occurrence, handle)
				self.stale.append({"src": occurrence["exists"]["src"], "s": handle, **self.slotOf(info), "reason": str(MappingCodes.InputConflicting)})
				continue
			if value is None and info.key not in record.get(info.section, {}) or isAbsent(value) or value is False and info.section == "facets":
				continue
			meta, others = self.metadata(occurrence, info, paths, variant)
			if others:
				self.mixed.append({"target": target, "handle": handle, "src": meta["src"], "sources": others})
			self.claim(plan, handle, info, value, meta, record)

	def slotOf(self, info: LineInfo) -> dict:
		return {"values": {"p": info.key}, "facets": {"facet": info.key}, "links": {"verb": info.key}}[info.section]

	def claim(self, plan: MappingScopePlan, handle: str, info: LineInfo, value: AnyValue, meta: dict, record: dict) -> None:
		builder = self.builder
		if info.section == "facets":
			builder.facet(handle, info.key, meta)
			return
		if info.section == "links":
			found = self.program.targetModel.verbs(plan.target, info.key)
			if not found:
				return
			decl, inverse = found[0]
			first, second = decl.participants[0].role, decl.participants[1].role
			members = value["set"] if isinstance(value, dict) and "set" in value else [value]
			for member in members:
				if isinstance(member, dict) and "ref" in member:
					other = member["ref"]
					builder.add({"rel": decl.path, "roles": {first: other, second: handle} if inverse else {first: handle, second: other}, **meta})
			return
		if info.also:
			# `Ref.Attr <- Path`: the claim is on the instance the record's `Ref` line refers to.
			reference = record.get("values", {}).get(info.also)
			if isinstance(reference, dict) and "ref" in reference:
				builder.add({"s": reference["ref"], "p": info.key.split(".", 1)[1], **meta, "v": cleanValue(value, builder.implicit)})
			return
		builder.add({"s": handle, "p": info.key, **meta, "v": cleanValue(value, builder.implicit)})

	def gap(self, target: str, reason: str, occurrence: dict, handle: str | None) -> None:
		entry = {"target": target, "reason": reason, "src": occurrence["exists"]["src"], "location": occurrence["location"]}
		if handle:
			entry["handle"] = handle
		self.gaps.append(entry)


def variantsOf(occurrence: dict, plan: MappingScopePlan, emitter: MappingEmitter) -> list[tuple[dict, str, dict, list[LineInfo]]]:
	"""For each conflicting pointer that is some lines' source input, one tree per conflicting claim."""
	result = []
	for pointer, claims in occurrence["conflicts"].items():
		lines = []
		for info in plan.lines:
			paths, _ = emitter.inputs({**occurrence, "scope": plan.name}, info)
			chosen = info.sourcePath(paths)
			if chosen and chosen[-1] == pointer:
				lines.append(info)
		if not lines:
			continue
		for index, claim in enumerate(claims):
			meta = {key: value for key, value in claim.items() if key != "value"}
			variant = {"value": setAt(occurrence["value"], pointer, claim["value"]), "location": f"{occurrence['location']}/variants/{index}"}
			result.append((variant, pointer, meta, lines))
	return result


def mappingStages(program: AnyValue, plans: list[MappingScopePlan], mode: str) -> dict[str, AnyValue]:
	"""The stages of a mapping program, ending with `MappingRead`."""
	members: dict[str, AnyValue] = {}
	handleStages = {}
	projectStages = {}
	variantStages = {}
	policy = Policy.Drop
	for plan in plans:
		scope = plan.program
		handleStages[plan.name] = each(project(scope.shape, plan.handleTemplate), policy)
		projectStages[plan.name] = namedStage(f"{plan.name}RecordsProject", each(project(scope.shape, scope.template), policy))
		variantStages[plan.name] = namedStage(f"{plan.name}VariantsProject", each(project(scope.shape, scope.template), policy))
		members[f"{plan.name}RecordsProject"] = projectStages[plan.name]
		members[f"{plan.name}VariantsProject"] = variantStages[plan.name]
	model = program.model

	def HandlesResolve(env, state):
		"""State → {state, correspondence, unresolved}: each scope instance's target handle (key-derived or source-qualified)."""
		index = StateIndex(state, model)
		unfolder = Unfolder(index, None)
		correspondence: dict[str, str] = {}
		unresolved: list[dict] = []
		for plan in plans:
			occurrences = []
			for handle in index.handlesOf(plan.source):
				occurrence = unfolder.occurrence(plan, handle) or {"value": {"$handle": handle, "$scope": index.scope, "$type": index.typeOf(handle)}, "location": f"/{plan.name}/{escape(handle)}"}
				occurrences.append({"value": occurrence["value"], "location": occurrence["location"]})
			result = yield from collect(handleStages[plan.name])(env, occurrences)
			resolved = iter(result["value"])
			failed = {entry.get("source") for entry in result["ledger"]}
			for occurrence in occurrences:
				if occurrence["location"] in failed:
					unresolved.append({"type": plan.target, "handle": occurrence["value"]["$handle"], "location": occurrence["location"],
						"reasons": [reasonCode(entry["reason"]) for entry in result["ledger"] if entry.get("source") == occurrence["location"]]})
					continue
				value = next(resolved)
				if isinstance(value.get("handle"), str):
					correspondence.setdefault(occurrence["value"]["$handle"], value["handle"])
		return {"state": state, "correspondence": correspondence, "unresolved": unresolved}

	def unfold(resolved):
		index = StateIndex(resolved["state"], model)
		unfolder = Unfolder(index, resolved["correspondence"])
		scopes = []
		for plan in plans:
			occurrences, skipped = [], []
			for handle in index.handlesOf(plan.source):
				if handle not in resolved["correspondence"]:
					continue
				occurrence = unfolder.occurrence(plan, handle)
				if occurrence is None:
					continue
				if plan.when is not None:
					keys = plan.segmentKeys[tuple(plan.when["path"])]
					if any(pointer in occurrence["conflicts"] for pointer in pointersOf(occurrence["value"], keys)):
						skipped.append({"target": plan.target, "reason": str(MappingCodes.InputConflicting), "src": occurrence["exists"]["src"], "location": occurrence["location"]})
						continue
					value = valueAt(occurrence["value"], keys)
					if value is None or textOf(value) != plan.when["value"]:
						continue
				occurrences.append(occurrence)
			scopes.append({"name": plan.name, "occurrences": occurrences, "skipped": skipped})
		return {**resolved, "scopes": scopes, "sources": sorted(set(index.sources.values()))}

	def MappingRecordsCollect(env, unfolded):
		"""Unfolded scopes → records, variant records and gaps, per scope."""
		scopes = []
		for plan, scope in zip(plans, unfolded["scopes"]):
			occurrences = [{"value": item["value"], "location": item["location"]} for item in scope["occurrences"]]
			main = yield from collect(projectStages[plan.name])(env, occurrences)
			emitter = MappingEmitter(program, plans, "")
			variants = []
			for occurrence in scope["occurrences"]:
				variants += [(occurrence, *item) for item in variantsOf(occurrence, plan, emitter)]
			projected = {"value": [], "ledger": []}
			if variants:
				projected = yield from collect(variantStages[plan.name])(env, [item[1] for item in variants])
			scopes.append({**scope, "records": main["value"], "gaps": main["ledger"], "variants": [
				{"occurrence": item[0]["location"], "pointer": item[2], "meta": item[3], "lines": [(info.section, info.key) for info in item[4]], "location": item[1]["location"]}
				for item in variants], "variantRecords": projected["value"], "variantGaps": projected["ledger"]})
		return {**unfolded, "scopes": scopes}

	def ClaimsEmit(env, collected):
		"""Records → {log, stale, gaps, mixed, correspondence}; claims are recorded at the run's time (`ClockRead`)."""
		runTime = yield env.ClockRead()
		return emitMapping(program, plans, collected, runTime)

	members["HandlesResolve"] = stage(HandlesResolve)
	members["InstancesUnfold"] = namedStage("InstancesUnfold", lift(unfold))
	members["MappingRecordsCollect"] = stage(MappingRecordsCollect)
	members["ClaimsEmit"] = stage(ClaimsEmit)
	members["MappingRead"] = namedStage("MappingRead", collect(pipe(members["HandlesResolve"], members["InstancesUnfold"], members["MappingRecordsCollect"], members["ClaimsEmit"])))
	return members


def emitMapping(program: AnyValue, plans: list[MappingScopePlan], collected: dict, runTime: str) -> dict:
	"""The mapping's spec-02 log and report data, in the shape re-running shares with bindings."""
	emitter = MappingEmitter(program, plans, runTime)
	for plan, scope in zip(plans, collected["scopes"]):
		byLocation = {item["location"]: item for item in scope["occurrences"]}
		records = {record["source"]: record for record in scope["records"]}
		for entry in scope["gaps"]:
			occurrence = byLocation.get(entry.get("source"))
			path = entry.get("path") or []
			if occurrence is None or len(path) < 2:
				continue
			handle = occurrence["value"].get("$target")
			section, key = path[0], path[1]
			info = plan.sectionLines.get((section, key))
			if info is not None and emitter.inputs({**occurrence, "scope": plan.name}, info)[1]:
				continue
			target = f"{plan.target}[{key}]" if section == "facets" else f"{plan.target}.{key}"
			emitter.gap(target, reasonCode(entry["reason"]), occurrence, handle)
			emitter.stale.append({"src": occurrence["exists"]["src"], "s": handle, **({"values": {"p": key}, "facets": {"facet": key}, "links": {"verb": key}}[section]), "reason": reasonCode(entry["reason"])})
		emitter.gaps += scope["skipped"]
		for occurrence in scope["occurrences"]:
			record = records.get(occurrence["location"])
			if record is None:
				continue
			emitter.record(plan, occurrence, record, None)
		variantRecords = {record["source"]: record for record in scope["variantRecords"]}
		for variant in scope["variants"]:
			record = variantRecords.get(variant["location"])
			occurrence = byLocation[variant["occurrence"]]
			if record is None:
				continue
			lines = [plan.sectionLines[(section, key)] for section, key in variant["lines"]]
			emitter.record(plan, occurrence, record, lines, (variant["pointer"], variant["meta"]))
	for item in collected["unresolved"]:
		emitter.unidentified.append({"src": "", "type": item["type"]})
		emitter.gaps.append({"target": item["type"], "reason": item["reasons"][0] if item["reasons"] else str(MappingCodes.ReferenceUnmapped), "location": item["location"]})
	log = emitter.builder.finish()
	counts: dict[str, int] = {}
	for claim in log["claims"]:
		counts[claim["src"]] = counts.get(claim["src"], 0) + 1
	tokens = sorted(set(collected["sources"]) | set(counts))
	aliases = {token: f"d{index + 1}" for index, token in enumerate(tokens)}
	log["sources"] = {alias: token for token, alias in aliases.items()}
	for claim in log["claims"] + log["retractions"]:
		claim["src"] = aliases[claim["src"]]
	stale = [{**item, "src": item["src"]} for item in emitter.stale]
	return {"log": log, "stale": stale, "unidentified": [{"src": token, "type": item["type"]} for item in emitter.unidentified for token in tokens],
		"deleted": [], "formats": {}, "gaps": emitter.gaps, "mixed": emitter.mixed, "correspondence": collected["correspondence"],
		"documents": [{"src": token, "at": runTime, "records": counts.get(token, 0)} for token in tokens]}


__all__ = ["MappingScopePlan", "StateIndex", "Unfolder", "MappingEmitter", "mappingStages", "emitMapping", "pointersOf", "valueAt", "intersect"]

# EOF
