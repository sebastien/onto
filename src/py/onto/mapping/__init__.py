"""Module: mapping — spec-04 mapping declarations and static checks, coverage and reversal, without execution."""

from __future__ import annotations

from .model import Mapping, MappingDocument, MappingExclusion, MappingLine, MappingScope
from .parser import parseMapping
from .formatter import mappingToJson, printMapping
from .operations import Operator, formatMapping, loadMapping, mappingFromJson, resolveMapping
from .coverage import mappingCoverage
from .reversal import LossyLine, mappingReverse

MappingOperator = Operator

__all__ = [
	"Mapping", "MappingDocument", "MappingExclusion", "MappingLine", "MappingScope", "Operator", "MappingOperator",
	"parseMapping", "resolveMapping", "loadMapping", "formatMapping", "printMapping", "mappingToJson", "mappingFromJson",
	"mappingCoverage", "mappingReverse", "LossyLine",
]

# EOF
