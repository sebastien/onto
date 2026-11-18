"""Module: conditional facet tests — `F of E {when=Attr:Value}` applies only to subjects whose `Attr` is `Value`."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology, observationsFromJson, observationsToJson, ontologyFromJson, ontologyToJson, reconcileObservations
from onto.ontology import Operator

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

BODY = """\
Kind = Goals|Household
Section
  Kind Kind {key}
  Signed Boolean
  * Tags Text
  ~ Label Text <- Kind {rule=?}
GoalsSection of Section {when=Kind:Goals}
  Notes Text
HouseholdSection of Section {when=Kind:Household}
  Size Integer
SignedSection of Section {when=Signed:true}
"""


def load(body: str = BODY):
	return loadOntology([Source("main.onto", "@ontology A\n" + body)])


def codes(body: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		load(body)
	return [item.code for item in raised.value.diagnostics]


def observe(text: str, mode: str = "strict"):
	return loadObservations(load(), Source("c.obs", "@obs A\n@src a=one\n@src b=two\n@src a\n" + text), mode)


def observeCodes(text: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		observe(text)
	return [item.code for item in raised.value.diagnostics]


# -----------------------------------------------------------------------------
#
# DECLARATIONS
#
# -----------------------------------------------------------------------------


def testConditionsAreKeptInNormalFormAndJson():
	ontology = load()
	text = Operator(ontology).print()
	assert "GoalsSection of Section {when=Kind:Goals}" in text
	assert ontologyToJson(ontologyFromJson(ontologyToJson(ontology))) == ontologyToJson(ontology)


@pytest.mark.parametrize("annotation", [
	"when=Missing:Goals", "when=Kind:Other", "when=Kind", "when=Signed:yes", "when=Tags:x", "when=Label:x",
	"when=GoalsSection.Notes:x", "when",
])
def testInvalidConditionsAreRejected(annotation: str):
	assert "annotation" in codes(BODY + f"Other of Section {{{annotation}}}\n")


def testConditionsApplyToFacetsOnly():
	assert "annotation" in codes(BODY + "Thing {when=Kind:Goals}\n")


# -----------------------------------------------------------------------------
#
# OBSERVATIONS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
	"s1:Section[GoalsSection]\n  Kind Goals\n",
	"s1:Section\n  Kind Goals\n  GoalsSection.Notes Plan\n",
	"s1:Section[GoalsSection]\n",
	"s1:Section[GoalsSection]\n  Kind ?\n",
	"s1:Section[SignedSection]\n  Signed true\n",
	"s1:Section[GoalsSection]\n@src b\ns1.Kind Household\n",
	"s1:Section\ns1.GoalsSection.Notes Plan {valid=2020-01-01..2020-12-31}\ns1.Kind Household {valid=2021-01-01..}\n",
])
def testFacetsAgreeingWithTheirConditionOrNotContradictedAreAccepted(text: str):
	assert observe(text).claims


@pytest.mark.parametrize("text", [
	"s1:Section[GoalsSection]\n  Kind Household\n",
	"s1:Section\n  Kind Household\n  GoalsSection.Notes Plan\n",
	"s1:Section[SignedSection]\n  Signed false\n",
	"@src same=one\ns1:Section[GoalsSection] {src=a}\n  Kind Household {src=same}\n",
])
def testAFacetContradictingItsConditionFromOneSourceIsAnError(text: str):
	assert observeCodes(text) == ["when"]


def testLenientModeHoldsContradictoryFacetStatementsButKeepsTheDiscriminator():
	observations = observe("s1:Section[GoalsSection]\n  Kind Household\n  GoalsSection.Notes Plan\n  HouseholdSection.Size 5\n", mode="lenient")
	assert [item.code for item in observations.diagnostics] == ["when", "when"]
	assert [gap.n for gap in observations.gaps] == [1, 3]
	state = reconcileObservations(load(), observations, "lenient")
	assert [claim.get("p") for claim in state.claims] == ["Kind", "HouseholdSection.Size"]
	data = observationsToJson(state)
	assert observationsToJson(observationsFromJson(load(), data, mode="lenient")) == data
