"""Module: observations.formatter — lossless audit logs, state text and JSON rendering."""

from __future__ import annotations

import json
import re
from collections import (
	Counter,
)
from copy import (
	deepcopy,
)
from fractions import (
	Fraction,
)
from typing import (
	Any,
)
from ..ontology import (
	Model,
	Namer,
	Ontology,
)
from ..text import (
	printAnnotations,
)
from .model import (
	Claim,
	Gap,
	HEADER_KEYS,
	META_KEYS,
	OBSERVATIONS_FORMAT,
	Observations,
	markImplicit,
	claimOrder,
	claimSlot,
	valueKey,
)

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def printText(value: str, inSet: bool = False) -> str:
	"""A text value as observations write it: bare, or a JSON string when bare text would read as something else."""
	# NOTE: Match the annotation parser's whitespace rule, including the separator before a value.
	unsafe = not value or value != value.strip() or any(char in value for char in '\n\r"') or re.search(r"(^|\s)(\{|//)", value) or value in ("?", "null") or value.startswith("[") or inSet and (value == "..." or any(char in value for char in ",]"))
	return json.dumps(value, ensure_ascii=False) if unsafe else value


def observationDefaults(observations: Observations) -> dict[str, Any]:
	return {key: float(value) if key == "conf" else value for key, value in observations.obs.items() if key in ("src", "at", "by", "conf")}


def claimMeta(claim: Claim) -> dict[str, Any]:
	return {key: claim[key] for key in META_KEYS if key in claim}


def gapJson(gap: Gap, liveClaims: set[str]) -> dict[str, Any]:
	return {"n": gap.n, "raw": gap.raw, "text": gap.text,
		"loc": {"file": gap.loc.file, "line": gap.loc.line}, "meta": dict(gap.meta),
		**({"ctx": gap.ctx} if gap.ctx is not None else {}),
		**({"witnesses": list(gap.witnesses)} if any(valueKey(claim) not in liveClaims for claim in gap.witnesses) else {}),
		"diagnostics": [{"code": item.code, "message": item.message} for item in gap.diagnostics]}


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class ObservationPrinter:
	"""Shared spelling for values, typed mentions and statement metadata."""

	def __init__(self, ontology: Ontology, observations: Observations):
		self.model = Model(ontology)
		self.observations = observations
		self.short = Namer(ontology.namespace, ontology.uses)
		self.typed: set[str] = set()

	def handle(self, name: str) -> str:
		if name == "?" or name in self.typed:
			return name
		self.typed.add(name)
		decl = self.model.get(self.observations.instances[name]["type"])
		return name if decl.arrow else f"{name}:{self.short(decl.path)}"

	def value(self, value: Any, inSet: bool = False, typed: bool = True) -> str:
		if value is None:
			return "null"
		if isinstance(value, bool):
			return "true" if value else "false"
		if isinstance(value, dict):
			if "unknown" in value:
				return "?"
			if "ref" in value:
				return self.handle(value["ref"]) if typed else value["ref"]
			# NOTE: Sort encoded values before introducing typed mentions; type annotations are not values.
			members = sorted(value["set"], key=lambda member: self.value(member, True, False))
			parts = [self.value(member, True, typed) for member in members]
			if value.get("partial"):
				parts.append("...")
			return f"[{', '.join(parts)}]"
		return printText(value, inSet)

	def meta(self, claim: Claim, defaults: dict[str, Any]) -> str:
		pairs = [(key, claim[key]) for key in META_KEYS if key in claim and (key not in defaults or claim[key] != defaults[key])]
		text = printAnnotations(pairs, list(META_KEYS))
		return f" {text}" if text else ""

	def statement(self, claim: Claim) -> str:
		for kind, operator in (("same", "="), ("distinct", "!=")):
			if kind in claim:
				left, right = claim[kind]
				return f"{self.handle(left)} {operator} {self.handle(right)}"
		if "rel" in claim:
			decl = self.model.get(claim["rel"])
			left, right = decl.participants
			prefix = f"{claim['s']}: " if "s" in claim else ""
			subject, obj = claim["roles"][left.role], claim["roles"][right.role]
			if subject == "?":
				# Only the object can be unknown in text. Keep canonical roles by using the inverse verb.
				if obj == "?" or not decl.arrow.inverse:
					raise ValueError("A relation with an unknown subject requires an inverse verb and a known object")
				return f"{prefix}{self.handle(obj)} {decl.arrow.inverse} ?"
			return f"{prefix}{self.handle(subject)} {decl.arrow.verb} {self.handle(obj)}"
		subject = self.handle(claim["s"])
		if "facet" in claim:
			return f"{subject}[{claim['facet']}]"
		if "p" in claim:
			return f"{subject}.{claim['p']}" + (f" {self.value(claim['v'])}" if "v" in claim else "")
		return subject

	def headers(self) -> list[str]:
		obs = self.observations.obs
		args = " ".join(f"{key}={obs[key]}" for key in HEADER_KEYS if key in obs)
		lines = [f"@obs {obs['ontology']}" + (f" {args}" if args else "")]
		if self.observations.sources:
			lines.append("@src " + " ".join(f"{alias}={token}" for alias, token in sorted(self.observations.sources.items())))
		if obs.get("scope") is not None:
			lines.append(f"@scope {obs['scope']}")
		ordinary: set[str] = set()
		namedLinks: set[str] = set()
		for claim in self.observations.claims + self.observations.retractions:
			if "s" in claim:
				ordinary.add(claim["s"])
				if "rel" in claim:
					namedLinks.add(claim["s"])
			ordinary.update(handle for handle in claim.get("roles", {}).values() if handle != "?")
			for kind in ("same", "distinct"):
				ordinary.update(claim.get(kind, []))
			value = claim.get("v")
			members = value.get("set", []) if isinstance(value, dict) and "set" in value else [value]
			ordinary.update(member["ref"] for member in members if isinstance(member, dict) and "ref" in member)
		for handle, instance in sorted(self.observations.instances.items()):
			decl = self.model.get(instance["type"])
			if handle in (namedLinks if decl.arrow else ordinary):
				continue
			if decl.arrow:
				left, right = decl.participants
				typeName = f"{self.short(left.type)}.{decl.arrow.verb}.{self.short(right.type)}"
			else:
				typeName = self.short(decl.path)
			lines.append(f"@type {handle} {typeName}")
			self.typed.add(handle)
		return lines

def renderObservationsLog(ontology: Ontology, observations: Observations, ordinals: list[int] | None = None) -> str:
	"""Render a log, optionally mapping each emitted statement to its original ordinal."""
	p = ObservationPrinter(ontology, observations)
	lines = p.headers()
	current = observationDefaults(observations)
	events = [(claim, False) for claim in observations.claims] + [(claim, True) for claim in observations.retractions]
	events += [({"n": gap.n, **gap.meta, "gap": gap}, False) for gap in observations.gaps]
	events.sort(key=lambda pair: (*claimOrder(pair[0]), not pair[0].get("exists", False)))
	directiveKeys = {key for key in ("src", "at") if all(key in event for event, _ in events)}
	grouped: set[int] = set()
	for claim, retract in events:
		if id(claim) in grouped:
			continue
		if ordinals is not None:
			ordinals.append(claim["n"])
		if "gap" in claim:
			gap = claim["gap"]
			if gap.ctx != current.get("ctx"):
				lines.append(f"@ctx {gap.ctx or 'none'}")
				current["ctx"] = gap.ctx
			# Emit effective defaults explicitly; raw source stays available on the Gap object.
			lines.append(gap.text + p.meta(gap.meta, {}))
			continue
		meta = claimMeta(claim)
		facets = []
		if claim.get("exists") and not retract:
			# NOTE: Reconstitute a record header's existence + facets as one statement.
			for facet in observations.claims:
				if "facet" not in facet or facet["n"] != claim["n"] or facet["s"] != claim["s"]:
					continue
				facetMeta = claimMeta(facet)
				context = facetMeta.pop("ctx", None)
				if facetMeta != {key: value for key, value in meta.items() if key not in ("valid", "ctx")}:
					continue
				if context is not None and meta.get("ctx", context) != context:
					continue
				if context is not None:
					meta["ctx"] = context
				facets.append(facet["facet"])
				grouped.add(id(facet))
		# There is no directive for clearing src/at. Do not set one when later claims lack it.
		for key in ("src", "at", "ctx"):
			value = meta.get(key)
			if value is not None and value != current.get(key):
				if key == "ctx" or key in directiveKeys:
					lines.append(f"@{key} {value}")
					current[key] = value
		text = p.statement(claim) + (f"[{', '.join(sorted(facets))}]" if facets else "")
		lines.append(("- " if retract else "") + text + p.meta(meta, current))
	return "\n".join(lines) + "\n"


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printObservationsState(ontology: Ontology, observations: Observations) -> str:
	"""Print a reconciled state; value-only subjects stay line-form to avoid inventing existence."""
	if observations.retractions:
		raise ValueError("State printing requires reconciliation first")
	if observations.gaps:
		raise ValueError("State text cannot preserve gaps; use JSON")
	p = ObservationPrinter(ontology, observations)
	lines = p.headers()
	implicit = sorted(handle for handle, instance in markImplicit(observations.instances, observations.claims).items() if instance.get("implicit"))
	if implicit:
		lines.append("@implicit " + " ".join(implicit))
	defaults = observationDefaults(observations)
	for key in ("src", "at"):
		counts = Counter(claim[key] for claim in observations.claims if key in claim)
		if counts and all(key in claim for claim in observations.claims):
			value = min(counts, key=lambda item: (-counts[item], item))
			if defaults.get(key) != value:
				lines.append(f"@{key} {value}")
			defaults[key] = value
	bySubject: dict[str, list[Claim]] = {}
	links = []
	identities = []
	for claim in observations.claims:
		if "same" in claim or "distinct" in claim:
			identities.append(claim)
		elif "rel" in claim:
			links.append(claim)
		else:
			bySubject.setdefault(claim["s"], []).append(claim)
	linkHandles = {claim["s"] for claim in links if "s" in claim}

	def typeOf(handle: str) -> str:
		return observations.instances[handle]["type"]

	def sourceSlot(claim: Claim) -> tuple:
		return (claimSlot(claim), observations.sources.get(claim.get("src"), claim.get("src")))

	sourceCounts = Counter(sourceSlot(claim) for claim in observations.claims if "p" in claim)
	chronologicalSlots = {claimSlot(claim) for claim in observations.claims
		if isinstance(claim.get("v"), dict) and "set" in claim["v"] and not claim["v"].get("partial")
		and sourceCounts[sourceSlot(claim)] > 1}

	def valueSort(claim: Claim) -> tuple:
		# Snapshot + later members is order-sensitive. Keep the slot's provenance-bearing claims intact.
		order = claimOrder(claim) if claimSlot(claim) in chronologicalSlots else (Fraction(0), 0)
		return (claim.get("p", ""), claim.get("ctx", ""), order, p.value(claim.get("v"), typed=False), valueKey(claimMeta(claim)))

	def record(handle: str) -> list[str]:
		claims = bySubject[handle]
		exists = sorted((claim for claim in claims if claim.get("exists")), key=lambda claim: valueKey(claimMeta(claim)))
		attrs = sorted((claim for claim in claims if "p" in claim), key=valueSort)
		facets = sorted((claim for claim in claims if "facet" in claim), key=lambda claim: (claim["facet"], claim.get("ctx", ""), valueKey(claimMeta(claim))))
		out = []
		inline = []
		if exists:
			head = exists[0]
			inline = [claim for claim in facets if "ctx" not in claim and "conflict" not in claim and claimMeta(claim) == {key: value for key, value in claimMeta(head).items() if key != "valid"}]
			names = sorted({claim["facet"] for claim in inline})
			out.append(p.handle(handle) + (f"[{', '.join(names)}]" if names else "") + p.meta(head, defaults))
			for claim in attrs:
				out.append(f"  {claim['p']} {p.value(claim['v'])}" + p.meta(claim, defaults))
		else:
			out += [p.statement(claim) + p.meta(claim, defaults) for claim in attrs]
		out += [p.statement(claim) + p.meta(claim, defaults) for claim in exists[1:]]
		out += [p.statement(claim) + p.meta(claim, defaults) for claim in facets if claim not in inline]
		return out

	for relation in (False, True):
		if relation:
			def linkSort(claim: Claim) -> tuple:
				decl = p.model.get(claim["rel"])
				left, right = decl.participants
				return (claim["roles"][left.role], decl.arrow.verb, claim["roles"][right.role], claim.get("s", ""), valueKey(claimMeta(claim)))
			for link in sorted(links, key=linkSort):
				block = [p.statement(link) + p.meta(link, defaults)]
				if link.get("s") in bySubject:
					# Relation attributes follow once, even when multiple sources claim the same link.
					block += [p.statement(claim) + p.meta(claim, defaults) for claim in sorted(bySubject.pop(link["s"]), key=valueSort)]
				lines += [""] + block
		for handle in sorted(bySubject, key=lambda item: (typeOf(item), item)):
			if handle not in linkHandles and (p.model.get(typeOf(handle)).kind == "relation") == relation:
				lines += [""] + record(handle)
	if identities:
		lines.append("")
		# NOTE: Link order chooses canonical handles; preserve it rather than sorting endpoints.
		for claim in sorted(identities, key=claimOrder):
			lines.append(p.statement(claim) + p.meta(claim, defaults))
	return "\n".join(lines) + "\n"


def printObservationsLog(ontology: Ontology, observations: Observations) -> str:
	"""Print a gap-free audit log; reject gaps rather than exposing them as active statements."""
	if observations.gaps:
		raise ValueError("Log text cannot preserve inert gaps; use JSON")
	return renderObservationsLog(ontology, observations)


def observationsToJson(observations: Observations) -> dict[str, Any]:
	"""Return an independent JSON-ready copy of a typed log or state."""
	liveClaims = {valueKey({key: value for key, value in claim.items() if key != "conflict"})
		for claim in observations.claims} if observations.gaps else set()
	return deepcopy({"format": OBSERVATIONS_FORMAT, "obs": observations.obs, "sources": observations.sources,
		"instances": observations.instances, "claims": observations.claims, "retractions": observations.retractions,
		**({"gaps": [gapJson(gap, liveClaims) for gap in observations.gaps]} if observations.gaps else {})})


# EOF
