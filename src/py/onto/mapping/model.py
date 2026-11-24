"""Module: mapping.model — spec-04 ontology mapping declarations and local transformations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..expressions import Expression
from ..functions.model import Function, FunctionDeclaration
from ..ontology.model import Decl
from ..text import Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Condition = dict[str, Any]

MAPPING_FORMAT = "onto.mapping/1"
HEADER_KEYS = ("from", "to", "view", "scope", "referential", "candidates", "retract", "confirm")
QUALIFIER_KEYS = ("cur", "period")
ANNOTATION_KEYS = ("name", "into", "present", "when", "src", "as", "ctx", "valid", *QUALIFIER_KEYS, "reverse", "candidate", "reason")


@dataclass(slots=True)
class MappingLine:
	"""One attribute/role, facet or verb assignment, optionally proposed or reversible."""

	target: str | None = None
	facet: str | None = None
	verb: str | None = None
	expr: Expression | None = None
	when: Condition | None = None
	src: str | None = None
	reverse: bool = False
	candidate: bool = False
	doc: str | None = None
	loc: Loc | None = None
	qualifiers: dict[str, Expression] = field(default_factory=dict)
	asType: str | None = None  # `{as=T}`: the target type its references translate to


@dataclass(slots=True)
class MappingScope:
	"""A source instance type mapped to a target type, with optional metadata expressions."""

	source: str
	target: str
	when: Condition | None = None
	ctx: Expression | None = None
	valid: Expression | None = None
	lines: list[MappingLine] = field(default_factory=list)
	doc: str | None = None
	loc: Loc | None = None
	name: str | None = None
	present: Expression | None = None
	into: Expression | None = None


@dataclass(slots=True)
class MappingExclusion:
	"""A fully qualified source element deliberately omitted by this mapping."""

	path: str
	reason: str
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class MappingDocument:
	"""Parsed mapping source with untyped local function examples and source locations."""

	fromNamespace: str
	toNamespace: str
	header: dict[str, str | int | bool] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	functions: list[FunctionDeclaration] = field(default_factory=list)
	maps: list[Decl] = field(default_factory=list)
	scopes: list[MappingScope] = field(default_factory=list)
	exclusions: list[MappingExclusion] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)
	loc: Loc | None = None


@dataclass(slots=True)
class Mapping:
	"""A resolved declaration, not an executable mapping or a run outcome."""

	fromNamespace: str
	toNamespace: str
	header: dict[str, str | int | bool] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	functions: list[Function] = field(default_factory=list)
	maps: list[Decl] = field(default_factory=list)
	scopes: list[MappingScope] = field(default_factory=list)
	exclusions: list[MappingExclusion] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)
	loc: Loc | None = None


__all__ = ["Condition", "MappingLine", "MappingScope", "MappingExclusion", "MappingDocument", "Mapping", "ANNOTATION_KEYS", "HEADER_KEYS", "MAPPING_FORMAT", "QUALIFIER_KEYS"]

# EOF
