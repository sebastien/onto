"""Module: observations.operations — typed loading, identity reconciliation and interchange."""

from __future__ import annotations

from copy import (
	deepcopy,
)
from dataclasses import (
	replace,
)
from typing import (
	Any,
)
from ..ontology import (
	Model,
	Ontology,
	isSymmetric,
)
from ..text import (
	Diagnostics,
	FormatError,
	Loc,
	Source,
)
from .formatter import (
	_printObservationsLog,
	observationsToJson,
	printObservationsLog,
	printObservationsState,
)
from .model import (
	Claim,
	Gap,
	Observations,
	ObservationsDocument,
	_markImplicit,
	_order,
	_slot,
	_useType,
	_valueIdentity,
	_valueKey,
	parseInterval,
)
from .parser import (
	_Resolver,
	_readObservationsJson,
	parseObservations,
)

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def _overlaps(left: Claim, right: Claim) -> bool:
	a, b = parseInterval(left["valid"]) if "valid" in left else (None, None)
	c, d = parseInterval(right["valid"]) if "valid" in right else (None, None)
	return (a is None or d is None or a <= d) and (c is None or b is None or c <= b)


def _retracts(retraction: Claim, claim: Claim, sources: dict[str, str]) -> bool:
	withdrawn = retraction.get("of", retraction.get("src"))
	claimed = claim.get("src")
	if sources.get(withdrawn, withdrawn) != sources.get(claimed, claimed) or _order(claim) > _order(retraction):
		return False
	if "by" in retraction and retraction["by"] != claim.get("by"):
		return False
	if "ctx" in retraction and retraction["ctx"] != claim.get("ctx"):
		return False
	for kind in ("same", "distinct"):
		if kind in retraction:
			return kind in claim and set(retraction[kind]) == set(claim[kind])
		if kind in claim:
			return "p" not in retraction and "facet" not in retraction and retraction.get("s") in claim[kind]
	if "rel" in retraction:
		return _slot(retraction) == _slot(claim) or bool(retraction.get("s") and retraction["s"] == claim.get("s"))
	if "s" not in claim or retraction["s"] != claim["s"]:
		return "p" not in retraction and "facet" not in retraction and (
			claim.get("ctx") == retraction["s"] or "rel" in claim and "s" not in claim and retraction["s"] in claim["roles"].values()
		)
	if "facet" in retraction:
		return claim.get("facet") == retraction["facet"] or claim.get("p", "").startswith(f"{retraction['facet']}.")
	if "p" in retraction:
		return claim.get("p") == retraction["p"] or claim.get("p", "").startswith(retraction["p"] + ".")
	return True


def _canonicalise(model: Model, claims: list[Claim], instances: dict[str, dict[str, str | bool]], diag: Diagnostics, mode: str) -> tuple[list[Claim], dict[str, dict[str, str | bool]]]:
	"""Apply surviving identity links before slot reconciliation; keep links in their original handles."""
	parents = {handle: handle for handle in instances}
	types = {handle: instance["type"] for handle, instance in instances.items()}
	groups = {handle: {handle} for handle in instances}
	# ponytail: group snapshots detect opposing joins; compact the merge history if identity logs get large.
	joins: list[tuple[set[str], set[str]]] = []
	held: set[int] = set()

	def root(handle: str) -> str:
		while parents[handle] != handle:
			parents[handle] = parents[parents[handle]]
			handle = parents[handle]
		return handle

	def conflict(claim: Claim, message: str) -> None:
		held.add(id(claim))
		if mode == "strict":
			diag.error("identity", message)
		else:
			diag.warn("identity", message)

	distinct = [claim["distinct"] for claim in claims if "distinct" in claim]
	for claim in sorted((claim for claim in claims if "same" in claim), key=_order):
		left, right = claim["same"]
		a, b = root(left), root(right)
		if a == b:
			if any(left in aliases and right in canonical for canonical, aliases in joins):
				conflict(claim, f"Identity link '{left} = {right}' opposes the earlier canonical choice '{a}'")
			continue
		if any({root(x), root(y)} == {a, b} for x, y in distinct):
			conflict(claim, f"Identity link '{left} = {right}' contradicts a distinct link")
			continue
		if not (types[a] == types[b] or model.isA(types[a], types[b]) or model.isA(types[b], types[a])):
			conflict(claim, f"Identity groups '{a}' and '{b}' have incompatible refined types")
			continue
		joins.append((set(groups[a]), set(groups[b])))
		parents[b] = a
		groups[a].update(groups.pop(b))
		if model.isA(types[b], types[a]):
			types[a] = types[b]
	diag.check()

	def value(item: Any) -> Any:
		if isinstance(item, dict) and "ref" in item:
			return {"ref": root(item["ref"])}
		if isinstance(item, dict) and "set" in item:
			# Aliases can collapse several previously distinct set members.
			members = {_valueKey(value(member)): value(member) for member in item["set"]}
			return item | {"set": [members[key] for key in sorted(members)]}
		return item

	result = []
	for claim in claims:
		if id(claim) in held:
			# Kept in the audit log, not in the applied state: sorting must not retry a held link.
			continue
		if "same" in claim or "distinct" in claim:
			result.append(claim)
			continue
		normal = dict(claim)
		for key in ("s", "ctx"):
			if key in normal:
				normal[key] = root(normal[key])
		if "v" in normal:
			normal["v"] = value(normal["v"])
		if "roles" in normal:
			normal["roles"] = {role: root(handle) if handle != "?" else "?" for role, handle in normal["roles"].items()}
			if isSymmetric(model.get(normal["rel"])) and "?" not in normal["roles"].values():
				roles = list(normal["roles"])
				left, right = sorted(normal["roles"].values())
				normal["roles"] = {roles[0]: left, roles[1]: right}
		result.append(normal)
	registry = {handle: {"type": types[root(handle)] if root(handle) == handle else instance["type"]} for handle, instance in instances.items()}
	return result, registry


def _gapContent(gaps: list[Gap]) -> list[str]:
	return sorted(_valueKey({"text": gap.text, "meta": gap.meta, "ctx": gap.ctx,
		"diagnostics": sorted({(item.code, item.message) for item in gap.diagnostics})}) for gap in gaps)


def _claimContent(claims: list[Claim]) -> list[str]:
	# NOTE: Ordinals are source-document locations; printing may regroup headers and renumber them.
	def content(claim: Claim) -> Claim:
		result = {key: value for key, value in claim.items() if key not in ("n", "conflict")}
		if isinstance(result.get("v"), dict) and "set" in result["v"]:
			result["v"] = result["v"] | {"set": sorted(result["v"]["set"], key=_valueKey)}
		return result
	return sorted(_valueKey(content(claim)) for claim in claims)


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Operator:
	"""Observation operations sharing an ontology and strict/lenient mode."""

	def __init__(self, ontology: Ontology, mode: str = "strict"):
		if mode not in ("strict", "lenient"):
			raise ValueError("mode must be strict or lenient")
		self.ontology = ontology
		self.mode = mode

	def resolve(self, doc: ObservationsDocument) -> Observations:
		"""Resolve a parsed document against this operator's ontology."""
		return resolveObservations(self.ontology, doc, self.mode)

	def load(self, source: Source) -> Observations:
		"""Parse and type a source in this operator's mode."""
		return loadObservations(self.ontology, source, self.mode)

	def reconcile(self, observations: Observations) -> Observations:
		"""Apply withdrawals and identity links without mutating the input."""
		return reconcileObservations(self.ontology, observations, self.mode)

	def format(self, source: Source, form: str = "state") -> str:
		"""Load and format a source as state or audit log text."""
		return formatObservations(self.ontology, source, form, self.mode)

	def printLog(self, observations: Observations) -> str:
		"""Print a gap-free audit log."""
		return printObservationsLog(self.ontology, observations)

	def printState(self, observations: Observations) -> str:
		"""Print an already reconciled, gap-free state."""
		return printObservationsState(self.ontology, observations)

	def toJson(self, observations: Observations) -> dict[str, Any]:
		"""Export typed observations without changing them."""
		return observationsToJson(observations)

	def fromJson(self, data: Any, name: str = "observations.json") -> Observations:
		"""Validate JSON in this operator's mode."""
		return observationsFromJson(self.ontology, data, name, self.mode)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def reconcileObservations(ontology: Ontology, observations: Observations, mode: str = "strict") -> Observations:
	"""Apply withdrawals, identity links and supersession; `mode` controls identity conflicts."""
	if mode not in ("strict", "lenient"):
		raise ValueError("mode must be strict or lenient")
	if mode == "strict" and observations.gaps:
		raise FormatError([replace(item, level="error") for gap in observations.gaps for item in gap.diagnostics])
	model = Model(ontology)
	diag = Diagnostics(list(observations.diagnostics))
	instances = observations.instances
	active: dict[tuple[tuple[str, str, str], str | None], list[Claim]] = {}

	def source(claim: Claim) -> str | None:
		name = claim.get("src")
		return observations.sources.get(name, name)

	def multi(claim: Claim) -> bool:
		if "p" not in claim:
			return False
		attr = model.lookup(instances[claim["s"]]["type"], claim["p"])
		return (attr.card or model.defaultCard) in ("+", "*")

	def meaning(claim: Claim) -> tuple:
		numeric = False
		qualifiers = {}
		if "p" in claim:
			attr = model.lookup(instances[claim["s"]]["type"], claim["p"])
			resolved = _useType(model, attr, claim)
			numeric = resolved.builtin in ("Integer", "Number", "Amount", "Percent", "Duration")
			qualifiers = resolved.qualifiers
		value = _valueIdentity(claim["v"], numeric) if "v" in claim else ("missing",)
		return value, _valueKey(claim.get("roles")), _valueKey(qualifiers)

	for item, retract in sorted([(claim, False) for claim in observations.claims] + [(claim, True) for claim in observations.retractions], key=lambda pair: _order(pair[0])):
		item = {key: value for key, value in item.items() if key != "conflict"}
		if not retract:
			# Keep history until withdrawals are applied: a by-scoped retraction must not erase
			# another producer merely because its claim had been superseded in the same source.
			active.setdefault((_slot(item), source(item)), []).append(item)
			continue
		removed = False
		for key, claims in list(active.items()):
			kept = []
			for claim in claims:
				if not _retracts(item, claim, observations.sources):
					kept.append(claim)
					continue
				if "v" not in item:
					removed = True
					continue
				if _slot(item) != _slot(claim):
					kept.append(claim)
					continue
				if meaning(item) == meaning(claim):
					removed = True
					continue
				if isinstance(claim.get("v"), dict) and "set" in claim["v"]:
					members = [member for member in claim["v"]["set"] if meaning(claim | {"v": member}) != meaning(item)]
					if len(members) != len(claim["v"]["set"]):
						removed = True
						if not members:
							# Withdrawal is not confirmed absence: do not manufacture an empty-set claim.
							continue
						claim = claim | {"v": claim["v"] | {"set": members}}
				kept.append(claim)
			active[key] = kept
		if not removed:
			diag.warn("retraction", f"Retraction of '{_slot(item)}' matched no claim")
	claims, instances = _canonicalise(model, [claim for group in active.values() for claim in group], observations.instances, diag, mode)
	active = {}
	for claim in sorted(claims, key=_order):
		key = (_slot(claim), source(claim))
		if "same" in claim or "distinct" in claim:
			# Links accumulate: dropping an earlier repeated join can change canonical handles on replay.
			active.setdefault(key, []).append(claim)
			continue
		complete = isinstance(claim.get("v"), dict) and "set" in claim["v"] and not claim["v"].get("partial")
		if not multi(claim) or complete:
			active[key] = [claim]
		elif not any(meaning(old) == meaning(claim) for old in active.get(key, [])):
			active.setdefault(key, []).append(claim)
	claims = [claim for group in active.values() for claim in group]
	conflicted: set[int] = set()
	# ponytail: pairwise conflict check; group by slot if large observation logs make this measurable.
	for index, left in enumerate(claims):
		if multi(left):
			continue
		for other, right in enumerate(claims[index + 1:], index + 1):
			if _slot(left) == _slot(right) and source(left) != source(right) and meaning(left) != meaning(right) and _overlaps(left, right):
				conflicted.update((index, other))
	claims = [claim | ({"conflict": True} if index in conflicted else {}) for index, claim in enumerate(claims)]
	return Observations(deepcopy(observations.obs), dict(observations.sources), _markImplicit(instances, claims),
		sorted(deepcopy(claims), key=lambda claim: claim["n"]), [], diag.items, deepcopy(observations.gaps))


def resolveObservations(ontology: Ontology, doc: ObservationsDocument, mode: str = "strict") -> Observations:
	"""Type parsed `doc`; lenient mode holds semantically invalid statements as gaps."""
	if mode not in ("strict", "lenient"):
		raise ValueError("mode must be strict or lenient")
	observations = _Resolver(ontology, doc).resolve(mode)
	# NOTE: Imported here: `meta` builds on the observations formatter.
	from ..meta import checkMetaReferences

	diagnostics = checkMetaReferences(ontology, observations, doc)
	if not diagnostics:
		return observations
	if mode == "strict":
		raise FormatError(list(observations.diagnostics) + diagnostics)
	return replace(observations, diagnostics=list(observations.diagnostics) + diagnostics)


def loadObservations(ontology: Ontology, source: Source, mode: str = "strict") -> Observations:
	"""Parse and validate `source` against `ontology`, retaining all claims and retractions."""
	return resolveObservations(ontology, parseObservations(source), mode)


def formatObservations(ontology: Ontology, source: Source, form: str = "state", mode: str = "strict") -> str:
	"""Load `source` and print its `state` or audit `log` form."""
	log = loadObservations(ontology, source, mode)
	if form == "log":
		return printObservationsLog(ontology, log)
	if form == "state":
		return printObservationsState(ontology, reconcileObservations(ontology, log, mode))
	raise ValueError("form must be state or log")


def observationsFromJson(ontology: Ontology, data: Any, name: str = "observations.json", mode: str = "strict") -> Observations:
	"""Validate JSON through text; explicit gaps require lenient mode and remain unapplied."""
	try:
		read = _readObservationsJson(ontology, data)
		if read.gaps and mode != "lenient":
			raise ValueError("Gap-bearing JSON requires lenient mode")
		text = _printObservationsLog(ontology, read)
		loaded = loadObservations(ontology, Source(name, text), mode)
		if read.obs != loaded.obs or read.sources != loaded.sources or read.instances != loaded.instances or any(
			_claimContent(getattr(read, key)) != _claimContent(getattr(loaded, key)) for key in ("claims", "retractions")
		) or _gapContent(read.gaps) != _gapContent(loaded.gaps):
			raise ValueError("Observations JSON does not survive its text round trip (including the instance registry)")
	except (ValueError, KeyError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	read.diagnostics = [item for gap in read.gaps for item in gap.diagnostics] if read.gaps else loaded.diagnostics
	return read


# EOF
