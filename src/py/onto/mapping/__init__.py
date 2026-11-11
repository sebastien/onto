"""Module: mapping — spec-04 mapping declarations and static checks, without execution."""

from __future__ import annotations

from .model import Mapping, MappingDocument, MappingExclusion, MappingLine, MappingScope
from .parser import parseMapping
from .formatter import mappingToJson, printMapping
from .operations import Operator, formatMapping, loadMapping, mappingFromJson, resolveMapping

MappingOperator = Operator

__all__ = [
	"Mapping", "MappingDocument", "MappingExclusion", "MappingLine", "MappingScope", "Operator", "MappingOperator",
	"parseMapping", "resolveMapping", "loadMapping", "formatMapping", "printMapping", "mappingToJson", "mappingFromJson",
]

# EOF
