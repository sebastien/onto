"""Module: ontology operator tests — feature layout and backwards-compatible API."""

from __future__ import annotations

from copy import deepcopy

from onto import OntologyOperator, Source, formatOntology, loadOntology, ontologyToJson
from onto.ontology import Model, Ontology, Operator
from onto.ontology.formatter import normaliseOntology, printOntology
from onto.ontology.model import Ontology as OntologyModel
from onto.ontology.operations import Operator as OntologyOperations
from onto.ontology.parser import parseOntology


def testFeatureModulesKeepPublicTypesAndImportsIdentical() -> None:
	assert Ontology is OntologyModel
	assert Operator is OntologyOperator is OntologyOperations
	assert Model.__module__ == "onto.ontology.model"


def testOperatorDelegatesToTheExistingFunctionalApi() -> None:
	sources = [Source("t", "@ontology A\nP\n  B Text\n  A Text\n")]
	operator = Operator(parseOntology(sources))
	assert operator.validate() == loadOntology(sources)
	assert operator.print() == formatOntology(sources)
	assert printOntology(operator.normalise()) == operator.print()
	assert normaliseOntology(operator.ontology) == operator.normalise()
	assert operator.toJson() == ontologyToJson(operator.ontology)


def testOperatorRetainsContextAndDoesNotMutateDuringFormatting() -> None:
	ontology = loadOntology([Source("t", "@ontology A\nP\n  B Text\n  A Text\n")])
	before = deepcopy(ontology)
	operator = Operator(ontology)
	assert operator.ontology is ontology
	operator.print()
	data = operator.toJson({"A/P": "id-1"})
	assert data["ids"] == {"A/P": "id-1"}
	assert ontology == before


# EOF
