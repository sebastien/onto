"""Module: meta reference tests — observations that refer to the `Meta` records of their ontology are resolved."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology, observationsFromJson, observationsToJson, reconcileObservations
from onto.meta import metaDeclarations, metaHandles, metaObservations, metaPaths, resolvesMetaPath
from onto.ontology import Model
from tests.helpers import schemaValidator

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

BODY = """\
Address =
  Street Text
Person
  Email Text
  Home Address
Household
Household -hasMember-> Person
  Role Text
Person -knows-> Person
Contact of Person
  Phone Text
Question
  Code Text
  Field Meta/Path
  * Fields Meta/Path
Question -populates-> Meta/Attribute
Question -isAbout-> Meta/Concept
"""


def ontology():
	"""The fixture ontology with its generated `Meta` declarations."""
	# NOTE: `metaDeclarations` reads only the namespace and header of the ontology it declares `Meta` for.
	meta = metaDeclarations(loadOntology([Source("header.onto", "@ontology A\n")]))
	return loadOntology([Source("main.onto", "@ontology A\n" + BODY), Source("meta.onto", meta)])


def observe(text: str, mode: str = "strict"):
	return loadObservations(ontology(), Source("q.obs", "@obs A\n" + text), mode)


def codes(text: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		observe(text)
	return [item.code for item in raised.value.diagnostics]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testGeneratedRecordsResolve():
	observe("q:Question\n  Code Email\nq populates Person__Email:Meta/Attribute\nq isAbout Person:Meta/Concept\n")


def testUnknownRecordsAreErrors():
	assert codes("q:Question\nq populates Person__Mail:Meta/Attribute\n") == ["meta.unresolved"]
	# NOTE: A record exists under another type only.
	assert codes("q:Question\nq isAbout Person__Email:Meta/Concept\n") == ["meta.unresolved"]


def testErrorsAreLocated():
	with pytest.raises(FormatError) as raised:
		observe("q:Question\n  Code X\nq populates Person__Mail:Meta/Attribute\n")
	[item] = raised.value.diagnostics
	assert item.loc and item.loc.line == 4


@pytest.mark.parametrize("value", [
	"Person", "Person.Email", "Address", "Address.Street", "A/Address.Street", "Person.Home.Street", "Person.Contact.Phone",
	"Household.hasMember.Person", "Household.hasMember.Person.Role", "A/Household.hasMember.A/Person.Role",
	"Person.knows.Person", "Text",
])
def testPathsResolve(value: str):
	observe(f"q:Question\n  Field {value}\n")


@pytest.mark.parametrize("value", ["Persons", "Person.Mail", "Address.Town", "Person.Contact.Fax", "Household.hasMember.Party"])
def testUnknownPathsAreErrors(value: str):
	assert codes(f"q:Question\n  Field {value}\n") == ["meta.path"]


def testCollectionPathsAreCheckedMemberByMember():
	observe("q:Question\nq.Fields [A/Address.Street, Person.Email, ...]\n")
	with pytest.raises(FormatError) as raised:
		observe('q:Question\nq.Fields [Person.Email, "Person.Home[False].Street", "Person.Contact[False].Phone"]\n')
	assert len(raised.value.diagnostics) == 2
	assert all(item.code == "meta.path" and item.loc.line == 3 for item in raised.value.diagnostics)


def testCollidingPathsGenerateDistinctMetaRecordsAndLinks():
	meta = metaDeclarations(ontology())
	source = Source("main.onto", "@ontology A\nA_B\n  Choice One|Two\nA/B\n  Choice Red|Blue\nD/X = Text\nD_X = Integer\n")
	model = loadOntology([source, Source("meta.onto", meta)])
	text = metaObservations(model)
	assert text == metaObservations(loadOntology([Source("meta.onto", meta), source]))
	reconciled = reconcileObservations(model, loadObservations(model, Source("meta.obs", text)))
	paths = {claim["s"]: claim["v"] for claim in reconciled.claims if claim.get("p") == "Path"}
	assert {"A/B", "A_B", "D/X", "D_X"} <= set(paths.values())
	for path in ("A/B.Choice", "A_B.Choice"):
		assert {reconciled.instances[handle]["type"] for handle, value in paths.items() if value == path} == {
			"A/Meta/Attribute", "A/Meta/Dimension",
		}
	links = {(paths[claim["roles"]["Concept"]], paths[claim["roles"]["Attribute"]])
		for claim in reconciled.claims if ".hasAttribute." in claim.get("rel", "")}
	assert {("A/B", "A/B.Choice"), ("A_B", "A_B.Choice")} <= links


def testLenientModeHoldsEveryInvalidMetaReferenceWithoutDroppingOtherClaims():
	observations = observe(
		"q:Question\n  Code Person__Mail\n  Field Person.Email\n- q.Field Person.Mail\n"
		"q.Fields [Person.Email, Person.Mail]\nq populates Person__Mail:Meta/Attribute\n"
		"q populates Person__Mail\nq populates Person__Email:Meta/Attribute\n", "lenient")
	assert sorted(item.code for item in observations.diagnostics) == ["meta.path", "meta.path", "meta.unresolved", "meta.unresolved"]
	assert all(item.level == "warning" for item in observations.diagnostics)
	assert [gap.n for gap in observations.gaps] == [4, 5, 6, 7]
	assert "Person__Mail" not in observations.instances
	assert observations.retractions == []
	assert [claim.get("v") for claim in observations.claims] == [None, "Person__Mail", "Person.Email", None]
	state = reconcileObservations(ontology(), observations, "lenient")
	assert state.claims == observations.claims and state.gaps == observations.gaps
	data = observationsToJson(observations)
	schemaValidator("observations").validate(data)
	assert observationsToJson(observationsFromJson(ontology(), data, mode="lenient")) == data


def testAnInvalidRegistryOnlyMetaDeclarationIsFatalInLenientMode():
	with pytest.raises(FormatError, match="meta.unresolved"):
		observe("@type Person__Mail Meta/Attribute\n", "lenient")


def testWithoutTheMetaDomainNothingIsChecked():
	loadObservations(
		loadOntology([Source("main.onto", "@ontology A\nPerson\nM/Attribute\nQ\nQ -populates-> M/Attribute\n")]),
		Source("q.obs", "@obs A\nq:Q\nq populates Nope:M/Attribute\n"),
	)


def testHelpersDescribeWhatMetaGenerates():
	model = Model(ontology())
	assert ("Person__Email", "Attribute") in metaHandles(model.ontology)
	assert "Household.hasMember.Person.Role" in metaPaths(model.ontology)
	assert resolvesMetaPath(model, "Address.Street") and not resolvesMetaPath(model, "Address.Town")


# EOF
