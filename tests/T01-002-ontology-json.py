"""Module: ontology JSON tests — export, strict import and round trips (spec-01)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from onto.ontology import Ontology, formatOntology, loadOntology, normaliseOntology, ontologyFromJson, ontologyToJson, printOntology
from onto.text import FormatError, Source
from tests.helpers import specExample

# -----------------------------------------------------------------------------
#
# HELPERS
#
# -----------------------------------------------------------------------------

EXAMPLE = specExample("spec-01-ontology")
EXCERPT = json.loads(specExample("spec-01-ontology", kind="json"))


def load(text: str) -> Ontology:
	return loadOntology([Source("t.onto", text)])


def toJson(text: str) -> dict[str, Any]:
	# NOTE: Through `json` so that the comparison is against plain JSON data.
	return json.loads(json.dumps(ontologyToJson(load(text))))


def printed(ontology: Ontology) -> str:
	return printOntology(normaliseOntology(ontology))


def errors(data: Any) -> list[str]:
	try:
		ontologyFromJson(data)
	except FormatError as error:
		return [item.code for item in error.diagnostics if item.level == "error"]
	return []


def changed(data: dict[str, Any], target: str, **changes: Any) -> dict[str, Any]:
	"""A copy of `data` where the declaration `target` has `changes` (None removes a member)."""
	result = copy.deepcopy(data)
	for item in result["decls"]:
		if item["path"] == target:
			for key, value in changes.items():
				if value is None:
					item.pop(key, None)
				else:
					item[key] = value
	return result


JSON = toJson(EXAMPLE)


# -----------------------------------------------------------------------------
#
# EXPORT
#
# -----------------------------------------------------------------------------


def testSpecExcerptMatchesExport():
	byPath = {item["path"]: item for item in JSON["decls"]}
	assert {key: JSON[key] for key in ("format", "namespace", "header", "uses")} == {key: EXCERPT[key] for key in ("format", "namespace", "header", "uses")}
	for item in EXCERPT["decls"]:
		full = byPath[item["path"]]
		for key, value in item.items():
			if key in ("attrs", "fields", "lines"):
				# NOTE: The excerpt lists a subset of attributes and lines.
				assert all(entry in full[key] for entry in value), (item["path"], key)
			else:
				assert full[key] == value, (item["path"], key)


def testDefaultsAreExplicit():
	household = next(item for item in JSON["decls"] if item.get("arrow", {}).get("verb") == "hasMember")
	assert household["arrow"] == {"verb": "hasMember", "inverse": "memberOf", "counts": "1:*"}
	assert [item["card"] for item in household["participants"]] == ["1", "1"]
	issues = next(item for item in JSON["decls"] if item.get("arrow", {}).get("verb") == "issues")
	assert issues["path"] == "Finance/Company.issues.Finance/Instrument"
	ownership = next(item for item in JSON["decls"] if item["path"] == "Finance/Ownership")
	assert all("card" in attr for attr in ownership["attrs"])
	default = toJson("@ontology A\nP\nQ\nP -has-> Q\n")
	assert default["decls"][-1]["arrow"] == {"verb": "has", "counts": "*:*"}


def testViewLinesHaveFullPaths():
	data = toJson("@ontology A\n@use Dimensions as D\nH\nD/P\nH -has-> D/P\n@view V\n  H.has\n  H.has.D/P\n")
	assert data["decls"][-1]["lines"] == [{"path": "A/H", "member": "has"}, {"path": "A/H.has.Dimensions/P"}]


# -----------------------------------------------------------------------------
#
# ROUND TRIPS
#
# -----------------------------------------------------------------------------


def testTextJsonTextIsLossless():
	back = ontologyFromJson(JSON)
	assert printed(back) == formatOntology([Source("t.onto", EXAMPLE)])
	assert ontologyToJson(back) == JSON


def testInputOrderDoesNotMatter():
	shuffled = {**JSON, "decls": list(reversed(JSON["decls"]))}
	assert ontologyToJson(ontologyFromJson(shuffled)) == JSON


def testIdentitySidecarTravels():
	data = {**JSON, "ids": {"Finance/Person": "id-1", "Finance/Person.Email": "id-2"}}
	back = ontologyFromJson(data)
	assert back.ids == data["ids"]
	assert ontologyToJson(back) == data


def testDomainsMapsAndContextsRoundTrip():
	text = (
		"@ontology A\n@use Dimensions as D\n@domain Money -- Money\n@domain Society\n"
		"D/Money/Basis = Monthly|Yearly\nD/Society/Freq = Fortnightly|Monthly\nMoney/Org\nSociety/Person\n"
		"  Email Text {id=key, privacy=Owner+Adviser}\n"
		"Money/Employment(Society/Person, Money/Org) {kind=state}\n"
		"Money/Check(Money/Employment, Society/Person) {kind=event}\n"
		"Society/Person -employedBy-> Money/Org {context=Money/Employment}\n"
		"Servicing of Money/Employment {ctx=Money/Check}\n  IsIncluded Boolean\n"
		"@map Money/FreqToBasis D/Society/Freq -> D/Money/Basis {rule=x26}\n"
		"  Fortnightly broader Monthly -- approx\n  Monthly exact Monthly\n"
	)
	data = toJson(text)
	assert data["decls"][:2] == [{"kind": "domain", "path": "A/Money", "doc": "Money"}, {"kind": "domain", "path": "A/Society"}]
	assert next(item for item in data["decls"] if item["kind"] == "map") == {
		"kind": "map", "path": "A/Money/FreqToBasis", "from": "Dimensions/Society/Freq", "to": "Dimensions/Money/Basis",
		"lines": [{"from": "Fortnightly", "match": "broader", "to": "Monthly", "doc": "approx"}, {"from": "Monthly", "match": "exact", "to": "Monthly"}],
		"ann": {"rule": "x26"},
	}
	assert next(item for item in data["decls"] if item["path"] == "A/Servicing")["ann"] == {"ctx": "A/Money/Check"}
	back = ontologyFromJson(data)
	assert ontologyToJson(back) == data
	assert printed(back) == formatOntology([Source("t.onto", text)])


# -----------------------------------------------------------------------------
#
# REJECTION
#
# -----------------------------------------------------------------------------

PERSON = "Finance/Person"
EMAIL = {"name": "Email", "card": "?", "type": {"builtin": "Text"}, "ann": {"key": True}}


@pytest.mark.parametrize(
	"data",
	[
		[],
		{**JSON, "format": "other"},
		{**JSON, "bogus": 1},
		{**JSON, "header": None},
		{**JSON, "header": 42},
		{**JSON, "header": True},
		{**JSON, "header": {"rev": 1}},
		{**JSON, "decls": {}},
		{**JSON, "decls": [{"kind": "widget", "path": "A"}]},
		{**JSON, "decls": [{"kind": [], "path": "A"}]},
		{**JSON, "ids": {"Finance/Person": 1}},
		changed(JSON, PERSON, base=None, extra=1),
		changed(JSON, PERSON, doc=None, base=None, attrs=[{**EMAIL, "card": None}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "derived": False}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "type": {"builtin": "Text", "path": "Finance/X"}}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "type": {"values": ["A"]}}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "type": {"values": ["A"], "open": "no"}}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "type": {"unknown": False}}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "type": {"builtin": "Widget"}}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "ann": {"key": False}}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "ann": {"src": None}}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "card": 1}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "doc": None}]),
		changed(JSON, PERSON, attrs=[{**EMAIL, "deps": []}]),
		changed(JSON, PERSON, attrs=[]),
		changed(JSON, "Dimensions/PersonName", fields=[]),
		changed(JSON, "Dimensions/AssetClass", fields=[EMAIL]),
		changed(JSON, "Finance/PortfolioReview", lines=[{"path": PERSON, "facets": []}]),
	],
)
def testMalformedJsonIsRejected(data):
	assert errors(data) == ["json"]


@pytest.mark.parametrize("count", [0, 1, 3])
def testBinaryJsonRequiresExactlyTwoParticipants(count: int):
	data = toJson("@ontology A\nP\nQ\nP -has-> Q\n")
	relation = data["decls"][-1]
	relation["participants"] = (relation["participants"] + [{"role": "Extra", "card": "1", "type": "A/P"}])[:count]
	assert errors(data) == ["json"]


@pytest.mark.parametrize(
	("data", "code"),
	[
		(changed(JSON, PERSON, base="Finance/Missing"), "reference"),
		(changed(JSON, PERSON, attrs=[{**EMAIL, "name": "A\n  B"}]), "json"),
		(changed(JSON, PERSON, attrs=[{**EMAIL, "card": "2"}]), "json"),
		(changed(JSON, PERSON, attrs=[{**EMAIL, "doc": " padded"}]), "json"),
		(changed(JSON, PERSON, attrs=[{**EMAIL, "ann": {"src": "a b"}}]), "annotation"),
		(changed(JSON, PERSON, attrs=[{**EMAIL, "ann": {"ctx": "Finance/Missing"}}]), "annotation"),
		(changed(JSON, "Finance/Household.hasMember.Finance/Person", path="Finance/Wrong"), "json"),
		(changed(JSON, "Finance/Trade", participants=[{"role": "Wrong", "card": "1", "type": "Finance/Household"}] * 2), "duplicate"),
		({**JSON, "decls": JSON["decls"] + [{"kind": "domain", "path": "Other/X"}]}, "json"),
		({**JSON, "decls": JSON["decls"] + [{"kind": "domain", "path": "Finance/X/Y"}]}, "name"),
	],
)
def testInconsistentJsonIsRejected(data, code):
	assert code in errors(data)


# EOF
