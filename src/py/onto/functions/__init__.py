"""Module: functions — spec-04 function-library declarations and interchange, without execution."""

from __future__ import annotations

from .model import ExampleSource, Function, FunctionDeclaration, FunctionExample, FunctionLibrary, FunctionsDocument, SignatureType
from .parser import parseFunctions
from .formatter import functionsToJson, printFunctions
from .operations import Operator, formatFunctions, functionsFromJson, loadFunctions, resolveFunctions

FunctionsOperator = Operator

__all__ = [
	"ExampleSource", "Function", "FunctionDeclaration", "FunctionExample", "FunctionLibrary", "FunctionsDocument", "SignatureType",
	"Operator", "FunctionsOperator", "parseFunctions", "resolveFunctions", "loadFunctions", "formatFunctions", "printFunctions", "functionsToJson", "functionsFromJson",
]

# EOF
