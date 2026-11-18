"""Module: ontology operator tests — feature layout and backwards-compatible API."""

from __future__ import annotations

from copy import deepcopy

from onto import OntologyOperator, Source, formatOntology, loadOntology, ontologyDiff, ontologyFromJson, ontologyToJson
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


def testRepeatedValidationDoesNotDuplicateWarnings() -> None:
	sources = [Source("t", "@ontology A\nDetail =\n  Name Text\nPerson\n  * Work Detail\n  * Home Detail\n")]
	operator = Operator(loadOntology(sources))
	warnings = list(operator.ontology.diagnostics)
	assert len(warnings) == 2 and all(item.level == "warning" and item.code == "key" for item in warnings)
	assert operator.validate().diagnostics == warnings
	assert operator.validate().diagnostics == warnings


def testCombinedNormalFormPreservesPathsShadowedByAnotherFilesAlias() -> None:
	sources = [
		Source("local.onto", "@ontology A\n@domain D\nD/Value = Text\nLocal/Item\nPerson\n  Value D/Value\n"),
		Source("external.onto", "@ontology A\n@use Dimensions as D\nD/Value = Integer\nAccount\n  Value D/Value\n"),
	]
	original = loadOntology(sources)
	text = Operator(original).print()
	assert "@use A as Local2\n" in text
	assert "@domain D\n" in text
	assert "Local/Item\n" in text
	assert "  Value Local2/D/Value\n" in text and "  Value D/Value\n" in text
	assert formatOntology(sources[::-1]) == text
	reloaded = loadOntology([Source("canonical.onto", text)])
	assert ontologyDiff(original, reloaded) == []
	assert Operator(reloaded).print() == text
	data = ontologyToJson(original)
	assert ontologyToJson(ontologyFromJson(data)) == data


def testSelfAliasPreservesADefinitionWithABuiltinName() -> None:
	source = Source("alias.onto", "@ontology A\n@use A as Local\nLocal/Text = Integer\nPerson\n  Value Local/Text\n")
	original = loadOntology([source])
	text = Operator(original).print()
	assert "Local/Text = Integer\n" in text
	assert ontologyDiff(original, loadOntology([Source("canonical.onto", text)])) == []


def testCombinedNormalFormPreservesShadowedReferencesToGeneratedHistory() -> None:
	sources = [
		Source("local.onto", "@ontology A\nD\n  Status Text {history}\nReport\n  Change D/StatusChange\n"),
		Source("external.onto", "@ontology A\n@use Dimensions as D\nD/Value = Integer\n"),
	]
	original = loadOntology(sources)
	text = Operator(original).print()
	assert "  Change Local/D/StatusChange\n" in text
	assert ontologyDiff(original, loadOntology([Source("canonical.onto", text)])) == []


# EOF
