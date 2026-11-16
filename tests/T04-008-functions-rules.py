"""Module: rule tests — a derived attribute's `rule` naming a library function is checked when the library loads."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadOntology
from onto.functions import loadFunctions

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

LIBRARY = """\
@functions Rules
@use A as A

@fn Band Integer -> A/Band                      -- Band of a score
  2 => Low
  8 => High
"""


def ontology(attr: str = "~ Level Band <- Score {rule=Rules/Band}", uses: str = ""):
	return loadOntology([Source("a.onto", f"@ontology A\n{uses}Band = Low|High\nKind = Retail|Business\nAudit\n  Score Integer\n  Count Number\n  Kind Kind\n  {attr}\n")])


def library(attr: str = "~ Level Band <- Score {rule=Rules/Band}", uses: str = "", text: str = LIBRARY):
	return loadFunctions([ontology(attr, uses)], [Source("rules.fn", text)])


def errors(attr: str, text: str = LIBRARY) -> list[str]:
	with pytest.raises(FormatError) as raised:
		library(attr, text=text)
	return [item.message for item in raised.value.diagnostics if item.code == "rule"]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testARuleNamingALibraryFunctionIsChecked():
	library()


def testAnAliasOfTheLibraryResolves():
	library("~ Level Band <- Score {rule=R/Band}", "@use Rules as R\n")


def testNumbersAreInterchangeableAsInputs():
	library("~ Level Band <- Count {rule=Rules/Band}")


@pytest.mark.parametrize("attr, message", [
	("~ Level Band <- Score {rule=Rules/Bands}", "unknown function"),
	("~ Level Band <- Score, Count {rule=Rules/Band}", "has 2 inputs"),
	("~ Level Band <- Kind {rule=Rules/Band}", "input 1"),
	("~ Level Kind <- Score {rule=Rules/Band}", "result"),
])
def testMismatchesAreErrors(attr: str, message: str):
	[found] = errors(attr)
	assert message in found


def testIncompleteInputsAcceptMoreArguments():
	text = LIBRARY + "\n@fn Mix Integer, Number -> A/Band\n  1, 2 => Low\n"
	library("~ Level Band <- Score, ... {rule=Rules/Mix}", text=text)
	assert errors("~ Level Band <- Score, Count, Kind {rule=Rules/Mix}", text)


@pytest.mark.parametrize("rule", ["?", "x26", "Other/Band"])
def testOtherRulesAreNotChecked(rule: str):
	library(f"~ Level Band <- Score {{rule={rule}}}")


# EOF
