"""Module: keyed structure tests — elements of a multi-valued structure named by their `{key}` field (spec-01, spec-02)."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology, observationsFromJson, observationsToJson, printObservationsState, reconcileObservations
from tests.helpers import schemaValidator

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

BODY = """\
Use = Mobile|Home|Work
Place = Postal|...
Phone =
  1 Use Use {key}
  1 Number Text
  Note Text
Address =
  1 Place Place {key}
  Lines Text
Person
  * Phones Phone
  * Addresses Address
  Main Phone
Contact of Person
  * Phones Phone
"""


def ontology(body: str = BODY):
	return loadOntology([Source("main.onto", "@ontology A\n" + body)])


def observe(text: str, mode: str = "strict"):
	return loadObservations(ontology(), Source("c.obs", "@obs A\n@src a=one\n@src a\n" + text), mode)


def codes(text: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		observe(text)
	return [item.code for item in raised.value.diagnostics]


def state(text: str) -> dict[str, object]:
	reconciled = reconcileObservations(ontology(), observe(text))
	return {claim["p"]: claim["v"] for claim in reconciled.claims if "p" in claim}


# -----------------------------------------------------------------------------
#
# DECLARATIONS
#
# -----------------------------------------------------------------------------


def testKeyFieldsAreOneRequiredVocabularyPerStructure():
	assert not [item for item in ontology().diagnostics if item.code == "key"]
	for body in (BODY.replace("  1 Number Text", "  1 Number Text {key}"), BODY.replace("  1 Use Use {key}", "  Use Use {key}"),
		BODY.replace("  1 Place Place {key}", "  1 Place Text {key}")):
		with pytest.raises(FormatError) as raised:
			ontology(body)
		assert "key" in [item.code for item in raised.value.diagnostics]


def testMultiValuedStructuresWithoutKeysWarn():
	warnings = [item for item in ontology(BODY + "  * Others Other\nOther =\n  Text Text\n").diagnostics if item.code == "key"]
	assert len(warnings) == 1 and warnings[0].level == "warning" and "Others" in warnings[0].message
	acknowledged = ontology(BODY + "  * Others Other {check=unkeyed}\nOther =\n  Text Text\n").diagnostics
	assert not [item for item in acknowledged if item.code == "key"]


# -----------------------------------------------------------------------------
#
# OBSERVATIONS
#
# -----------------------------------------------------------------------------


def testElementsAreDistinctSlotsInLineAndRecordForms():
	text = "p1:Person\n  Phones[Mobile].Number 021\n  Phones[Home].Number 09\np1.Phones[Home].Note Evenings\np1.Addresses[Other].Lines \"1 Road\"\n"
	assert state(text) == {"Phones[Mobile].Number": "021", "Phones[Home].Number": "09", "Phones[Home].Note": "Evenings", "Addresses[Other].Lines": "1 Road"}
	printed = printObservationsState(ontology(), reconcileObservations(ontology(), observe(text)))
	assert "Phones[Mobile].Number 021" in printed


def testElementsRoundTripThroughJsonAndTheSchema():
	observations = observe("p1:Person\n  Phones[Mobile].Number 021\n")
	data = observationsToJson(observations)
	schemaValidator("observations").validate(data)
	assert observationsToJson(observationsFromJson(ontology(), data)) == data


@pytest.mark.parametrize("line", [
	"p1.Phones.Number 021",                # a keyed attribute needs its element
	"p1.Phones[Fax].Number 021",           # not a value of a closed key vocabulary
	"p1.Phones[Mobile].Use Mobile",        # the key field is implied by the key
	"p1.Main[Mobile].Number 021",          # a single structure has no elements
	"p1.Contact[Mobile].Phones[Home].Number 021",  # a facet name cannot carry an element key
])
def testMisnamedElementsAreRejected(line: str):
	assert codes("p1:Person\n" + line + "\n") == ["key"]


def testRetractingOneElementOrAll():
	text = "p1:Person\n  Phones[Mobile].Number 021\n  Phones[Mobile].Note Work\n  Phones[Home].Number 09\n"
	assert state(text + "- p1.Phones[Mobile]\n") == {"Phones[Home].Number": "09"}
	assert state(text + "- p1.Phones\n") == {}


# EOF
