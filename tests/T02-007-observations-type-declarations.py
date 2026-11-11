"""Module: observations type declarations — registry-only typing and lossless normal forms."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from onto.observations import Observations
from onto import FormatError, Source, formatObservations, loadObservations, loadOntology, observationsCoverage, observationsFromJson, observationsToJson, printObservationsLog, printObservationsState, reconcileObservations
from onto.observations.parser import parseObservations

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

ONTOLOGY = loadOntology([Source("t", """@ontology A
@use External as X
Party
Person < Party
  Name Text
  Owner Party
Household
Scenario
SubScenario < Scenario
X/Person
X/Org
X/Org -employs-> X/Person
Household -hasMember/memberOf-> Person
  Role Text
Group(Household, Person)
  Note Text
Review of Person {ctx=Scenario}
  Included Boolean
T = Text
@view V
  Person.Name
""")])


def load(text: str, mode: str = "strict") -> Observations:
	return loadObservations(ONTOLOGY, Source("type.obs", "@obs A\n" + text), mode)


def content(log: Observations) -> dict[str, Any]:
	data = observationsToJson(log)
	for key in ("claims", "retractions"):
		data[key] = sorted([{name: value for name, value in claim.items() if name != "n"} for claim in data[key]], key=lambda claim: json.dumps(claim, sort_keys=True))
	return data

# -----------------------------------------------------------------------------
#
# PARSING AND REGISTRY SEMANTICS
#
# -----------------------------------------------------------------------------


def testTypeDeclarationsCarryNoMetadataClaimsOrStatementOrdinals():
	doc = parseObservations(Source("types.obs", "@obs A src=feed at=2026-01-01 by=importer\n@type p Person\np.Name P\n@type q Party\np\n"))
	assert [(item.handle, item.type, item.loc.line) for item in doc.declarations] == [("p", "Person", 2), ("q", "Party", 4)]
	assert [statement.n for statement in doc.statements] == [1, 2]
	log = load("@src feed\n@type p Person\n@type q Party\n")
	assert log.instances == {"p": {"type": "A/Person"}, "q": {"type": "A/Party"}}
	assert log.claims == log.retractions == []
	assert observationsCoverage(ONTOLOGY, log, "V")[0].subject is None


def testDeclarationsSupportForwardReferencesAndCompatibleRefinement():
	log = load("p.Name P\n@type p Party\n@type p Person\n@type p Party\n")
	assert log.instances["p"] == {"type": "A/Person"}
	assert log.claims == [{"n": 1, "s": "p", "p": "Name", "v": "P"}]
	assert "@type p" not in printObservationsLog(ONTOLOGY, log)
	assert "p:Person.Name P" in printObservationsLog(ONTOLOGY, log)


def testAssociationAndBinaryDeclarationsRegisterTypesWithoutEndpoints():
	log = load("@type group Group\n@type r Household.hasMember.Person\ngroup.Note Note\nr.Role Adult\n")
	assert log.instances["group"] == {"type": "A/Group"}
	assert log.instances["r"] == {"type": "A/Household.hasMember.A/Person"}
	assert all("exists" not in claim and "rel" not in claim and "roles" not in claim for claim in log.claims)
	assert all(name not in log.instances for name in ("Household", "Person"))


def testLaterStatementsCanAssertExistenceButCannotChangeAnIncompatibleDeclaredType():
	log = load("@type p Party\np:Person\n")
	assert log.instances["p"] == {"type": "A/Person"}
	assert log.claims == [{"n": 1, "s": "p", "exists": True}]
	with pytest.raises(FormatError):
		load("@type p Person\np:Household\n")
	log = load("@type p Person\np:Household\n", "lenient")
	assert log.instances["p"] == {"type": "A/Person"}
	assert len(log.gaps) == 1 and log.claims == []


@pytest.mark.parametrize("mode", ["strict", "lenient"])
@pytest.mark.parametrize("declaration", [
	"@type", "@type p", "@type p Person extra", "@type bad-handle Person",
	"@type p Person {src=feed}", "@type p Missing", "@type p Text", "@type p T",
	"@type r Person.hasMember.Household", "@type r Household.HasMember.Person", "@type r Person.knows",
	"@type p Person\n@type p Household",
	"@type p Person\n  Name NotARecord", "p:Person\n  @type q Person",
])
def testInvalidDeclarationsRemainFatalInBothModes(declaration: str, mode: str):
	with pytest.raises(FormatError):
		load(declaration + "\n", mode)

# -----------------------------------------------------------------------------
#
# NORMAL FORMS AND JSON
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("form", ["log", "state"])
def testOrphanRegistryRoundTripsWithoutExistence(form: str):
	log = reconcileObservations(ONTOLOGY, load("p:Person\n- p\n"))
	before = deepcopy(log)
	printed = printObservationsLog(ONTOLOGY, log) if form == "log" else printObservationsState(ONTOLOGY, log)
	assert printed == "@obs A\n@type p Person\n"
	loaded = loadObservations(ONTOLOGY, Source("normal.obs", printed))
	assert observationsToJson(loaded) == observationsToJson(log)
	assert loaded.claims == loaded.retractions == []
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)
	assert formatObservations(ONTOLOGY, Source("normal.obs", printed), form) == printed
	assert log == before


def testContextOnlyHandleIsTypedWithoutClaimingItsExistence():
	log = load("@type context SubScenario\np:Person\np.Review.Included true {ctx=context}\n")
	state = reconcileObservations(ONTOLOGY, log)
	assert state.instances["context"] == {"type": "A/SubScenario", "implicit": True}
	printed = printObservationsState(ONTOLOGY, state)
	assert printed.startswith("@obs A\n@type context SubScenario\n@implicit context\n")
	assert "context:SubScenario" not in printed
	loaded = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert content(loaded) == content(state)
	data = observationsToJson(state)
	assert observationsToJson(reconcileObservations(ONTOLOGY, observationsFromJson(ONTOLOGY, data))) == data
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


def testNamedRelationAttributesSurviveWithoutReassertingTheWithdrawnLink():
	log = load("p:Person {src=entities}\nh:Household {src=entities}\nr: h hasMember p {src=link}\nr.Role Adult {src=notes}\n- r {src=link}\n")
	state = reconcileObservations(ONTOLOGY, log)
	printed = printObservationsState(ONTOLOGY, state)
	assert "@type r Household.hasMember.Person\n" in printed
	assert "r.Role Adult" in printed
	assert "r: h hasMember p" not in printed
	loaded = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert content(loaded) == content(state)
	assert not any(claim.get("s") == "r" and ("exists" in claim or "rel" in claim) for claim in loaded.claims)
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(state))) == observationsToJson(state)
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


def testAliasesAndDeterministicDeclarationOrderingUseShortestTypeNames():
	log = load("@scope feed\n@type z X/Person\n@type a X/Org.employs.X/Person\n")
	printed = printObservationsLog(ONTOLOGY, log)
	assert printed == "@obs A\n@scope feed\n@type a X/Org.employs.X/Person\n@type z X/Person\n"
	assert observationsToJson(loadObservations(ONTOLOGY, Source("t", printed))) == observationsToJson(log)


def testOrdinaryMentionsAndDefiningLinksDoNotProduceRedundantDeclarations():
	log = load("p:Person\np.Owner q:Party\nh:Household\nr: h hasMember p\nr.Role Adult\n")
	assert "@type" not in printObservationsLog(ONTOLOGY, log)
	assert "@type" not in printObservationsState(ONTOLOGY, reconcileObservations(ONTOLOGY, log))


def testMergedNamedBinaryAliasKeepsItsTypeWithoutAnotherDefiningLink():
	state = reconcileObservations(ONTOLOGY, load("p:Person\nh:Household\none: h hasMember p\ntwo: h hasMember p\none = two\n"))
	printed = printObservationsState(ONTOLOGY, state)
	assert "@type two Household.hasMember.Person\n" in printed
	assert "two: h hasMember p" not in printed
	loaded = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert content(loaded) == content(state)
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(state))) == observationsToJson(state)
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


def testLenientGapsStillPreserveRegistryOnlyTypeEvidence():
	log = load("@type context Scenario\np:Person\np.Review.Missing X {ctx=context}\n", "lenient")
	data = observationsToJson(log)
	assert len(log.gaps) == 1
	assert observationsToJson(observationsFromJson(ONTOLOGY, data, mode="lenient")) == data


# EOF
