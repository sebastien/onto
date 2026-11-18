"""Module: exclusive group tests — `{one=G}` attributes and fields hold at most one value of the group."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology, observationsFromJson, observationsToJson, reconcileObservations
from onto.ontology import Operator

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

BODY = """\
Benefit =
  Amount Number {one=Value}
  PeriodicAmount Number {one=Value}
  Basis Text
Cover
  Benefit Benefit
  Rate Number {one=Price}
  Premium Number {one=Price}
"""


def load(body: str = BODY):
	return loadOntology([Source("main.onto", "@ontology A\n" + body)])


def codes(body: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		load(body)
	return [item.code for item in raised.value.diagnostics]


def observe(text: str, mode: str = "strict"):
	return loadObservations(load(), Source("c.obs", "@obs A\n" + text), mode)


def observeCodes(text: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		observe(text)
	return [item.code for item in raised.value.diagnostics]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testGroupsAreKeptInNormalForm():
	text = Operator(load()).print()
	assert "Amount Number {one=Value}" in text and "Rate Number {one=Price}" in text


@pytest.mark.parametrize("body, code", [
	("P\n  A Number {one=G}\n", "one"),
	("P\n  1 A Number {one=G}\n  B Number {one=G}\n", "one"),
	("P\n  A Number {one=G}\n  ~ B Number <- A {one=G}\n", "one"),
	("P\n  A Number {one=1}\n  B Number {one=1}\n", "annotation"),
	("P {one=G}\n  A Number\n", "annotation"),
])
def testInvalidGroupsAreErrors(body: str, code: str):
	assert code in codes(body)


def testOneValueOfAGroupIsAccepted():
	observe("c:Cover\n  Benefit.Amount 100\n  Benefit.Basis Agreed\n  Rate 2\n")


@pytest.mark.parametrize("text", [
	"c:Cover\n  Benefit.Amount 100\n  Benefit.PeriodicAmount 10\n",
	"c:Cover\n  Rate 2\n  Premium 30\n",
	"@src a=feed b=feed\nc:Cover\n  Rate 2 {src=a}\n  Premium 30 {src=b}\n",
])
def testTwoValuesOfAGroupAreErrors(text: str):
	assert observeCodes(text) == ["one"]


@pytest.mark.parametrize("text", [
	"c:Cover\n  Benefit.Amount 100\n  Benefit.PeriodicAmount null\n",
	"c:Cover\n  Rate 2\n  Premium ?\n",
	"c:Cover\n  Rate 2 {valid=2020-01-01..2021-12-31}\n  Premium 30 {valid=2022-01-01..}\n",
	"@src a=feed\n@src b=other\nc:Cover\n  Rate 2 {src=a}\n  Premium 30 {src=b}\n",
	"c:Cover\n  Rate 2\nd:Cover\n  Premium 30\n",
])
def testAbsenceUnknownsOtherPeriodsSourcesAndSubjectsAreAccepted(text: str):
	observe(text)


def testLenientModeKeepsEarlierExclusiveValuesAndHoldsAllClashes():
	observations = observe("c:Cover\n  Rate 2\n  Premium 30\n  Premium 40\n  Benefit.Amount 100\n", "lenient")
	assert [item.code for item in observations.diagnostics] == ["one", "one"]
	assert [gap.n for gap in observations.gaps] == [3, 4]
	state = reconcileObservations(load(), observations, "lenient")
	assert [claim.get("p") for claim in state.claims] == [None, "Rate", "Benefit.Amount"]
	data = observationsToJson(state)
	assert observationsToJson(observationsFromJson(load(), data, mode="lenient")) == data


# EOF
