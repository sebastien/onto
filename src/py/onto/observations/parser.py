"""Module: observations.parser — source parsing, ontology-backed resolution and JSON decoding."""

from __future__ import annotations

import json
import re
from copy import (
	deepcopy,
)
from collections.abc import Callable
from dataclasses import (
	replace,
)
from decimal import (
	Decimal,
)
from typing import (
	Any,
)
from ..ontology.model import RE_ELEMENT_PATH
from ..ontology import (
	Attr,
	Decl,
	Model,
	Ontology,
	QUALIFIERS,
	ResolvedType,
	isSymmetric,
)
from ..text import (
	Diagnostic,
	Diagnostics,
	Loc,
	Source,
	annotation,
	isName,
	isPath,
	isToken,
	parseAnnotations,
	parseArguments,
	scanUnquoted,
	sourceLines,
	splitAnnotations,
)
from .model import (
	Claim,
	Gap,
	HANDLE,
	HEADER_KEYS,
	META_KEYS,
	OBSERVATIONS_FORMAT,
	Observations,
	ObservationsDocument,
	PATH,
	RE_DURATION,
	RE_HEADER,
	RE_IDENTITY,
	RE_LINK,
	RE_REF,
	RE_VALUE,
	Statement,
	TypeDeclaration,
	timestampValue,
	useType,
	typedValueIdentity,
	valueKey,
	canonicalNumber,
	parseInterval,
)

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def metadata(pairs: list[tuple[str, str | bool]], loc: Loc, diag: Diagnostics) -> dict[str, Any]:
	result = dict(pairs)
	for key, value in pairs:
		try:
			if key not in META_KEYS:
				raise ValueError(f"Unknown metadata '{key}'")
			if key == "conflict":
				if value is not True:
					raise ValueError("conflict is a flag")
				continue
			if not isinstance(value, str):
				raise ValueError(f"'{key}' needs a value")
			if key == "at":
				timestampValue(value)
			elif key == "valid":
				parseInterval(value)
			elif key == "ctx" and (not isName(value) or value == "none"):
				raise ValueError("ctx must be a handle other than none")
			elif key == "conf":
				canonicalNumber(value)
				if not Decimal(0) <= Decimal(value) <= Decimal(1):
					raise ValueError("conf must be within 0..1")
			elif key == "scale" and value not in ("?", "1", "100"):
				raise ValueError("scale must be 1, 100 or ?")
		except ValueError as error:
			diag.error("meta", str(error), loc)
	result.pop("conflict", None)
	return result


def rangeOrder(element: ResolvedType) -> Callable[[Any], Any] | None:
	"""A sort key for the bounds of a range of `element`, or None when its values have no comparable order."""
	if element.builtin in ("Integer", "Number", "Amount", "Percent"):
		return Decimal
	if element.builtin in ("Date", "DateTime"):
		return timestampValue
	if element.builtin == "Duration":
		# NOTE: An ISO 8601 duration (unit unknown) has no comparable magnitude here.
		return lambda value: None if RE_DURATION.fullmatch(str(value)) else Decimal(value)
	if element.kind == "vocab" and element.ordered:
		values = element.values or []
		return lambda value: values.index(value) if value in values else None
	return None


def rawMembers(text: str) -> tuple[list[str], bool]:
	if not text.endswith("]"):
		raise ValueError("Unterminated collection")
	body = text[1:-1]
	if not body.strip():
		return [], False
	start, items = 0, []
	for index in scanUnquoted(body):
		if body[index] == ",":
			items.append(body[start:index].strip())
			start = index + 1
	items.append(body[start:].strip())
	partial = items[-1] == "..."
	if partial:
		items.pop()
	if any(not item or item in ("...", "?", "null") or item.startswith("[") for item in items):
		raise ValueError("Collections require concrete, non-nested members")
	return items, partial


def expandRef(text: str, aliases: dict[str, str]) -> str:
	"""Expand the handle of a bare or typed reference, preserving its type spelling."""
	handle, colon, kind = text.partition(":")
	return aliases.get(handle, handle) + colon + kind


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class ObservationResolver:
	"""Resolve typed mentions before checking references, allowing forward references."""

	def __init__(self, ontology: Ontology, doc: ObservationsDocument):
		self.model = Model(ontology)
		self.doc = doc
		self.diag = Diagnostics(list(doc.diagnostics))
		self.instances: dict[str, dict[str, str]] = {}
		self.references: list[tuple[str, str, Loc]] = []

	def typePath(self, name: str, loc: Loc) -> str | None:
		def resolve(path: str) -> str:
			head, slash, rest = path.partition("/")
			aliases = dict(self.model.ontology.uses)
			return f"{aliases[head]}/{rest}" if slash and head in aliases else f"{self.model.ontology.namespace}/{path}"

		if isPath(name):
			return resolve(name)
		parts = name.split(".")
		if len(parts) == 3 and isPath(parts[0]) and re.fullmatch(r"[a-z][A-Za-z0-9_]*", parts[1]) and isPath(parts[2]):
			return f"{resolve(parts[0])}.{parts[1]}.{resolve(parts[2])}"
		self.diag.error("type", f"Invalid instance type '{name}'", loc)
		return None

	def declare(self, handle: str, path: str, loc: Loc, allowBinary: bool = False) -> None:
		decl = self.model.get(path)
		if not decl or decl.kind not in ("entity", "relation") or decl.arrow and not allowBinary:
			kind = "instance type" if allowBinary else "entity or association"
			self.diag.error("type", f"Unknown {kind} '{path}'", loc)
			return
		old = self.instances.get(handle, {}).get("type")
		if old is None or self.model.isA(path, old):
			self.instances[handle] = {"type": path}
		elif old != path and not self.model.isA(old, path):
			self.diag.error("type", f"Handle '{handle}' has incompatible types '{old}' and '{path}'", loc)

	def ref(self, text: str, loc: Loc) -> str:
		match = RE_REF.fullmatch(text)
		if not match:
			raise ValueError(f"Invalid reference '{text}'")
		handle, typeName = match.groups()
		handle = self.doc.aliases.get(handle, handle)
		if typeName:
			if path := self.typePath(typeName, loc):
				self.declare(handle, path, loc)
		return handle

	def scalar(self, raw: str, resolved: ResolvedType, loc: Loc) -> Any:
		quoted = raw.startswith('"')
		text = json.loads(raw) if quoted else raw
		if not isinstance(text, str):
			raise ValueError("Quoted values must be JSON strings")
		if resolved.kind in ("entity", "relation"):
			if quoted:
				raise ValueError("Reference values must be unquoted handles")
			handle = self.ref(text, loc)
			self.references.append((handle, resolved.path, loc))
			return {"ref": handle}
		if resolved.kind == "range" and resolved.element:
			if quoted:
				raise ValueError("A range is written unquoted: low..high, low.. or ..high")
			return self.range(text, resolved.element, loc)
		if resolved.kind == "vocab":
			if quoted or not (isPath if resolved.hierarchical else isName)(text) or (not resolved.open and text not in resolved.values):
				raise ValueError(f"'{text}' is not a vocabulary value")
			return text
		builtin = resolved.builtin
		if quoted and builtin not in (None, "Text"):
			raise ValueError(f"Quoted text is not a {builtin}")
		if builtin in ("Integer", "Number", "Amount", "Percent"):
			canonical = canonicalNumber(text)
			if builtin == "Integer" and Decimal(text) != Decimal(text).to_integral_value():
				raise ValueError(f"'{text}' is not an integer")
			return canonical
		if builtin == "Boolean":
			if text not in ("true", "false"):
				raise ValueError(f"'{text}' is not a boolean")
			return text == "true"
		if builtin in ("Date", "DateTime"):
			timestampValue(text)
			if ("T" in text) != (builtin == "DateTime"):
				raise ValueError(f"'{text}' is not a {builtin}")
		if builtin == "Duration":
			unit = resolved.qualifiers.get("unit", "?")
			if unit == "?" and RE_DURATION.fullmatch(text):
				return text
			return canonicalNumber(text)
		if resolved.kind == "struct":
			raise ValueError("Structures require field paths")
		return text

	def range(self, text: str, element: ResolvedType, loc: Loc) -> str:
		"""Canonical `low..high` of a `Range<T>` value; a single value `v` is `v..v`. Bounds are inclusive and ordered."""
		low, separator, high = text.partition("..")
		if not separator:
			low = high = text
		if not low and not high:
			raise ValueError("A range needs at least one bound")
		bounds = [self.scalar(bound, element, loc) if bound else None for bound in (low, high)]
		if None not in bounds and (order := rangeOrder(element)) is not None:
			left, right = order(bounds[0]), order(bounds[1])
			if left is not None and right is not None and left > right:
				raise ValueError(f"Range '{text}' has its low bound above its high bound")
		return "..".join("" if bound is None else str(bound) for bound in bounds)

	def value(self, raw: str, attr: Attr, statement: Statement) -> Any:
		card = attr.card or self.model.defaultCard
		resolved = useType(self.model, attr, statement.meta)
		if raw == "?":
			return {"unknown": True}
		if raw == "null":
			if card in ("+", "*"):
				raise ValueError("null requires a single-valued slot")
			return None
		if raw.startswith("["):
			if card not in ("+", "*"):
				raise ValueError("Collection on a single-valued slot")
			members, partial = rawMembers(raw)
			if not members and not partial and card == "+":
				raise ValueError("[] contradicts cardinality +")
			values = [self.scalar(item, resolved, statement.loc) for item in members]
			if len({typedValueIdentity(value, resolved) for value in values}) != len(values):
				raise ValueError("Duplicate collection members")
			return {"set": sorted(values, key=valueKey), **({"partial": True} if partial else {})}
		return self.scalar(raw, resolved, statement.loc)

	def link(self, statement: Statement, meta: dict[str, Any], report: bool = True) -> Claim | None:
		subject = self.ref(statement.s, statement.loc)
		obj = self.ref(statement.obj, statement.loc) if statement.obj != "?" else "?"
		subjectType = self.instances.get(subject, {}).get("type")
		objectType = self.instances.get(obj, {}).get("type")
		candidates = self.model.verbs(subjectType, statement.verb)
		if subjectType is None:
			# A uniquely identified named relation can expose reference fields that type its endpoints.
			for decl in self.model.ontology.decls:
				if decl.arrow and decl.arrow.verb == statement.verb:
					candidates.append((decl, False))
				elif decl.arrow and decl.arrow.inverse == statement.verb:
					candidates.append((decl, True))
		candidates = [(decl, inverse) for decl, inverse in candidates
			if obj == "?" or objectType is None or self.model.isA(objectType, decl.participants[0 if inverse else 1].type)]
		if len(candidates) != 1:
			if report:
				self.diag.error("reference", f"Unknown, incompatible or ambiguous relation '{statement.verb}'", statement.loc)
			return None
		decl, inverse = candidates[0]
		left, right = (obj, subject) if inverse else (subject, obj)
		if isSymmetric(decl) and "?" not in (left, right):
			left, right = sorted((left, right))
		if statement.name:
			old = self.instances.get(statement.name)
			if old and old["type"] != decl.path:
				if report:
					self.diag.error("type", f"Incompatible relation handle '{statement.name}'", statement.loc)
				return None
			self.instances[statement.name] = {"type": decl.path}
		for handle, participant in zip((left, right), decl.participants):
			if handle != "?":
				self.references.append((handle, participant.type, statement.loc))
		return {"n": statement.n, **({"s": statement.name} if statement.name else {}), "rel": decl.path,
			"roles": {decl.participants[0].role: left, decl.participants[1].role: right}, **meta}

	def context(self, statement: Statement, facet: Decl | None, meta: dict[str, Any]) -> dict[str, Any]:
		expected = annotation(facet.ann, "ctx") if facet else None
		if not expected:
			if "ctx" in meta:
				self.diag.error("meta", "ctx applies only to contextual facets", statement.loc)
			return {key: value for key, value in meta.items() if key != "ctx"}
		ctx = meta.get("ctx", statement.ctx)
		if not ctx:
			self.diag.error("meta", f"Contextual facet '{facet.path}' requires ctx", statement.loc)
		else:
			self.references.append((ctx, expected, statement.loc))
		return meta | ({"ctx": ctx} if ctx else {})

	def checkValid(self, path: str, meta: dict[str, Any], loc: Loc) -> None:
		kind = annotation(self.model.get(path).ann, "kind")
		if "valid" in meta and kind and ((".." in meta["valid"]) != (kind == "state")):
			self.diag.error("meta", f"{kind} requires {'an interval' if kind == 'state' else 'a point'} valid", loc)

	def resolve(self, mode: str = "strict") -> Observations:
		ontology = self.model.ontology
		if self.doc.obs.get("ontology") != ontology.namespace:
			self.diag.error("header", "Observation namespace does not match ontology")
		revision = dict(ontology.header).get("rev")
		if self.doc.obs.get("rev") is not None and self.doc.obs["rev"] != revision:
			self.diag.error("header", "Observation revision does not match ontology")
		for declaration in self.doc.declarations:
			if path := self.typePath(declaration.type, declaration.loc):
				self.declare(declaration.handle, path, declaration.loc, allowBinary=True)
		# Directives establish the document's registry; invalid declarations cannot become statement gaps.
		self.diag.check()
		# NOTE: Register typed mentions in references as well as subjects before resolving binary verbs.
		for statement in self.doc.statements:
			if statement.form in ("link", "same", "distinct"):
				self.ref(statement.s, statement.loc)
				if statement.obj != "?":
					self.ref(statement.obj, statement.loc)
			else:
				self.ref(statement.s + (f":{statement.type}" if statement.type else ""), statement.loc)
		# Reference values can introduce types. Iterate until no more handles become available.
		# ponytail: bounded repeated scan; index pending subjects if large logs make forward typing expensive.
		for _ in range(len(self.doc.statements) + 1):
			before = dict(self.instances)
			for statement in self.doc.statements:
				if statement.form == "link":
					self.link(statement, {}, report=False)
					continue
				if statement.form != "value" or statement.raw is None:
					continue
				owner = self.instances.get(statement.s, {}).get("type")
				attr = self.model.lookup(owner, statement.p) if owner else None
				if attr:
					try:
						self.value(statement.raw, attr, statement)
					except ValueError:
						pass
			if self.instances == before:
				break
		self.references.clear()
		claims, retractions = [], []
		links = {}
		for statement in self.doc.statements:
			if statement.form == "link":
				links[statement.n] = self.link(statement, {})
		for statement in self.doc.statements:
			meta = dict(statement.meta)
			if "conf" in meta:
				meta["conf"] = float(meta["conf"])
			for key in ("of", "approved"):
				if not statement.retract and key in meta:
					self.diag.error("meta", f"{key} is only valid on retractions", statement.loc)
			if statement.form != "value" and any(key in meta for key in QUALIFIERS):
				self.diag.error("meta", "Measurement qualifiers require a value", statement.loc)
			if any(str(meta.get(key, "")).startswith("?:") for key in QUALIFIERS):
				self.diag.error("meta", "An observed qualifier is a value, not ?:V", statement.loc)
			target = retractions if statement.retract else claims
			base = {"n": statement.n, "s": statement.s}
			if statement.form in ("same", "distinct"):
				left, right = self.ref(statement.s, statement.loc), self.ref(statement.obj, statement.loc)
				leftType = self.instances.get(left, {}).get("type")
				rightType = self.instances.get(right, {}).get("type")
				if left == right:
					self.diag.error("identity", "An identity link cannot name the same handle twice", statement.loc)
				if not leftType or not rightType or not (leftType == rightType or self.model.isA(leftType, rightType) or self.model.isA(rightType, leftType)):
					self.diag.error("type", "Identity links require typed, compatible handles", statement.loc)
				if "ctx" in meta:
					self.diag.error("meta", "ctx applies only to contextual facets", statement.loc)
				pair = sorted((left, right)) if statement.form == "distinct" else [left, right]
				target.append({"n": statement.n, statement.form: pair, **meta})
				continue
			if statement.form == "link":
				if "ctx" in meta:
					self.diag.error("meta", "ctx applies only to contextual facets", statement.loc)
				if link := links[statement.n]:
					self.checkValid(link["rel"], meta, statement.loc)
					target.append(link | meta)
				continue
			owner = self.instances.get(statement.s, {}).get("type")
			if not owner:
				self.diag.error("type", f"Untyped handle '{statement.s}'", statement.loc)
				continue
			if statement.form == "exists":
				facets = self.model.facets(owner)
				contextual = any(name in facets and annotation(facets[name].ann, "ctx") for name in statement.facets)
				if not contextual and "ctx" in meta:
					self.diag.error("meta", "ctx requires a contextual facet", statement.loc)
				if not statement.retract or not statement.facets:
					self.checkValid(owner, meta, statement.loc)
					target.append(base | {"exists": True} | {key: value for key, value in meta.items() if key != "ctx"})
				for name in statement.facets:
					facet = facets.get(name)
					if not facet:
						self.diag.error("reference", f"Unknown facet '{name}' on '{owner}'", statement.loc)
						continue
					facetMeta = meta if annotation(facet.ann, "ctx") else {key: value for key, value in meta.items() if key != "ctx"}
					target.append(base | {"facet": name} | self.context(statement, facet, {key: value for key, value in facetMeta.items() if key != "valid"}))
			else:
				attr = self.model.lookup(owner, statement.p)
				if not attr:
					self.diag.error("reference", f"Unknown attribute '{owner}.{statement.p}'", statement.loc)
					continue
				if error := self.model.elementPathError(owner, statement.p):
					self.diag.error("key", error, statement.loc)
					continue
				facet = self.model.facetOf(owner, statement.p)
				claim = base | {"p": statement.p} | self.context(statement, facet, meta)
				try:
					if statement.raw is not None:
						claim["v"] = self.value(statement.raw, attr, statement)
						for conflict in useType(self.model, attr, meta).conflicts:
							self.diag.error("qualifier", conflict, statement.loc)
					elif any(key in meta for key in QUALIFIERS):
						self.diag.error("meta", "Measurement qualifiers require a value", statement.loc)
					target.append(claim)
				except ValueError as error:
					self.diag.error("value", str(error), statement.loc)
		for handle, expected, loc in set(self.references):
			actual = self.instances.get(handle, {}).get("type")
			if not actual or not self.model.isA(actual, expected):
				self.diag.error("type", f"'{handle}' is '{actual}', expected '{expected}'", loc)
		observations = Observations(dict(self.doc.obs), dict(self.doc.sources), dict(sorted(self.instances.items())), claims, retractions)
		return validateStatements(self, observations, self.diag.items, mode)

	def gapText(self, statement: Statement) -> str:
		"""Spell a held statement for JSON replay, which has no local alias table."""
		text = splitAnnotations(statement.text)[0]
		aliases = self.doc.aliases
		if not aliases:
			return text
		prefix = "- " if statement.retract else ""
		if statement.form in ("same", "distinct", "link"):
			verb = {"same": "=", "distinct": "!="}.get(statement.form, statement.verb)
			name = f"{statement.name}: " if statement.name else ""
			return f"{prefix}{name}{statement.s} {verb} {statement.obj}"
		# Only the initial handle changes in a header or attribute path.
		text = prefix + re.sub(rf"^{HANDLE}", lambda _: statement.s, text.removeprefix(prefix), count=1)
		raw = statement.raw
		if raw is None:
			return text
		owner = self.instances.get(statement.s, {}).get("type")
		attr = self.model.lookup(owner, statement.p) if owner else None
		if not attr or useType(self.model, attr, statement.meta).kind not in ("entity", "relation"):
			return text

		def ref(item: str) -> str:
			return expandRef(item, aliases) if RE_REF.fullmatch(item) else item

		if raw.startswith("["):
			try:
				members, partial = rawMembers(raw)
			except ValueError:
				return text  # Malformed collection syntax fails before resolving any members.
			if partial:
				members.append("...")
			value = "[" + ", ".join(map(ref, members)) + "]"
		else:
			value = ref(raw)
		return text[:-len(raw)] + value


def validateStatements(resolver: ObservationResolver, observations: Observations, diagnostics: list[Diagnostic], mode: str) -> Observations:
	"""Reject errors in strict mode; in lenient mode hold whole statements as inert gaps."""
	if not diagnostics:
		return observations
	doc = resolver.doc
	statements = {statement.loc: statement for statement in doc.statements}
	allDiagnostics = observations.diagnostics + diagnostics
	if mode == "strict" or any(item.level == "error" and item.loc not in statements for item in diagnostics):
		return replace(observations, diagnostics=Diagnostics(allDiagnostics).check())
	errors: dict[Loc, list[Diagnostic]] = {}
	for item in dict.fromkeys(diagnostics):
		if item.level == "error":
			errors.setdefault(item.loc, []).append(replace(item, level="warning"))
	gaps = [Gap(statement.n, statement.rawLine, resolver.gapText(statement), statement.loc,
		deepcopy(statement.meta), statement.ctx, tuple(errors[statement.loc]))
		for statement in doc.statements if statement.loc in errors]
	blocked = {gap.n for gap in gaps}
	return replace(observations,
		claims=[claim for claim in observations.claims if claim["n"] not in blocked],
		retractions=[claim for claim in observations.retractions if claim["n"] not in blocked],
		diagnostics=list(dict.fromkeys(replace(item, level="warning") for item in allDiagnostics)),
		gaps=sorted(observations.gaps + gaps, key=lambda gap: gap.n))

# -----------------------------------------------------------------------------
#
# JSON DECODING
#
# -----------------------------------------------------------------------------


def jsonObject(value: Any, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
	if not isinstance(value, dict):
		raise ValueError("Expected a JSON object")
	if not set(required) <= value.keys() or value.keys() - set(required + optional):
		raise ValueError(f"Expected members {required}, optional {optional}")
	return value


def jsonString(value: Any, check: Callable[[str], bool] = isToken) -> str:
	if not isinstance(value, str) or not check(value):
		raise ValueError(f"Invalid JSON string '{value}'")
	return value


def jsonValue(value: Any, member: bool = False) -> Any:
	if isinstance(value, (str, bool)) or value is None and not member:
		return value
	if not isinstance(value, dict):
		raise ValueError("A value must be a string, boolean, reference, collection, unknown or null")
	if set(value) == {"ref"}:
		jsonString(value["ref"], isName)
	elif set(value) == {"unknown"} and value["unknown"] is True and not member:
		pass
	elif set(value) in ({"set"}, {"set", "partial"}) and not member:
		if not isinstance(value["set"], list) or "partial" in value and value["partial"] is not True:
			raise ValueError("Invalid collection")
		for item in value["set"]:
			jsonValue(item, True)
	else:
		raise ValueError("Invalid value members or non-concrete collection member")
	return value


def jsonClaim(value: Any, retract: bool) -> Claim:
	claim = jsonObject(value, ("n",), ("s", "exists", "facet", "p", "v", "rel", "roles", "same", "distinct", *META_KEYS))
	if type(claim["n"]) is not int or claim["n"] < 1:
		raise ValueError("n must be a positive statement ordinal")
	forms = [key for key in ("exists", "facet", "p", "rel", "same", "distinct") if key in claim]
	if len(forms) != 1:
		raise ValueError("A claim must have exactly one form")
	form = forms[0]
	if form in ("same", "distinct"):
		pair = claim[form]
		if "s" in claim or not isinstance(pair, list) or len(pair) != 2:
			raise ValueError("Identity links require two handles and no s")
		for handle in pair:
			jsonString(handle, isName)
	if "s" in claim:
		jsonString(claim["s"], isName)
	elif form not in ("rel", "same", "distinct"):
		raise ValueError("A non-relation claim requires s")
	if form == "exists" and claim["exists"] is not True:
		raise ValueError("exists must be true")
	if form == "facet":
		jsonString(claim["facet"], isName)
	if form == "p":
		jsonString(claim["p"], lambda text: RE_ELEMENT_PATH.fullmatch(text) is not None)
		if "v" not in claim and not retract:
			raise ValueError("An attribute claim requires v")
	if "v" in claim:
		if form != "p":
			raise ValueError("Only attribute claims have v")
		jsonValue(claim["v"])
	if form == "rel":
		jsonString(claim["rel"], lambda text: re.fullmatch(rf"{PATH}\.[a-z][A-Za-z0-9_]*\.{PATH}", text) is not None)
		if "roles" not in claim or not isinstance(claim["roles"], dict):
			raise ValueError("A binary claim requires roles")
		for role, handle in claim["roles"].items():
			jsonString(role, isName)
			jsonString(handle, lambda text: text == "?" or isName(text))
	elif "roles" in claim:
		raise ValueError("Only binary claims have roles")
	for key in META_KEYS:
		if key not in claim:
			continue
		if key == "conflict":
			if claim[key] is not True:
				raise ValueError("conflict must be true")
		elif key == "conf":
			if type(claim[key]) not in (int, float) or not 0 <= claim[key] <= 1:
				raise ValueError("conf must be a number within 0..1")
		else:
			jsonString(claim[key])
	return {key: deepcopy(item) for key, item in claim.items() if key != "conflict"}


def readObservationsJson(ontology: Ontology, value: Any) -> Observations:
	data = jsonObject(value, ("format", "obs", "sources", "instances", "claims", "retractions"), ("gaps",))
	if data["format"] != OBSERVATIONS_FORMAT:
		raise ValueError(f"format must be '{OBSERVATIONS_FORMAT}'")
	obs = jsonObject(data["obs"], ("ontology",), (*HEADER_KEYS, "scope"))
	jsonString(obs["ontology"], isPath)
	for key in HEADER_KEYS:
		if key in obs:
			jsonString(obs[key])
	if obs.get("scope") is not None:
		jsonString(obs["scope"])
	sources, instances = data["sources"], data["instances"]
	if not isinstance(sources, dict) or not isinstance(instances, dict):
		raise ValueError("sources and instances must be objects")
	for alias, token in sources.items():
		jsonString(alias, isName)
		jsonString(token)
	model = Model(ontology)
	for handle, instance in instances.items():
		jsonString(handle, isName)
		jsonObject(instance, ("type",), ("implicit",))
		if "implicit" in instance and instance["implicit"] is not True:
			raise ValueError("implicit must be true when present")
		path = jsonString(instance["type"], lambda text: model.get(text) is not None)
		if model.get(path).kind not in ("entity", "relation"):
			raise ValueError(f"'{path}' is not an instance type")
	groups = []
	for key in ("claims", "retractions"):
		if not isinstance(data[key], list):
			raise ValueError(f"{key} must be an array")
		group = [jsonClaim(claim, key == "retractions") for claim in data[key]]
		for claim in group:
			if "s" in claim and claim["s"] not in instances:
				raise ValueError(f"Unregistered subject '{claim['s']}'")
			for kind in ("same", "distinct"):
				if kind in claim and any(handle not in instances for handle in claim[kind]):
					raise ValueError("Unregistered identity handle")
			if "rel" in claim:
				decl = model.get(claim["rel"])
				if not decl or not decl.arrow or set(claim["roles"]) != {participant.role for participant in decl.participants}:
					raise ValueError("Binary roles must match the declared relation")
		groups.append(group)
	registry = {handle: {"type": instance["type"]} for handle, instance in instances.items()}
	gaps = data.get("gaps", [])
	if not isinstance(gaps, list):
		raise ValueError("gaps must be an array")
	gaps = [jsonGap(gap) for gap in gaps]
	ordinals = {gap.n for gap in gaps}
	if len(ordinals) != len(gaps) or any(claim["n"] in ordinals for group in groups for claim in group):
		raise ValueError("Gap ordinals must be unique and cannot occur on claims or retractions")
	return Observations(deepcopy(obs) | {"scope": obs.get("scope")}, dict(sources), registry, *groups, gaps=gaps)


def jsonGap(value: Any) -> Gap:
	data = jsonObject(value, ("n", "raw", "text", "loc", "meta", "diagnostics"), ("ctx", "witnesses"))
	if type(data["n"]) is not int or data["n"] < 1:
		raise ValueError("A gap requires a positive statement ordinal")
	for key in ("raw", "text"):
		jsonString(data[key], lambda text: bool(text.strip()) and "\n" not in text and "\r" not in text)
	loc = jsonObject(data["loc"], ("file", "line"))
	if loc["file"] is not None:
		jsonString(loc["file"], lambda text: bool(text))
	if type(loc["line"]) is not int or loc["line"] < 1:
		raise ValueError("A gap requires a positive source line")
	location = Loc(loc["file"], loc["line"])
	meta = data["meta"]
	if not isinstance(meta, dict):
		raise ValueError("Gap meta must be an object")
	for key, item in meta.items():
		jsonString(key, isName)
		jsonString(item)
	diag = Diagnostics()
	if metadata(list(meta.items()), location, diag) != meta or diag.hasErrors():
		raise ValueError("Invalid gap metadata")
	if "ctx" in data:
		jsonString(data["ctx"], lambda text: isName(text) and text != "none")
	if not isinstance(data["diagnostics"], list) or not data["diagnostics"]:
		raise ValueError("A gap requires diagnostics")
	diagnostics = []
	for item in data["diagnostics"]:
		jsonObject(item, ("code", "message"))
		diagnostics.append(Diagnostic("warning", jsonString(item["code"], lambda text: all(isName(part) for part in text.split("."))),
			jsonString(item["message"], lambda text: bool(text)), location))
	witnesses = []
	if "witnesses" in data:
		if not isinstance(data["witnesses"], list) or not data["witnesses"]:
			raise ValueError("Gap witnesses must be a nonempty array")
		ordinals = {data["n"]}
		for item in data["witnesses"]:
			witness = jsonClaim(item, False)
			if "p" not in witness or witness["n"] in ordinals:
				raise ValueError("Gap witnesses must be attribute claims from distinct other statements")
			ordinals.add(witness["n"])
			witnesses.append(witness)
	return Gap(data["n"], data["raw"], data["text"], location, dict(meta), data.get("ctx"), tuple(diagnostics), tuple(witnesses))


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseObservations(source: Source) -> ObservationsDocument:
	"""Parse `source` into statements, expanding record and claim-neutral entity bodies."""
	diag = Diagnostics()
	doc = ObservationsDocument()
	defaults: dict[str, Any] = {}
	record, ctx = None, None
	entity = False
	rawLines = source.text.split("\n")
	if "\r" in source.text:
		diag.error("syntax", "Line endings must be LF", Loc(source.name, 1))
	for position, line in enumerate(sourceLines(source)):
		if line.tabs or line.indent not in (0, 2):
			diag.error("indent", "Body lines require exactly two spaces", line.loc)
			record = None
			continue
		if line.indent == 2:
			if record is None:
				diag.error("indent", "Body line without a record header", line.loc)
				continue
			if entity and line.text.startswith("->"):
				text = f"{record} {line.text[2:].lstrip()}"
				if not line.text[2:3].isspace() or not RE_LINK.fullmatch(splitAnnotations(text)[0]):
					diag.error("syntax", "An entity link requires '-> verb object'", line.loc)
					continue
			else:
				text = f"{record}.{line.text}"
		else:
			record = None
			entity = False
			text = line.text
		if text.startswith("@"):
			parts = text.split(maxsplit=1)
			directive, args = parts[0], parts[1] if len(parts) == 2 else ""
			if directive == "@obs":
				if position != 0:
					diag.error("header", "@obs must be first", line.loc)
					continue
				parts = args.split(maxsplit=1)
				namespace, rest = (parts[0], parts[1] if len(parts) == 2 else "") if parts else ("", "")
				if not isPath(namespace):
					diag.error("name", "Invalid ontology namespace", line.loc)
				header = parseArguments(rest, line.loc, diag)
				for key, _ in header:
					if key not in HEADER_KEYS:
						diag.error("header", f"Unknown @obs key '{key}'", line.loc)
				metadata([(key, value) for key, value in header if key != "rev"], line.loc, diag)
				doc.obs = {"ontology": namespace, **dict(header), "scope": None}
				defaults = {key: value for key, value in header if key != "rev"}
			elif directive == "@src" and "=" in args:
				for key, value in parseArguments(args, line.loc, diag):
					if key in doc.sources and doc.sources[key] != value:
						diag.error("duplicate", f"Source alias '{key}' redefined", line.loc)
					doc.sources[key] = value
			elif directive in ("@src", "@at") and isToken(args):
				key = directive[1:]
				metadata([(key, args)], line.loc, diag)
				defaults[key] = args
			elif directive == "@ctx" and isName(args):
				ctx = None if args == "none" else args
			elif directive == "@scope" and isToken(args):
				if doc.obs.get("scope") not in (None, args):
					diag.error("scope", "Scope cannot change within one observations document", line.loc)
				else:
					doc.obs["scope"] = args
			elif directive == "@type":
				parts = args.split()
				if len(parts) != 2 or not isName(parts[0]):
					diag.error("directive", "@type requires a handle and an instance type, without metadata", line.loc)
				else:
					doc.declarations.append(TypeDeclaration(parts[0], parts[1], line.loc))
			elif directive == "@entity":
				parts = args.split()
				if len(parts) != 2:
					diag.error("directive", "@entity requires [alias=]handle and an instance type", line.loc)
					continue
				alias, equals, handle = parts[0].rpartition("=")
				if not isName(handle) or equals and (not isName(alias) or {alias, handle} & {"none", "null"}):
					diag.error("directive", "Invalid @entity handle or alias", line.loc)
					continue
				if equals:
					if alias in doc.aliases and doc.aliases[alias] != handle:
						diag.error("duplicate", f"Entity alias '{alias}' redefined", line.loc)
					doc.aliases[alias] = handle
				else:
					handle = doc.aliases.get(handle, handle)  # Reopen a previously bound subject.
				doc.declarations.append(TypeDeclaration(handle, parts[1], line.loc))
				record, entity = handle, True
			elif directive == "@implicit" and args and all(isName(handle) for handle in args.split()):
				# NOTE: Display-only: neither introduces types nor asserts existence.
				pass
			else:
				diag.error("directive", f"Invalid directive '{text}'", line.loc)
			continue
		if not doc.obs.get("ontology"):
			diag.error("header", "File must start with @obs", line.loc)
			continue
		retract = text.startswith("- ")
		body, ann = splitAnnotations(text[2:] if retract else text)
		meta = defaults | metadata(parseAnnotations(ann, line.loc, diag), line.loc, diag)
		base = dict(n=len(doc.statements) + 1, loc=line.loc, meta=meta, retract=retract, ctx=ctx,
			text=text, rawLine=rawLines[line.loc.line - 1])
		if match := RE_IDENTITY.fullmatch(body):
			left, operator, right = match.groups()
			doc.statements.append(Statement(form="same" if operator == "=" else "distinct", s=left, type=None, obj=right, **base))
		elif match := RE_LINK.fullmatch(body):
			name, subject, verb, obj = match.groups()
			doc.statements.append(Statement(form="link", s=subject, type=None, name=name, verb=verb, obj=obj, **base))
		elif match := RE_HEADER.fullmatch(body):
			handle, typeName, facetText = match.groups()
			facets = [item.strip() for item in facetText.split(",")] if facetText is not None else []
			if any(not isName(item) for item in facets) or len(set(facets)) != len(facets):
				diag.error("syntax", "Invalid facet list", line.loc)
			doc.statements.append(Statement(form="exists", s=handle, type=typeName, facets=facets, **base))
			if not retract:
				record = handle
		elif match := RE_VALUE.fullmatch(body):
			ref, path, raw = match.groups()
			handle, typeName = RE_REF.fullmatch(ref).groups()
			if raw is None and not retract:
				diag.error("syntax", "Missing value", line.loc)
			doc.statements.append(Statement(form="value", s=handle, type=typeName, p=path, raw=raw, **base))
		else:
			diag.error("syntax", f"Unrecognised statement '{text}'", line.loc)
	if not doc.obs.get("ontology"):
		diag.error("header", "Missing @obs directive")
	if doc.aliases:
		for declaration in doc.declarations:
			if declaration.handle in doc.aliases:
				diag.error("duplicate", f"Entity alias '{declaration.handle}' shadows a declared handle", declaration.loc)
		# Value operands are expanded by ref() only when the ontology calls for a handle.
		for statement in doc.statements:
			statement.s = expandRef(statement.s, doc.aliases)
			if statement.obj:
				statement.obj = expandRef(statement.obj, doc.aliases)
			if statement.name:
				statement.name = doc.aliases.get(statement.name, statement.name)
			if statement.ctx:
				statement.ctx = doc.aliases.get(statement.ctx, statement.ctx)
			if "ctx" in statement.meta:
				value = statement.meta["ctx"]
				statement.meta["ctx"] = doc.aliases.get(value, value)
	doc.diagnostics = diag.check()
	return doc


# EOF
