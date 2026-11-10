"""Module: observations coverage tests — view selection and per-instance coverage."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import pytest

from onto import FormatError, Source, loadObservations, loadOntology, observationsCoverage

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

ONTOLOGY = loadOntology([Source("coverage.onto", """@ontology A
Name =
  Given Text
  Family Text
Party
  Code Text
Person < Party
  Name Name
  Email Text
  Age Integer
  * Tags Text
Employee < Person
  Title Text
Scenario
Assessment of Person {ctx=Scenario}
  Included Boolean
Investor of Person
  Rating Low|High
Household
Household -has/memberOf-> Person
  Role Adult|Child
Person -knows-> Person
Review(Person, Household)
  Note Text
ReviewFacet of Review
  Checked Boolean
@view Fields
  Person.Email
  Person.Age
  Person.Tags
@view Names
  Person.Name
@view Core
  Person
@view Facets
  Person[Investor]
@view Contexts
  Person[Assessment]
@view OneFacetAttribute
  Person.Investor.Rating
@view AllFacets
  Person[*]
@view Links
  Household.has
@view ExactLink
  Household.has.Person
@view InverseLink
  Person.memberOf
@view Association
  Review[ReviewFacet]
@view Nested
  Fields
  Names
  Person.Email
""")])


def load(text: str):
	return loadObservations(ONTOLOGY, Source("test.obs", "@obs A\n" + text))


def report(text: str, view: str = "Fields") -> dict:
	return {(item.path, item.subject, item.ctx): item for item in observationsCoverage(ONTOLOGY, load(text), view)}

# -----------------------------------------------------------------------------
#
# COVERAGE
#
# -----------------------------------------------------------------------------


def testStatusesAndMissingSlotsAreReportedPerInstance():
	items = report("p:Person\n  Email p@example.org\n  Age ?\n  Tags []\nq:Person\n  Email null\n")
	assert items[("A/Person.Email", "p", None)].statuses == ("supplied",)
	assert items[("A/Person.Age", "p", None)].statuses == ("unknown",)
	assert items[("A/Person.Tags", "p", None)].statuses == ("absent",)
	assert items[("A/Person.Email", "q", None)].statuses == ("absent",)
	assert items[("A/Person.Age", "q", None)].statuses == ("missing",)
	assert items[("A/Person", "p", None)].statuses == ("supplied",)
	assert not any(".Code" in path for path, _, _ in items)


def testConflictingSourcesRemainVisibleWithoutChoosingOne():
	items = report("p:Person\np.Email x {src=a}\np.Email null {src=b}\n")
	item = items[("A/Person.Email", "p", None)]
	assert item.statuses == ("supplied", "absent")
	assert item.conflict is True


def testSupersededAndRetractedClaimsDoNotCount():
	items = report("p:Person\np.Email ?\np.Email Known\np.Age 21\n- p.Age\n")
	assert items[("A/Person.Email", "p", None)].statuses == ("supplied",)
	assert items[("A/Person.Age", "p", None)].statuses == ("missing",)


def testPartialCollectionsDoNotPretendToBeCompleteOrEmpty():
	items = report('p:Person\np.Tags ["a", ...]\nq:Person\nq.Tags [...]\n')
	assert items[("A/Person.Tags", "p", None)].statuses == ("supplied",)
	assert items[("A/Person.Tags", "p", None)].partial is True
	assert items[("A/Person.Tags", "q", None)].statuses == ("unknown",)
	assert items[("A/Person.Tags", "q", None)].partial is True


def testStructuredSelectionsReportLeafFields():
	items = report("p:Person\np.Name.Given P\n", "Names")
	assert items[("A/Person.Name.Given", "p", None)].statuses == ("supplied",)
	assert items[("A/Person.Name.Family", "p", None)].statuses == ("missing",)
	assert ("A/Person.Name", "p", None) not in items
	for text, status in (("?", "unknown"), ("null", "absent")):
		items = report(f"p:Person\np.Name {text}\n", "Names")
		assert items[("A/Person.Name.Given", "p", None)].statuses == (status,)
		assert items[("A/Person.Name.Family", "p", None)].statuses == (status,)


def testCoreIncludesInheritedAttributesButNotSubclassExtrasOrFacets():
	items = report("p:Employee\np.Code X\np.Title Employee\n", "Core")
	assert items[("A/Person.Code", "p", None)].statuses == ("supplied",)
	assert ("A/Person.Title", "p", None) not in items
	assert not any("Investor" in path for path, _, _ in items)


def testFacetApplicabilityCanBeImpliedByAnAttributeClaim():
	items = report("p:Person\np.Investor.Rating ?\n", "OneFacetAttribute")
	assert items[("A/Person[Investor]", "p", None)].statuses == ("supplied",)
	assert items[("A/Person.Investor.Rating", "p", None)].statuses == ("unknown",)
	items = report("p:Person\n", "Facets")
	assert items[("A/Person[Investor]", "p", None)].statuses == ("missing",)
	items = report("p:Person\np.Investor.Rating Low {src=a}\np.Investor.Rating High {src=b}\n", "OneFacetAttribute")
	assert items[("A/Person.Investor.Rating", "p", None)].conflict is True
	assert items[("A/Person[Investor]", "p", None)].conflict is False


def testContextualSlotsUseSeparateKnownContexts():
	items = report("p:Person\na:Scenario\nb:Scenario\np.Assessment.Included true {ctx=a}\n", "Contexts")
	assert items[("A/Person.Assessment.Included", "p", "a")].statuses == ("supplied",)
	assert items[("A/Person.Assessment.Included", "p", "b")].statuses == ("missing",)
	assert items[("A/Person[Assessment]", "p", "a")].statuses == ("supplied",)
	assert items[("A/Scenario", "a", None)].statuses == ("supplied",)
	items = report("p:Person\n", "Contexts")
	assert items[("A/Person.Assessment.Included", "p", None)].statuses == ("missing",)


def testWildcardFacetsAndNestedViewsAreDeduplicated():
	items = report("p:Person\n", "AllFacets")
	assert ("A/Person[Assessment]", "p", None) in items
	assert ("A/Person[Investor]", "p", None) in items
	log = load("p:Person\n")
	rows = observationsCoverage(ONTOLOGY, log, "Nested")
	assert len(rows) == len({(item.path, item.subject, item.ctx) for item in rows})
	assert ("A/Person.Name.Given", "p", None) in {(item.path, item.subject, item.ctx) for item in rows}


@pytest.mark.parametrize("view", ["Links", "ExactLink", "InverseLink"])
def testBinarySelectionsIncludeAnonymousExistenceAndParticipantIdentity(view: str):
	items = report("h:Household\nh has p:Person\n", view)
	assert items[("A/Household.has.A/Person", None, None)].statuses == ("supplied",)
	assert items[("A/Person", "p", None)].statuses == ("missing",)
	assert items[("A/Household", "h", None)].statuses == ("supplied",)
	assert not any("Person.Email" in path for path, _, _ in items)
	assert items[("A/Household.has.A/Person.Role", None, None)].statuses == ("missing",)


def testNamedBinaryAttributesAndAssociationsAreCovered():
	items = report("h:Household\np:Person\nr: h has p\nr.Role Adult\n", "Links")
	assert items[("A/Household.has.A/Person.Role", "r", None)].statuses == ("supplied",)
	items = report("h:Household\np:Person\nr:Review\nr.Household h\nr.Person p\nr.ReviewFacet.Checked true\n", "Association")
	assert items[("A/Review.Person", "r", None)].statuses == ("supplied",)
	assert items[("A/Review.Note", "r", None)].statuses == ("missing",)
	assert items[("A/Review[ReviewFacet]", "r", None)].statuses == ("supplied",)
	assert items[("A/Review.ReviewFacet.Checked", "r", None)].statuses == ("supplied",)


def testEmptyDocumentsReportMissingRequestsWithoutInventingHandles():
	items = report("")
	assert items and all(item.statuses == ("missing",) and item.subject is None for item in items.values())


def testDeletedInstancesAndIdentityAliasesDoNotBecomePhantomMissingSubjects():
	items = report("p:Person\n- p\n")
	assert not any(subject == "p" for _, subject, _ in items)
	items = report("a:Person\nb:Person\nb.Email Known\na = b\n")
	assert items[("A/Person.Email", "a", None)].statuses == ("supplied",)
	assert not any(subject == "b" for _, subject, _ in items)


def testUnknownViewIsAnErrorAndCoverageIsPureAndDeterministic():
	log = load("p:Person\n")
	before = deepcopy(log)
	with pytest.raises(FormatError, match="Unknown view"):
		observationsCoverage(ONTOLOGY, log, "Person")
	with pytest.raises(FormatError, match="Unknown view"):
		observationsCoverage(ONTOLOGY, log, "Missing")
	assert observationsCoverage(ONTOLOGY, log, "Fields") == observationsCoverage(ONTOLOGY, log, "A/Fields")
	assert log == before


def testRecursiveStructureSelectionTerminates():
	ontology = loadOntology([Source("t", "@ontology A\nNode =\n  Value Text\n  Next Node\nP\n  Data Node\n@view V\n  P\n")])
	log = loadObservations(ontology, Source("t", "@obs A\np:P\np.Data.Value Root\np.Data.Next.Value Child\n"))
	rows = observationsCoverage(ontology, log, "V")
	assert len(rows) == 3
	assert any(item.path == "A/P.Data.Value" and item.statuses == ("supplied",) for item in rows)
	assert any(item.path == "A/P.Data.Next" and item.statuses == ("supplied",) for item in rows)


def testCompleteSpecExamplesProducePerPersonCoverage():
	root = Path(__file__).parent.parent / "docs/specs"
	ontologyText = re.findall(r"```text\n(.*?)```", (root / "spec-01-ontology.md").read_text(), re.S)[0]
	observationText = re.findall(r"```text\n(.*?)```", (root / "spec-02-observations.md").read_text(), re.S)[0]
	ontology = loadOntology([Source("finance.onto", ontologyText)])
	log = loadObservations(ontology, Source("statement.obs", observationText))
	items = {(item.path, item.subject, item.ctx): item for item in observationsCoverage(ontology, log, "PortfolioReview")}
	assert items[("Finance/Person.DateOfBirth", "p1", None)].statuses == ("supplied",)
	assert items[("Finance/Person.DateOfBirth", "p1", None)].conflict is False
	assert items[("Finance/Person.DateOfBirth", "p2", None)].statuses == ("missing",)
	assert items[("Finance/Person.Name.Surname", "p1", None)].statuses == ("supplied",)
	assert items[("Finance/Trade.Counterparty", "t1", None)].statuses == ("unknown",)


# EOF
