"""Module: history tests — `{history}` attributes generate their change concept and relation."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology, ontologyFromJson, ontologyToJson
from onto.meta import metaObservations
from onto.ontology import Model, Operator
from tests.helpers import schemaValidator

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

BODY = """\
Policy/Status = Proposed|InForce|Lapsed
Policy {layer=Holding}
  Status Policy/Status {history}                -- Current status
Application
Cover of Application
  Stage Text {history}
"""


def load(body: str = BODY, header: str = ""):
	return loadOntology([Source("main.onto", f"@ontology A{header}\n{body}")])


def codes(body: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		load(body)
	return [item.code for item in raised.value.diagnostics]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testHistoryGeneratesAChangeConceptAndRelation():
	model = Model(load())
	change = model.get("A/Policy/StatusChange")
	assert change and change.kind == "entity" and change.generated
	assert [(attr.name, attr.card) for attr in change.attrs] == [("Status", "1"), ("OccurredDate", "?"), ("Reason", "?")]
	assert change.attrs[0].type.path == "A/Policy/Status"
	assert ("layer", "Holding") in change.ann
	relation = model.get("A/Policy.hasChange.A/Policy/StatusChange")
	assert relation and relation.arrow.inverse == "isChangeOf" and relation.arrow.counts == "1:*"


def testAFacetHistoryHangsOffItsSubject():
	model = Model(load())
	assert model.get("A/Cover/StageChange")
	assert model.get("A/Application.hasChange.A/Cover/StageChange")


def testNormalFormAndJsonKeepOnlyTheFlag():
	ontology = load()
	text = Operator(ontology).print()
	assert "Status Policy/Status {history}" in text and "StatusChange" not in text
	data = ontologyToJson(ontology)
	assert all("Change" not in decl["path"] for decl in data["decls"])
	schemaValidator("ontology").validate(data)
	again = ontologyFromJson(data)
	assert Model(again).get("A/Policy/StatusChange") and ontologyToJson(again) == data


def testObservationsAndMetaSeeTheGeneratedConcepts():
	ontology = load()
	loadObservations(ontology, Source("p.obs", "@obs A\np:Policy\n  Status InForce\np hasChange c:Policy/StatusChange\nc\n  Status InForce\n  OccurredDate 2026-01-02\n"))
	assert "Policy_StatusChange:Meta/Concept" in metaObservations(ontology)


def testDeclaringTheGeneratedConceptIsAnError():
	assert "collision" in codes(BODY + "Policy/StatusChange\n")


def testDeclaringTheGeneratedRelationIsAnError():
	assert "collision" in codes(BODY + "Policy -hasChange-> Policy/StatusChange\n")


@pytest.mark.parametrize("name", ["OccurredDate", "Reason"])
def testHistoryAttributeCannotCollideWithGeneratedFields(name: str):
	assert "collision" in codes(f"Person\n  {name} Text {{history}}\n")


def testGeneratedHistoryRelationUsesDistinctRolesWhenEndNamesMatch():
	model = Model(load("StatusChange\n  Status Text {history}\n"))
	relation = model.get("A/StatusChange.hasChange.A/StatusChange/StatusChange")
	assert [role.role for role in relation.participants] == ["Subject", "Object"]


def testGeneratedHistoryPreservesQualifiersAndVocabularyFlags():
	model = Model(load(
		"Units = Metre|Inch\nAsset\n  Length Number {unit=?:Units, history}\n"
		"  Stage Z/B|A {ordered, hierarchical, history}\n"
	))
	length = model.get("A/Asset/LengthChange").attrs[0]
	assert model.resolveType(length.type, length.ann).qualifierVocabularies == {"unit": "A/Units"}
	stage = model.get("A/Asset/StageChange").attrs[0]
	resolved = model.resolveType(stage.type, stage.ann)
	assert resolved.ordered and resolved.hierarchical and resolved.values == ["Z", "Z/B", "A"]


@pytest.mark.parametrize("attr", ["* Tags Text {history}", "~ Age Number <- ... {history}"])
def testMultiValuedOrDerivedAttributesHaveNoHistory(attr: str):
	assert "history" in codes(f"Person\n  {attr}\n")


def testHistoryIsAFlagOnAttributes():
	assert "annotation" in codes("Person\n  Status Text {history=yes}\n")
	assert "annotation" in codes("Person {history}\n")


@pytest.mark.parametrize("body", [
	"Detail =\n  Status Text {history}\n",
	"Person\nCompany\nPerson -worksAt-> Company\n  Status Text {history}\n",
])
def testHistoryRequiresAnEntityFacetOrAssociationOwner(body: str):
	assert "history" in codes(body)


def testGeneratedDeclarationsRespectLayering():
	load("@domain Party\n@domain Lending\nParty/Person\nLending/Loan\n  Status Text {history}\n  Borrower Party/Person\n", " layering=declared")


# EOF
