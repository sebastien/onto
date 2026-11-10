"""Module: onto — compact text formats for ontologies (spec-01); later phases add observations and mappings."""

from .ontology import (
	Model,
	Ontology,
	formatOntology,
	loadOntology,
	normaliseOntology,
	ontologyFromJson,
	ontologyToJson,
	parseOntology,
	printOntology,
	validateOntology,
)
from .text import Diagnostic, FormatError, Source

__all__ = [
	"Diagnostic",
	"FormatError",
	"Model",
	"Ontology",
	"Source",
	"formatOntology",
	"loadOntology",
	"normaliseOntology",
	"ontologyFromJson",
	"ontologyToJson",
	"parseOntology",
	"printOntology",
	"validateOntology",
]

# EOF
