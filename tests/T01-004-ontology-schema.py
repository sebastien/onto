"""Module: ontology schema tests — structural requirements and exported documents."""

from __future__ import annotations

import json

import pytest

from onto import Source, loadOntology, ontologyToJson
from tests.helpers import schemaValidator, specExample


def testOntologyExportMatchesSchema() -> None:
	ontology = loadOntology([Source("spec", specExample("spec-01-ontology"))])
	schemaValidator("ontology").validate(ontologyToJson(ontology))
	schemaValidator("ontology").validate(json.loads(specExample("spec-01-ontology", kind="json")))


@pytest.mark.parametrize("deps,valid", [(None, False), ([], False), ([{"ellipsis": True}], True)])
def testDerivedAttributesRequireDependencies(deps: list[dict] | None, valid: bool) -> None:
	attr = {"name": "Age", "card": "?", "derived": True}
	if deps is not None:
		attr["deps"] = deps
	assert schemaValidator("ontology", "attr").is_valid(attr) is valid


@pytest.mark.parametrize("key", ["default", "layer"])
def testUnsupportedHeadersAreRejected(key: str) -> None:
	data = {"format": "onto.ontology/1", "namespace": "A", "header": {key: "Old"}, "decls": []}
	assert not schemaValidator("ontology").is_valid(data)


def testRangesRequireABuiltinOrPath():
	assert not schemaValidator("ontology", "type").is_valid({"range": {"unknown": True}})


def testArrowRequiresExactlyTwoParticipants():
	participant = {"role": "Person", "card": "1", "type": "A/Person"}
	decl = {"kind": "relation", "path": "A/Person.knows.A/Person", "participants": [participant] * 3,
		"arrow": {"verb": "knows", "counts": "*:*"}}
	assert not schemaValidator("ontology", "decl").is_valid(decl)


# EOF
