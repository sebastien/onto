"""Module: observations — parse, type and reconcile observation claims (spec-02)."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .ontology import Attr, Model, Namer, Ontology, QUALIFIERS, ResolvedType, isSymmetric
from .text import Diagnostic, Diagnostics, FormatError, Loc, Source, annotation, isName, isPath, isToken, parseAnnotations, parseArguments, printAnnotations, scanUnquoted, sourceLines, splitAnnotations

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

type Claim = dict[str, Any]


@dataclass(slots=True)
class Statement:
	"""A statement before ontology-backed resolution; `raw` retains its value spelling."""

	n: int
	form: str
	s: str
	type: str | None
	loc: Loc
	meta: dict[str, str | bool]
	retract: bool = False
	p: str | None = None
	raw: str | None = None
	facets: list[str] = field(default_factory=list)
	verb: str | None = None
	obj: str | None = None
	name: str | None = None
	ctx: str | None = None


@dataclass(slots=True)
class ObservationsDocument:
	"""Parsed directives and statements, retaining source locations."""

	obs: dict[str, str | None] = field(default_factory=dict)
	sources: dict[str, str] = field(default_factory=dict)
	statements: list[Statement] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass(slots=True)
class Observations:
	"""Typed log or reconciled state; claim values use the spec-02 JSON representation."""

	obs: dict[str, str | None]
	sources: dict[str, str]
	instances: dict[str, dict[str, str]]
	claims: list[Claim]
	retractions: list[Claim]
	diagnostics: list[Diagnostic] = field(default_factory=list)


OBSERVATIONS_FORMAT = "onto.observations/1"
HEADER_KEYS = ("rev", "src", "at", "by", "conf")
META_KEYS = ("src", "at", "valid", "ctx", "conf", "by", "of", *QUALIFIERS, "conflict")
HANDLE = r"[A-Za-z_][A-Za-z0-9_]*"
PATH = rf"{HANDLE}(?:/{HANDLE})*"
REF = rf"{HANDLE}(?::{PATH})?"
RE_REF = re.compile(rf"({HANDLE})(?::({PATH}))?")
RE_HEADER = re.compile(rf"({HANDLE})(?::({PATH}))?(?:\[([^\]]*)\])?")
RE_VALUE = re.compile(rf"({REF})\.({HANDLE}(?:\.{HANDLE})*)(?:\s+(.+))?")
RE_LINK = re.compile(rf"(?:({HANDLE}):\s+)?({REF})\s+([a-z][A-Za-z0-9_]*)\s+({REF}|\?)")
RE_DECIMAL = re.compile(r"([+-]?)(\d*(?:\.\d*)?)(?:[eE]([+-]?\d+))?", re.ASCII)
RE_INTEGER = re.compile(r"[+-]?\d+", re.ASCII)
RE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?", re.ASCII)
RE_DURATION = re.compile(r"P(?=\d|T\d)(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?", re.ASCII)

# -----------------------------------------------------------------------------
#
# VALUES AND METADATA
#
# -----------------------------------------------------------------------------


def canonicalNumber(text: str) -> str:
	"""Canonical decimal spelling without binary floating point or decimal-context rounding."""
	match = RE_DECIMAL.fullmatch(text)
	if not match or not any(char.isdigit() for char in match[2]):
		raise ValueError(f"Invalid decimal '{text}'")
	sign, mantissa, exponent = match.groups()
	whole, _, fraction = mantissa.partition(".")
	whole = whole.lstrip("0") or "0"
	fraction = fraction.rstrip("0")
	if whole == "0" and not fraction:
		return "0"
	value = ("-" if sign == "-" else "") + whole + (f".{fraction}" if fraction else "")
	return value + (f"e{int(exponent)}" if exponent and int(exponent) else "")


def _time(text: str) -> datetime:
	if not RE_TIME.fullmatch(text):
		raise ValueError(f"Invalid date or date-time '{text}'")
	value = datetime.fromisoformat(text) if "T" in text else datetime.combine(date.fromisoformat(text), datetime.min.time())
	# NOTE: Unzoned timestamps and dates share a UTC comparison basis; no machine-local timezone.
	return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parseInterval(text: str) -> tuple[datetime | None, datetime | None]:
	"""Parse a point or open/closed interval; reject impossible dates and reversed bounds."""
	parts = text.split("..") if ".." in text else [text, text]
	if len(parts) != 2 or not any(parts):
		raise ValueError(f"Invalid interval '{text}'")
	start, end = (_time(part) if part else None for part in parts)
	if start and end and start > end:
		raise ValueError(f"Reversed interval '{text}'")
	return start, end


def _metadata(pairs: list[tuple[str, str | bool]], loc: Loc, diag: Diagnostics) -> dict[str, Any]:
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
				_time(value)
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


def _members(text: str) -> tuple[list[str], bool]:
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


def _valueKey(value: Any) -> str:
	return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _valueIdentity(value: Any, numeric: bool) -> tuple:
	# NOTE: Preserve the spec's exponent spelling in JSON, but compare exact numeric values.
	if numeric and isinstance(value, str) and RE_DECIMAL.fullmatch(value):
		return ("number", Decimal(value))
	if isinstance(value, dict) and "set" in value:
		return ("set", frozenset(_valueIdentity(item, numeric) for item in value["set"]), value.get("partial", False))
	return ("value", _valueKey(value))

# -----------------------------------------------------------------------------
#
# PARSING
#
# -----------------------------------------------------------------------------


def parseObservations(source: Source) -> ObservationsDocument:
	"""Parse `source` into statements; directives supply metadata defaults, never record headers."""
	diag = Diagnostics()
	doc = ObservationsDocument()
	defaults: dict[str, Any] = {}
	record, ctx = None, None
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
			text = f"{record}.{line.text}"
		else:
			record = None
			text = line.text
		if text.startswith("@"):
			directive, _, args = text.partition(" ")
			args = args.strip()
			if directive == "@obs":
				if position != 0:
					diag.error("header", "@obs must be first", line.loc)
					continue
				namespace, _, rest = args.partition(" ")
				if not isPath(namespace):
					diag.error("name", "Invalid ontology namespace", line.loc)
				header = parseArguments(rest, line.loc, diag)
				for key, _ in header:
					if key not in HEADER_KEYS:
						diag.error("header", f"Unknown @obs key '{key}'", line.loc)
				_metadata([(key, value) for key, value in header if key != "rev"], line.loc, diag)
				doc.obs = {"ontology": namespace, **dict(header), "scope": None}
				defaults = {key: value for key, value in header if key != "rev"}
			elif directive == "@src" and "=" in args:
				for key, value in parseArguments(args, line.loc, diag):
					if key in doc.sources and doc.sources[key] != value:
						diag.error("duplicate", f"Source alias '{key}' redefined", line.loc)
					doc.sources[key] = value
			elif directive in ("@src", "@at") and isToken(args):
				key = directive[1:]
				_metadata([(key, args)], line.loc, diag)
				defaults[key] = args
			elif directive == "@ctx" and isName(args):
				ctx = None if args == "none" else args
			elif directive == "@scope" and isToken(args):
				doc.obs["scope"] = args
			else:
				diag.error("directive", f"Invalid directive '{text}'", line.loc)
			continue
		if not doc.obs.get("ontology"):
			diag.error("header", "File must start with @obs", line.loc)
			continue
		retract = text.startswith("- ")
		body, ann = splitAnnotations(text[2:] if retract else text)
		meta = defaults | _metadata(parseAnnotations(ann, line.loc, diag), line.loc, diag)
		base = dict(n=len(doc.statements) + 1, loc=line.loc, meta=meta, retract=retract, ctx=ctx)
		if match := RE_LINK.fullmatch(body):
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
	doc.diagnostics = diag.check()
	return doc

# -----------------------------------------------------------------------------
#
# TYPING
#
# -----------------------------------------------------------------------------


class _Resolver:
	"""Resolve typed mentions before checking references, allowing forward references."""

	def __init__(self, ontology: Ontology, doc: ObservationsDocument):
		self.model = Model(ontology)
		self.doc = doc
		self.diag = Diagnostics(list(doc.diagnostics))
		self.instances: dict[str, dict[str, str]] = {}
		self.references: list[tuple[str, str, Loc]] = []

	def declare(self, handle: str, path: str, loc: Loc) -> None:
		decl = self.model.get(path)
		if not decl or decl.kind not in ("entity", "relation") or decl.arrow:
			self.diag.error("type", f"Unknown entity or association '{path}'", loc)
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
		if typeName:
			head, slash, rest = typeName.partition("/")
			aliases = dict(self.model.ontology.uses)
			path = f"{aliases[head]}/{rest}" if slash and head in aliases else f"{self.model.ontology.namespace}/{typeName}"
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
		if resolved.kind == "vocab":
			if quoted or not isName(text) or (not resolved.open and text not in resolved.values):
				raise ValueError(f"'{text}' is not a vocabulary value")
			return text
		builtin = resolved.builtin
		if quoted and builtin not in (None, "Text"):
			raise ValueError(f"Quoted text is not a {builtin}")
		if builtin in ("Integer", "Number", "Amount", "Percent"):
			if builtin == "Integer" and not RE_INTEGER.fullmatch(text):
				raise ValueError(f"'{text}' is not an integer")
			return canonicalNumber(text)
		if builtin == "Boolean":
			if text not in ("true", "false"):
				raise ValueError(f"'{text}' is not a boolean")
			return text == "true"
		if builtin in ("Date", "DateTime"):
			_time(text)
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

	def value(self, raw: str, attr: Attr, statement: Statement) -> Any:
		card = attr.card or self.model.defaultCard
		resolved = self.model.resolveType(attr.type, attr.ann)
		if raw == "?":
			return {"unknown": True}
		if raw == "null":
			if card in ("+", "*"):
				raise ValueError("null requires a single-valued slot")
			return None
		if raw.startswith("["):
			if card not in ("+", "*"):
				raise ValueError("Collection on a single-valued slot")
			members, partial = _members(raw)
			if not members and not partial and card == "+":
				raise ValueError("[] contradicts cardinality +")
			values = [self.scalar(item, resolved, statement.loc) for item in members]
			numeric = resolved.builtin in ("Integer", "Number", "Amount", "Percent", "Duration")
			if len({_valueIdentity(value, numeric) for value in values}) != len(values):
				raise ValueError("Duplicate collection members")
			return {"set": sorted(values, key=_valueKey), **({"partial": True} if partial else {})}
		return self.scalar(raw, resolved, statement.loc)

	def link(self, statement: Statement, meta: dict[str, Any]) -> Claim | None:
		subject = self.ref(statement.s, statement.loc)
		obj = self.ref(statement.obj, statement.loc) if statement.obj != "?" else "?"
		subjectType = self.instances.get(subject, {}).get("type")
		objectType = self.instances.get(obj, {}).get("type")
		candidates = [
			(decl, inverse) for decl, inverse in self.model.verbs(subjectType, statement.verb)
			if obj == "?" or objectType and self.model.isA(objectType, decl.participants[0 if inverse else 1].type)
		]
		if len(candidates) != 1:
			self.diag.error("reference", f"Unknown, incompatible or ambiguous relation '{statement.verb}'", statement.loc)
			return None
		decl, inverse = candidates[0]
		left, right = (obj, subject) if inverse else (subject, obj)
		if isSymmetric(decl) and "?" not in (left, right):
			left, right = sorted((left, right))
		if statement.name:
			old = self.instances.get(statement.name)
			if old and old["type"] != decl.path:
				self.diag.error("type", f"Incompatible relation handle '{statement.name}'", statement.loc)
			self.instances[statement.name] = {"type": decl.path}
		return {"n": statement.n, **({"s": statement.name} if statement.name else {}), "rel": decl.path,
			"roles": {decl.participants[0].role: left, decl.participants[1].role: right}, **meta}

	def context(self, statement: Statement, facet, meta: dict[str, Any]) -> dict[str, Any]:
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

	def resolve(self) -> Observations:
		ontology = self.model.ontology
		if self.doc.obs.get("ontology") != ontology.namespace:
			self.diag.error("header", "Observation namespace does not match ontology")
		revision = dict(ontology.header).get("rev")
		if self.doc.obs.get("rev") is not None and self.doc.obs["rev"] != revision:
			self.diag.error("header", "Observation revision does not match ontology")
		# NOTE: Register typed mentions in references as well as subjects before resolving binary verbs.
		for statement in self.doc.statements:
			if statement.form == "link":
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
		claims, retractions = [], []
		links = {}
		for statement in self.doc.statements:
			if statement.form == "link":
				links[statement.n] = self.link(statement, {})
		for statement in self.doc.statements:
			meta = dict(statement.meta)
			if "conf" in meta:
				meta["conf"] = float(meta["conf"])
			if not statement.retract and "of" in meta:
				self.diag.error("meta", "of is only valid on retractions", statement.loc)
			if statement.form != "value" and any(key in meta for key in QUALIFIERS):
				self.diag.error("meta", "Measurement qualifiers require a value", statement.loc)
			target = retractions if statement.retract else claims
			base = {"n": statement.n, "s": statement.s}
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
				facet = self.model.facetOf(owner, statement.p)
				claim = base | {"p": statement.p} | self.context(statement, facet, meta)
				try:
					if statement.raw is not None:
						claim["v"] = self.value(statement.raw, attr, statement)
						resolved = self.model.resolveType(attr.type, attr.ann)
						for key in QUALIFIERS:
							fixed = resolved.qualifiers.get(key, "?")
							if key in meta and fixed != "?" and meta[key] != fixed:
								self.diag.error("qualifier", f"{key}={meta[key]} contradicts {key}={fixed}", statement.loc)
					elif any(key in meta for key in QUALIFIERS):
						self.diag.error("meta", "Measurement qualifiers require a value", statement.loc)
					target.append(claim)
				except ValueError as error:
					self.diag.error("value", str(error), statement.loc)
		for handle, expected, loc in set(self.references):
			actual = self.instances.get(handle, {}).get("type")
			if not actual or not self.model.isA(actual, expected):
				self.diag.error("type", f"'{handle}' is '{actual}', expected '{expected}'", loc)
		return Observations(dict(self.doc.obs), dict(self.doc.sources), dict(sorted(self.instances.items())), claims, retractions, self.diag.check())

# -----------------------------------------------------------------------------
#
# RECONCILIATION
#
# -----------------------------------------------------------------------------


def _slot(claim: Claim) -> tuple[str, str, str]:
	if "rel" in claim:
		subject = claim.get("s") or f"{claim['rel']}:{_valueKey(claim['roles'])}"
		member = ""
	else:
		subject = claim["s"]
		member = f"[{claim['facet']}]" if "facet" in claim else claim.get("p", "")
	return subject, member, claim.get("ctx", "")


def _order(claim: Claim) -> tuple[datetime, int]:
	return (_time(claim["at"]) if "at" in claim else datetime.min.replace(tzinfo=timezone.utc), claim["n"])


def _overlaps(left: Claim, right: Claim) -> bool:
	a, b = parseInterval(left["valid"]) if "valid" in left else (None, None)
	c, d = parseInterval(right["valid"]) if "valid" in right else (None, None)
	return (a is None or d is None or a <= d) and (c is None or b is None or c <= b)


def _retracts(retraction: Claim, claim: Claim, sources: dict[str, str]) -> bool:
	withdrawn = retraction.get("of", retraction.get("src"))
	claimed = claim.get("src")
	if sources.get(withdrawn, withdrawn) != sources.get(claimed, claimed) or _order(claim) > _order(retraction):
		return False
	if "ctx" in retraction and retraction["ctx"] != claim.get("ctx"):
		return False
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


def reconcileObservations(ontology: Ontology, observations: Observations) -> Observations:
	"""Apply source-scoped retractions and supersession; retain and flag cross-source conflicts."""
	model = Model(ontology)
	diag = Diagnostics(list(observations.diagnostics))
	active: dict[tuple[tuple[str, str, str], str | None], list[Claim]] = {}

	def source(claim: Claim) -> str | None:
		name = claim.get("src")
		return observations.sources.get(name, name)

	def multi(claim: Claim) -> bool:
		if "p" not in claim:
			return False
		attr = model.lookup(observations.instances[claim["s"]]["type"], claim["p"])
		return (attr.card or model.defaultCard) in ("+", "*")

	def meaning(claim: Claim) -> tuple:
		numeric = False
		qualifiers = {}
		if "p" in claim:
			attr = model.lookup(observations.instances[claim["s"]]["type"], claim["p"])
			resolved = model.resolveType(attr.type, attr.ann)
			numeric = resolved.builtin in ("Integer", "Number", "Amount", "Percent", "Duration")
			qualifiers = resolved.qualifiers | {key: claim[key] for key in QUALIFIERS if key in claim}
		value = _valueIdentity(claim["v"], numeric) if "v" in claim else ("missing",)
		return value, _valueKey(claim.get("roles")), _valueKey(qualifiers)

	for item, retract in sorted([(claim, False) for claim in observations.claims] + [(claim, True) for claim in observations.retractions], key=lambda pair: _order(pair[0])):
		item = {key: value for key, value in item.items() if key != "conflict"}
		if not retract:
			key = (_slot(item), source(item))
			complete = isinstance(item.get("v"), dict) and "set" in item["v"] and not item["v"].get("partial")
			if not multi(item) or complete:
				active[key] = [item]
			elif not any(meaning(old) == meaning(item) for old in active.get(key, [])):
				active.setdefault(key, []).append(item)
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
						claim = claim | {"v": claim["v"] | {"set": members}}
				kept.append(claim)
			active[key] = kept
		if not removed:
			diag.warn("retraction", f"Retraction of '{_slot(item)}' matched no claim")
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
	return Observations(deepcopy(observations.obs), dict(observations.sources), deepcopy(observations.instances),
		sorted(deepcopy(claims), key=lambda claim: claim["n"]), [], diag.items)

# -----------------------------------------------------------------------------
#
# PRINTING
#
# -----------------------------------------------------------------------------


class _Printer:
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

	def value(self, value: Any, inSet: bool = False) -> str:
		if value is None:
			return "null"
		if isinstance(value, bool):
			return "true" if value else "false"
		if isinstance(value, dict):
			if "unknown" in value:
				return "?"
			if "ref" in value:
				return self.handle(value["ref"])
			# NOTE: Sort before introducing typed mentions; typing must not change collection ordering.
			members = sorted(value["set"], key=_valueKey)
			parts = [self.value(member, True) for member in members]
			if value.get("partial"):
				parts.append("...")
			return f"[{', '.join(parts)}]"
		unsafe = not value or value != value.strip() or any(char in value for char in '\n\r"') or " {" in value or re.search(r"(^|\s)//", value) or value in ("?", "null") or value.startswith("[") or inSet and (value == "..." or any(char in value for char in ",]"))
		return json.dumps(value, ensure_ascii=False) if unsafe else value

	def meta(self, claim: Claim, defaults: dict[str, Any]) -> str:
		pairs = [(key, claim[key]) for key in META_KEYS if key in claim and (key not in defaults or claim[key] != defaults[key])]
		text = printAnnotations(pairs, list(META_KEYS))
		return f" {text}" if text else ""

	def statement(self, claim: Claim) -> str:
		if "rel" in claim:
			decl = self.model.get(claim["rel"])
			left, right = decl.participants
			prefix = f"{claim['s']}: " if "s" in claim else ""
			return f"{prefix}{self.handle(claim['roles'][left.role])} {decl.arrow.verb} {self.handle(claim['roles'][right.role])}"
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
		return lines


def _defaults(observations: Observations) -> dict[str, Any]:
	return {key: float(value) if key == "conf" else value for key, value in observations.obs.items() if key in ("src", "at", "by", "conf")}


def _claimMeta(claim: Claim) -> dict[str, Any]:
	return {key: claim[key] for key in META_KEYS if key in claim}


def printObservationsLog(ontology: Ontology, observations: Observations) -> str:
	"""Print all claims and retractions chronologically, without introducing new claims."""
	p = _Printer(ontology, observations)
	lines = p.headers()
	current = _defaults(observations)
	events = sorted([(claim, False) for claim in observations.claims] + [(claim, True) for claim in observations.retractions], key=lambda pair: (*_order(pair[0]), not pair[0].get("exists", False)))
	directiveKeys = {key for key in ("src", "at") if all(key in event for event, _ in events)}
	grouped: set[int] = set()
	for claim, retract in events:
		if id(claim) in grouped:
			continue
		meta = _claimMeta(claim)
		facets = []
		if claim.get("exists") and not retract:
			# NOTE: Reconstitute a record header's existence + facets as one statement.
			for facet in observations.claims:
				if "facet" not in facet or facet["n"] != claim["n"] or facet["s"] != claim["s"]:
					continue
				facetMeta = _claimMeta(facet)
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


def printObservationsState(ontology: Ontology, observations: Observations) -> str:
	"""Print a reconciled state; value-only subjects stay line-form to avoid inventing existence."""
	if observations.retractions:
		raise ValueError("State printing requires reconciliation first")
	p = _Printer(ontology, observations)
	lines = p.headers()
	defaults = _defaults(observations)
	for key in ("src", "at"):
		counts = Counter(claim[key] for claim in observations.claims if key in claim)
		if counts and all(key in claim for claim in observations.claims):
			value = min(counts, key=lambda item: (-counts[item], item))
			if defaults.get(key) != value:
				lines.append(f"@{key} {value}")
			defaults[key] = value
	bySubject: dict[str, list[Claim]] = {}
	links = []
	for claim in observations.claims:
		if "rel" in claim:
			links.append(claim)
		else:
			bySubject.setdefault(claim["s"], []).append(claim)
	linkHandles = {claim["s"] for claim in links if "s" in claim}

	def typeOf(handle: str) -> str:
		return observations.instances[handle]["type"]

	def valueSort(claim: Claim) -> tuple:
		return (claim.get("p", ""), claim.get("ctx", ""), _valueKey(claim.get("v")), _valueKey(_claimMeta(claim)))

	def record(handle: str) -> list[str]:
		claims = bySubject[handle]
		exists = sorted((claim for claim in claims if claim.get("exists")), key=lambda claim: _valueKey(_claimMeta(claim)))
		attrs = sorted((claim for claim in claims if "p" in claim), key=valueSort)
		facets = sorted((claim for claim in claims if "facet" in claim), key=lambda claim: (claim["facet"], claim.get("ctx", ""), _valueKey(_claimMeta(claim))))
		out = []
		inline = []
		if exists:
			head = exists[0]
			inline = [claim for claim in facets if "ctx" not in claim and "conflict" not in claim and _claimMeta(claim) == {key: value for key, value in _claimMeta(head).items() if key != "valid"}]
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
				return (claim["roles"][left.role], decl.arrow.verb, claim["roles"][right.role], claim.get("s", ""), _valueKey(_claimMeta(claim)))
			for link in sorted(links, key=linkSort):
				block = [p.statement(link) + p.meta(link, defaults)]
				if link.get("s") in bySubject:
					# Relation attributes follow once, even when multiple sources claim the same link.
					block += [p.statement(claim) + p.meta(claim, defaults) for claim in sorted(bySubject.pop(link["s"]), key=valueSort)]
				lines += [""] + block
		for handle in sorted(bySubject, key=lambda item: (typeOf(item), item)):
			if handle not in linkHandles and (p.model.get(typeOf(handle)).kind == "relation") == relation:
				lines += [""] + record(handle)
	return "\n".join(lines) + "\n"


# -----------------------------------------------------------------------------
#
# JSON INPUT
#
# -----------------------------------------------------------------------------


def _jsonObject(value: Any, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
	if not isinstance(value, dict):
		raise ValueError("Expected a JSON object")
	if not set(required) <= value.keys() or value.keys() - set(required + optional):
		raise ValueError(f"Expected members {required}, optional {optional}")
	return value


def _jsonString(value: Any, check=isToken) -> str:
	if not isinstance(value, str) or not check(value):
		raise ValueError(f"Invalid JSON string '{value}'")
	return value


def _jsonValue(value: Any, member: bool = False) -> Any:
	if isinstance(value, (str, bool)) or value is None and not member:
		return value
	if not isinstance(value, dict):
		raise ValueError("A value must be a string, boolean, reference, collection, unknown or null")
	if set(value) == {"ref"}:
		_jsonString(value["ref"], isName)
	elif set(value) == {"unknown"} and value["unknown"] is True and not member:
		pass
	elif set(value) in ({"set"}, {"set", "partial"}) and not member:
		if not isinstance(value["set"], list) or "partial" in value and value["partial"] is not True:
			raise ValueError("Invalid collection")
		for item in value["set"]:
			_jsonValue(item, True)
	else:
		raise ValueError("Invalid value members or non-concrete collection member")
	return value


def _jsonClaim(value: Any, retract: bool) -> Claim:
	claim = _jsonObject(value, ("n",), ("s", "exists", "facet", "p", "v", "rel", "roles", *META_KEYS))
	if type(claim["n"]) is not int or claim["n"] < 1:
		raise ValueError("n must be a positive statement ordinal")
	forms = [key for key in ("exists", "facet", "p", "rel") if key in claim]
	if len(forms) != 1:
		raise ValueError("A claim must have exactly one form")
	form = forms[0]
	if "s" in claim:
		_jsonString(claim["s"], isName)
	elif form != "rel":
		raise ValueError("A non-relation claim requires s")
	if form == "exists" and claim["exists"] is not True:
		raise ValueError("exists must be true")
	if form == "facet":
		_jsonString(claim["facet"], isName)
	if form == "p":
		_jsonString(claim["p"], lambda text: re.fullmatch(rf"{HANDLE}(?:\.{HANDLE})*", text) is not None)
		if "v" not in claim and not retract:
			raise ValueError("An attribute claim requires v")
	if "v" in claim:
		if form != "p":
			raise ValueError("Only attribute claims have v")
		_jsonValue(claim["v"])
	if form == "rel":
		_jsonString(claim["rel"], lambda text: re.fullmatch(rf"{PATH}\.[a-z][A-Za-z0-9_]*\.{PATH}", text) is not None)
		if "roles" not in claim or not isinstance(claim["roles"], dict):
			raise ValueError("A binary claim requires roles")
		for role, handle in claim["roles"].items():
			_jsonString(role, isName)
			_jsonString(handle, lambda text: text == "?" or isName(text))
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
			_jsonString(claim[key])
	return {key: deepcopy(item) for key, item in claim.items() if key != "conflict"}


def _readObservationsJson(ontology: Ontology, value: Any) -> Observations:
	data = _jsonObject(value, ("format", "obs", "sources", "instances", "claims", "retractions"))
	if data["format"] != OBSERVATIONS_FORMAT:
		raise ValueError(f"format must be '{OBSERVATIONS_FORMAT}'")
	obs = _jsonObject(data["obs"], ("ontology",), (*HEADER_KEYS, "scope"))
	_jsonString(obs["ontology"], isPath)
	for key in HEADER_KEYS:
		if key in obs:
			_jsonString(obs[key])
	if obs.get("scope") is not None:
		_jsonString(obs["scope"])
	sources, instances = data["sources"], data["instances"]
	if not isinstance(sources, dict) or not isinstance(instances, dict):
		raise ValueError("sources and instances must be objects")
	for alias, token in sources.items():
		_jsonString(alias, isName)
		_jsonString(token)
	model = Model(ontology)
	for handle, instance in instances.items():
		_jsonString(handle, isName)
		_jsonObject(instance, ("type",))
		path = _jsonString(instance["type"], lambda text: model.get(text) is not None)
		if model.get(path).kind not in ("entity", "relation"):
			raise ValueError(f"'{path}' is not an instance type")
	groups = []
	for key in ("claims", "retractions"):
		if not isinstance(data[key], list):
			raise ValueError(f"{key} must be an array")
		group = [_jsonClaim(claim, key == "retractions") for claim in data[key]]
		for claim in group:
			if "s" in claim and claim["s"] not in instances:
				raise ValueError(f"Unregistered subject '{claim['s']}'")
			if "rel" in claim:
				decl = model.get(claim["rel"])
				if not decl or not decl.arrow or set(claim["roles"]) != {participant.role for participant in decl.participants}:
					raise ValueError("Binary roles must match the declared relation")
		groups.append(group)
	return Observations(deepcopy(obs) | {"scope": obs.get("scope")}, dict(sources), deepcopy(instances), *groups)


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
# API
#
# -----------------------------------------------------------------------------


def resolveObservations(ontology: Ontology, doc: ObservationsDocument) -> Observations:
	"""Resolve handles, references, values and contexts in parsed `doc` against `ontology`."""
	return _Resolver(ontology, doc).resolve()


def loadObservations(ontology: Ontology, source: Source) -> Observations:
	"""Parse and validate `source` against `ontology`, retaining all claims and retractions."""
	return resolveObservations(ontology, parseObservations(source))


def observationsToJson(observations: Observations) -> dict[str, Any]:
	"""Return an independent JSON-ready copy of a typed log or state."""
	return deepcopy({"format": OBSERVATIONS_FORMAT, "obs": observations.obs, "sources": observations.sources,
		"instances": observations.instances, "claims": observations.claims, "retractions": observations.retractions})


def formatObservations(ontology: Ontology, source: Source, form: str = "state") -> str:
	"""Load `source` and print its `state` or audit `log` form."""
	log = loadObservations(ontology, source)
	if form == "log":
		return printObservationsLog(ontology, log)
	if form == "state":
		return printObservationsState(ontology, reconcileObservations(ontology, log))
	raise ValueError("form must be state or log")


def observationsFromJson(ontology: Ontology, data: Any, name: str = "observations.json") -> Observations:
	"""Read strict JSON through text validation; retain its ordinals and reject lossy representations."""
	try:
		read = _readObservationsJson(ontology, data)
		text = printObservationsLog(ontology, read)
		loaded = loadObservations(ontology, Source(name, text))
		if read.obs != loaded.obs or read.sources != loaded.sources or read.instances != loaded.instances or any(
			_claimContent(getattr(read, key)) != _claimContent(getattr(loaded, key)) for key in ("claims", "retractions")
		):
			raise ValueError("Observations JSON does not survive its text round trip (including the instance registry)")
	except (ValueError, KeyError) as error:
		diag = Diagnostics()
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	read.diagnostics = loaded.diagnostics
	return read


# EOF
