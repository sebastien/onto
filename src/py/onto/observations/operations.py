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
	Diagnostic,
	Diagnostics,
	FormatError,
	Loc,
	Source,
	annotation,
)
from .formatter import (
	renderObservationsLog,
	observationsToJson,
	printObservationsCompact,
	printObservationsLog,
	printObservationsState,
)
from .model import (
	Claim,
	Gap,
	Observations,
	ObservationsDocument,
	markImplicit,
	claimOrder,
	claimSlot,
	useType,
	typedValueIdentity,
	valueKey,
	parseInterval,
	withNamedRelationRoles,
)
from .parser import (
	ObservationResolver,
	readObservationsJson,
	parseObservations,
	validateStatements,
)

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def overlaps(left: Claim, right: Claim) -> bool:
	a, b = parseInterval(left["valid"]) if "valid" in left else (None, None)
	c, d = parseInterval(right["valid"]) if "valid" in right else (None, None)
	return (a is None or d is None or a <= d) and (c is None or b is None or c <= b)


def retracts(retraction: Claim, claim: Claim, sources: dict[str, str]) -> bool:
	withdrawn = retraction.get("of", retraction.get("src"))
	claimed = claim.get("src")
	if sources.get(withdrawn, withdrawn) != sources.get(claimed, claimed) or claimOrder(claim) > claimOrder(retraction):
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
		return claimSlot(retraction) == claimSlot(claim) or bool(retraction.get("s") and retraction["s"] == claim.get("s"))
	if "s" not in claim or retraction["s"] != claim["s"]:
		return "p" not in retraction and "facet" not in retraction and (
			claim.get("ctx") == retraction["s"] or "rel" in claim and "s" not in claim and retraction["s"] in claim["roles"].values()
		)
	if "facet" in retraction:
		return claim.get("facet") == retraction["facet"] or claim.get("p", "").startswith(f"{retraction['facet']}.")
	if "p" in retraction:
		# `- h.Phones` withdraws every element (`Phones[Mobile].Number`), `- h.Phones[Mobile]` one of them.
		return claim.get("p") == retraction["p"] or claim.get("p", "").startswith((retraction["p"] + ".", retraction["p"] + "["))
	return True


def canonicalise(model: Model, claims: list[Claim], instances: dict[str, dict[str, str | bool]], diag: Diagnostics, mode: str) -> tuple[list[Claim], dict[str, dict[str, str | bool]]]:
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
	for claim in sorted((claim for claim in claims if "same" in claim), key=claimOrder):
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
			members = {valueKey(value(member)): value(member) for member in item["set"]}
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


def gapContent(gaps: list[Gap]) -> list[str]:
	return sorted(valueKey({"text": gap.text, "meta": gap.meta, "ctx": gap.ctx,
		"diagnostics": sorted({(item.code, item.message) for item in gap.diagnostics})}) for gap in gaps)


def claimContent(claims: list[Claim]) -> list[str]:
	# NOTE: Ordinals are source-document locations; printing may regroup headers and renumber them.
	def content(claim: Claim) -> Claim:
		result = {key: value for key, value in claim.items() if key not in ("n", "conflict")}
		if "conf" in result:
			result["conf"] = float(result["conf"])
		if isinstance(result.get("v"), dict) and "set" in result["v"]:
			result["v"] = result["v"] | {"set": sorted(result["v"]["set"], key=valueKey)}
		return result
	return sorted(valueKey(content(claim)) for claim in claims)


def mergeObservationLogs(ontology: Ontology, logs: list[Observations], *, locations: list[Loc] | None = None) -> dict[str, Any]:
	"""Combine mapping input statements as observation JSON. Inert gaps remain in each input's report."""
	model = Model(ontology)
	bareSources = {
		token for log in logs for group in (log.claims, log.retractions) for claim in group
		for key in ("src", "of") if (token := claim.get(key)) is not None and token not in log.sources
	}
	out = None
	offset, sourceNumber = 0, 0
	for i, log in enumerate(logs):
		loc = locations[i] if locations is not None else None
		data = observationsToJson(log)
		scope = log.obs.get("scope")
		if log.obs["ontology"] != ontology.namespace:
			raise FormatError([Diagnostic("error", "run.ontology", f"expected observations of {ontology.namespace}", loc)])
		if out is None:
			out = {**data, "sources": {}, "instances": {}, "claims": [], "retractions": []}
			out.pop("gaps", None)
			out["obs"] = {key: value for key, value in log.obs.items() if key in ("ontology", "rev", "scope")}
		elif scope != (shared := out["obs"].get("scope")):
			raise FormatError([Diagnostic("error", "run.scope", f"@scope {scope!r} does not match the first input's @scope {shared!r}", loc)])
		aliases = {}
		for alias, token in data["sources"].items():
			sourceNumber += 1
			while f"d{sourceNumber}" in bareSources:
				sourceNumber += 1
			aliases[alias] = f"d{sourceNumber}"
			out["sources"][aliases[alias]] = token
		for handle, item in data["instances"].items():
			existing = out["instances"].get(handle)
			if existing and scope is None:
				raise FormatError([Diagnostic("error", "run.scope", f"handle '{handle}' appears in multiple inputs without a shared @scope", loc)])
			if not existing or model.isA(item["type"], existing["type"]):
				out["instances"][handle] = item
			elif item["type"] != existing["type"] and not model.isA(existing["type"], item["type"]):
				raise FormatError([Diagnostic("error", "run.type", f"handle '{handle}' has incompatible types '{existing['type']}' and '{item['type']}'", loc)])
		last = 0
		for key in ("claims", "retractions"):
			for claim in data[key]:
				renamed = {name: aliases.get(value, value) if name in ("src", "of") else value for name, value in claim.items()}
				out[key].append({**renamed, "n": offset + claim["n"]})
				last = max(last, claim["n"])
		offset += last
	return out or observationsToJson(Observations({"ontology": ontology.namespace, "scope": None}, {}, {}, [], []))


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

	def printCompact(self, observations: Observations) -> str:
		"""Print a gap-free audit log with compact subject blocks."""
		return printObservationsCompact(self.ontology, observations)

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


def sourceToken(observations: Observations, claim: Claim) -> str | None:
	"""Resolve a claim's provenance alias, keeping bare tokens and absent sources."""
	name = claim.get("src")
	return observations.sources.get(name, name)


def reconcileObservations(ontology: Ontology, observations: Observations, mode: str = "strict") -> Observations:
	"""Apply withdrawals, identity links and supersession; `mode` controls conflicting joins."""
	if mode not in ("strict", "lenient"):
		raise ValueError("mode must be strict or lenient")
	if mode == "strict" and observations.gaps:
		raise FormatError([replace(item, level="error") for gap in observations.gaps for item in gap.diagnostics])
	model = Model(ontology)
	diag = Diagnostics(list(observations.diagnostics))
	instances = observations.instances
	active: dict[tuple[tuple[str, str, str], str | None], list[Claim]] = {}

	def multi(claim: Claim, registry: dict[str, dict[str, str | bool]]) -> bool:
		if "p" not in claim:
			return False
		attr = model.lookup(registry[claim["s"]]["type"], claim["p"])
		return (attr.card or model.defaultCard) in ("+", "*")

	def meaning(claim: Claim, registry: dict[str, dict[str, str | bool]]) -> tuple:
		resolved = None
		if "p" in claim:
			attr = model.lookup(registry[claim["s"]]["type"], claim["p"])
			resolved = useType(model, attr, claim)
		value = typedValueIdentity(claim["v"], resolved) if "v" in claim else ("missing",)
		return value, valueKey(claim.get("roles")), valueKey(resolved.qualifiers if resolved is not None else {})

	for item, retract in sorted([(claim, False) for claim in observations.claims] + [(claim, True) for claim in observations.retractions], key=lambda pair: claimOrder(pair[0])):
		item = {key: value for key, value in item.items() if key != "conflict"}
		if not retract:
			# Keep history until withdrawals are applied: a by-scoped retraction must not erase
			# another producer merely because its claim had been superseded in the same source.
			history = active.setdefault((claimSlot(item), sourceToken(observations, item)), [])
			history.append(withNamedRelationRoles(item, history))
			continue
		removed = False
		for key, claims in list(active.items()):
			kept = []
			for claim in claims:
				if not retracts(item, claim, observations.sources):
					kept.append(claim)
					continue
				if "v" not in item:
					removed = True
					continue
				if claimSlot(item) != claimSlot(claim):
					kept.append(claim)
					continue
				if meaning(item, instances) == meaning(claim, instances):
					removed = True
					continue
				if isinstance(claim.get("v"), dict) and "set" in claim["v"]:
					members = [member for member in claim["v"]["set"] if meaning(claim | {"v": member}, instances) != meaning(item, instances)]
					if len(members) != len(claim["v"]["set"]):
						removed = True
						if not members:
							# Withdrawal is not confirmed absence: do not manufacture an empty-set claim.
							continue
						claim = claim | {"v": claim["v"] | {"set": members}}
				kept.append(claim)
			active[key] = kept
		if not removed:
			diag.warn("retraction", f"Retraction of '{claimSlot(item)}' matched no claim")
	def surviving(items: list[Claim], diagnostics: Diagnostics) -> Observations:
		rewritten, registry = canonicalise(model, items, instances, diagnostics, mode)
		slots: dict[tuple[tuple[str, str, str], str | None], list[Claim]] = {}
		for claim in sorted(rewritten, key=claimOrder):
			key = (claimSlot(claim), sourceToken(observations, claim))
			claim = withNamedRelationRoles(claim, slots.get(key, []))
			if "same" in claim or "distinct" in claim:
				# Links accumulate: dropping an earlier repeated join can change canonical handles on replay.
				slots.setdefault(key, []).append(claim)
				continue
			complete = isinstance(claim.get("v"), dict) and "set" in claim["v"] and not claim["v"].get("partial")
			if not multi(claim, registry) or complete:
				slots[key] = [claim]
			elif not any(meaning(old, registry) == meaning(claim, registry) for old in slots.get(key, [])):
				slots.setdefault(key, []).append(claim)
		return replace(observations, claims=[claim for group in slots.values() for claim in group], instances=registry)

	def stateErrors(state: Observations) -> list[Diagnostic]:
		return checkExclusive(ontology, state) + checkFacetConditions(ontology, state)

	live = [claim for group in active.values() for claim in group]
	identityDiagnostics = Diagnostics()
	state = surviving(live, identityDiagnostics)
	errors = stateErrors(state)
	if errors and mode == "lenient" and any("same" in claim for claim in live):
		# ponytail: replay joins only on failure; index affected groups if conflict-heavy logs get large.
		accepted = [claim for claim in live if "same" not in claim]
		for link in sorted((claim for claim in live if "same" in claim), key=claimOrder):
			trial = stateErrors(surviving([*accepted, link], Diagnostics()))
			if trial:
				left, right = link["same"]
				for error in trial:
					diag.warn("identity", f"Identity link '{left} = {right}' was not applied: {error.message}")
			else:
				accepted.append(link)
		identityDiagnostics = Diagnostics()
		state = surviving(accepted, identityDiagnostics)
		errors = stateErrors(state)
	diag.items.extend(identityDiagnostics.items + errors)
	diag.check()
	claims, instances = state.claims, state.instances
	conflicted: set[int] = set()
	# ponytail: pairwise conflict check; group by slot if large observation logs make this measurable.
	for index, left in enumerate(claims):
		if multi(left, instances):
			continue
		for other, right in enumerate(claims[index + 1:], index + 1):
			# An existence-only assertion does not disagree with a source that states endpoints.
			if ("rel" in left) != ("rel" in right) or claimSlot(left) != claimSlot(right):
				continue
			if sourceToken(observations, left) != sourceToken(observations, right) and meaning(left, instances) != meaning(right, instances) and overlaps(left, right):
				conflicted.update((index, other))
	claims = [claim | ({"conflict": True} if index in conflicted else {}) for index, claim in enumerate(claims)]
	return Observations(deepcopy(observations.obs), dict(observations.sources), markImplicit(instances, claims),
		sorted(deepcopy(claims), key=lambda claim: claim["n"]), [], diag.items, deepcopy(observations.gaps))


def checkExclusive(ontology: Ontology, observations: Observations, doc: ObservationsDocument | None = None, witnesses: dict[int, dict[int, Claim]] | None = None) -> list[Diagnostic]:
	"""Errors for two attributes of one `{one=G}` group stated with values by one source over overlapping periods."""
	model = Model(ontology)
	diag = Diagnostics()
	locations = {statement.n: statement.loc for statement in doc.statements} if doc else {}
	stated: dict[tuple, list[Claim]] = {}
	for claim in sorted(observations.claims, key=claimOrder):
		value, path, owner = claim.get("v"), claim.get("p"), observations.instances.get(claim.get("s", ""), {}).get("type")
		if value is None or (isinstance(value, dict) and value.get("unknown")) or not isinstance(path, str) or not isinstance(owner, str):
			continue
		if isinstance(value, dict) and "set" in value and not value["set"]:
			continue
		attr = model.lookup(owner, path)
		group = annotation(attr.ann, "one") if attr else None
		if isinstance(group, str):
			prefix = path.rpartition(".")[0]
			accepted = stated.setdefault((claim["s"], claim.get("ctx"), prefix, group, sourceToken(observations, claim)), [])
			clash = next((other for other in accepted if other["p"] != path and overlaps(claim, other)), None)
			if clash:
				subject = claim["s"]
				where = f"{subject}.{prefix}" if prefix else subject
				diag.error("one", f"'{where}' states both '{clash['p']}' and '{path}' of exclusive group '{group}'", locations.get(claim["n"]))
				if witnesses is not None:
					witnesses.setdefault(claim["n"], {})[clash["n"]] = clash
			else:
				accepted.append(claim)
	return diag.items


def conditionText(value: object) -> str | None:
	"""A stated value as a facet condition spells it; None for `null` and `?`."""
	if value is None or isinstance(value, dict):
		return None
	return ("true" if value else "false") if isinstance(value, bool) else str(value)


def checkFacetConditions(ontology: Ontology, observations: Observations, doc: ObservationsDocument | None = None, witnesses: dict[int, dict[int, Claim]] | None = None) -> list[Diagnostic]:
	"""Errors for a facet `{when=Attr:Value}` claimed by a source that states another value of `Attr` for the same subject."""
	model = Model(ontology)
	diag = Diagnostics()
	locations = {statement.n: statement.loc for statement in doc.statements} if doc else {}
	stated: dict[tuple, list[Claim]] = {}
	facetClaims: list[tuple[Claim, str, str, str]] = []
	for claim in observations.claims:
		owner = observations.instances.get(claim.get("s", ""), {}).get("type")
		if not isinstance(owner, str):
			continue
		path = claim.get("p")
		name = claim.get("facet") or (path.split(".", 1)[0] if isinstance(path, str) and "." in path else None)
		facet = model.facets(owner).get(name) if name else None
		if facet is None:
			if isinstance(path, str):
				stated.setdefault((claim["s"], sourceToken(observations, claim), path), []).append(claim)
			continue
		condition = annotation(facet.ann, "when")
		if isinstance(condition, str) and ":" in condition:
			attr, _, value = condition.partition(":")
			facetClaims.append((claim, name, attr, value))
	for claim, name, attr, value in facetClaims:
		clash = next((other for other in stated.get((claim["s"], sourceToken(observations, claim), attr), [])
			if (text := conditionText(other.get("v"))) is not None and text != value and overlaps(claim, other)), None)
		if clash:
			diag.error("when", f"'{claim['s']}' has facet '{name}', which applies when {attr} is {value}, but states {attr} {conditionText(clash['v'])}",
				locations.get(claim["n"]))
			if witnesses is not None:
				witnesses.setdefault(claim["n"], {})[clash["n"]] = clash
	return diag.items


def resolveObservations(ontology: Ontology, doc: ObservationsDocument, mode: str = "strict") -> Observations:
	"""Type parsed `doc`; lenient mode holds semantically invalid statements as gaps."""
	if mode not in ("strict", "lenient"):
		raise ValueError("mode must be strict or lenient")
	resolver = ObservationResolver(ontology, doc)
	observations = resolver.resolve(mode)
	# NOTE: Imported here: `meta` builds on the observations formatter.
	from ..meta import metaReferenceErrors

	diagnostics, unresolved = metaReferenceErrors(ontology, observations, doc)
	if mode == "strict":
		return validateStatements(resolver, observations,
			diagnostics + checkExclusive(ontology, observations, doc) + checkFacetConditions(ontology, observations, doc), mode)
	observations = validateStatements(resolver, observations, diagnostics, mode)
	if unresolved:
		observations.instances = {handle: item for handle, item in observations.instances.items() if handle not in unresolved}
	witnesses: dict[int, dict[int, Claim]] = {}
	observations = validateStatements(resolver, observations, checkExclusive(ontology, observations, doc, witnesses), mode)
	observations = validateStatements(resolver, observations, checkFacetConditions(ontology, observations, doc, witnesses), mode)
	observations.gaps = [replace(gap, witnesses=tuple(deepcopy(claim) for claim in witnesses[gap.n].values()))
		if gap.n in witnesses else gap for gap in observations.gaps]
	return observations


def loadObservations(ontology: Ontology, source: Source, mode: str = "strict") -> Observations:
	"""Parse and validate `source` against `ontology`, retaining all claims and retractions."""
	return resolveObservations(ontology, parseObservations(source), mode)


def formatObservations(ontology: Ontology, source: Source, form: str = "state", mode: str = "strict") -> str:
	"""Load `source` and print its `state`, `log` or `compact` form."""
	log = loadObservations(ontology, source, mode)
	if form == "log":
		return printObservationsLog(ontology, log)
	if form == "compact":
		return printObservationsCompact(ontology, log)
	if form == "state":
		return printObservationsState(ontology, reconcileObservations(ontology, log, mode))
	raise ValueError("form must be state, log or compact")


def gapWitnessesMatch(ontology: Ontology, observations: Observations, gap: Gap, name: str) -> bool:
	# Isolate historical evidence: it can validate this gap, but must never affect live claims or other gaps.
	replay = replace(observations, claims=list(gap.witnesses), retractions=[], gaps=[gap])
	loaded = loadObservations(ontology, Source(name, renderObservationsLog(ontology, replay)), "lenient")
	return (observations.instances == loaded.instances and not loaded.retractions
		and claimContent(replay.claims) == claimContent(loaded.claims) and gapContent(replay.gaps) == gapContent(loaded.gaps)
		and claimContent(replay.claims) == claimContent(list(loaded.gaps[0].witnesses)))


def observationsFromJson(ontology: Ontology, data: Any, name: str = "observations.json", mode: str = "strict") -> Observations:
	"""Validate JSON through text; explicit gaps require lenient mode and remain unapplied."""
	try:
		read = readObservationsJson(ontology, data)
		if read.gaps and mode != "lenient":
			raise ValueError("Gap-bearing JSON requires lenient mode")
		witnessed = [gap for gap in read.gaps if gap.witnesses]
		replay = replace(read, gaps=[gap for gap in read.gaps if not gap.witnesses])
		ordinals: list[int] = []
		text = renderObservationsLog(ontology, replay, ordinals)
		loaded = loadObservations(ontology, Source(name, text), mode)
		if read.obs != loaded.obs or read.sources != loaded.sources or read.instances != loaded.instances or any(
			claimContent(getattr(read, key)) != claimContent(getattr(loaded, key)) for key in ("claims", "retractions")
		) or gapContent(replay.gaps) != gapContent(loaded.gaps) or any(
			not gapWitnessesMatch(ontology, read, gap, name) for gap in witnessed
		):
			raise ValueError("Observations JSON does not survive its text round trip (including the instance registry)")
		# Keep the rederived live witnesses for a future reconciliation, using original statement numbers.
		liveWitnesses = {ordinals[gap.n - 1]: tuple(claim | {"n": ordinals[claim["n"] - 1]} for claim in gap.witnesses)
			for gap in loaded.gaps if gap.witnesses}
		read.gaps = [replace(gap, witnesses=liveWitnesses[gap.n]) if gap.n in liveWitnesses else gap for gap in read.gaps]
	except (ValueError, KeyError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	read.diagnostics = [item for gap in read.gaps for item in gap.diagnostics] if read.gaps else loaded.diagnostics
	return read


# EOF
