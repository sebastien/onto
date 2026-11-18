"""Module: mapping schema tests — function signatures and observation value encoding."""

from __future__ import annotations

import json

import pytest

from tests.helpers import schemaValidator, specExample


@pytest.mark.parametrize("index", [1, 2])
def testMappingAndFunctionSpecExamplesMatchSchema(index: int) -> None:
	schemaValidator("mapping").validate(json.loads(specExample("spec-04-mapping", index, kind="json")))


@pytest.mark.parametrize("signature,valid", [
	({"builtin": "Text"}, True), ({"path": "Finance/Person", "collection": True}, True),
	({"any": True}, False), ({"builtin": "Text", "path": "Finance/Person"}, False),
	({"builtin": "Text", "typo": True}, False), ({"collection": True}, False),
])
def testSignatureVariantsAreExclusiveAndClosed(signature: dict, valid: bool) -> None:
	assert schemaValidator("mapping", "signatureType").is_valid(signature) is valid


@pytest.mark.parametrize("value,valid", [
	({"ref": "p"}, True), ({"set": ["3", True, {"ref": "p"}], "partial": True}, True),
	(None, True), ({"unknown": True}, True), ({"ref": "invalid-handle"}, False),
	({"set": [3]}, False), ({"set": [None]}, False), ({"set": [{"set": []}]}, False),
	({"set": [{"unknown": True}]}, False),
])
def testFunctionExamplesUseObservationValues(value: object, valid: bool) -> None:
	assert schemaValidator("mapping", "value").is_valid(value) is valid


def testFormatMetadataKeepsTheRenamedContract() -> None:
	validator = schemaValidator("mapping", "expr")
	assert validator.is_valid({"meta": "format"})
	assert not validator.is_valid({"meta": "codec"})


# EOF
