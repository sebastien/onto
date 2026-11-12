"""Module: integrations.hexa.stages — record collection, field discovery, claim emission and the binding stage namespace.

BindingRead: DocumentsRead → ClaimsEmit
DocumentsRead: parallel(DocumentRecordsCollect), with DocumentFieldsDiscover when an inventory is given
DocumentRecordsCollect: <Type>RecordsSelect → <Type>RecordsProject, for each scope line
"""

from __future__ import annotations

import re
from typing import Any as AnyValue

from hexa.combinators import Policy, collect, each, parallel, pipe, project, select, stage
from hexa.runtime import Ledger, report
from hexa.shapes import Failure

from ...expressions import printExpression
from ...inventory.operations import documentFields
from ...ontology.model import Model
from ...text import annotation
from .model import ScopeProgram
from .vocabulary import BindingCodes, isAbsent, reasonCode

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


EACH = {"each": True}
RE_DECIMAL_TEXT = re.compile(r"-?[0-9]+(?:\.([0-9]+))?")


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def namedStage(name: str, inner: AnyValue) -> AnyValue:
	"""A stage carrying `name` in traces and ledger targets, without hexa's process-wide registration."""

	def run(env, *inputs):
		return (yield from inner(env, *inputs))

	run.__name__ = run.__qualname__ = name
	return stage(run)


def itemPolicy(mode: str) -> tuple[AnyValue, dict]:
	"""Strict runs abort on a scope occurrence that is not an object; lenient runs drop it. Both report it."""

	def reason(failure):
		return BindingCodes.TypeMismatch if failure.kind is Failure.Shape else failure.code

	if mode == "strict":
		return Policy.Abort, {"on": [Failure.Shape], "reason": reason}
	return Policy.Drop, {"reason": reason}


def combine(parent: dict, child: dict) -> dict:
	"""A child occurrence located from the document root, with its enclosing blocks' captures."""
	result = {"value": child["value"], "location": parent["location"] + child["location"]}
	captures = parent.get("captures")
	if "captures" in child:
		captures = captures.copy() if captures is not None else None
		if captures is None:
			captures = child["captures"]
		else:
			for key, value in child["captures"].items():
				captures[key] = value
				if key in child["captures"].evidence:
					captures.evidence[key] = child["captures"].evidence[key]
	if captures is not None:
		result["captures"] = captures
	if "origin" in child:
		result["origin"] = child["origin"]
	return result


def selectStage(scope: ScopeProgram) -> AnyValue:
	"""`<Name>RecordsSelect`: enumerate occurrences level by level; a missing path is a gap below its parent only."""
	levels = [select(level) for level in scope.levels]
	owner: list[AnyValue] = []

	def run(env, document):
		occurrences = [{"value": document, "location": ""}]
		for level in levels:
			following = []
			for parent in occurrences:
				try:
					found = yield from level(env, parent["value"])
				except Failure as failure:
					if failure.kind is not Failure.Gap:
						raise
					fields = {"source": parent["location"] + (failure.location or "")}
					if failure.path is not None:
						fields["path"] = failure.path
					yield report(Ledger.Gap, target=owner[0], reason=failure.code, **fields)
					continue
				following += [combine(parent, child) for child in found]
			occurrences = following
		return occurrences

	run.__name__ = run.__qualname__ = f"{scope.name}RecordsSelect"
	owner.append(stage(run))
	return owner[0]


def scopeStages(scope: ScopeProgram, mode: str) -> tuple[AnyValue, AnyValue]:
	"""`<Name>RecordsSelect` (a missing path is a gap, no records) and `<Name>RecordsProject`."""
	policy, options = itemPolicy(mode)
	projectStage = namedStage(f"{scope.name}RecordsProject", each(project(scope.shape, scope.template, outer=list(scope.outer)), policy, **options))
	return selectStage(scope), projectStage


def cleanValue(value: AnyValue, types: dict[str, str]) -> AnyValue:
	"""Strip the integration's reference types, recording them for implicit instances."""
	if isinstance(value, dict) and "ref" in value:
		if "type" in value:
			types.setdefault(value["ref"], value["type"])
		return {"ref": value["ref"]}
	if isinstance(value, dict) and "set" in value:
		return {**value, "set": [cleanValue(item, types) for item in value["set"]]}
	return value


def refs(value: AnyValue) -> list[str]:
	if isinstance(value, dict) and "ref" in value:
		return [value["ref"]]
	if isinstance(value, dict) and "set" in value:
		return [item["ref"] for item in value["set"] if isinstance(item, dict) and "ref" in item]
	return []


def handleOf(value: AnyValue) -> str | None:
	if isinstance(value, dict) and "ref" in value:
		return value["ref"]
	return value if isinstance(value, str) else None


def rawValues(value: AnyValue, steps: list[AnyValue], found: dict[str, list]) -> None:
	"""Raw scalar values by field path in inventory syntax."""
	if isinstance(value, dict):
		for key, item in value.items():
			rawValues(item, steps + [key], found)
	elif isinstance(value, list):
		for item in value:
			rawValues(item, steps + [EACH], found)
	elif steps and value is not None:
		found.setdefault(printExpression({"path": steps}, binding=True), []).append(value)


def writingFormats(document: AnyValue, csv: bool, fields: set[str]) -> dict[str, dict[str, int]]:
	"""`DocumentFormatsDiscover`: counts of the writing formats of each bound field's raw values; names only."""
	found: dict[str, list] = {}
	rawValues(document, [{"root": True}] if csv or isinstance(document, list) else [], found)
	tallies: dict[str, dict[str, int]] = {}
	for path in sorted(fields & set(found)):
		for value in found[path]:
			if (name := classify(value)) is not None:
				tallies.setdefault(path, {})
				tallies[path][name] = tallies[path].get(name, 0) + 1
	return tallies


def classify(value: AnyValue) -> str | None:
	"""A raw value's writing format: `decimals:N` for decimal text, else `trim` or `padded` for text."""
	if not isinstance(value, str):
		return None
	if match := RE_DECIMAL_TEXT.fullmatch(value):
		return f"decimals:{len(match[1] or '')}"
	return "padded" if value != value.strip() else "trim"


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class ClaimsBuilder:
	"""Assemble a spec-02 JSON log from records, numbering claims in record order."""

	def __init__(self, model: Model, ontology: str, scope: str, by: str):
		self.model = model
		self.data: dict[str, AnyValue] = {"format": "onto.observations/1", "obs": {"ontology": ontology, "scope": scope}, "sources": {},
			"instances": {}, "claims": [], "retractions": []}
		self.by = by
		self.aliases: dict[str, str] = {}
		self.implicit: dict[str, str] = {}
		self.headers: dict[str, tuple[int, dict]] = {}
		self.n = 0

	def alias(self, token: str) -> str:
		if token not in self.aliases:
			self.aliases[token] = f"d{len(self.aliases) + 1}"
			self.data["sources"][self.aliases[token]] = token
		return self.aliases[token]

	def instance(self, handle: str, typePath: str) -> None:
		existing = self.data["instances"].get(handle)
		if existing is None or self.model.isA(typePath, existing["type"]) and typePath != existing["type"]:
			self.data["instances"][handle] = {"type": typePath}

	def add(self, claim: dict, retraction: bool = False) -> dict:
		self.n += 1
		claim = {"n": self.n, **claim}
		self.data["retractions" if retraction else "claims"].append(claim)
		return claim

	def exists(self, handle: str, meta: dict) -> dict:
		"""An existence claim, the header facet claims of the same metadata share its statement (`n`)."""
		claim = self.add({"s": handle, "exists": True, **meta})
		self.headers[handle] = (claim["n"], meta)
		return claim

	def facet(self, handle: str, name: str, meta: dict, ctx: str | None = None) -> None:
		"""A facet claim; in spec-02 text `h[F]` also asserts existence, so a facet whose metadata differs
		from its header gets its own statement with an existence claim, as the text form reads it back."""
		meta = {key: value for key, value in meta.items() if key not in ("valid", "ctx")}
		header = self.headers.get(handle)
		if header is not None and {key: value for key, value in header[1].items() if key not in ("valid", "ctx")} == meta:
			n = header[0]
		else:
			self.n += 1
			n = self.n
			self.data["claims"].append({"n": n, "s": handle, "exists": True, **meta})
		self.data["claims"].append({"n": n, "s": handle, "facet": name, **meta, **({"ctx": ctx} if ctx else {})})

	def contextual(self, typePath: str, member: str, isFacet: bool) -> bool:
		facet = self.model.facets(typePath).get(member if isFacet else member.split(".")[0])
		return bool(facet is not None and (isFacet or self.model.facetOf(typePath, member) is facet) and annotation(facet.ann, "ctx"))

	def record(self, record: dict, meta: dict) -> None:
		"""Existence, values, facets and links of one identified record (or `- h` when deleted)."""
		handle, typePath = record["handle"], record["type"]
		self.instance(handle, typePath)
		if record.get("deleted") is True:
			self.add({"s": handle, "exists": True, **meta}, retraction=True)
			return
		valid = record.get("valid")
		self.exists(handle, {**meta, **({"valid": valid} if isinstance(valid, str) else {})})
		ctx = handleOf(record.get("ctx"))
		relation = self.model.get(typePath)
		for name, value in record.get("facets", {}).items():
			if value is True:
				self.facet(handle, name, meta, ctx if ctx and self.contextual(typePath, name, True) else None)
		for name, value in record.get("values", {}).items():
			if isAbsent(value):
				continue
			claim = {"s": handle, "p": name, **meta, "v": cleanValue(value, self.implicit)}
			if ctx and self.contextual(typePath, name, False):
				claim["ctx"] = ctx
			self.add(claim)
		for verb, value in record.get("links", {}).items():
			if isAbsent(value):
				continue
			cleanValue(value, self.implicit)
			found = self.model.verbs(typePath, verb) if relation is None or relation.kind == "entity" else []
			if not found:
				continue
			decl, inverse = found[0]
			first, second = decl.participants[0].role, decl.participants[1].role
			for other in refs(value):
				roles = {first: other, second: handle} if inverse else {first: handle, second: other}
				self.add({"rel": decl.path, "roles": roles, **meta})

	def finish(self) -> dict:
		for handle, typePath in self.implicit.items():
			if handle not in self.data["instances"]:
				self.data["instances"][handle] = {"type": typePath}
		self.data["instances"] = dict(sorted(self.data["instances"].items()))
		return self.data


def gapTarget(typePath: str, path: list) -> str:
	"""The onto path a template hole stands for: `T.Attr`, `T[F]`, `T.verb`, or the type for a record."""
	if len(path) >= 2 and path[0] in ("values", "links"):
		return f"{typePath}.{path[1]}"
	if len(path) >= 2 and path[0] == "facets":
		return f"{typePath}[{path[1]}]"
	return typePath


def documentGaps(records: list[dict], gaps: list[dict], scopes: dict[str, ScopeProgram], src: str) -> tuple[list[dict], list[dict], list[dict]]:
	"""Report gaps, stale slots (their input produced a gap: kept, not retracted) and unidentified scope types."""
	bySource = {(record.get("scope"), record.get("source")): record for record in records}
	report, stale, unidentified = [], [], []
	for entry in gaps:
		scope = next((item for item in scopes.values() if entry.get("target") in (f"{item.name}RecordsProject", f"{item.name}RecordsSelect")), None)
		path = entry.get("path") or []
		record = bySource.get((scope.name, entry.get("source"))) if scope else None
		gap = {"target": gapTarget(scope.type, path) if scope else str(entry.get("target")), "reason": reasonCode(entry["reason"]), "src": src}
		if "source" in entry:
			gap["location"] = entry["source"]
		if record is not None and "handle" in record:
			gap["handle"] = record["handle"]
		if record is not None and isinstance(record.get("origin"), dict):
			gap["origin"] = record["origin"]
		if path[:1] != ["formats"]:
			report.append(gap)
		if scope is None:
			continue
		if path[:1] == ["handle"] or record is None and entry.get("target") == f"{scope.name}RecordsProject":
			unidentified.append({"src": src, "type": scope.type})
		elif record is not None and "handle" in record and len(path) >= 2 and path[0] in ("values", "facets", "links"):
			kind = {"values": "p", "facets": "facet", "links": "verb"}[path[0]]
			stale.append({"src": src, "s": record["handle"], kind: path[1], "reason": gap["reason"]})
	return report, stale, unidentified


def emitClaims(program: AnyValue, documents: list[dict], runTime: str | None) -> dict:
	"""`ClaimsEmit`: the run's spec-02 log, stale slots, format tallies and observed fields."""
	binding = program.binding
	builder = ClaimsBuilder(program.model, binding.ontology, str(binding.header.get("scope", binding.ontology)), f"bind:{binding.ontology}")
	scopes = {scope.name: scope for scope in program.scopes}
	stale: list[dict] = []
	unidentified: list[dict] = []
	formats: dict[str, dict[str, int]] = {}
	deleted: list[dict] = []
	gaps: list[dict] = []
	for document in documents:
		alias = builder.alias(document["src"])
		for record in document["records"]:
			for path, name in record.get("formats", {}).items():
				if isinstance(name, str):
					formats.setdefault(path, {})
					formats[path][name] = formats[path].get(name, 0) + 1
			if "handle" not in record:
				continue
			meta = {"src": alias, "at": record["at"] if isinstance(record.get("at"), str) else runTime, "by": builder.by}
			if record.get("deleted") is True:
				deleted.append({"src": document["src"], "s": record["handle"]})
			builder.record(record, meta)
		for path, tally in document.get("writing", {}).items():
			for name, count in tally.items():
				formats.setdefault(path, {})
				formats[path][name] = formats[path].get(name, 0) + count
		documentReport, documentStale, documentUnidentified = documentGaps(document["records"], document["gaps"], scopes, document["src"])
		gaps += documentReport
		stale += documentStale
		unidentified += documentUnidentified
	result = {"log": builder.finish(), "stale": stale, "unidentified": unidentified, "deleted": deleted, "formats": formats, "gaps": gaps,
		"documents": [documentSummary(document, runTime) for document in documents]}
	if program.inventory is not None:
		result["fields"] = fieldsReport(program, documents)
	return result


def documentSummary(document: dict, runTime: str | None) -> dict:
	"""A document's `src`, `replaces`, run time `at` and number of records read."""
	times = [record["at"] for record in document["records"] if isinstance(record.get("at"), str)]
	result = {key: document[key] for key in ("src", "replaces") if key in document}
	return result | {"at": times[0] if times else runTime, "records": sum("handle" in record for record in document["records"])}


def fieldsReport(program: AnyValue, documents: list[dict]) -> dict:
	"""Fields seen but missing from the inventory (with document counts), and inventory fields seen with other types."""
	types = program.inventory.types()
	missing: dict[str, int] = {}
	mismatched: dict[str, dict] = {}
	for document in documents:
		for path, seen in document.get("fields", {}).items():
			if path not in types:
				missing[path] = missing.get(path, 0) + 1
			elif types[path] not in seen:
				entry = mismatched.setdefault(path, {"inventory": types[path], "seen": []})
				entry["seen"] = sorted(set(entry["seen"]) | set(seen))
	return {"missing": dict(sorted(missing.items())), "mismatched": dict(sorted(mismatched.items()))}


def needsClock(documents: list[dict]) -> bool:
	return any("handle" in record and not isinstance(record.get("at"), str) for document in documents for record in document["records"])


def bindingStages(program: AnyValue) -> dict[str, AnyValue]:
	"""The stages of a binding program, by name, ending with `BindingRead`."""
	members: dict[str, AnyValue] = {}
	pairs = []
	for scope in program.scopes:
		selecting, projecting = scopeStages(scope, program.mode)
		members[selecting.name], members[projecting.name] = selecting, projecting
		pairs.append((selecting, projecting))
	csv = program.binding.header.get("format") == "csv"

	def scopesRead(env, document):
		records = []
		for selecting, projecting in pairs:
			occurrences = yield from selecting(env, document)
			records += yield from projecting(env, occurrences)
		return records

	collected = collect(stage(scopesRead))

	def DocumentFieldsDiscover(env, item):
		"""{src, document} → {src, fields}: field paths in inventory syntax and their JSON types."""
		return (yield {"src": item["src"], "fields": documentFields(item["document"], csv)})

	def DocumentRecordsCollect(env, item):
		"""{src, document} → {src, records, gaps}; ledger locations point into this document only."""
		result = yield from collected(env, item["document"])
		output = {"src": item["src"], "records": result["value"], "gaps": result["ledger"]}
		if "replaces" in item:
			output["replaces"] = item["replaces"]
		if program.inventory is not None:
			output["fields"] = (yield from members["DocumentFieldsDiscover"](env, item))["fields"]
		if program.formats is not None:
			output["writing"] = (yield from members["DocumentFormatsDiscover"](env, item))["formats"]
		return output

	def ClaimsEmit(env, documents):
		"""[{src, records, gaps, fields?}] → {log, stale, formats, fields?}; reads the clock only without `@at`."""
		runTime = (yield env.ClockRead()) if needsClock(documents) or not any(record for document in documents for record in document["records"]) else None
		return emitClaims(program, documents, runTime)

	def DocumentFormatsDiscover(env, item):
		"""{src, document} → {src, formats}: writing formats (`decimals:N`, `trim`, `padded`) of bound fields, names and counts only."""
		return (yield {"src": item["src"], "formats": writingFormats(item["document"], csv, program.writeFields)})

	members["DocumentFieldsDiscover"] = stage(DocumentFieldsDiscover)
	members["DocumentFormatsDiscover"] = stage(DocumentFormatsDiscover)
	members["DocumentRecordsCollect"] = stage(DocumentRecordsCollect)
	members["DocumentsRead"] = namedStage("DocumentsRead", parallel(members["DocumentRecordsCollect"], Policy.Abort))
	members["ClaimsEmit"] = stage(ClaimsEmit)
	members["BindingRead"] = namedStage("BindingRead", collect(pipe(members["DocumentsRead"], members["ClaimsEmit"])))
	return members


__all__ = ["namedStage", "scopeStages", "emitClaims", "bindingStages", "ClaimsBuilder", "documentGaps", "gapTarget", "cleanValue", "needsClock", "writingFormats", "classify"]

# EOF
