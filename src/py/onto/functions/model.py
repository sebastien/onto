"""Module: functions.model — function-library declarations and typed conformance examples."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ontology.model import TypeExpr
from ..text import Annotations, Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


FUNCTIONS_FORMAT = "onto.functions/1"

BUILTIN_SIGNATURES = {
	"concat": (1, None, "Text"),
	"split": (2, 2, "Text"),
	"join": (2, 2, "Text"),
	"trim": (1, 1, "Text"),
	"lower": (1, 1, "Text"),
	"upper": (1, 1, "Text"),
	"number": (1, 1, "Number"),
	"text": (1, 1, "Text"),
	"date": (1, 2, "Date"),
	"datetime": (2, 2, "DateTime"),
	"epoch": (1, 1, "Integer"),
	"format": (2, 2, "Text"),
	"sum": (1, None, "Number"),
	"multiply": (1, None, "Number"),
	"subtract": (2, 2, "Number"),
	"divide": (2, 2, "Number"),
	"count": (1, 1, "Integer"),
	"ref": (2, 2, None),  # The first argument names the result's instance type.
}
BUILTIN_ARITIES = {name: (minimum, maximum) for name, (minimum, maximum, _) in BUILTIN_SIGNATURES.items()}
BUILTIN_RESULTS = {name: result for name, (_, _, result) in BUILTIN_SIGNATURES.items() if result is not None}


@dataclass(slots=True)
class SignatureType:
	"""A concrete built-in or named function type, optionally a `Range<T>` of it, optionally a collection."""

	builtin: str | None = None
	path: str | None = None
	collection: bool = False
	range: bool = False

	def typeExpr(self) -> TypeExpr:
		element = TypeExpr(builtin=self.builtin, path=self.path)
		return TypeExpr(range=element) if self.range else element


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


@dataclass(slots=True)
class FunctionResult:
	"""One application outcome; `reason` marks a gap, `partial` marks incomplete lifted inputs."""

	value: Any = None
	reason: str | None = None
	partial: bool = False


__all__ = [
	"FUNCTIONS_FORMAT", "BUILTIN_SIGNATURES", "BUILTIN_ARITIES", "BUILTIN_RESULTS",
	"SignatureType", "ExampleSource", "FunctionExample", "FunctionDeclaration", "Function",
	"FunctionsDocument", "FunctionLibrary", "FunctionResult",
]


# EOF
