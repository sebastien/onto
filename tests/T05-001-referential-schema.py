"""Module: referential schema tests — implicit-instance duration syntax."""

from __future__ import annotations

import json

import pytest

from tests._helpers import _schemaValidator, _specExample


def testReferentialSpecExampleMatchesSchema() -> None:
	_schemaValidator("referential").validate(json.loads(_specExample("spec-05-identities", kind="json")))


@pytest.mark.parametrize("duration,valid", [
	("never", True), ("P7D", True), ("PT1S", True), ("PT0.5S", True),
	("P", False), ("PT", False), ("PT.5S", False), ("P7DT", False),
])
def testImplicitDurations(duration: str, valid: bool) -> None:
	policy = {"type": "Finance/Person", "implicit": duration}
	assert _schemaValidator("referential", "policy").is_valid(policy) is valid


# EOF
