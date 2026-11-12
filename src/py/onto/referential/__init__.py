"""Module: referential — spec-05 identity policy declarations, without registry operations."""

from __future__ import annotations

from .model import Policy, Referential
from .parser import parseReferential
from .formatter import printReferential, referentialToJson
from .operations import Operator, formatReferential, loadReferential, referentialFromJson, referentialImplicit, referentialPolicy, validateReferential

ReferentialOperator = Operator

__all__ = [
	"Policy", "Referential", "Operator", "ReferentialOperator", "parseReferential", "validateReferential", "loadReferential", "formatReferential",
	"printReferential", "referentialToJson", "referentialFromJson", "referentialPolicy", "referentialImplicit",
]

# EOF
