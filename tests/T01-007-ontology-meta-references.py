"""Module: meta reference tests — observations that refer to the `Meta` records of their ontology are resolved."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology
from onto.meta import metaDeclarations, metaHandles, metaPaths, resolvesMetaPath
from onto.ontology import Model

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
Contact of Person
  Phone Text
Question
  Code Text
  Field Meta/Path
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
	"Person", "Person.Email", "Address", "Address.Street", "Person.Home.Street", "Person.Contact.Phone",
	"Household.hasMember.Person", "Household.hasMember.Person.Role", "Text",
])
def testPathsResolve(value: str):
	observe(f"q:Question\n  Field {value}\n")


@pytest.mark.parametrize("value", ["Persons", "Person.Mail", "Address.Town", "Person.Contact.Fax", "Household.hasMember.Party"])
def testUnknownPathsAreErrors(value: str):
	assert codes(f"q:Question\n  Field {value}\n") == ["meta.path"]


def testLenientModeKeepsTheDiagnostics():
	observations = observe("q:Question\nq populates Person__Mail:Meta/Attribute\n", "lenient")
	assert [item.code for item in observations.diagnostics] == ["meta.unresolved"]


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
