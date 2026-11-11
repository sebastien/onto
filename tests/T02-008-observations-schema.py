"""Module: observations schema tests — timestamps and claim variant contracts."""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import json

import pytest

from onto import Source, loadObservations, loadOntology, observationsToJson, reconcileObservations
from tests._helpers import _schemaValidator, _specExample

ONTOLOGY = loadOntology([Source("t", "@ontology A\nPerson\n  Name Text\n")])
FORMS = [
	{"s": "p", "exists": True}, {"s": "p", "facet": "Review"},
	{"s": "p", "p": "Name", "v": "Hi"},
	{"rel": "A/Person.knows.A/Person", "roles": {"Subject": "p", "Object": "q"}},
	{"same": ["p", "q"]}, {"distinct": ["p", "q"]},
]


def testObservationSpecExampleMatchesSchema() -> None:
	_schemaValidator("observations").validate(json.loads(_specExample("spec-02-observations", kind="json")))


@pytest.mark.parametrize("left,right", list(combinations(FORMS, 2)))
def testEveryPairOfClaimFormsIsRejected(left: dict, right: dict) -> None:
	assert not _schemaValidator("observations", "claim").is_valid({"n": 1, **left, **right})


@pytest.mark.parametrize("form", FORMS)
def testIndividualClaimFormsMatchSchema(form: dict) -> None:
	_schemaValidator("observations", "claim").validate({"n": 1, **form})


@pytest.mark.parametrize("valid", [
	"2026-11-10", "2026-11-10T09:30:00.123Z",
	"2026-11-10T09:30:00.123Z..2026-11-11T09:30:00.456+01:00",
	"..2026-11-10T09:30:00.123Z", "2026-11-10T09:30:00.123Z..",
])
def testExportedValidityMatchesSchema(valid: str) -> None:
	log = loadObservations(ONTOLOGY, Source("t", f"@obs A\np:Person\np.Name Hi {{valid={valid}}}\n"))
	validator = _schemaValidator("observations")
	validator.validate(observationsToJson(log))
	validator.validate(observationsToJson(reconcileObservations(ONTOLOGY, log)))


@pytest.mark.parametrize("valid", ["", "..", "2026-11-10garbage", "2026-11-10...2026-11-11"])
def testMalformedIntervalSyntaxIsRejected(valid: str) -> None:
	assert not _schemaValidator("observations", "interval").is_valid(valid)


def testOnlyRetractionsMayOmitAttributeValues() -> None:
	data = observationsToJson(loadObservations(ONTOLOGY, Source("t", "@obs A\np:Person\n")))
	data["claims"] = [{"n": 1, "s": "p", "p": "Name"}]
	validator = _schemaValidator("observations")
	assert not validator.is_valid(data)
	retracted = deepcopy(data)
	retracted["claims"], retracted["retractions"] = [], data["claims"]
	validator.validate(retracted)


@pytest.mark.parametrize("claim", [
	{"n": 1, "s": "p", "exists": True, "v": "orphan"},
	{"n": 1, "s": "p", "facet": "Review", "roles": {}},
	{"n": 1, "same": ["p", "q"], "rel": "A/Person.knows.A/Person"},
	{"n": 1, "rel": "A/Person.knows.A/Person", "roles": {}, "p": "Name"},
])
def testClaimPayloadsCannotMixVariants(claim: dict) -> None:
	assert not _schemaValidator("observations", "claim").is_valid(claim)


# EOF
