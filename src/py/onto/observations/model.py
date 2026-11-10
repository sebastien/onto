"""Module: observations.model — model for the observations format."""

from __future__ import annotations

import json
import re
from dataclasses import (
	dataclass,
	field,
)
from datetime import (
	date,
	datetime,
)
from decimal import (
	Decimal,
	DecimalException,
)
from fractions import (
	Fraction,
)
from typing import (
	Any,
)
from ..ontology import (
	Attr,
	Model,
	QUALIFIERS,
	ResolvedType,
)
from ..text import (
	Diagnostic,
	Loc,
)

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
	text: str = ""
	rawLine: str = ""


@dataclass(slots=True, frozen=True)
class Gap:
	"""An unapplied statement with its raw source, expanded text, defaults and diagnostics."""

	n: int
	raw: str
	text: str
	loc: Loc
	meta: dict[str, str | bool]
	ctx: str | None
	diagnostics: tuple[Diagnostic, ...]


@dataclass(slots=True)
class TypeDeclaration:
	"""A registry-only handle/type declaration, not an observation statement."""

	handle: str
	type: str
	loc: Loc


@dataclass(slots=True)
class ObservationsDocument:
	"""Parsed directives and statements, retaining source locations."""

	obs: dict[str, str | None] = field(default_factory=dict)
	sources: dict[str, str] = field(default_factory=dict)
	statements: list[Statement] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)
	declarations: list[TypeDeclaration] = field(default_factory=list)


@dataclass(slots=True)
class Observations:
	"""Typed log or reconciled state; claim values use the spec-02 JSON representation."""

	obs: dict[str, str | None]
	sources: dict[str, str]
	instances: dict[str, dict[str, str | bool]]
	claims: list[Claim]
	retractions: list[Claim]
	diagnostics: list[Diagnostic] = field(default_factory=list)
	gaps: list[Gap] = field(default_factory=list)


OBSERVATIONS_FORMAT = "onto.observations/1"


HEADER_KEYS = ("rev", "src", "at", "by", "conf")


META_KEYS = ("src", "at", "valid", "ctx", "conf", "by", "of", "approved", *QUALIFIERS, "conflict")


HANDLE = r"[A-Za-z_][A-Za-z0-9_]*"


PATH = rf"{HANDLE}(?:/{HANDLE})*"


REF = rf"{HANDLE}(?::{PATH})?"


RE_REF = re.compile(rf"({HANDLE})(?::({PATH}))?")


RE_HEADER = re.compile(rf"({HANDLE})(?::({PATH}))?(?:\[([^\]]*)\])?")


RE_VALUE = re.compile(rf"({REF})\.({HANDLE}(?:\.{HANDLE})*)(?:\s+(.+))?")


RE_LINK = re.compile(rf"(?:({HANDLE}):\s+)?({REF})\s+([a-z][A-Za-z0-9_]*)\s+({REF}|\?)")


RE_IDENTITY = re.compile(rf"({REF})\s+(!=|=)\s+({REF})")


RE_DECIMAL = re.compile(r"([+-]?)(\d*(?:\.\d*)?)(?:[eE]([+-]?\d+))?", re.ASCII)


RE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?", re.ASCII)


RE_DURATION = re.compile(r"P(?=\d|T\d)(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?", re.ASCII)

# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


def canonicalNumber(text: str) -> str:
	"""Canonical decimal spelling without binary floating point or decimal-context rounding."""
	match = RE_DECIMAL.fullmatch(text)
	if not match or not any(char.isdigit() for char in match[2]):
		raise ValueError(f"Invalid decimal '{text}'")
	try:
		Decimal(text)
	except DecimalException as error:
		raise ValueError(f"Decimal exponent is outside the supported range: '{text}'") from error
	sign, mantissa, exponent = match.groups()
	whole, _, fraction = mantissa.partition(".")
	whole = whole.lstrip("0") or "0"
	fraction = fraction.rstrip("0")
	if whole == "0" and not fraction:
		return "0"
	value = ("-" if sign == "-" else "") + whole + (f".{fraction}" if fraction else "")
	return value + (f"e{int(exponent)}" if exponent and int(exponent) else "")


def _time(text: str) -> Fraction:
	if not RE_TIME.fullmatch(text):
		raise ValueError(f"Invalid date or date-time '{text}'")
	value = datetime.fromisoformat(text) if "T" in text else datetime.combine(date.fromisoformat(text), datetime.min.time())
	# NOTE: Compare exact UTC seconds, including sub-microsecond fractions; datetime alone truncates them.
	seconds = Fraction(value.toordinal() * 86400 + value.hour * 3600 + value.minute * 60 + value.second)
	if fraction := re.search(r"\.(\d+)", text):
		seconds += Fraction(f"0.{fraction[1]}")
	if offset := value.utcoffset():
		seconds -= offset.days * 86400 + offset.seconds
	return seconds


def parseInterval(text: str) -> tuple[Fraction | None, Fraction | None]:
	"""Parse a point or open/closed interval; reject impossible dates and reversed bounds."""
	parts = text.split("..") if ".." in text else [text, text]
	if len(parts) != 2 or not any(parts):
		raise ValueError(f"Invalid interval '{text}'")
	start, end = (_time(part) if part else None for part in parts)
	if start and end and start > end:
		raise ValueError(f"Reversed interval '{text}'")
	return start, end


def _valueKey(value: Any) -> str:
	return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _valueIdentity(value: Any, numeric: bool) -> tuple:
	# NOTE: Preserve the spec's exponent spelling in JSON, but compare exact numeric values.
	if numeric and isinstance(value, str) and RE_DECIMAL.fullmatch(value):
		return ("number", Decimal(value))
	if isinstance(value, dict) and "set" in value:
		return ("set", frozenset(_valueIdentity(item, numeric) for item in value["set"]), value.get("partial", False))
	return ("value", _valueKey(value))


def _useType(model: Model, attr: Attr, meta: dict[str, Any]) -> ResolvedType:
	qualifiers = [(key, meta[key]) for key in QUALIFIERS if key in meta]
	return model.resolveType(attr.type, qualifiers + attr.ann)


def _slot(claim: Claim) -> tuple[str, str, str]:
	if "same" in claim or "distinct" in claim:
		kind = "same" if "same" in claim else "distinct"
		return kind, _valueKey(claim[kind]), ""
	if "rel" in claim:
		subject = claim.get("s") or f"{claim['rel']}:{_valueKey(claim['roles'])}"
		member = ""
	else:
		subject = claim["s"]
		member = f"[{claim['facet']}]" if "facet" in claim else claim.get("p", "")
	return subject, member, claim.get("ctx", "")


def _order(claim: Claim) -> tuple[Fraction, int]:
	return (_time(claim["at"]) if "at" in claim else Fraction(0), claim["n"])


def _markImplicit(instances: dict[str, dict[str, str | bool]], claims: list[Claim]) -> dict[str, dict[str, str | bool]]:
	explicit = {claim["s"] for claim in claims if claim.get("exists") or "rel" in claim and "s" in claim}
	referenced = set()
	for claim in claims:
		if "ctx" in claim:
			referenced.add(claim["ctx"])
		referenced.update(handle for handle in claim.get("roles", {}).values() if handle != "?")
		value = claim.get("v")
		for member in value.get("set", []) if isinstance(value, dict) and "set" in value else [value]:
			if isinstance(member, dict) and "ref" in member:
				referenced.add(member["ref"])
	implicit = referenced - explicit
	return {handle: {"type": instance["type"], **({"implicit": True} if handle in implicit else {})} for handle, instance in instances.items()}


# EOF
