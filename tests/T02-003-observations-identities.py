"""Module: observations identity tests — links, producer-scoped retractions and implicit references."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from onto.observations import Observations
from onto import FormatError, Source, formatObservations, loadObservations, loadOntology, observationsFromJson, observationsToJson, printObservationsLog, printObservationsState, reconcileObservations

# -----------------------------------------------------------------------------
#
# FIXTURES AND HELPERS
#
# -----------------------------------------------------------------------------

ONTOLOGY = loadOntology([Source("identity.onto", """@ontology A
Party
Person < Party
  Name Text
  Owner Party
  Context Scenario
  * Friends Party
Employee < Person
Customer < Person
Organisation < Party
Scenario
Review of Person {ctx=Scenario}
  Included Boolean
Person -knows/knownBy-> Person
Person -partner/partner-> Person
Household
Household -has-> Person
Assignment(Party, Person)
""")])


def load(text: str) -> Observations:
	return loadObservations(ONTOLOGY, Source("test.obs", "@obs A\n" + text))


def state(text: str, mode: str = "strict") -> Observations:
	# NOTE: `mode` applies to identity reconciliation; these inputs deliberately load strictly.
	return reconcileObservations(ONTOLOGY, load(text), mode)


def _subjectValues(log: Observations, path: str) -> list[tuple[str, Any]]:
	return [(claim["s"], claim["v"]) for claim in log.claims if claim.get("p") == path]


# -----------------------------------------------------------------------------
#
# PRODUCER-SCOPED RETRACTIONS
#
# -----------------------------------------------------------------------------


def testRetractionByFiltersProducerEvenWithSameSource():
	log = state("p:Person\np.Name First {src=feed, by=one}\np.Name Second {src=feed, by=two}\n- p.Name {src=feed, by=one}\n")
	assert _subjectValues(log, "Name") == [("p", "Second")]
	log = state("p:Person\np.Name First {src=feed, by=one}\np.Name Second {src=feed, by=two}\n- p.Name {src=feed, by=two}\n")
	assert _subjectValues(log, "Name") == [("p", "First")]


def testUnqualifiedRetractionWithdrawsEveryProducerOfTheSource():
	log = state("p:Person\np.Name First {src=feed, by=one}\np.Name Second {src=feed, by=two}\n- p.Name {src=feed}\n")
	assert _subjectValues(log, "Name") == []


def testOfAndByAreBothAppliedAndApprovalSurvivesRoundTrip():
	text = "p:Person\np.Name First {src=feed, by=one}\np.Name Second {src=feed, by=two}\n- p.Name {src=curator, of=feed, by=two, approved=confirm:2}\n"
	log = load(text)
	assert _subjectValues(reconcileObservations(ONTOLOGY, log), "Name") == [("p", "First")]
	assert log.retractions[0]["approved"] == "confirm:2"
	assert "by=two, of=feed, approved=confirm:2" in printObservationsLog(ONTOLOGY, log)
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)


def testProducerQualifiedRetractionDoesNotMatchUnqualifiedClaim():
	log = state("p:Person\np.Name First {src=feed}\n- p.Name {src=feed, by=one}\n")
	assert _subjectValues(log, "Name") == [("p", "First")]
	assert any(item.code == "retraction" for item in log.diagnostics)


def testApprovalIsOnlyValidOnRetractions():
	with pytest.raises(FormatError, match="approved is only valid on retractions"):
		load("p:Person {approved=human}\n")

# -----------------------------------------------------------------------------
#
# IMPLICIT INSTANCES
#
# -----------------------------------------------------------------------------


def testReferenceOnlyHandleIsImplicitWithoutCreatingExistence():
	log = state("p:Person\np.Owner q:Party\n")
	assert log.instances["q"] == {"type": "A/Party", "implicit": True}
	assert not any(claim.get("s") == "q" and claim.get("exists") for claim in log.claims)
	text = printObservationsState(ONTOLOGY, log)
	assert "@implicit q\n" in text
	assert "Owner q:Party" in text
	assert formatObservations(ONTOLOGY, Source("t", text)) == text
	assert reconcileObservations(ONTOLOGY, observationsFromJson(ONTOLOGY, observationsToJson(log))).instances == log.instances


def testImplicitMarkersAreIgnoredAndRecomputed():
	log = state("@implicit p bogus\np:Person\np.Owner q:Party\n")
	assert "implicit" not in log.instances["p"]
	assert "bogus" not in log.instances
	assert log.instances["q"]["implicit"] is True
	data = observationsToJson(log)
	data["instances"]["p"]["implicit"] = True
	read = observationsFromJson(ONTOLOGY, data)
	assert all("implicit" not in instance for instance in read.instances.values())
	assert "implicit" not in reconcileObservations(ONTOLOGY, read).instances["p"]


def testExistenceFromAnySourceClearsImplicitMarker():
	log = state("p:Person\np.Owner q:Party {src=one}\nq {src=two}\n")
	assert "implicit" not in log.instances["q"]
	log = state("p:Person\np.Owner q:Party {src=one}\nq {src=two}\n- q {src=two}\n")
	assert log.instances["q"]["implicit"] is True
	log = state("p:Person\np.Owner q:Party\n- p.Owner\n")
	assert "implicit" not in log.instances["q"]


def testRelationsCollectionsAndContextsMarkTheirReferencedHandles():
	log = state("p:Person\np.Friends [q:Party]\np knows r:Person\np.Review.Included true {ctx=c}\np.Context c:Scenario\n")
	assert {handle for handle, instance in log.instances.items() if instance.get("implicit")} == {"q", "r", "c"}
	text = printObservationsState(ONTOLOGY, log)
	assert "@implicit c q r\n" in text
	assert formatObservations(ONTOLOGY, Source("t", text)) == text


def testUnknownParticipantIsNotAnImplicitHandle():
	log = state("p:Person\np knows ?\n")
	assert "?" not in log.instances

# -----------------------------------------------------------------------------
#
# IDENTITY LINKS
#
# -----------------------------------------------------------------------------


def testLinksParseWithOrdinalsAndDistinctOrderIsCanonical():
	log = load("@implicit ignored\na:Person = b:Person {src=curator}\nb != a\n")
	assert log.claims == [{"n": 1, "same": ["a", "b"], "src": "curator"}, {"n": 2, "distinct": ["a", "b"]}]
	assert not any("exists" in claim for claim in log.claims)
	assert printObservationsLog(ONTOLOGY, log).endswith("a:Person = b:Person {src=curator}\na != b\n")
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)


@pytest.mark.parametrize("text", ["a:Person = a\n", "a:Person != a\n", "a:Person = b:Scenario\n", "a = b\n", "a:Employee = b:Customer\n", "a:Person = b:Person {ctx=a}\n", "a:Person = b:Person {cur=USD}\n"])
def testInvalidIdentityLinksAreRejected(text: str):
	with pytest.raises(FormatError):
		load(text)


def testCanonicalHandlesRewriteSubjectsReferencesCollectionsRolesAndContext():
	log = state("""a:Person
b:Person
x:Person
c:Scenario
d:Scenario
b.Name Alias
x.Owner b
x.Friends [a, b]
x knows b
x.Review.Included true {ctx=d}
a = b
c = d
""")
	assert _subjectValues(log, "Name") == [("a", "Alias")]
	assert _subjectValues(log, "Owner") == [("x", {"ref": "a"})]
	assert _subjectValues(log, "Friends") == [("x", {"set": [{"ref": "a"}]})]
	assert next(claim for claim in log.claims if "rel" in claim)["roles"] == {"Subject": "x", "Object": "a"}
	assert next(claim for claim in log.claims if claim.get("p") == "Review.Included")["ctx"] == "c"
	assert [claim["same"] for claim in log.claims if "same" in claim] == [["a", "b"], ["c", "d"]]


def testGroupCanonicalUsesTheFirstHandlesExistingGroup():
	log = state("a:Person = b:Person\nc:Person = d:Person\nb = d\nd.Name CanonicalA\n")
	assert _subjectValues(log, "Name") == [("a", "CanonicalA")]


def testCanonicalTypeIsRefinedBeforeAttributeLookup():
	log = state("a:Party = b:Person\nb.Name Person\n")
	assert log.instances["a"]["type"] == "A/Person"
	assert _subjectValues(log, "Name") == [("a", "Person")]


def testAliasSlotsSupersedeAndConflictAfterLinkApplication():
	log = state("a:Person\nb:Person\na.Name Old {src=one}\nb.Name New {src=one}\na.Name Other {src=two}\na = b\n")
	assert _subjectValues(log, "Name") == [("a", "New"), ("a", "Other")]
	assert all(claim.get("conflict") for claim in log.claims if claim.get("p") == "Name")


def testRetractionOfIdentityLinkSplitsGroupsAndDoesNotRetractOtherFacts():
	log = state("a:Person = b:Person {src=curator, by=one}\nb.Name B\n- b = a {src=curator, by=one}\n")
	assert _subjectValues(log, "Name") == [("b", "B")]
	assert not any("same" in claim for claim in log.claims)
	log = state("a:Person = b:Person {src=curator, by=one}\nb.Name B\n- a = b {src=curator, by=two}\n")
	assert _subjectValues(log, "Name") == [("a", "B")]


@pytest.mark.parametrize("links", ["a:Person = b:Person\na != b\n", "a:Person != b:Person\na = b\n", "a:Person = b:Person\nb = a\n", "a:Person = b:Party\nb = c:Organisation\n", "a:Person = b:Person\nc:Person = d:Person\nc = a\nb = d\n"])
def testIdentityConflictsFailStrictlyWithoutMutatingTheLog(links: str):
	log = load(links)
	before = deepcopy(log)
	with pytest.raises(FormatError, match="identity"):
		reconcileObservations(ONTOLOGY, log)
	assert log == before


def testLenientDistinctWinsAndCanonicalChoiceDoesNotChange():
	log = state("a:Person = b:Person\na != b\nb.Name B\n", "lenient")
	assert _subjectValues(log, "Name") == [("b", "B")]
	assert any(item.level == "warning" and item.code == "identity" for item in log.diagnostics)
	log = state("b:Person = a:Person\na = b\na.Name B\n", "lenient")
	assert _subjectValues(log, "Name") == [("b", "B")]
	assert [claim["same"] for claim in log.claims if "same" in claim] == [["b", "a"]]
	text = printObservationsState(ONTOLOGY, log)
	assert formatObservations(ONTOLOGY, Source("t", text), mode="lenient") == text


@pytest.mark.parametrize("form", ["log", "state"])
def testIdentityNormalFormsAndJsonRemainStable(form: str):
	text = "@obs A\nb:Person\na:Person\nx:Person\nb.Name B\nx.Owner b\na = b {src=curator}\n"
	printed = formatObservations(ONTOLOGY, Source("t", text), form)
	assert formatObservations(ONTOLOGY, Source("t", printed), form) == printed
	log = loadObservations(ONTOLOGY, Source("t", printed))
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)


@pytest.mark.parametrize("change", [
	lambda data: data["claims"][0].update(s="a"),
	lambda data: data["claims"][0].update(same=["a"]),
	lambda data: data["claims"][0].update(same=["a", "missing"]),
	lambda data: data["claims"][0].update(same=["a", "a"]),
	lambda data: data["claims"][0].update(distinct=["a", "b"]),
	lambda data: data["instances"]["a"].update(implicit=False),
])
def testMalformedIdentityJsonIsRejected(change):
	data = observationsToJson(load("a:Person = b:Person\n"))
	change(data)
	with pytest.raises(FormatError):
		observationsFromJson(ONTOLOGY, data)


def testUnknownRunModeIsRejected():
	with pytest.raises(ValueError):
		reconcileObservations(ONTOLOGY, load(""), "guess")


@pytest.mark.parametrize("fact", ["", "d.Name CanonicalA\n"])
def testStatePreservesGroupJoinOrderAndCanonicalHandle(fact: str):
	log = load("a:Person = b:Person\nc:Person = d:Person\nb = d\n" + fact)
	resolved = reconcileObservations(ONTOLOGY, log)
	assert _subjectValues(resolved, "Name") == ([("a", "CanonicalA")] if fact else [])
	printed = printObservationsState(ONTOLOGY, resolved)
	loaded = loadObservations(ONTOLOGY, Source("t", printed))
	assert [claim["same"] for claim in loaded.claims if "same" in claim] == [["a", "b"], ["c", "d"], ["b", "d"]]
	assert _subjectValues(reconcileObservations(ONTOLOGY, loaded), "Name") == _subjectValues(resolved, "Name")
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed
	text = printObservationsLog(ONTOLOGY, log)
	assert _subjectValues(reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", text))), "Name") == _subjectValues(resolved, "Name")


def testStateIdentityOrderUsesInstantsThenOrdinalsAndKeepsMetadata():
	log = load("""a:Person = b:Person {src=first, at=2026-01-01T01:00:00+01:00, by=one}
c:Person = d:Person {src=second, at=2026-01-01T00:00:00Z, by=two}
b = d {src=third, at=2026-01-02, conf=0.9}
e:Person != a {src=distinct, at=2025-12-31}
d.Name CanonicalA
""")
	resolved = reconcileObservations(ONTOLOGY, log)
	printed = printObservationsState(ONTOLOGY, resolved)
	loaded = loadObservations(ONTOLOGY, Source("t", printed))
	links = [claim for claim in loaded.claims if "same" in claim or "distinct" in claim]
	assert [claim.get("same", claim.get("distinct")) for claim in links] == [["a", "e"], ["a", "b"], ["c", "d"], ["b", "d"]]
	assert [claim["src"] for claim in links] == ["distinct", "first", "second", "third"]
	assert links[1]["by"] == "one" and links[2]["by"] == "two" and links[3]["conf"] == 0.9
	assert _subjectValues(reconcileObservations(ONTOLOGY, loaded), "Name") == [("a", "CanonicalA")]
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


# EOF
