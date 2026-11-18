"""Module: observations — public API for the observations format."""

from __future__ import annotations

from .model import (
	Claim,
	Statement,
	TypeDeclaration,
	Gap,
	ObservationsDocument,
	Observations,
	OBSERVATIONS_FORMAT,
	HEADER_KEYS,
	META_KEYS,
	HANDLE,
	PATH,
	REF,
	RE_REF,
	RE_HEADER,
	RE_VALUE,
	RE_LINK,
	RE_IDENTITY,
	RE_DECIMAL,
	RE_TIME,
	RE_DURATION,
	canonicalNumber,
	parseInterval,
)
from .parser import (
	parseObservations,
)
from .formatter import (
	printObservationsState,
	printObservationsLog,
	observationsToJson,
)
from .operations import (
	Operator,
	reconcileObservations,
	resolveObservations,
	loadObservations,
	formatObservations,
	observationsFromJson,
)

__all__ = [
	"Operator",
	"Claim",
	"Statement",
	"TypeDeclaration",
	"Gap",
	"ObservationsDocument",
	"Observations",
	# Compatibility exports: grammar and lexical helpers, rather than the recommended facade.
	"OBSERVATIONS_FORMAT",
	"HEADER_KEYS",
	"META_KEYS",
	"HANDLE",
	"PATH",
	"REF",
	"RE_REF",
	"RE_HEADER",
	"RE_VALUE",
	"RE_LINK",
	"RE_IDENTITY",
	"RE_DECIMAL",
	"RE_TIME",
	"RE_DURATION",
	"canonicalNumber",
	"parseInterval",
	# Functional API.
	"parseObservations",
	"printObservationsState",
	"printObservationsLog",
	"observationsToJson",
	"reconcileObservations",
	"resolveObservations",
	"loadObservations",
	"formatObservations",
	"observationsFromJson",
]

# EOF
