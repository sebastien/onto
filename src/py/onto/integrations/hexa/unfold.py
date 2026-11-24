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
from hexa.shapes import Location

from ...observations.model import parseInterval
from ...ontology.model import Model, TypeExpr
from ...text import isToken
from .compiler import LineInfo
from .model import ScopeProgram
from .stages import ClaimsBuilder, cleanValue, namedStage
from .vocabulary import MappingCodes, handleOf, isAbsent, reasonCode, textOf

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
	contextOverride: bool = False
	contextualScope: bool = False
	contextInputs: list[list[str]] = field(default_factory=list)
	readsSelf: bool = False  # a line reads `$`, the scope instance
	presence: bool = False
	presenceInputs: list[list[str]] = field(default_factory=list)
	update: bool = False
	targetInputs: list[list[str]] = field(default_factory=list)
	sourceRefs: dict[str, tuple[str, list[str]]] = field(default_factory=dict)  # `@ref<n>` -> (source type, key segments)

	def activeLines(self, occurrence: dict) -> list[LineInfo]:
		"""Global lines run once; lines reading contextual slots run in their context occurrence."""
		contextual = occurrence.get("context") is not None
		return [info for info in self.lines if info.contextual == contextual]


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


def isPresent(value: AnyValue) -> bool:
	"""A known nonempty value; false and zero are present."""
	return not (value is None or isAbsent(value) or value == {"unknown": True} or value == "" or isinstance(value, dict) and "set" in value and not value["set"])


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
		"""Return a non-conflicting existence claim if possible, otherwise the first."""
		claims = [claim for claim in self.exists.get(handle, []) if not claim.get("conflict")] or self.exists.get(handle, [])
		return claims[0] if claims else None

	def handlesOf(self, typePath: str) -> list[str]:
		"""Instances of `typePath` or its specialisations, in handle order."""
		return sorted(handle for handle, item in self.instances.items() if self.model.isA(item["type"], typePath))

	def claims(self, handle: str, key: str, context: str | None) -> list[dict]:
		"""One attribute slot, never mixing claims from distinct contexts."""
		return [claim for claim in self.values.get(handle, {}).get(key, []) if claim.get("ctx") == context]


class Unfolder:
	"""Turn scope instances into trees limited to the scope's reach, with metadata tables and conflicts."""

	def __init__(self, index: StateIndex, correspondence: dict[str, str] | None, targets: dict[str, dict[str, str]] | None = None,
		scopeTargets: dict[str, dict[str, str]] | None = None, skipped: dict[str, set[str]] | None = None):
		self.index = index
		self.correspondence = correspondence
		# Source handle -> target types whose scope lines' `when` all skip it (no instance is emitted)
		self.skipped = skipped or {}
		# Source handle -> {target type: target handle}, for source types with several scope lines
		self.targets = targets or {}
		self.scopeTargets = scopeTargets or {}

	def reference(self, handle: str, children: dict, pointer: str, meta: dict, conflicts: dict, context: str | None = None) -> dict:
		"""Unfold a reference, adding target correspondence and requested children."""
		result: dict = {"ref": handle}
		if self.correspondence is not None and handle in self.correspondence:
			result["target"] = self.correspondence[handle]
			if handle in self.targets:
				# The target's type, so a target emitted by no scope (e.g. one its `when` skips) is implicit, not untyped
				result["targetType"] = next(iter(self.targets[handle]))
		if self.targets.get(handle):
			result["targets"] = self.targets[handle]
		if self.skipped.get(handle):
			result["skipped"] = sorted(self.skipped[handle])
		if children:
			result["of"] = self.subtree(handle, children, f"{pointer}/of", meta, conflicts, context)
		return result

	def value(self, value: AnyValue, segment: AnyValue, children: dict, pointer: str, meta: dict, conflicts: dict, context: str | None = None) -> AnyValue:
		"""Unfold references in a scalar or set value; leave other values unchanged."""
		if segment.kind != "ref" or not isinstance(value, dict):
			return value
		if "ref" in value:
			return self.reference(value["ref"], children, pointer, meta, conflicts, context)
		if "set" in value:
			members = [self.reference(item["ref"], children, f"{pointer}/set/{index}", meta, conflicts, context) if isinstance(item, dict) and "ref" in item else item
				for index, item in enumerate(value["set"])]
			return {**value, "set": members}
		return value

	def subtree(self, handle: str, reach: dict, base: str, meta: dict, conflicts: dict, context: str | None = None) -> dict:
		"""Unfold reachable slots and record their metadata and conflicts by pointer."""
		tree: dict = {}
		sources = self.index.sources
		for key, node in reach.items():
			segment, children = node["segment"], node["children"]
			pointer = f"{base}/{escape(key)}"
			if segment.kind == "verb":
				members = self.verb(handle, segment, children, pointer, meta, conflicts, context)
				if members is not None:
					tree[key] = members
				continue
			claims = self.index.claims(handle, key, context if segment.context else None)
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
			tree[key] = self.value(value, segment, children, pointer, meta, conflicts, context)
		return tree

	def verb(self, handle: str, segment: AnyValue, children: dict, pointer: str, meta: dict, conflicts: dict, context: str | None = None) -> dict | None:
		"""Unfold related instances for a verb, recording relation provenance."""
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
			members.append(self.reference(claim["roles"][other], children, f"{pointer}/set/{index}", meta, conflicts, context))
			meta[f"{pointer}/set/{index}"] = metaOf(claim, self.index.sources)
		meta[pointer] = metaOf(claims[0], self.index.sources)
		return {"set": members}

	def contexts(self, handle: str, reach: dict) -> set[str]:
		"""Contexts supplied along finite read paths, including paths through references."""
		result: set[str] = set()
		for key, node in reach.items():
			segment, children = node["segment"], node["children"]
			if segment.kind == "verb":
				found = self.index.model.verbs(segment.owner, key)
				if found:
					decl, inverse = found[0]
					mine, other = (decl.participants[1].role, decl.participants[0].role) if inverse else (decl.participants[0].role, decl.participants[1].role)
					for claim in self.index.relations:
						if claim["rel"] == decl.path and claim["roles"].get(mine) == handle:
							result |= self.contexts(claim["roles"][other], children)
				continue
			for claim in self.index.values.get(handle, {}).get(key, []):
				if segment.context and claim.get("ctx"):
					result.add(claim["ctx"])
				if children:
					value = claim["v"]
					for member in value.get("set", [value]) if isinstance(value, dict) else []:
						if isinstance(member, dict) and "ref" in member:
							result |= self.contexts(member["ref"], children)
		return result

	def occurrence(self, plan: MappingScopePlan, handle: str, context: str | None = None) -> dict | None:
		"""`{value: tree, location, meta, conflicts, exists}`, or None when the instance has no existence claim."""
		existence = self.index.existence(handle)
		if existence is None:
			return None
		meta: dict = {}
		conflicts: dict = {}
		tree = self.subtree(handle, plan.reach, "", meta, conflicts, context)
		existsMeta = metaOf(existence, self.index.sources)
		tree |= {"@handle": handle, "@type": self.index.typeOf(handle), "@scope": self.index.scope, "@at": existence.get("at"), "@src": existsMeta["src"]}
		if "valid" in existence:
			tree["@valid"] = existence["valid"]
		if plan.name in self.scopeTargets.get(handle, {}):
			tree["@target"] = self.scopeTargets[handle][plan.name]
		elif self.correspondence is not None and handle in self.correspondence:
			tree["@target"] = self.targets.get(handle, {}).get(plan.target, self.correspondence[handle])
		if plan.readsSelf:
			# `$` reads the instance itself: a reference translated like any other
			tree["@self"] = self.reference(handle, {}, "", meta, conflicts, context)
		for key, (typePath, keys) in plan.sourceRefs.items():
			# `ref(S, Key)`: the source instance `<S>_<key>`, a reference translated like any other
			value = valueAt(tree, keys)
			if value is not None and not isAbsent(value) and value != {"unknown": True} and not isinstance(value, dict):
				tree[key] = self.reference(handleOf(typePath, textOf(value)), {}, "", meta, conflicts, context)
		location = f"/{plan.name}/{escape(handle)}" + (f"/contexts/{escape(context)}" if context else "")
		return {"value": tree, "location": location, "meta": meta, "conflicts": conflicts, "exists": existsMeta, "context": context}


def lineApplies(plan: MappingScopePlan, occurrence: dict, info: LineInfo) -> bool:
	"""Whether a line's `when` holds, or a default's siblings' conditions all fail. An absent condition value
	fails a `when` and holds for a default; conflicts are reported as conflicting inputs before this."""
	condition = info.when or info.unless
	if condition is None:
		return True
	value = valueAt(occurrence["value"], plan.segmentKeys[tuple(condition["path"])])
	if value is None:
		return info.when is None
	text = textOf(value)
	return text == info.when["value"] if info.when else text not in info.unless["values"]


def scopeSelected(plan: MappingScopePlan, occurrence: dict) -> bool:
	if plan.when is None:
		return True
	keys = plan.segmentKeys[tuple(plan.when["path"])]
	return not any(pointer in occurrence["conflicts"] for pointer in pointersOf(occurrence["value"], keys)) and (
		textOf(valueAt(occurrence["value"], keys)) == plan.when["value"])


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
		self.emittedExistence: set[tuple] = set()
		self.emittedHandles: set[str] = set()

	def inputs(self, occurrence: dict, info: LineInfo, variant: str | None = None) -> tuple[list[list[str]], list[str]]:
		"""Each input path's present pointers, and the conflicting pointers among them."""
		tree, conflicts = occurrence["value"], occurrence["conflicts"]
		paths = []
		for steps in info.inputs:
			segments = self.segmentKeys(occurrence, steps)
			paths.append(pointersOf(tree, segments))
		hits = sorted({pointer for pointers in paths for pointer in pointers if pointer in conflicts and pointer != variant})
		if info.contextType:
			hits = sorted(set(hits) | self.contextConflicts(self.plans[occurrence["scope"]], occurrence))
		return paths, hits

	def contextConflicts(self, plan: MappingScopePlan, occurrence: dict) -> set[str]:
		"""An explicit ctx expression cannot coalesce past a conflicting input."""
		return {pointer for keys in plan.contextInputs for pointer in pointersOf(occurrence["value"], keys) if pointer in occurrence["conflicts"]}

	def segmentKeys(self, occurrence: dict, steps: list[str]) -> list[str]:
		return self.plans[occurrence["scope"]].segmentKeys[tuple(steps)]

	def metadata(self, occurrence: dict, info: LineInfo, paths: list[list[str]], variant: tuple[str, dict] | None) -> tuple[dict, list[str]] | None:
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
		valids = [entry["valid"] for entry in entries if "valid" in entry]
		if valids:
			valid = intersect(valids)
			if valid is None:
				return None
			meta["valid"] = valid
		confs = [entry["conf"] for entry in entries if "conf" in entry]
		if confs:
			meta["conf"] = min(confs)
		return meta, [item for item in sources if item != src]

	def record(self, plan: MappingScopePlan, occurrence: dict, record: dict, lines: list[LineInfo] | None, variant: tuple[str, dict] | None = None) -> None:
		"""Emit claims for an occurrence or conflict variant, reporting failed slots."""
		handle = record.get("handle")
		if not isinstance(handle, str):
			return
		occurrence = {**occurrence, "scope": plan.name}
		if plan.presence:
			if any(pointer in occurrence["conflicts"] for keys in plan.presenceInputs for pointer in pointersOf(occurrence["value"], keys)):
				if variant is None:
					self.presenceGap(plan, occurrence, handle, str(MappingCodes.InputConflicting), record)
				return
			if not isPresent(record.get("present")):
				return
		if plan.update and handle not in self.emittedHandles:
			self.gap(plan.target, str(MappingCodes.ReferenceUnmapped), occurrence, handle)
			for info in plan.activeLines(occurrence):
				self.markStale(plan, occurrence, info, handle, str(MappingCodes.ReferenceUnmapped), record, variant)
			return
		if variant is None and not plan.update:
			exists = occurrence["exists"]
			meta = {"src": exists["src"], "at": self.runTime, "by": self.by}
			valid = record.get("valid") if isinstance(record.get("valid"), str) else exists.get("valid")
			if valid:
				meta["valid"] = valid
			if "conf" in exists:
				meta["conf"] = exists["conf"]
			self.builder.instance(handle, plan.target)
			self.emittedHandles.add(handle)
			existenceKey = (handle, tuple(sorted(meta.items())))
			if existenceKey not in self.emittedExistence:
				self.builder.exists(handle, meta)
				self.emittedExistence.add(existenceKey)
		for info in lines if lines is not None else plan.activeLines(occurrence):
			value = record.get(info.section, {}).get(info.record)
			paths, conflicting = self.inputs(occurrence, info, variant[0] if variant else None)
			target = f"{plan.target}[{info.key}]" if info.section == "facets" else f"{plan.target}.{info.key}"
			if conflicting and variant is None and conflicting == info.sourcePath(paths)[-1:] and not self.contextConflicts(plan, occurrence):
				continue
			if conflicting:
				self.gap(target, str(MappingCodes.InputConflicting), occurrence, handle)
				self.markStale(plan, occurrence, info, handle, str(MappingCodes.InputConflicting), record, variant)
				continue
			if value is None and info.record not in record.get(info.section, {}) or isAbsent(value) or value is False and info.section == "facets":
				continue
			metadata = self.metadata(occurrence, info, paths, variant)
			if metadata is None:
				continue  # There is no time at which all inputs hold.
			meta, others = metadata
			if info.qualifiers:
				qualifiers = record.get("qualifiers", {}).get(info.record, {})
				attr = self.program.targetModel.lookup(plan.target, info.key)
				resolved = self.program.targetModel.resolveType(attr.type, attr.ann)
				valid = True
				for key in info.qualifiers:
					member = qualifiers.get(key)
					vocabulary = resolved.qualifierVocabularies.get(key)
					kind = self.program.targetModel.resolveType(TypeExpr(path=vocabulary)) if vocabulary else None
					if not isinstance(member, str) or member == "?" or not isToken(member) or kind is not None and not kind.open and member not in (kind.values or []):
						valid = False
						break
					meta[key] = member
				if not valid:
					self.gap(target, str(MappingCodes.ValueUnmapped), occurrence, handle)
					self.markStale(plan, occurrence, info, handle, str(MappingCodes.ValueUnmapped), record, variant)
					continue
			if info.contextType:
				context = self.contextSlot(plan, occurrence, info, record).get("ctx")
				if not context:
					self.gap(target, str(MappingCodes.ReferenceUnmapped), occurrence, handle)
					self.markStale(plan, occurrence, info, handle, str(MappingCodes.ReferenceUnmapped), record, variant)
					continue
				self.builder.instance(context, info.contextType)
				meta["ctx"] = context
			if others:
				self.mixed.append({"target": target, "handle": handle, "src": meta["src"], "sources": others})
			self.claim(plan, handle, info, value, meta, record)

	def contextSlot(self, plan: MappingScopePlan, occurrence: dict, info: LineInfo, record: dict | None = None) -> dict:
		"""The target slot context, or no key when an unresolved context requires conservative retention."""
		if not info.contextType:
			return {}
		value = (record or {}).get("ctx") if plan.contextOverride else {"ref": occurrence.get("targetContext")}
		context = value.get("ref") if isinstance(value, dict) else None
		return {"ctx": context} if isinstance(context, str) else {}

	def markStale(self, plan: MappingScopePlan, occurrence: dict, info: LineInfo, handle: str, reason: str,
		record: dict | None = None, variant: tuple[str, dict] | None = None) -> None:
		"""Retain the failed output slot for its source input's provenance, not the instance's."""
		occurrence = {**occurrence, "scope": plan.name}
		paths, _ = self.inputs(occurrence, info)
		pointers = info.sourcePath(paths) or [pointer for path in paths for pointer in path]
		entries = [variant[1] if variant and pointer == variant[0] else occurrence["meta"].get(pointer) for pointer in pointers]
		entries = [entry for entry in entries if entry is not None]
		last = entries[-1] if entries else occurrence["exists"]
		sources = {entry["src"] for entry in (last if isinstance(last, list) else [last])}
		for src in sorted(sources, key=lambda token: token or ""):
			self.stale.append({"src": src, "s": handle, **self.slotOf(info), **self.contextSlot(plan, occurrence, info, record), "reason": reason})

	def presenceGap(self, plan: MappingScopePlan, occurrence: dict, handle: str, reason: str, record: dict | None) -> None:
		"""A failed presence selector leaves both the declaration and its lines stale."""
		self.gap(plan.target, reason, occurrence, handle)
		if not plan.update:
			self.stale.append({"src": occurrence["exists"]["src"], "s": handle, "exists": True, "reason": reason})
		for info in plan.activeLines(occurrence):
			self.markStale(plan, occurrence, info, handle, reason, record)

	def projectionGap(self, plan: MappingScopePlan, occurrence: dict, record: dict | None, entry: dict,
		variant: tuple[str, dict] | None = None, lines: list[LineInfo] | None = None) -> None:
		"""Report a main or variant projection hole only for the lines active in this occurrence."""
		path = entry.get("path") or []
		if path[:1] == ["present"] and plan.presence:
			if variant is None:
				self.presenceGap(plan, occurrence, occurrence["value"]["@target"], reasonCode(entry["reason"]), record)
			return
		if len(path) < 2:
			return
		section, key = path[0], path[1]
		info = plan.sectionLines.get((section, key))
		if info is None or info not in (lines if lines is not None else plan.activeLines(occurrence)):
			return
		if not lineApplies(plan, occurrence, info):
			return  # a line whose condition is false demands nothing, not even a value
		if self.inputs({**occurrence, "scope": plan.name}, info, variant[0] if variant else None)[1]:
			return
		handle = occurrence["value"]["@target"]
		target = f"{plan.target}[{info.key}]" if section == "facets" else f"{plan.target}.{info.key}"
		self.gap(target, reasonCode(entry["reason"]), occurrence, handle)
		self.markStale(plan, occurrence, info, handle, reasonCode(entry["reason"]), record, variant)

	def slotOf(self, info: LineInfo) -> dict:
		return {"values": {"p": info.key}, "facets": {"facet": info.key}, "links": {"verb": info.key}}[info.section]

	def claim(self, plan: MappingScopePlan, handle: str, info: LineInfo, value: AnyValue, meta: dict, record: dict) -> None:
		"""Emit a value, facet, or relation claim for a projected line."""
		builder = self.builder
		if info.section == "facets":
			builder.facet(handle, info.key, meta, meta.get("ctx"))
			return
		if info.section == "links":
			found = self.program.targetModel.verbs(plan.target, info.key)
			if not found:
				return
			members = value["set"] if isinstance(value, dict) and "set" in value else [value]
			for member in members:
				if isinstance(member, dict) and "ref" in member:
					kind = member.get("type") or builder.implicit.get(member["ref"])
					matches = [(decl, inverse) for decl, inverse in found if kind is None or self.program.targetModel.isA(kind, decl.participants[0 if inverse else 1].type)]
					if len(matches) != 1:
						self.gaps.append({"target": f"{plan.target}.{info.key}", "reason": str(MappingCodes.ReferenceUnmapped), "src": meta["src"], "handle": handle})
						continue
					decl, inverse = matches[0]
					first, second = decl.participants[0].role, decl.participants[1].role
					cleanValue(member, builder.implicit)
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
		"""Record a mapping gap with its source location and optional handle."""
		entry = {"target": target, "reason": reason, "src": occurrence["exists"]["src"], "location": occurrence["location"]}
		if handle:
			entry["handle"] = handle
		self.gaps.append(entry)


def variantsOf(occurrence: dict, plan: MappingScopePlan, emitter: MappingEmitter) -> list[tuple[dict, str, dict, list[LineInfo]]]:
	"""For each conflicting pointer that is some lines' source input, one tree per conflicting claim."""
	result = []
	for pointer, claims in occurrence["conflicts"].items():
		lines = []
		for info in plan.activeLines(occurrence):
			if info.contextType and emitter.contextConflicts(plan, occurrence):
				continue
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


def implicitReferences(state: dict, model: Model, plans: list[MappingScopePlan]) -> dict:
	"""The state with the instances `ref(S, Key)` names and no claim mentions, typed `S` and implicit (as a binding's `ref`)."""
	if not any(plan.sourceRefs for plan in plans):
		return state
	index = StateIndex(state, model)
	unfolder = Unfolder(index, None)
	instances = dict(state.get("instances", {}))
	for plan in plans:
		for handle in index.handlesOf(plan.source) if plan.sourceRefs else []:
			occurrence = unfolder.occurrence(plan, handle)
			for typePath, keys in plan.sourceRefs.values():
				value = valueAt(occurrence["value"], keys) if occurrence else None
				if value is not None and not isAbsent(value) and value != {"unknown": True} and not isinstance(value, dict):
					instances.setdefault(handleOf(typePath, textOf(value)), {"type": typePath})
	return {**state, "instances": instances}


def mappingStages(program: AnyValue, plans: list[MappingScopePlan], mode: str) -> dict[str, AnyValue]:
	"""The stages of a mapping program, ending with `MappingRead`."""
	members: dict[str, AnyValue] = {}
	handleStages = {}
	presenceStages = {}
	projectStages = {}
	variantStages = {}
	policy = Policy.Drop
	for plan in plans:
		scope = plan.program
		handleStages[plan.name] = each(project(scope.shape, plan.handleTemplate), policy)
		if plan.presence and not plan.update:
			presenceStages[plan.name] = each(project(scope.shape, {"present?": scope.template["present?"], "source": Location}), policy)
		projectStages[plan.name] = namedStage(f"{plan.name}RecordsProject", each(project(scope.shape, scope.template), policy))
		variantStages[plan.name] = namedStage(f"{plan.name}VariantsProject", each(project(scope.shape, scope.template), policy))
		members[f"{plan.name}RecordsProject"] = projectStages[plan.name]
		members[f"{plan.name}VariantsProject"] = variantStages[plan.name]
	model = program.model

	def HandlesResolve(env, state):
		"""State → {state, correspondence, unresolved}: each scope instance's target handle (key-derived or source-qualified)."""
		state = implicitReferences(state, model, plans)
		index = StateIndex(state, model)
		unfolder = Unfolder(index, None)
		correspondence: dict[str, str] = {}
		targets: dict[str, dict[str, str]] = {}
		scopeTargets: dict[str, dict[str, str]] = {}
		unresolved: list[dict] = []
		selected: dict[str, set[str]] = {}  # source handle -> target types an identity scope's `when` selects it for
		present: set[str] = set()  # locations of instances with an existence claim
		for plan in sorted(plans, key=lambda item: item.update):
			if plan.update:
				unfolder = Unfolder(index, correspondence, targets, scopeTargets)
			occurrences = []
			targetConflicts = set()
			whenSelected = set()
			presenceOccurrences = []
			for handle in index.handlesOf(plan.source):
				occurrence = unfolder.occurrence(plan, handle) or {"value": {"@handle": handle, "@scope": index.scope, "@type": index.typeOf(handle)}, "location": f"/{plan.name}/{escape(handle)}"}
				if "exists" in occurrence:
					present.add(occurrence["location"])
					if not plan.update and scopeSelected(plan, occurrence):
						whenSelected.add(handle)
				if plan.name in presenceStages and "exists" in occurrence:
					contexts = sorted(unfolder.contexts(handle, plan.reach)) if plan.contextualScope else [None]
					for context in contexts:
						candidate = unfolder.occurrence(plan, handle, context) if context else occurrence
						if scopeSelected(plan, candidate) and not any(pointer in candidate["conflicts"]
							for path in plan.presenceInputs for pointer in pointersOf(candidate["value"], path)):
							presenceOccurrences.append(candidate)
				if plan.update:
					if plan.when:
						keys = plan.segmentKeys[tuple(plan.when["path"])]
						if any(pointer in occurrence.get("conflicts", {}) for pointer in pointersOf(occurrence["value"], keys)):
							unresolved.append({"type": plan.target, "handle": handle, "location": occurrence["location"], "reasons": [str(MappingCodes.InputConflicting)]})
							continue
						value = valueAt(occurrence["value"], keys)
						if value is None or textOf(value) != plan.when["value"]:
							continue
					if any(pointer in occurrence.get("conflicts", {}) for path in plan.presenceInputs for pointer in pointersOf(occurrence["value"], path)):
						unresolved.append({"type": plan.target, "handle": handle, "location": occurrence["location"], "reasons": [str(MappingCodes.InputConflicting)]})
						continue
					if any(pointer in occurrence.get("conflicts", {}) for path in plan.targetInputs for pointer in pointersOf(occurrence["value"], path)):
						targetConflicts.add(occurrence["location"])
				occurrences.append({"value": occurrence["value"], "location": occurrence["location"]})
			result = yield from collect(handleStages[plan.name])(env, occurrences)
			presenceSelected = set()
			if presenceOccurrences:
				projected = yield from collect(presenceStages[plan.name])(env, presenceOccurrences)
				byLocation = {item["location"]: item["value"]["@handle"] for item in presenceOccurrences}
				presenceSelected = {byLocation[item["source"]] for item in projected["value"] if isPresent(item.get("present"))}
			resolved = iter(result["value"])
			failed = {entry.get("source") for entry in result["ledger"]}
			for occurrence in occurrences:
				if occurrence["location"] in failed:
					unresolved.append({"type": plan.target, "handle": occurrence["value"]["@handle"], "location": occurrence["location"],
						"reasons": [reasonCode(entry["reason"]) for entry in result["ledger"] if entry.get("source") == occurrence["location"]]})
					continue
				value = next(resolved)
				if plan.update and plan.presence and not isPresent(value.get("present")):
					continue
				if occurrence["location"] in targetConflicts:
					unresolved.append({"type": plan.target, "handle": occurrence["value"]["@handle"], "location": occurrence["location"], "reasons": [str(MappingCodes.InputConflicting)]})
					continue
				if isinstance(value.get("handle"), str):
					if not plan.update:
						# An instance known only by reference (no existence claim) cannot be tested: it is not skipped
						active = presenceSelected if plan.presence else whenSelected
						if occurrence["location"] not in present or occurrence["value"]["@handle"] in active:
							selected.setdefault(occurrence["value"]["@handle"], set()).add(plan.target)
						correspondence.setdefault(occurrence["value"]["@handle"], value["handle"])
						targets.setdefault(occurrence["value"]["@handle"], {}).setdefault(plan.target, value["handle"])
					scopeTargets.setdefault(occurrence["value"]["@handle"], {})[plan.name] = value["handle"]
				elif plan.update:
					unresolved.append({"type": plan.target, "handle": occurrence["value"]["@handle"], "location": occurrence["location"], "reasons": [str(MappingCodes.ReferenceUnmapped)]})
		skipped = {handle: set(types) - selected.get(handle, set()) for handle, types in targets.items() if set(types) - selected.get(handle, set())}
		return {"state": state, "correspondence": correspondence, "targets": targets, "scopeTargets": scopeTargets, "unresolved": unresolved, "skipped": skipped}

	def unfold(resolved):
		index = StateIndex(resolved["state"], model)
		unfolder = Unfolder(index, resolved["correspondence"], resolved.get("targets"), resolved.get("scopeTargets"), resolved.get("skipped"))
		scopes = []
		for plan in plans:
			occurrences, skipped = [], []
			for handle in index.handlesOf(plan.source):
				if plan.name not in resolved.get("scopeTargets", {}).get(handle, {}):
					continue
				contexts = [None] + sorted(unfolder.contexts(handle, plan.reach)) if any(info.contextual for info in plan.lines) or plan.contextualScope else [None]
				for context in contexts:
					if context is None and plan.contextualScope:
						continue
					occurrence = unfolder.occurrence(plan, handle, context)
					if occurrence is None:
						continue
					occurrence["targetContext"] = resolved["correspondence"].get(context)
					if plan.when is not None:
						keys = plan.segmentKeys[tuple(plan.when["path"])]
						if any(pointer in occurrence["conflicts"] for pointer in pointersOf(occurrence["value"], keys)):
							skipped.append({"occurrence": occurrence, "target": plan.target, "reason": str(MappingCodes.InputConflicting), "src": occurrence["exists"]["src"], "location": occurrence["location"]})
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
				{"occurrence": item[0]["location"], "pointer": item[2], "meta": item[3], "lines": [(info.section, info.record) for info in item[4]], "location": item[1]["location"]}
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
	for plan, scope in sorted(zip(plans, collected["scopes"]), key=lambda item: item[0].update):
		byLocation = {item["location"]: item for item in scope["occurrences"]}
		records = {record["source"]: record for record in scope["records"]}
		for entry in scope["gaps"]:
			occurrence = byLocation.get(entry.get("source"))
			if occurrence is not None:
				emitter.projectionGap(plan, occurrence, records.get(occurrence["location"]), entry)
		for skipped in scope["skipped"]:
			occurrence = skipped["occurrence"]
			emitter.gaps.append({key: value for key, value in skipped.items() if key != "occurrence"})
			handle = occurrence["value"]["@target"]
			emitter.stale.append({"src": skipped["src"], "s": handle, "reason": skipped["reason"]})
			for info in plan.activeLines(occurrence):
				emitter.markStale(plan, occurrence, info, handle, skipped["reason"])
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
			for entry in scope["variantGaps"]:
				if entry.get("source") == variant["location"]:
					emitter.projectionGap(plan, occurrence, record, entry, (variant["pointer"], variant["meta"]), lines)
			emitter.record(plan, occurrence, record, lines, (variant["pointer"], variant["meta"]))
	for item in collected["unresolved"]:
		emitter.unidentified.append({"src": "", "type": item["type"]})
		emitter.gaps.append({"target": item["type"], "reason": item["reasons"][0] if item["reasons"] else str(MappingCodes.ReferenceUnmapped), "location": item["location"]})
	log = emitter.builder.finish()
	counts: dict[str, int] = {}
	for claim in log["claims"]:
		if (src := claim.get("src")) is not None:
			counts[src] = counts.get(src, 0) + 1
	tokens = sorted(set(collected["sources"]) | set(counts))
	aliases = {token: f"d{index + 1}" for index, token in enumerate(tokens)}
	log["sources"] = {alias: token for token, alias in aliases.items()}
	for claim in log["claims"] + log["retractions"]:
		if (src := claim.pop("src", None)) is not None:
			claim["src"] = aliases[src]
	stale = [{**item, "src": item["src"]} for item in emitter.stale]
	return {"log": log, "stale": stale, "unidentified": [{"src": token, "type": item["type"]} for item in emitter.unidentified for token in tokens],
		"deleted": [], "formats": {}, "gaps": emitter.gaps, "mixed": emitter.mixed, "correspondence": collected["correspondence"],
		"documents": [{"src": token, "at": runTime, "records": counts.get(token, 0)} for token in tokens]}


__all__ = ["MappingScopePlan", "StateIndex", "Unfolder", "MappingEmitter", "mappingStages", "emitMapping", "pointersOf", "valueAt", "intersect"]

# EOF
