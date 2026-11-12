"""Module: hexa formats and fields tests — `$format` reading, format tallies, formats updates and observed fields (spec-06)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import Source, inventoryFromDocuments, loadBinding, loadOntology, parseFormats, parseInventory, printInventory  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, bindingFormatsUpdate, programEncoding  # noqa: E402
from tests._helpers import _specExample  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", _specExample("spec-04-mapping", 1))])
FEED = json.loads(_specExample("spec-04-mapping", 0, "json"))
FORMATS = parseFormats(Source("exchange.formats", _specExample("spec-04-mapping", 15)))
TEXT = _specExample("spec-04-mapping", 2).replace('date(payableDate, "YYYYMMDD")', "date(payableDate, $format)")
BINDING = loadBinding(EXCHANGE, Source("exchange.bind", TEXT))
FIELD = "instruments[*].dividends[*].payableDate"


def feedWith(*payableDates: str) -> dict:
	feed = json.loads(json.dumps(FEED))
	feed["instruments"][0]["dividends"] = [{"exDate": f"2026-0{index + 1}-01", "payableDate": value, "amount": 1, "currency": "USD"} for index, value in enumerate(payableDates)]
	return feed


def readRun(ops, program, feed):
	result = asyncio.run(run({}, program.stages.BindingRead, [{"src": "feed:x", "document": feed}]))
	return ops.result(program, result)


# -----------------------------------------------------------------------------
#
# FORMATS
#
# -----------------------------------------------------------------------------


def test_format_positions_try_the_chosen_then_seen_then_candidate_patterns():
	program = HexaBindingOperator(EXCHANGE).compile(BINDING, formats=FORMATS)
	branches = programEncoding(program)["Dividend"]["shape"]["$loose"]["payableDate?"]["$either"][1]["$tolerant"]["$either"]
	patterns = [branch["via"]["arguments"][0] for branch in branches]
	assert patterns[:3] == ["YYYYMMDD", "YYYY-MM-DD", "DD/MM/YYYY"]
	assert len(patterns) == len(set(patterns)) == 6
	# Without a formats file, the candidates come in their fixed order.
	bare = HexaBindingOperator(EXCHANGE).compile(BINDING)
	assert programEncoding(bare)["Dividend"]["shape"]["$loose"]["payableDate?"]["$either"][1]["$tolerant"]["$either"][0]["via"]["arguments"] == ["YYYY-MM-DD"]


def test_runs_tally_formats_and_update_the_formats_file():
	ops = HexaBindingOperator(EXCHANGE)
	program = ops.compile(BINDING, formats=FORMATS)
	log, report = readRun(ops, program, feedWith("20260915", "2026-10-15", "2026-11-15"))
	assert sorted(claim["v"] for claim in log.claims if claim.get("p") == "PayableDate") == ["2026-09-15", "2026-10-15", "2026-11-15"]
	assert report.formats[FIELD] == {"YYYYMMDD": 1, "YYYY-MM-DD": 2}
	updated, changes = ops.formatsUpdate(FORMATS, report)
	assert updated.entries[FIELD].seen == {"YYYYMMDD": 413, "YYYY-MM-DD": 5}
	assert changes == []
	assert updated.entries["instruments[*].name"].format == "trim"


def test_a_switch_of_most_frequent_format_is_a_change():
	ops = HexaBindingOperator(EXCHANGE)
	formats = parseFormats(Source("f", f"path\tformat\tseen\tpin\n{FIELD}\tYYYYMMDD\tYYYYMMDD 1\n"))
	_, report = readRun(ops, ops.compile(BINDING, formats=formats), feedWith("2026-09-15", "2026-10-15"))
	updated, changes = bindingFormatsUpdate(formats, report)
	assert updated.entries[FIELD].format == "YYYY-MM-DD"
	assert [(change.path, change.previous, change.format) for change in changes] == [(FIELD, "YYYYMMDD", "YYYY-MM-DD")]


def test_ambiguous_values_read_in_the_chosen_format():
	ops = HexaBindingOperator(EXCHANGE)
	formats = parseFormats(Source("f", f"path\tformat\tseen\tpin\n{FIELD}\tMM/DD/YYYY\tMM/DD/YYYY 9\n"))
	log, report = readRun(ops, ops.compile(BINDING, formats=formats), feedWith("01/02/2026", "13/02/2026"))
	assert sorted(claim["v"] for claim in log.claims if claim.get("p") == "PayableDate") == ["2026-01-02", "2026-02-13"]
	assert report.formats[FIELD] == {"MM/DD/YYYY": 1, "DD/MM/YYYY": 1}


def test_values_matching_no_format_are_gaps_and_not_counted():
	ops = HexaBindingOperator(EXCHANGE)
	log, report = readRun(ops, ops.compile(BINDING, formats=FORMATS), feedWith("someday", "20260915"))
	assert [gap.reason for gap in report.gaps if gap.target.endswith("PayableDate")] == ["DatePattern.Invalid"]
	assert report.formats[FIELD] == {"YYYYMMDD": 1}
	assert [entry["p"] for entry in report.stale] == ["PayableDate"]


def test_writing_formats_are_learned_from_raw_values():
	ops = HexaBindingOperator(EXCHANGE)
	feed = json.loads(json.dumps(FEED))
	feed["instruments"][0]["dividends"][0]["amount"] = "0.420"
	_, report = readRun(ops, ops.compile(BINDING, formats=FORMATS), feed)
	assert report.formats["instruments[*].name"] == {"trim": 1, "padded": 1}
	assert report.formats["instruments[*].dividends[*].amount"] == {"decimals:3": 1}
	assert "instruments[*].bond.couponRate" not in report.formats
	updated, changes = ops.formatsUpdate(FORMATS, report)
	assert updated.entries["instruments[*].name"].seen == {"trim": 381, "padded": 36}
	# Without a formats file only `$format` date patterns are counted.
	assert set(readRun(ops, ops.compile(BINDING), feed)[1].formats) == {FIELD}


# -----------------------------------------------------------------------------
#
# OBSERVED FIELDS
#
# -----------------------------------------------------------------------------


def test_fields_missing_from_the_inventory_or_typed_differently_are_reported():
	inventory = parseInventory(Source("i", printInventory(inventoryFromDocuments([FEED])).replace("instruments[*].ticker\ttext\n", "").replace("instruments[*].class\ttext", "instruments[*].class\tnumber")))
	ops = HexaBindingOperator(EXCHANGE)
	program = ops.compile(BINDING, inventory=inventory)
	feed = json.loads(json.dumps(FEED))
	documents = [{"src": "a", "document": feed}, {"src": "b", "document": feed}]
	result = asyncio.run(run({}, program.stages.BindingRead, documents))
	_, report = ops.result(program, result)
	assert report.fields == {"missing": {"instruments[*].ticker": 2}, "mismatched": {"instruments[*].class": {"inventory": "number", "seen": ["text"]}}}
	assert HexaBindingOperator(EXCHANGE).result(HexaBindingOperator(EXCHANGE).compile(BINDING), asyncio.run(run({}, HexaBindingOperator(EXCHANGE).compile(BINDING).stages.BindingRead, documents)))[1].fields is None


# EOF
