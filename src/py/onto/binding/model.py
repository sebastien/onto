"""Module: binding.model — spec-04 document-to-ontology binding declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..conditions import Condition
from ..expressions import Expression
from ..functions.model import Function, FunctionDeclaration
from ..text import Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


BINDING_FORMAT = "onto.binding/1"
HEADER_KEYS = ("rev", "name", "format", "scope", "null", "complete", "retract", "confirm")
ANNOTATION_KEYS = ("id", "when", "src", "ctx", "valid", "deleted", "null", "unset", "reverse", "candidate", "reason")


@dataclass(slots=True)
class BindingLine:
	"""One attribute/role, facet or binary-verb assignment."""

	target: str | None = None
	facet: str | None = None
	verb: str | None = None
	expr: Expression | None = None
	when: Condition | None = None
	null: str | None = None
	unset: str | None = None  # `{unset=V}`: the value the source writes for "not given", canonical for the attribute
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
	valid: Expression | None = None  # `@valid <- expr`: when every claim of a document holds.


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
	valid: Expression | None = None  # `@valid <- expr`: when every claim of a document holds.


def bindingBy(binding: "Binding") -> str:
	"""The `by` of a binding's claims: `bind:<Namespace>`, or `bind:<Namespace>/<name>` for a named binding."""
	name = binding.header.get("name")
	return f"bind:{binding.ontology}/{name}" if name else f"bind:{binding.ontology}"


__all__ = ["bindingBy", "Condition", "BindingLine", "BindingScope", "BindingExclusion", "BindingDocument", "Binding", "ANNOTATION_KEYS", "BINDING_FORMAT", "HEADER_KEYS"]

# EOF
