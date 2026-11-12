"""Module: binding — spec-04 binding declarations and interchange, without execution."""

from __future__ import annotations

from .model import Binding, BindingDocument, BindingExclusion, BindingLine, BindingScope, Condition
from .parser import parseBinding
from .formatter import bindingToJson, printBinding
from .operations import Operator, bindingFromJson, formatBinding, loadBinding, resolveBinding
from .coverage import bindingCoverage

BindingOperator = Operator

__all__ = [
	"Binding", "BindingDocument", "BindingExclusion", "BindingLine", "BindingScope", "Condition", "Operator", "BindingOperator",
	"parseBinding", "resolveBinding", "loadBinding", "formatBinding", "printBinding", "bindingToJson", "bindingFromJson",
	"bindingCoverage",
]

# EOF
