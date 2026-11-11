"""Module: ontology schema tests — structural requirements and exported documents."""

from __future__ import annotations

import json

import pytest

from onto import Source, loadOntology, ontologyToJson
from tests._helpers import _schemaValidator, _specExample


def testOntologyExportMatchesSchema() -> None:
	ontology = loadOntology([Source("spec", _specExample("spec-01-ontology"))])
	_schemaValidator("ontology").validate(ontologyToJson(ontology))
	_schemaValidator("ontology").validate(json.loads(_specExample("spec-01-ontology", kind="json")))


@pytest.mark.parametrize("deps,valid", [(None, False), ([], False), ([{"ellipsis": True}], True)])
def testDerivedAttributesRequireDependencies(deps: list[dict] | None, valid: bool) -> None:
	attr = {"name": "Age", "card": "?", "derived": True}
	if deps is not None:
		attr["deps"] = deps
	assert _schemaValidator("ontology", "attr").is_valid(attr) is valid


# EOF
