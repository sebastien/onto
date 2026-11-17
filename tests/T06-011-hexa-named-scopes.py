"""Named repeated targets and presence-selected declarations."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run
from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations
from onto.integrations.hexa.operations import HexaMappingOperator

SOURCE = loadOntology([Source("s.onto", """@ontology S
Row
  Main Text
  Short Text
  Expected Boolean
  Amount Amount {cur=?}
  App App
  Extra Extra
Extra =
  Note Text
App
Link
  Row Row
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Goal
  Description Text
Expectation
  IsExpected Boolean
  Amount Amount {cur=?, period=?}
  Horizon Range<Duration>
App
Link
  Goal Goal
Goal -isGoalOf/hasGoal-> App
Expectation -isRecordedIn/recordsExpectation-> App
""")])
MAPPING = """@mapping S -> T
App -> App
Row -> Goal {name=Main, present=trim(Main)}
  Description <- Main
  isGoalOf <- App
Row -> Goal {name=Short, present=trim(Short)}
  Description <- Short
  isGoalOf <- App
Row -> Expectation {name=Savings, present=Expected}
  IsExpected <- Expected
  Horizon <- "P1Y..P5Y"
  Amount <- Amount {period="Year", when=Expected:true}
  isRecordedIn <- App
"""


def mapped(fields, text=MAPPING):
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-17\n@src f=fixture\n@src f\nApp_1:App\nRow_1:Row\n  App App_1\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-17"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


def test_repeated_targets_have_distinct_stable_identities_and_links():
	log, report = mapped("  Main General\n  Short Specific\n  Expected true\n  Amount 1000\n")
	assert not report.gaps
	goals = {h for h, item in log["instances"].items() if item["type"] == "T/Goal"}
	assert len(goals) == 2
	assert any("_40Main" in h for h in goals) and any("_40Short" in h for h in goals)
	assert len([c for c in log["claims"] if ".isGoalOf." in c.get("rel", "")]) == 2
	again, _ = mapped("  Main General\n  Short Specific\n  Expected true\n  Amount 1000\n", printMapping(loadMapping(SOURCE, TARGET, Source("m", MAPPING))))
	assert set(again["instances"]) == set(log["instances"])


@pytest.mark.parametrize("fields", ["", "  Main \"   \"\n", "  Main ?\n", "  Expected ?\n"])
def test_absent_blank_unknown_answers_do_not_mint_declarations(fields):
	log, report = mapped(fields)
	assert not report.gaps
	assert not any(item["type"] in ("T/Goal", "T/Expectation") for item in log["instances"].values())


def test_false_is_present_but_does_not_assert_a_stale_positive_amount():
	log, report = mapped("  Expected false\n  Amount 1000\n")
	assert not report.gaps
	assert any(item["type"] == "T/Expectation" for item in log["instances"].values())
	assert any(c.get("p") == "IsExpected" and c["v"] is False for c in log["claims"])
	assert not any(c.get("p") == "Amount" for c in log["claims"])
	assert any(c.get("p") == "Horizon" and c["v"] == "P1Y..P5Y" for c in log["claims"])


def test_conflicting_presence_does_not_mint_goals():
	log, report = mapped("  Short One\n@src g=other\n@src g\nRow_1.Short Two\n")
	assert any(g.reason == "Mapping.InputConflicting" for g in report.gaps)
	assert not any(item["type"] == "T/Goal" for item in log["instances"].values())


def test_invalid_presence_expression_reports_a_gap_instead_of_silently_skipping():
	log, report = mapped("  Main not-a-number\n", MAPPING.replace("present=trim(Main)", "present=number(Main)"))
	assert report.gaps
	assert not any(item["type"] == "T/Goal" for item in log["instances"].values())


def test_names_and_presence_roundtrip_json_and_text():
	mapping = loadMapping(SOURCE, TARGET, Source("m", MAPPING))
	data = mappingToJson(mapping)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data
	assert printMapping(loadMapping(SOURCE, TARGET, Source("m", printMapping(mapping)))) == printMapping(mapping)


def test_invalid_literal_range_is_rejected_statically():
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("range.map", MAPPING.replace("P1Y..P5Y", "not-a-duration..P5Y")))


def test_group_exclusions_cover_structure_leaves_without_hiding_reads():
	from onto.mapping.coverage import mappingCoverage
	mapping = loadMapping(SOURCE, TARGET, Source("m", MAPPING + "- Row {reason=out-of-scope}\n"))
	rows = {row.source: row.status for row in mappingCoverage(SOURCE, TARGET, mapping).rows}
	assert rows["Row.Extra.Note"] == "out-of-scope"
	assert rows["Row.Main"] != "out-of-scope"


@pytest.mark.parametrize("text", [
	MAPPING.replace("name=Short", "name=Main"),
	MAPPING.replace("name=Short, ", ""),
	MAPPING + "Link -> Link\n  Goal <- Row\n",
])
def test_unnamed_duplicate_targets_and_ambiguous_incoming_references_fail(text):
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("bad.map", text))

# EOF
