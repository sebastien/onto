"""Mapping measurements with qualifiers read from source expressions."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run
from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations
from onto.integrations.hexa.operations import HexaMappingOperator


SOURCE = loadOntology([Source("source.onto", """@ontology Source
Expense
  Value Amount {cur=?}
  Period Text
  Currency Text
  Current Boolean
""")])
TARGET = loadOntology([Source("target.onto", """@ontology Target
Period = Week|Month|Year
Currency = NZD|USD
Expense
  Amount Amount {cur=?:Currency, period=?:Period}
  Name Text
""")])
MAPPING = """@mapping Source -> Target
Expense -> Expense
  Amount <- Value {period=Period}
"""


def mapped(fields, text=MAPPING):
	mapping = loadMapping(SOURCE, TARGET, Source("test.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("test.obs", "@obs Source at=2026-11-17\n@src f=fixture\n@src f\nExpense_1:Expense\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-17"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


@pytest.mark.parametrize("period", ["Week", "Month", "Year"])
def test_period_is_claim_metadata_not_an_unqualified_amount(period):
	log, report = mapped(f"  Value 50\n  Period {period}\n")
	assert not report.gaps
	claim = next(c for c in log["claims"] if c.get("p") == "Amount")
	assert claim["v"] == "50" and claim["period"] == period
	assert "cur" not in claim


@pytest.mark.parametrize("period", ["", "  Period Daily\n", "  Period ?\n"])
def test_missing_invalid_or_unknown_period_never_emits_amount(period):
	log, report = mapped("  Value 50\n" + period)
	assert report.gaps
	assert not any(c.get("p") == "Amount" for c in log["claims"])
	assert report.stale


def test_zero_and_currency_and_literal_qualifiers():
	log, report = mapped("  Value 0\n  Period Month\n  Currency NZD\n", MAPPING.replace("period=Period", 'cur=Currency, period="Month"'))
	assert not report.gaps
	claim = next(c for c in log["claims"] if c.get("p") == "Amount")
	assert (claim["v"], claim["cur"], claim["period"]) == ("0", "NZD", "Month")


def test_absent_amount_and_false_condition_do_not_demand_qualifiers():
	for fields, text in [("", MAPPING), ("  Value 50\n  Current false\n", MAPPING.replace("period=Period", "period=Period, when=Current:true"))]:
		log, report = mapped(fields, text)
		assert not report.gaps
		assert not any(c.get("p") == "Amount" for c in log["claims"])


def test_conflicting_period_does_not_choose_one():
	log, report = mapped("  Value 50\n  Period Week\n@src g=other\n@src g\nExpense_1.Period Month\n")
	assert any(g.reason == "Mapping.InputConflicting" for g in report.gaps)
	assert not any(c.get("p") == "Amount" for c in log["claims"])


def test_overloaded_verb_uses_reference_type_not_first_relation():
	source = loadOntology([Source("s.onto", "@ontology S\nCost\n  Household Household\nHousehold\n")])
	target = loadOntology([Source("t.onto", """@ontology T
Cost
Household
Party
Party -incurs/isIncurredBy-> Cost
Household -incurs/isIncurredBy-> Cost
""")])
	mapping = loadMapping(source, target, Source("m.map", "@mapping S -> T\nCost -> Cost\n  isIncurredBy <- Household\nHousehold -> Household\n"))
	ops = HexaMappingOperator(source, target, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(source, Source("o.obs", "@obs S at=2026-11-17\n@src f=fixture\n@src f\nHousehold_1:Household\nCost_1:Cost\n  Household Household_1\n"))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-17"}, program.stages.MappingRead, observationsToJson(obs)))
	log, report = ops.result(program, result)
	assert not report.gaps
	assert [c["rel"] for c in observationsToJson(log)["claims"] if "rel" in c] == ["T/Household.incurs.T/Cost"]


def test_qualifier_expression_roundtrips_and_counts_as_coverage():
	from onto.mapping.coverage import mappingCoverage
	mapping = loadMapping(SOURCE, TARGET, Source("test.map", MAPPING))
	data = mappingToJson(mapping)
	loaded = mappingFromJson(SOURCE, TARGET, data)
	assert mappingToJson(loaded) == data
	assert printMapping(loadMapping(SOURCE, TARGET, Source("printed.map", printMapping(mapping)))) == printMapping(mapping)
	assert any(row.source == "Expense.Period" and row.status == "transformed" for row in mappingCoverage(SOURCE, TARGET, mapping).rows)


def test_qualifier_inputs_contribute_metadata():
	log, report = mapped("  Value 50 {conf=0.9, valid=2026-01-01..2026-12-31}\n  Period Week {conf=0.7, valid=2026-06-01..2026-06-30}\n")
	assert not report.gaps
	claim = next(c for c in log["claims"] if c.get("p") == "Amount")
	assert claim["conf"] == 0.7
	assert claim["valid"] == "2026-06-01..2026-06-30"


def test_qualifiers_cannot_relabel_fixed_measurements():
	for source, target, text in [
		(SOURCE, loadOntology([Source("fixed.onto", "@ontology Target\nExpense\n  Amount Amount {period=Month}\n")]), MAPPING),
		(loadOntology([Source("fixed.onto", "@ontology Source\nExpense\n  Value Amount {cur=USD}\n  Currency Text\n")]), TARGET, MAPPING.replace("period=Period", "cur=Currency")),
	]:
		with pytest.raises(FormatError):
			loadMapping(source, target, Source("fixed.map", text))


@pytest.mark.parametrize("line", ['Name <- Period {period=Period}', 'Amount <- Value {period=Value}', 'Amount <- Value {period=Period, period=Period}'])
def test_rejects_nonmeasurement_nonscalar_and_duplicate_qualifiers(line):
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("invalid.map", "@mapping Source -> Target\nExpense -> Expense\n  " + line + "\n"))

# EOF
