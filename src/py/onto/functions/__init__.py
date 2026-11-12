"""Module: functions — spec-04 declarations, pure execution and executable conformance."""

from __future__ import annotations

from .model import ExampleSource, Function, FunctionDeclaration, FunctionExample, FunctionLibrary, FunctionResult, FunctionsDocument, SignatureType
from .parser import parseFunctions
from .formatter import functionsToJson, printFunctions
from .operations import Operator, formatFunctions, functionsFromJson, loadFunctions, resolveFunctions
from .runtime import FunctionEvaluator

FunctionsOperator = Operator

__all__ = [
	"ExampleSource", "Function", "FunctionDeclaration", "FunctionExample", "FunctionLibrary", "FunctionsDocument", "SignatureType",
	"FunctionEvaluator", "FunctionResult",
	"Operator", "FunctionsOperator", "parseFunctions", "resolveFunctions", "loadFunctions", "formatFunctions", "printFunctions", "functionsToJson", "functionsFromJson",
]

# EOF
