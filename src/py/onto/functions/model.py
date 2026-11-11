"""Module: functions.model — function-library declarations and typed conformance examples."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..text import Annotations, Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


FUNCTIONS_FORMAT = "onto.functions/1"


@dataclass(slots=True)
class SignatureType:
	"""A concrete built-in or named function type, optionally a collection."""

	builtin: str | None = None
	path: str | None = None
	collection: bool = False


@dataclass(slots=True)
class ExampleSource:
	"""An example before its observations-encoded values have been typed."""

	args: list[str]
	result: str
	loc: Loc


@dataclass(slots=True)
class FunctionExample:
	"""Typed arguments and expected result, not an executable implementation."""

	args: list[Any]
	result: Any
	loc: Loc | None = None


@dataclass(slots=True)
class FunctionDeclaration:
	"""A source declaration with resolved signature paths and untyped examples."""

	name: str
	args: list[SignatureType]
	result: SignatureType
	examples: list[ExampleSource] = field(default_factory=list)
	ann: Annotations = field(default_factory=list)
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class Function:
	"""A named signature with typed examples and optional inverse/null handling."""

	name: str
	args: list[SignatureType]
	result: SignatureType
	examples: list[FunctionExample] = field(default_factory=list)
	ann: Annotations = field(default_factory=list)
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class FunctionsDocument:
	"""Parsed files of one library, retaining declaration and example locations."""

	namespace: str
	header: dict[str, str] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	functions: list[FunctionDeclaration] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass(slots=True)
class FunctionLibrary:
	"""A library with fully qualified signature types and typed examples."""

	namespace: str
	header: dict[str, str] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	functions: list[Function] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)


# EOF
