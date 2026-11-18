"""Module: observations gap tests — lenient statement isolation and lossless retention."""

from __future__ import annotations

from copy import deepcopy

import pytest

from onto.observations import Observations
from onto import FormatError, Source, formatObservations, loadObservations, loadOntology, observationsCoverage, observationsFromJson, observationsToJson, printObservationsLog, printObservationsState, reconcileObservations
from tests.helpers import schemaValidator

# -----------------------------------------------------------------------------
#
# FIXTURES AND HELPERS
#
# -----------------------------------------------------------------------------

ONTOLOGY = loadOntology([Source("t", """@ontology A
Person
  Name Text
  Age Integer
  Friend Person
Household
Scenario
Review of Person {ctx=Scenario}
  Included Boolean
Household -has-> Person
  Role Text
@view V
  Person.Name
  Person.Age
""")])


def load(text: str, mode: str = "lenient") -> Observations:
	return loadObservations(ONTOLOGY, Source("input.obs", "@obs A\n" + text), mode)


def gapKeys(log: Observations) -> list[tuple[str, dict[str, str | bool], str | None, list[str]]]:
	return [(gap.text, gap.meta, gap.ctx, [item.code for item in gap.diagnostics]) for gap in log.gaps]

# -----------------------------------------------------------------------------
#
# ISOLATION
#
# -----------------------------------------------------------------------------


def testStrictRemainsTheDefaultAndLenientRetainsUnknownStatements():
	text = "p:Person\n  Name Known\n  Missing mystery // original comment\n  Age 21\n"
	with pytest.raises(FormatError):
		loadObservations(ONTOLOGY, Source("input.obs", "@obs A\n" + text))
	log = load(text)
	assert len(log.gaps) == 1
	gap = log.gaps[0]
	assert (gap.n, gap.raw, gap.text, gap.loc.file, gap.loc.line) == (3, "  Missing mystery // original comment", "p.Missing mystery", "input.obs", 4)
	assert [claim.get("p") for claim in log.claims] == [None, "Name", "Age"]
	assert gap.diagnostics[0].code == "reference"
	assert all(item.level == "warning" for item in log.diagnostics)


def testValidInputIsIdenticalInBothModes():
	text = "p:Person\np.Name Known\np.Age 21\np.Friend q:Person\n"
	assert load(text) == load(text, "strict")


@pytest.mark.parametrize("statement", ["p.Age invalid", "p.Age 2.5", "p[Missing]", "p.Friend q", "p.Review.Included true", "p.Name X {ctx=p}", "p = p", "p knows p", "q:Unknown", "p:Household"])
def testSemanticFailuresAreGapsNotPartiallyAppliedClaims(statement: str):
	log = load(f"p:Person\n{statement}\np.Name StillValid\n")
	assert len(log.gaps) == 1
	assert all(claim["n"] != 2 for claim in log.claims + log.retractions)
	assert any(claim.get("v") == "StillValid" for claim in log.claims)
	assert log.instances["p"]["type"] == "A/Person"


def testUnknownFacetHeaderIsAtomicButItsTypeCanSupportLaterStatements():
	log = load("p:Person[Missing]\n  Name StillValid\n")
	assert len(log.gaps) == 1
	assert not any(claim.get("exists") for claim in log.claims)
	assert log.claims[0]["v"] == "StillValid"


def testUnsafeRetractionIsRetainedButNeverExecuted():
	log = load("p:Person\np.Name Keep\n- p {ctx=p}\np.Age 21\n- p.Age broken\n")
	assert len(log.gaps) == 2
	assert log.retractions == []
	state = reconcileObservations(ONTOLOGY, log, "lenient")
	assert {claim["p"]: claim["v"] for claim in state.claims if "p" in claim} == {"Name": "Keep", "Age": "21"}
	assert state.gaps == log.gaps


def testInvalidReferenceDropsItsWholeCollectionStatement():
	ontology = loadOntology([Source("t", "@ontology A\nPerson\n  * Friends Person\nHousehold\n")])
	log = loadObservations(ontology, Source("t", "@obs A\np:Person\nq:Person\nh:Household\np.Friends [q, h]\n"), "lenient")
	assert len(log.gaps) == 1
	assert not any(claim.get("p") == "Friends" for claim in log.claims)


def testFailedNamedRelationDoesNotOverwriteAnExistingType():
	log = load("p:Person\nh:Household\np: h has p\np.Name StillPerson\n")
	assert len(log.gaps) == 1
	assert log.instances["p"]["type"] == "A/Person"
	assert log.claims[-1]["v"] == "StillPerson"


@pytest.mark.parametrize("text", ["@obs Wrong\np:Person\n", "@obs A rev=wrong\n", "@obs A\n@src a=x a=y\n", "@obs A\n@at not-a-date\n", "@obs A\np:Person\n  Name N {extra=x}\n", "@obs A\np:Person\n   Name BadIndent\n", "@obs A\np:Person\nmalformed ???\n"])
def testAmbiguousSyntaxAndDocumentDefaultsRemainFatal(text: str):
	with pytest.raises(FormatError):
		loadObservations(ONTOLOGY, Source("t", text), "lenient")

# -----------------------------------------------------------------------------
#
# PRESERVATION
#
# -----------------------------------------------------------------------------


def testJsonRetainsGapDefaultsContextsAndOrdinalPosition():
	text = "@obs A at=2026-01-01 src=feed by=importer conf=0.8\np:Person\ns:Scenario\n@ctx s\np.Missing first\n@src other\n@at 2026-02-01\n@ctx none\np.Other second\np.Name Known\n"
	log = loadObservations(ONTOLOGY, Source("raw.obs", text), "lenient")
	loaded = observationsFromJson(ONTOLOGY, observationsToJson(log), mode="lenient")
	assert gapKeys(loaded) == gapKeys(log)
	assert loaded.claims == log.claims
	assert [gap.n for gap in loaded.gaps] == [3, 4]


def testGapJsonRoundTripRetainsRawTextLocationAndDiagnostics():
	log = load("p:Person\n  Name Known\n  Missing mystery // comment\n")
	data = observationsToJson(log)
	before = deepcopy(data)
	with pytest.raises(FormatError, match="requires lenient mode"):
		observationsFromJson(ONTOLOGY, data)
	loaded = observationsFromJson(ONTOLOGY, data, mode="lenient")
	assert observationsToJson(loaded) == data
	assert data == before
	assert loaded.gaps[0].raw.endswith("// comment")
	assert loaded.diagnostics[0].loc.file == "input.obs"
	assert "gaps" not in observationsToJson(load("p:Person\n"))


def testStateJsonKeepsGapsButStateTextRefusesToSilentlyLoseThem():
	state = reconcileObservations(ONTOLOGY, load("p:Person\np.Missing X\n"), "lenient")
	with pytest.raises(ValueError, match="cannot preserve gaps"):
		printObservationsState(ONTOLOGY, state)
	with pytest.raises(ValueError, match="inert gaps"):
		printObservationsLog(ONTOLOGY, state)
	data = observationsToJson(state)
	assert observationsToJson(observationsFromJson(ONTOLOGY, data, mode="lenient")) == data


@pytest.mark.parametrize("statement, update, code, survivingValue", [
	("p.B 2", "- p.A", "one", None),
	("p[F]", "- p.A", "when", None),
	("p[F]", "p.A 2", "when", "2"),
])
def testStateJsonKeepsConflictGapsAfterTheirBlockerIsRemoved(statement, update, code, survivingValue):
	ontology = loadOntology([Source("t", """@ontology A
P
  A Integer {one=Choice}
  B Integer {one=Choice}
F of P {when=A:2}
""")])
	log = loadObservations(ontology, Source("t", f"@obs A\np:P\np.A 1\n{statement}\n{update}\n"), "lenient")
	assert [item.code for item in log.gaps[0].diagnostics] == [code]
	logData = observationsToJson(log)
	assert "witnesses" not in logData["gaps"][0]
	for original in (log, observationsFromJson(ontology, logData, mode="lenient")):
		state = reconcileObservations(ontology, original, "lenient")
		assert [claim["v"] for claim in state.claims if "v" in claim] == ([survivingValue] if survivingValue else [])
		data = observationsToJson(state)
		schemaValidator("observations").validate(data)
		loaded = observationsFromJson(ontology, data, mode="lenient")
		assert observationsToJson(loaded) == data
		assert loaded.claims == state.claims and not loaded.retractions
		assert reconcileObservations(ontology, loaded, "lenient").claims == state.claims
		# Neither a bare diagnostic nor a type-correct but non-conflicting witness is enough.
		unwitnessed = deepcopy(data)
		unwitnessed["gaps"][0].pop("witnesses")
		with pytest.raises(FormatError, match="round trip"):
			observationsFromJson(ontology, unwitnessed, mode="lenient")
		data["gaps"][0]["witnesses"][0]["src"] = "differentSource"
		with pytest.raises(FormatError, match="round trip"):
			observationsFromJson(ontology, data, mode="lenient")


def testTextFormattingRefusesGapsAndCoverageDoesNotTreatThemAsEvidence():
	text = "@obs A\np:Person\np.Age Invalid\n"
	with pytest.raises(ValueError, match="inert gaps"):
		formatObservations(ONTOLOGY, Source("t", text), "log", "lenient")
	log = loadObservations(ONTOLOGY, Source("t", text), "lenient")
	with pytest.raises(FormatError):
		observationsCoverage(ONTOLOGY, log, "V")
	items = observationsCoverage(ONTOLOGY, log, "V", mode="lenient")
	assert next(item for item in items if item.path == "A/Person.Age").statuses == ("missing",)


@pytest.mark.parametrize("change", [
	lambda data: data.update(gaps=None),
	lambda data: data["gaps"][0].update(n=0),
	lambda data: data["gaps"][0].update(raw="x\ny"),
	lambda data: data["gaps"][0].update(text="p.Name ActuallyValid"),
	lambda data: data["gaps"][0].update(meta={"ctx": "none"}),
	lambda data: data["gaps"][0].update(diagnostics=[]),
	lambda data: data["gaps"][0]["diagnostics"][0].update(code="value"),
	lambda data: data["gaps"][0]["diagnostics"][0].update(message="fabricated"),
	lambda data: data["gaps"][0]["loc"].update(line=False),
	lambda data: data["gaps"][0].update(extra=1),
])
def testMalformedOrFabricatedGapJsonIsRejected(change):
	data = observationsToJson(load("p:Person\np.Missing X\n"))
	change(data)
	with pytest.raises(FormatError):
		observationsFromJson(ONTOLOGY, data, mode="lenient")


def testMalformedClaimsDoNotBecomeJsonGapsWithoutAnExplicitGapRecord():
	data = observationsToJson(load("p:Person\np.Age 21\n"))
	data["claims"][-1]["v"] = "invalid"
	with pytest.raises(FormatError):
		observationsFromJson(ONTOLOGY, data, mode="lenient")


def testAnUpdatedOntologyCannotSilentlyActivateAGapRetraction():
	log = load("p:Person\n- p.Missing X\n")
	data = observationsToJson(log)
	updated = loadOntology([Source("t", "@ontology A\nPerson\n  Missing Text\n")])
	with pytest.raises(FormatError, match="round trip"):
		observationsFromJson(updated, data, mode="lenient")
	assert len(log.gaps) == 1 and log.retractions == []


def testStrictReconciliationRefusesUnresolvedGapsWithoutMutatingTheLog():
	log = load("p:Person\np.Missing X\n")
	before = deepcopy(log)
	with pytest.raises(FormatError):
		reconcileObservations(ONTOLOGY, log)
	assert log == before
	assert reconcileObservations(ONTOLOGY, log, "lenient").gaps == log.gaps


def testUnknownModeIsRejectedEvenForLogFormatting():
	with pytest.raises(ValueError):
		formatObservations(ONTOLOGY, Source("t", "@obs A\n"), "log", "guess")


# EOF
