"""Module: observations round-trip tests — parsing, typing and reconciliation (spec-02)."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from onto import FormatError, Ontology, Source, loadOntology
from onto.observations import Observations
from tests._helpers import _semanticClaims, _specExample
from onto.observations import canonicalNumber, formatObservations, loadObservations, observationsFromJson, observationsToJson, parseInterval, parseObservations, printObservationsLog, printObservationsState, reconcileObservations

# -----------------------------------------------------------------------------
#
# FIXTURES AND HELPERS
#
# -----------------------------------------------------------------------------

EXAMPLE = _specExample("spec-02-observations")
ONTOLOGY_EXAMPLE = _specExample("spec-01-ontology")
ONTOLOGY = loadOntology([Source("finance.onto", ONTOLOGY_EXAMPLE)])
MODEL = loadOntology([Source("model.onto", """@ontology A
Money = Amount {cur=USD}
Years = Duration {unit=Year}
PersonName =
  Surname Text
Party
Person < Party
  Name Text
  Age Integer
  Dob Date
  At DateTime
  Duration Duration
  Years Years
  Pay Money
  Active Boolean
  Category A|B
  Open A|...
  Tags Text
  * Values Number
  + Required Text
  Owner Party
  Struct PersonName
Household
Scenario
Review of Person {ctx=Scenario}
  Included Boolean
Investor of Person
  Rating Low|Medium|High
Person -knows/knownBy-> Person
Person -partner/partner-> Person
Household -has/memberOf-> Person
Income(Payer: Party, Recipient: + Person) {kind=state}
  Amount Money
""")])


def load(text: str, ontology: Ontology = MODEL) -> Observations:
	return loadObservations(ontology, Source("test.obs", text))


def state(text: str) -> Observations:
	return reconcileObservations(MODEL, load(text))


def values(log: Observations, path: str) -> list[Any]:
	return [claim["v"] for claim in log.claims if claim.get("p") == path]


def errors(text: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		load(text)
	return [item.code for item in raised.value.diagnostics]


# -----------------------------------------------------------------------------
#
# PARSING AND TYPING
#
# -----------------------------------------------------------------------------


def testCompleteSpecExample():
	log = load(EXAMPLE, ONTOLOGY)
	assert log.obs == {"ontology": "Finance", "rev": "2026-11-10", "at": "2026-11-10", "scope": None}
	assert log.instances["r1"]["type"] == "Finance/Household.hasMember.Finance/Person"
	assert len(log.retractions) == 1
	assert log.retractions[0]["v"] == "1990-06-16"
	assert values(log, "Trader") == [{"set": [{"ref": "p1"}, {"ref": "p2"}]}]
	assert values(log, "Price") == ["98.5"]
	assert log.claims[0]["n"] == 1
	assert log.claims[0]["src"] == "st"
	data = observationsToJson(log)
	assert json.loads(json.dumps(data)) == data
	data["claims"].clear()
	assert log.claims


def testSpecJsonExcerptMatchesTheCompleteLog():
	data = observationsToJson(load(EXAMPLE, ONTOLOGY))
	excerpt = json.loads(_specExample("spec-02-observations", kind="json"))
	for key in ("format", "obs", "sources"):
		assert data[key] == excerpt[key]
	for handle, instance in excerpt["instances"].items():
		assert data["instances"][handle] == instance
	for key in ("claims", "retractions"):
		assert all(claim in data[key] for claim in excerpt[key])


def testOrdinalsAndRecordMetadata():
	doc = parseObservations(Source("x", "@obs A at=2026-01-01\n// skip\np:Person {src=x}\n  Name Person\n\n@src other\np.Age 21\n"))
	assert [item.n for item in doc.statements] == [1, 2, 3]
	assert [item.loc.line for item in doc.statements] == [3, 4, 7]
	log = load("@obs A at=2026-01-01\np:Person {src=x}\n  Name Person\n")
	assert log.claims[0]["src"] == "x"
	assert "src" not in log.claims[1]
	assert log.claims[1]["at"] == "2026-01-01"


@pytest.mark.parametrize(("raw", "expected"), [("+12", "12"), ("007.50", "7.5"), ("-0.0", "0"), ("1.250E+03", "1.25e3"), ("-.50", "-0.5"), ("12e-0", "12"), ("123456789012345678901234567890.123456789", "123456789012345678901234567890.123456789")])
def testCanonicalNumbers(raw: str, expected: str):
	assert canonicalNumber(raw) == expected


def testTypedValues():
	log = load('''@obs A
p:Person
  Name " leading \\ntext "
  Age +00021
  Active false
  Dob 2000-02-29
  At 2026-01-01T12:30:00+13:00
  Duration P2Y6M
  Years 2.50
  Pay 12345678901234567890.2500
  Category A
  Open Other
  Struct.Surname Ng
  Values [3, 1.00, 2, ...]
''')
	assert values(log, "Name") == [" leading \ntext "]
	assert values(log, "Age") == ["21"]
	assert values(log, "Active") == [False]
	assert values(log, "Years") == ["2.5"]
	assert values(log, "Pay") == ["12345678901234567890.25"]
	assert values(log, "Values") == [{"set": ["1", "2", "3"], "partial": True}]


def testUnknownAbsentEmptyAndPartialAreDistinct():
	log = load("@obs A\np:Person\np.Name ?\np.Name null\np.Values []\np.Values [...]\n")
	assert values(log, "Name") == [{"unknown": True}, None]
	assert values(log, "Values") == [{"set": []}, {"set": [], "partial": True}]


def testQuotedCollections():
	log = load('@obs A\np:Person\np.Required ["a,b", "x]y", "?", "null"]\n')
	assert len(values(log, "Required")[0]["set"]) == 4


def testReferenceTypingAndRefinement():
	log = load("@obs A\np:Party\nq:Person.Owner p:Person\n")
	assert log.instances["p"]["type"] == "A/Person"
	assert values(log, "Owner") == [{"ref": "p"}]
	log = load("@obs A\np:Person\np.Owner q:Person\nq.Name Q\n")
	assert log.instances["q"]["type"] == "A/Person"


def testBinaryForwardInverseSymmetryAndNamedAttributes():
	log = load("@obs A\np:Person\nq:Person\nh:Household\np memberOf h\nq partner p\nr: p knows q\n")
	links = [claim for claim in log.claims if "rel" in claim]
	assert links[0]["roles"] == {"Household": "h", "Person": "p"}
	assert links[1]["roles"] == {"Subject": "p", "Object": "q"}
	assert links[2]["s"] == "r"
	assert log.instances["r"]["type"] == "A/Person.knows.A/Person"


def testAssociationRolesAndForwardReference():
	log = load("@obs A\ni:Income {valid=2026-01-01..}\n  Payer p:Person\n  Recipient [q:Person]\n  Amount 20\np.Name P\n")
	assert values(log, "Payer") == [{"ref": "p"}]
	assert values(log, "Recipient") == [{"set": [{"ref": "q"}]}]


def testContextsAreLimitedToContextualClaims():
	log = load("@obs A\np:Person\na:Scenario\nb:Scenario\n@ctx a\np[Review, Investor] {ctx=b}\np.Review.Included true\np.Name P\n@ctx none\np.Review.Included false {ctx=b}\n")
	assert [claim.get("ctx") for claim in log.claims if "facet" in claim] == ["b", None]
	assert [claim["ctx"] for claim in log.claims if claim.get("p") == "Review.Included"] == ["a", "b"]
	assert "ctx" not in next(claim for claim in log.claims if claim.get("p") == "Name")


@pytest.mark.parametrize(("statement", "code"), [
	("p.Age 2.5", "value"), ("p.Age NaN", "value"), ("p.Age 1,000", "value"),
	("p.Dob 2026-02-30", "value"), ("p.At 2026-02-30T12:30", "value"), ("p.At 2026-01-01T25:00", "value"),
	("p.Active yes", "value"), ("p.Category Other", "value"), ("p.Category \"A\"", "value"),
	("p.Values [1, 1.00]", "value"), ("p.Values [?, 1]", "value"), ("p.Values [[1]]", "value"),
	("p.Values [1,]", "value"), ("p.Values [1", "value"), ("p.Values null", "value"),
	("p.Name []", "value"), ("p.Required []", "value"), ("p.Struct Name", "value"),
	("p.Owner p:Household", "type"), ("p.Owner q", "type"), ("p.Owner \"p\"", "value"),
	("p.Pay 2 {cur=EUR}", "qualifier"), ("p.Name N {conf=2}", "meta"),
	("p.Name N {at=2026-02-30}", "meta"), ("p.Name N {valid=2026-02-01..2026-01-01}", "meta"),
	("p.Name N {of=other}", "meta"), ("p.Name N {ctx=p}", "meta"),
	("p.Review.Included true", "meta"), ("p.Review.Included true {ctx=p}", "type"),
	("p.Review.Included true {ctx=none}", "meta"), ("p[Missing]", "reference"),
	("p.Missing X", "reference"), ("q.Name X", "type"), ("p unknown p", "reference"),
	("p.Name X {format=markdown}", "meta"), ("p.Name X {src}", "meta"),
])
def testInvalidStatements(statement: str, code: str):
	assert code in errors(f"@obs A\np:Person\n{statement}\n")


@pytest.mark.parametrize("text", ["p:Person\n", "@obs B\np:Person\n", "@obs A rev=wrong\n", "@obs A\n@obs A\n", "@obs A\n   p:Person\n", "@obs A\n\tp:Person\n", "@obs A\n  Name X\n", "@obs A\r\np:Person\n"])
def testInvalidDocuments(text: str):
	assert errors(text)


def testIntervalsCompareActualInstants():
	start, end = parseInterval("2026-01-01T01:00:00+01:00..2026-01-01T00:30:00Z")
	assert start < end
	with pytest.raises(ValueError):
		parseInterval("..")

# -----------------------------------------------------------------------------
#
# RECONCILIATION
#
# -----------------------------------------------------------------------------


def testLatestPerSourceAndCrossSourceConflicts():
	log = state("@obs A\np:Person\np.Name Old {src=a, at=2026-01-01}\np.Name New {src=a, at=2026-02-01}\np.Name Other {src=b, at=2026-02-01}\n")
	assert values(log, "Name") == ["New", "Other"]
	assert all(claim["conflict"] for claim in log.claims if claim.get("p") == "Name")
	assert log.retractions == []


def testEqualTimesUseDocumentOrderAndTimezoneOffsetsAreChronological():
	log = state("@obs A\np:Person\np.Name First {at=2026-01-01}\np.Name Second {at=2026-01-01}\n")
	assert values(log, "Name") == ["Second"]
	log = state("@obs A\np:Person\np.Name Later {at=2026-01-01T01:00Z}\np.Name Earlier {at=2026-01-01T02:00+02:00}\n")
	assert values(log, "Name") == ["Later"]


def testDisjointValidityDoesNotConflict():
	log = state("@obs A\np:Person\np.Name A {src=a, valid=2026-01-01..2026-02-01}\np.Name B {src=b, valid=2026-03-01..}\n")
	assert not any(claim.get("conflict") for claim in log.claims)


def testPartialCollectionsAccumulateCompleteCollectionsReplace():
	log = state("@obs A\np:Person\np.Values 1\np.Values [2, ...]\np.Values 3\n")
	assert values(log, "Values") == ["1", {"set": ["2"], "partial": True}, "3"]
	log = state("@obs A\np:Person\np.Values 1\np.Values [2, ...]\np.Values [3]\n")
	assert values(log, "Values") == [{"set": ["3"]}]


def testRetractionRespectsSourceTimeAndNullValue():
	log = state("@obs A\np:Person\np.Name null {src=a, at=2026-01-01}\np.Name Other {src=b, at=2026-01-01}\n- p.Name null {src=a, at=2026-02-01}\n")
	assert values(log, "Name") == ["Other"]
	log = state("@obs A\np:Person\np.Name Future {src=a, at=2026-03-01}\n- p.Name {src=a, at=2026-02-01}\n")
	assert values(log, "Name") == ["Future"]
	assert any(item.code == "retraction" for item in log.diagnostics)


def testCuratorCanRetractOtherSource():
	log = state("@obs A\np:Person\np.Name Wrong {src=a}\n- p.Name {src=curator, of=a}\n")
	assert values(log, "Name") == []


def testSourceAliasesDenoteTheSameProvenanceToken():
	text = "@obs A\n@src a=system:1 b=system:1\np:Person\np.Name First {src=a}\np.Name Second {src=b}\n"
	log = state(text)
	assert values(log, "Name") == ["Second"]
	assert not any(claim.get("conflict") for claim in log.claims)
	assert values(state(text + "- p.Name {src=system:1}\n"), "Name") == []


def testRetractionOfMemberFromCompleteSet():
	log = state("@obs A\np:Person\np.Values [1, 2, 3]\n- p.Values 2\n")
	assert values(log, "Values") == [{"set": ["1", "3"]}]


def testRetractionOfFacetAndContext():
	text = "@obs A\np:Person\na:Scenario\nb:Scenario\np[Review] {ctx=a}\np.Review.Included true {ctx=a}\np.Review.Included false {ctx=b}\n"
	log = state(text + "- p[Review] {ctx=a}\n")
	assert values(log, "Review.Included") == [False]
	log = state(text + "- a\n")
	assert values(log, "Review.Included") == [False]


def testReconciliationIsPureAndIdempotent():
	log = load("@obs A\np:Person\np.Name Old\np.Name New\n- p.Age 2\n")
	before = deepcopy(log)
	resolved = reconcileObservations(MODEL, log)
	assert log == before
	assert observationsToJson(reconcileObservations(MODEL, resolved)) == observationsToJson(resolved)


def testNumericEqualityDoesNotDependOnExponentSpelling():
	assert "value" in errors("@obs A\np:Person\np.Values [1000, 1e3]\n")
	log = state("@obs A\np:Person\np.Pay 1e3 {src=a}\np.Pay 1000 {src=b, cur=USD}\n")
	assert not any(claim.get("conflict") for claim in log.claims)
	log = state("@obs A\np:Person\np.Values [1000, 2]\n- p.Values 1e3\n")
	assert values(log, "Values") == [{"set": ["2"]}]
	log = state("@obs A\np:Person\np.Required [\"1000\", \"1e3\"]\n")
	assert len(values(log, "Required")[0]["set"]) == 2


# -----------------------------------------------------------------------------
#
# NORMAL FORMS AND JSON IMPORT
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("form", ["log", "state"])
def testSpecNormalFormsAreIdempotent(form: str):
	text = formatObservations(ONTOLOGY, Source("finance.obs", EXAMPLE), form)
	assert formatObservations(ONTOLOGY, Source("normal.obs", text), form) == text
	if form == "log":
		assert not any(line.startswith("  ") for line in text.splitlines())
	else:
		assert "@ctx " not in text
		assert "  Isin US0000000001" in text
		assert "- p1.DateOfBirth" not in text
		assert "1990-06-16" not in text


def testLogRoundTripPreservesClaimsAndRetractions():
	before = load(EXAMPLE, ONTOLOGY)
	text = printObservationsLog(ONTOLOGY, before)
	after = load(text, ONTOLOGY)
	assert _semanticClaims(before) == _semanticClaims(after)
	assert [{key: value for key, value in claim.items() if key != "n"} for claim in before.retractions] == [{key: value for key, value in claim.items() if key != "n"} for claim in after.retractions]
	assert before.instances == after.instances


@pytest.mark.parametrize("form", ["log", "state"])
def testMetadataDefaultsDoNotLeakToClaimsWithoutSourceOrTime(form: str):
	text = "@obs A\np:Person\np.Name First {src=x, at=2026-01-01}\np.Age 21\n"
	printed = formatObservations(MODEL, Source("t", text), form)
	assert "@src x" not in printed and "@at 2026-01-01" not in printed
	actual = load(printed)
	assert "src" not in next(claim for claim in actual.claims if claim.get("p") == "Age")


@pytest.mark.parametrize("form", ["log", "state"])
def testUnsafeTextAndCollectionsSurvivePrinting(form: str):
	text = '''@obs A
p:Person
  Name " a // b {c}\\n\\\"quote\\\" "
  Required ["...", "?", "null", "[", "a,b", "x]y", "", "// comment"]
'''
	printed = formatObservations(MODEL, Source("t", text), form)
	assert values(load(printed), "Name") == values(load(text), "Name")
	assert values(load(printed), "Required") == values(load(text), "Required")
	assert formatObservations(MODEL, Source("t", printed), form) == printed


@pytest.mark.parametrize("form", ["log", "state"])
def testContextualNormalForms(form: str):
	text = "@obs A\np:Person\na:Scenario\nb:Scenario\np[Review] {ctx=a}\np.Review.Included true {ctx=a}\np.Review.Included false {ctx=b}\n"
	printed = formatObservations(MODEL, Source("t", text), form)
	assert formatObservations(MODEL, Source("t", printed), form) == printed
	assert values(load(printed), "Review.Included") == [True, False]
	if form == "state":
		assert "{ctx=a}" in printed and "{ctx=b}" in printed
		assert "@ctx" not in printed


@pytest.mark.parametrize("form", ["log", "state"])
@pytest.mark.parametrize("value", ["{src=x}", "a\t{src=x}", "a\u00a0{src=x}", "a\v{src=x}", "a\f{src=x}"])
def testAnnotationLikeTextPreservesValuesAndMetadata(form: str, value: str) -> None:
	before = load("@obs A\np:Person\np.Name " + json.dumps(value) + "\n")
	printed = formatObservations(MODEL, Source("t", "@obs A\np:Person\np.Name " + json.dumps(value) + "\n"), form)
	after = load(printed)
	assert _semanticClaims(after) == _semanticClaims(before)
	assert observationsFromJson(MODEL, observationsToJson(before)) == before


def testStateOnlyEmitsRealExistenceClaims():
	log = state("@obs A\np:Person\n- p\np.Name Back\n")
	text = printObservationsState(MODEL, log)
	assert "p:Person.Name Back" in text
	assert _semanticClaims(load(text)) == _semanticClaims(log)


def testStatePreservesMultipleSourcesAndConflicts():
	log = state("@obs A\np:Person {src=a}\np {src=b}\np.Name A {src=a}\np.Name B {src=b}\n")
	text = printObservationsState(MODEL, log)
	assert text.count("{conflict") + text.count(", conflict}") == 2
	assert _semanticClaims(reconcileObservations(MODEL, load(text))) == _semanticClaims(log)
	assert formatObservations(MODEL, Source("t", text)) == text


def testStateRejectsUnappliedRetractions():
	with pytest.raises(ValueError):
		printObservationsState(MODEL, load("@obs A\np:Person\n- p\n"))


def testInvalidFormIsRejected():
	with pytest.raises(ValueError):
		formatObservations(MODEL, Source("t", "@obs A\n"), "other")


def testSpecLogJsonRoundTripPreservesOrdinals():
	log = load(EXAMPLE, ONTOLOGY)
	data = observationsToJson(log)
	before = deepcopy(data)
	assert observationsToJson(observationsFromJson(ONTOLOGY, data)) == data
	assert data == before


def testStateJsonRoundTripRecomputesConflicts():
	log = state("@obs A\np:Person\np.Name A {src=a}\np.Name B {src=b}\n")
	data = observationsToJson(log)
	loaded = observationsFromJson(MODEL, data)
	assert not any(claim.get("conflict") for claim in loaded.claims)
	assert observationsToJson(reconcileObservations(MODEL, loaded)) == data


def testJsonCollectionsAcceptUnorderedMembership():
	data = observationsToJson(load("@obs A\np:Person\np.Values [1, 2]\n"))
	data["claims"][-1]["v"]["set"].reverse()
	assert observationsFromJson(MODEL, data).claims[-1]["v"]["set"] == ["2", "1"]


def testJsonPreservesUnusedInstanceRegistryWithoutInventingExistence():
	data = observationsToJson(state("@obs A\np:Person\n- p\n"))
	loaded = observationsFromJson(MODEL, data)
	assert observationsToJson(loaded) == data
	assert loaded.claims == loaded.retractions == []


@pytest.mark.parametrize("form", ["log", "state"])
def testNamedBinaryAttributesAndMultipleSourceLinksRoundTrip(form: str):
	ontology = loadOntology([Source("t", "@ontology A\nPerson\nHousehold\nHousehold -has/memberOf-> Person\n  Role Adult|Child\n")])
	text = "@obs A at=2026-01-01\nh:Household\np:Person\nr: p memberOf h {src=a}\nr.Role Adult {src=a}\nr: h has p {src=b}\n"
	printed = formatObservations(ontology, Source("t", text), form)
	assert "r: h has p" in printed
	assert "r.Role Adult" in printed
	assert formatObservations(ontology, Source("t", printed), form) == printed
	log = load(text, ontology)
	assert observationsToJson(observationsFromJson(ontology, observationsToJson(log))) == observationsToJson(log)


def testSharedBinaryVerbsAndUnknownParticipantsPrintUnambiguously():
	ontology = loadOntology([Source("t", "@ontology A\nPerson\nAsset\nProperty\nPerson -owns/ownedBy-> Asset\nPerson -owns/ownedBy-> Property\n")])
	text = "@obs A\np:Person\na:Asset\nh:Property\np owns a\nh ownedBy p\n"
	printed = formatObservations(ontology, Source("t", text))
	assert "p owns a" in printed and "p owns h" in printed
	assert formatObservations(ontology, Source("t", printed)) == printed
	with pytest.raises(FormatError, match="ambiguous"):
		load("@obs A\np:Person\np owns ?\n", ontology)
	unknown = "@obs A\np:Person\np knows ?\n"
	assert "p knows ?" in formatObservations(MODEL, Source("t", unknown))


def testJsonRejectsWrongBinaryRolesAndIncompatibleNamedType():
	data = observationsToJson(load("@obs A\np:Person\nq:Person\nr: p knows q\n"))
	badRoles = deepcopy(data)
	badRoles["claims"][-1]["roles"] = {"Wrong": "p", "Object": "q"}
	with pytest.raises(FormatError):
		observationsFromJson(MODEL, badRoles)
	data["instances"]["r"]["type"] = "A/Person.partner.A/Person"
	with pytest.raises(FormatError, match="round trip"):
		observationsFromJson(MODEL, data)


@pytest.mark.parametrize("change", [
	lambda data: data.update(extra=1),
	lambda data: data.update(format="other"),
	lambda data: data.update(obs=None),
	lambda data: data["obs"].update(extra="x"),
	lambda data: data["obs"].update(at=None),
	lambda data: data.update(sources=[]),
	lambda data: data["sources"].update({"Bad Alias": "x"}),
	lambda data: data.update(instances=[]),
	lambda data: data["instances"]["p"].update(extra=1),
	lambda data: data["instances"]["p"].update(type="A/Money"),
	lambda data: data.update(claims={}),
	lambda data: data.update(retractions=None),
	lambda data: data["claims"][0].update(exists=False),
	lambda data: data["claims"][0].update(n=0),
	lambda data: data["claims"][0].update(n=True),
	lambda data: data["claims"][0].update(n=1.5),
	lambda data: data["claims"][0].update(extra=1),
	lambda data: data["claims"][0].update(p="Name", v="x"),
	lambda data: data["claims"][0].update(roles={}),
	lambda data: data["claims"][0].update(v="x"),
	lambda data: data["claims"][0].update(conf=True),
	lambda data: data["claims"][0].update(conf=float("nan")),
	lambda data: data["claims"][0].update(conf=2),
	lambda data: data["claims"][0].update(conflict=False),
	lambda data: data["claims"][0].update(s="missing"),
	lambda data: data["claims"][-1].pop("v"),
	lambda data: data["claims"][-1].update(v=21),
	lambda data: data["claims"][-1].update(v=True),
	lambda data: data["claims"][-1].update(v={"unknown": False}),
	lambda data: data["claims"][-1].update(v={"unknown": True, "extra": 1}),
	lambda data: data["claims"][-1].update(v={"set": [None]}),
	lambda data: data["claims"][-1].update(v={"set": [{"unknown": True}]}),
	lambda data: data["claims"][-1].update(v={"set": [], "partial": False}),
	lambda data: data["claims"][-1].update(v="021"),
])
def testStrictJsonRejectsMalformedOrLossyInput(change):
	data = observationsToJson(load("@obs A\np:Person\np.Age 21\n"))
	change(data)
	with pytest.raises(FormatError):
		observationsFromJson(MODEL, data)


@pytest.mark.parametrize("bad", [None, [], 1, True, "{}"])
def testJsonRequiresObject(bad):
	with pytest.raises(FormatError):
		observationsFromJson(MODEL, bad)


# EOF
