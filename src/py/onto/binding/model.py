"""Module: binding.model — spec-04 document-to-ontology binding declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..expressions import Expression
from ..functions.model import Function, FunctionDeclaration
from ..text import Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


type Condition = dict[str, Any]

BINDING_FORMAT = "onto.binding/1"
HEADER_KEYS = ("rev", "format", "scope", "null", "complete", "retract", "confirm")
ANNOTATION_KEYS = ("id", "when", "src", "ctx", "valid", "deleted", "null", "reverse", "candidate", "reason")


@dataclass(slots=True)
class BindingLine:
	"""One attribute/role, facet or binary-verb assignment."""

	target: str | None = None
	facet: str | None = None
	verb: str | None = None
	expr: Expression | None = None
	when: Condition | None = None
	null: str | None = None
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class BindingScope:
	"""Instances of `type` selected by a document path, keyed by an expression."""

	type: str
	path: Expression
	id: Expression
	valid: Expression | None = None
	ctx: Expression | None = None
	deleted: Condition | None = None
	lines: list[BindingLine] = field(default_factory=list)
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class BindingExclusion:
	"""A deliberately unbound document field and its reason."""

	path: Expression
	reason: str
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class BindingDocument:
	"""Parsed binding declarations; local function examples are not yet typed."""

	ontology: str
	header: dict[str, str | int] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	at: Expression | None = None
	columns: list[str] | None = None
	functions: list[FunctionDeclaration] = field(default_factory=list)
	scopes: list[BindingScope] = field(default_factory=list)
	exclusions: list[BindingExclusion] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)
	loc: Loc | None = None


@dataclass(slots=True)
class Binding:
	"""A resolved binding with typed local examples and qualified type/function names."""

	ontology: str
	header: dict[str, str | int] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	at: Expression | None = None
	columns: list[str] | None = None
	functions: list[Function] = field(default_factory=list)
	scopes: list[BindingScope] = field(default_factory=list)
	exclusions: list[BindingExclusion] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)
	loc: Loc | None = None


__all__ = ["Condition", "BindingLine", "BindingScope", "BindingExclusion", "BindingDocument", "Binding"]

# EOF
