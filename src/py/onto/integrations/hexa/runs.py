"""Module: integrations.hexa.runs — re-running: previous output, retractions, safeguards, approval and outcomes (spec-06).

<Kind>Run: <Kind>Read → OutputPreviousRetrieve → RetractionsCompose → RetractionsAdmit → OutcomeMaterialize

Retractions travel between stages and the host with source *tokens* in `src` and `of`;
a log written for the host maps them to its own aliases.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any as AnyValue

from hexa.combinators import lift, pipe, stage
from hexa.shapes import Failure

from ...formats.operations import formatsUpdate
from ...observations.model import claimSlot, timestampValue
from ...observations.operations import observationsFromJson, reconcileObservations
from ...ontology.model import Model, Ontology
from .stages import namedStage
from .vocabulary import BindingCodes

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


IGNORED = ("n", "at", "src", "conflict")


@dataclass(slots=True)
class RunSettings:
	"""What re-running needs to know about a compiled binding or mapping."""

	ontology: Ontology
	by: str
	mode: str
	complete: str = "document"
	retract: str = "20%"
	confirm: int = 1
	formats: AnyValue = None


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def slotKey(claim: dict) -> tuple:
	"""A claim's slot (subject, attribute or facet or relation, context); retractions of a slot share it."""
	return claimSlot(claim)


def tokenized(claim: dict, sources: dict[str, str]) -> dict:
	"""A claim with source tokens instead of the aliases of the log it came from."""
	result = dict(claim)
	for key in ("src", "of"):
		if key in result:
			result[key] = sources.get(result[key], result[key])
	return result


def comparable(claim: dict) -> dict:
	"""Value and metadata other than `at` (and log-specific numbering)."""
	return {key: value for key, value in claim.items() if key not in IGNORED}


def latest(log: dict) -> AnyValue:
	times = [timestampValue(item["at"]) for item in log.get("claims", []) + log.get("retractions", []) if "at" in item]
	return max(times) if times else None


def retraction(claim: dict, meta: dict) -> dict:
	"""`- h`, `- h.Attr`, `- h[F]` or `- s verb o` for the slot of `claim`."""
	if "rel" in claim:
		result = {"rel": claim["rel"], "roles": claim["roles"]} if "s" not in claim else {"s": claim["s"], "exists": True}
	elif claim.get("exists"):
		result = {"s": claim["s"], "exists": True}
	elif "facet" in claim:
		result = {"s": claim["s"], "facet": claim["facet"]}
	else:
		result = {"s": claim["s"], "p": claim["p"]}
	if "ctx" in claim:
		result["ctx"] = claim["ctx"]
	return result | meta


def subjects(claim: dict) -> set[str]:
	if "s" in claim:
		return {claim["s"]}
	return set(claim.get("roles", {}).values())


def percentage(text: str) -> float:
	return float(str(text).rstrip("%")) / 100


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Rerun:
	"""Compare a run's output with each source's previous output, then admit or hold retractions."""

	def __init__(self, settings: RunSettings):
		self.settings = settings
		self.model = Model(settings.ontology)

	def previousState(self, log: dict) -> tuple[list[dict], dict[str, str]]:
		"""The previous output reconciled into its state, with its source aliases."""
		state = reconcileObservations(self.settings.ontology, observationsFromJson(self.settings.ontology, log, mode="lenient"), mode="lenient")
		return [tokenized(claim, log.get("sources", {})) for claim in state.claims], log.get("sources", {})

	def compose(self, run: dict) -> dict:
		"""`RetractionsCompose`: per source, new or changed claims and the retractions of absent slots."""
		settings = self.settings
		value = run["value"]
		log = value["log"]
		aliases = log["sources"]
		claims = [tokenized(claim, aliases) for claim in log["claims"]]
		deleted = [tokenized(item, aliases) for item in log["retractions"]]
		olderSources: set[str] = set()
		safeguards: list[str] = []
		strict = settings.mode == "strict"
		noRetractions = settings.complete == "none"
		if settings.complete == "document" and value["documents"] and not any(document["records"] for document in value["documents"]):
			if strict:
				raise Failure(Failure.Contract, BindingCodes.InputEmpty)
			safeguards.append(str(BindingCodes.InputEmpty))
			noRetractions = True
		# Unattributed mapping claims have no host partition to fetch or retract.
		output = [claim for claim in claims if "src" not in claim]
		retractions: list[dict] = []
		counts: dict[str, int] = {}
		instances: dict[str, dict] = {}
		composed: set[str] = set()
		for document in value["documents"]:
			src = document["src"]
			if src in composed:
				continue  # `mine` already contains every document's claims for this source.
			composed.add(src)
			mine = [claim for claim in claims if claim.get("src") == src]
			previous = run["previous"].get(src)
			if previous is None:
				output += mine
				continue
			prior, _ = self.previousState(previous)
			instances |= previous.get("instances", {})
			bySlot: dict[tuple, list[dict]] = {}
			for claim in prior:
				bySlot.setdefault(slotKey(claim), []).append(claim)
			counts[src] = len(bySlot)
			at = document.get("at") or (mine[0]["at"] if mine else None)
			previousAt = latest(previous)
			if at is not None and previousAt is not None and timestampValue(at) < previousAt:
				if strict:
					raise Failure(Failure.Contract, BindingCodes.SnapshotOlder)
				safeguards.append(f"{BindingCodes.SnapshotOlder}:{src}")
				olderSources.add(src)
				output += [claim for claim in mine if slotKey(claim) not in bySlot]
				continue
			kept = [claim for claim in mine if not any(comparable(claim) == comparable(item) for item in bySlot.get(slotKey(claim), []))]
			# A kept facet keeps its statement's existence claim: in text, `h[F]` also asserts existence.
			statements = {claim["n"] for claim in kept if "facet" in claim}
			output += [claim for claim in mine if claim in kept or claim["n"] in statements]
			if noRetractions or at is None:
				continue
			priorSrc = document.get("replaces") or src
			removed = {item["s"] for item in deleted if item.get("src") == src and item.get("of", src) == priorSrc and item.get("exists")}
			retractions += self.absent(value, src, document, mine, bySlot, at, previous.get("instances", {}), removed)
		deleted = [item for item in deleted if item.get("src") not in olderSources]
		return {**run, "output": {"claims": output, "deleted": deleted, "retractions": retractions, "instances": instances}, "counts": counts, "safeguards": safeguards}

	def slotOwners(self, claim: dict, key: tuple) -> list[tuple[str, str]]:
		"""Subject and line name(s) by which a previous slot can be reported stale."""
		if "rel" not in claim:
			return [(key[0], key[1])]
		decl = self.model.get(claim["rel"])
		if decl is None or decl.arrow is None:
			return []
		first, second = (claim["roles"][party.role] for party in decl.participants)
		owners = [(first, decl.arrow.verb)]
		if decl.arrow.inverse:
			owners.append((second, decl.arrow.inverse))
		return owners

	def absent(self, value: dict, src: str, document: dict, mine: list[dict], bySlot: dict, at: str, types: dict[str, dict],
		removed: set[str]) -> list[dict]:
		"""Retractions of the previous slots this run no longer produces, within completeness, never stale ones."""
		settings = self.settings
		meta = {"src": src, "by": settings.by, "at": at} | ({"of": document["replaces"]} if document.get("replaces") else {})
		present = {slotKey(claim) for claim in mine}
		produced = {claim["s"] for claim in mine if claim.get("exists")}
		stale = {(item["s"], item.get("p") or (f"[{item['facet']}]" if "facet" in item else item.get("verb", "")), item["ctx"])
			for item in value["stale"] if item["src"] == src and "ctx" in item}
		unscopedStale = {(item["s"], item.get("p") or (f"[{item['facet']}]" if "facet" in item else item.get("verb", "")))
			for item in value["stale"] if item["src"] == src and "ctx" not in item}
		unidentified = {item["type"] for item in value["unidentified"] if item["src"] == src}
		# A missing key could belong to any unmatched handle of that type.
		unmatched = {handle for handle, instance in types.items() if handle not in produced
			and any(instance["type"] == item or self.model.isA(instance["type"], item) for item in unidentified)}
		gone = set(removed)
		result: list[dict] = []
		for key, items in bySlot.items():
			claim = items[0]
			if key in present or not claim.get("exists") or claim["s"] in removed or claim["s"] in unmatched:
				continue
			if (claim["s"], "", claim.get("ctx")) in stale or (claim["s"], "") in unscopedStale:
				continue
			if settings.complete == "record":
				continue
			gone.add(claim["s"])
			result.append(retraction(claim, meta))
		for key, items in bySlot.items():
			claim = items[0]
			if key in present or claim.get("exists") or "rel" in claim and "s" in claim:
				continue
			owners = subjects(claim)
			if owners & gone or owners & unmatched or any((subject, member, claim.get("ctx")) in stale or (subject, member) in unscopedStale
				for subject, member in self.slotOwners(claim, key)):
				continue
			if settings.complete == "record" and not owners & produced:
				continue
			result.append(retraction(claim, meta))
		return result

	def admit(self, run: dict) -> dict:
		"""`RetractionsAdmit`: retractions over the ceiling are held; lenient runs confirm repeated ones."""
		settings = self.settings
		ceiling = percentage(settings.retract)
		admitted, held, confirmed, lapsed = [], [], [], []
		bySource: dict[str, list[dict]] = {}
		for item in run["output"]["retractions"]:
			bySource.setdefault(item["src"], []).append(item)
		for src in {document["src"] for document in run["value"]["documents"]} | set(run["pending"]):
			computed = bySource.get(src, [])
			pending = {slotKey(item["retraction"]): item for item in run["pending"].get(src) or []}
			keys = {slotKey(item) for item in computed}
			lapsed += [item for key, item in pending.items() if key not in keys]
			count = run["counts"].get(src, 0)
			if not computed:
				continue
			if not count or len(computed) <= ceiling * count:
				admitted += computed
				continue
			for item in computed:
				earlier = pending.get(slotKey(item))
				confirmations = earlier["confirmations"] + 1 if earlier else 0
				if settings.mode == "lenient" and earlier and confirmations >= settings.confirm:
					approvedItem = {**earlier["retraction"], "approved": f"confirm:{confirmations}"}
					admitted.append(approvedItem)
					confirmed.append(approvedItem)
				else:
					held.append({"retraction": earlier["retraction"] if earlier else item, "confirmations": confirmations, "src": src})
		return {**run, "admitted": admitted, "held": held, "confirmed": confirmed, "lapsed": lapsed}

	def materialize(self, run: dict) -> dict:
		"""`OutcomeMaterialize`: `Applied` with the log and held retractions, or `Pending` (strict) writing nothing."""
		settings = self.settings
		value = run["value"]
		changes = []
		if settings.formats is not None or value.get("formats"):
			_, found = formatsUpdate(settings.formats, value.get("formats", {}))
			changes = [{"path": item.path, "previous": item.previous, "format": item.format} for item in found]
		safeguards = list(run["safeguards"])
		if run["held"]:
			safeguards.append("retract")
		pending = settings.mode == "strict" and bool(run["held"] or changes)
		# Retracted and held subjects keep their types, even when this run no longer mentions them.
		known = run["output"]["instances"] | value["log"]["instances"]
		mentioned = {handle for item in run["output"]["deleted"] + run["admitted"] + [entry["retraction"] for entry in run["held"]]
			for handle in subjects(item) | ({item["ctx"]} if "ctx" in item else set())}
		template = {**value["log"], "instances": dict(sorted((value["log"]["instances"] | {handle: known[handle] for handle in mentioned if handle in known}).items()))}
		log = outputLog(template, run["output"]["claims"], run["output"]["deleted"] + run["admitted"])
		report = {"gaps": value["gaps"], "formats": value.get("formats", {}), "fields": value.get("fields"), "stale": value["stale"],
			"held": run["held"], "confirmed": run["confirmed"], "lapsed": run["lapsed"], "safeguards": safeguards, "formatChanges": changes}
		for key in ("mixed", "correspondence", "lossy"):
			if key in value:
				report[key] = value[key]
		return {"status": "Pending" if pending else "Applied", "log": log, "held": run["held"], "lapsed": run["lapsed"], "report": report}


def outputLog(template: dict, claims: list[dict], retractions: list[dict]) -> dict:
	"""A spec-02 JSON log of `claims` and `retractions` (with source tokens), renumbered in order."""
	log = {key: deepcopy(template[key]) for key in ("format", "obs", "instances")}
	sources: dict[str, str] = {}
	aliases: dict[str, str] = {}

	def alias(token: str) -> str:
		if token not in aliases:
			aliases[token] = f"d{len(aliases) + 1}"
			sources[aliases[token]] = token
		return aliases[token]

	for token in template["sources"].values():
		alias(token)
	numbered = []
	index, previous = 0, None
	for item in claims + retractions:
		# Claims of one statement (a header and its facets) share `n`; keep them together.
		if "n" not in item or item["n"] != previous:
			index += 1
		previous = item.get("n")
		entry = {"n": index, **{key: value for key, value in item.items() if key != "n"}}
		for key in ("src", "of"):
			if key in entry:
				entry[key] = alias(entry[key])
		numbered.append(entry)
	log["sources"] = sources
	log["claims"] = numbered[:len(claims)]
	log["retractions"] = numbered[len(claims):]
	return log


def runStages(settings: RunSettings, read: AnyValue, kind: str) -> dict[str, AnyValue]:
	"""`OutputPreviousRetrieve`, `RetractionsCompose`, `RetractionsAdmit`, `OutcomeMaterialize` and `<kind>Run`."""
	rerun = Rerun(settings)

	def OutputPreviousRetrieve(env, run):
		"""Run → run with `previous` and `pending` per source, from the host's store."""
		previous, pending, partitions = {}, {}, {}
		for document in run["value"]["documents"]:
			src = document["src"]
			priorSrc = document.get("replaces") or src
			if src in partitions:
				if partitions[src] != priorSrc:
					raise Failure(Failure.Contract, BindingCodes.ReplacementConflicting)
				continue
			partitions[src] = priorSrc
		for src, priorSrc in partitions.items():
			previous[src] = yield env.OutputPreviousRead({"by": settings.by, "src": priorSrc})
			pending[src] = yield env.RetractionsPendingRead({"by": settings.by, "src": src})
		return {**run, "previous": previous, "pending": pending}

	members = {
		"OutputPreviousRetrieve": stage(OutputPreviousRetrieve),
		"RetractionsCompose": namedStage("RetractionsCompose", lift(rerun.compose)),
		"RetractionsAdmit": namedStage("RetractionsAdmit", lift(rerun.admit)),
		"OutcomeMaterialize": namedStage("OutcomeMaterialize", lift(rerun.materialize)),
	}
	members[f"{kind}Run"] = namedStage(f"{kind}Run", pipe(read, members["OutputPreviousRetrieve"], members["RetractionsCompose"],
		members["RetractionsAdmit"], members["OutcomeMaterialize"]))
	return members


def approveLog(outcome: dict, token: str) -> dict:
	"""The log a person's approval writes: a pending run's log, plus its held retractions with `approved=<token>`."""
	held = [{**item["retraction"], "approved": token} for item in outcome["held"]]
	base = outcome["log"] if outcome["status"] == "Pending" else {**outcome["log"], "claims": [], "retractions": []}
	sources = base["sources"]
	claims = [tokenized(claim, sources) for claim in base["claims"]]
	retractions = [tokenized(item, sources) for item in base["retractions"]]
	return outputLog({**base, "sources": {}}, claims, retractions + held)


__all__ = ["RunSettings", "Rerun", "runStages", "approveLog", "outputLog", "slotKey"]

# EOF
