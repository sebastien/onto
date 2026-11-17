"""Source references: `ref(S, Key)` in a mapping names a source instance by its key (spec-04 Expressions)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingReverse, mappingToJson, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SOURCE = loadOntology([Source("s.onto", """@ontology S
Client
  Id Integer {key}
Group
  Id Integer {key}
Record
  Id Integer {key}
Tag
  Record Record
  Table Text
  ForeignId Integer
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Party
Household
Note
Note -concerns/hasNote-> Party
Note -concerns/hasNote-> Household
""")])
MAPPING = """@mapping S -> T

Client -> Party

Group -> Household

Record -> Note

Tag -> Note {into=Record}
  concerns <- ref(Client, ForeignId) {when=Table:ClientId}
  concerns <- ref(Group, ForeignId) {when=Table:GroupId}
"""
STATE = "Client_9:Client\nGroup_9:Group\nRecord_1:Record\n"


def mapped(fields: str, text: str = MAPPING, state: str = STATE):
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-18\n@scope s\n@src f=fixture\n@src f\n" + state + "Tag_1:Tag\n  Record Record_1\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-18"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


def concerns(log) -> list[tuple[str, str]]:
	return sorted((claim["rel"], claim["roles"].get("object") or sorted(claim["roles"].values())[0]) for claim in log["claims"] if ".concerns." in claim.get("rel", ""))


# -----------------------------------------------------------------------------
#
# EXECUTION
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(("fields", "relation", "target"), [
	("  Table ClientId\n  ForeignId 9\n", "T/Note.concerns.T/Party", "Party_s_2FClient_2F9"),
	("  Table GroupId\n  ForeignId 9\n", "T/Note.concerns.T/Household", "Household_s_2FGroup_2F9"),
])
def test_the_key_names_the_source_instance_translated_by_correspondence(fields, relation, target):
	log, report = mapped(fields)
	assert not report.gaps
	claims = [claim for claim in log["claims"] if ".concerns." in claim.get("rel", "")]
	assert [(claim["rel"], set(claim["roles"].values())) for claim in claims] == [(relation, {target, "Note_s_2FRecord_2F1"})]


def test_an_instance_absent_from_the_state_is_implicit_as_a_bindings_ref():
	log, report = mapped("  Table ClientId\n  ForeignId 10\n")
	assert not report.gaps
	claims = [claim for claim in log["claims"] if ".concerns." in claim.get("rel", "")]
	assert [set(claim["roles"].values()) for claim in claims] == [{"Party_s_2FClient_2F10", "Note_s_2FRecord_2F1"}]
	assert log["instances"]["Party_s_2FClient_2F10"]["type"] == "T/Party"
	assert not any(claim.get("s") == "Party_s_2FClient_2F10" and claim.get("exists") for claim in log["claims"])


def test_a_type_without_correspondence_cannot_choose_a_relation():
	with pytest.raises(FormatError, match="concerns"):
		loadMapping(SOURCE, TARGET, Source("m", MAPPING.replace("Client -> Party\n\n", "")))


def test_another_table_says_nothing():
	log, report = mapped("  Table LeadId\n  ForeignId 9\n")
	assert not report.gaps and not any(".concerns." in claim.get("rel", "") for claim in log["claims"])


# -----------------------------------------------------------------------------
#
# DECLARATIONS
#
# -----------------------------------------------------------------------------


def test_source_references_print_and_round_trip():
	mapping = loadMapping(SOURCE, TARGET, Source("m", MAPPING))
	printed = printMapping(mapping)
	assert "concerns <- ref(Client, ForeignId) {when=Table:ClientId}" in printed
	data = mappingToJson(mapping)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data


def test_source_references_are_lossy_under_reversal():
	text = "@mapping S -> T\nClient -> Party\nRecord -> Note\n  concerns <- ref(Client, Id)\n"
	_, lossy = mappingReverse(loadMapping(SOURCE, TARGET, Source("m", text)), SOURCE, TARGET)
	assert [item.line for item in lossy] == ["concerns"]


@pytest.mark.parametrize("expr", ["ref(Missing, ForeignId)", "ref(Client, concat(Table, ForeignId))", "ref(Client)", "ref(T/Party, ForeignId)"])
def test_invalid_source_references_are_rejected(expr):
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("m", MAPPING.replace("ref(Client, ForeignId)", expr)))
