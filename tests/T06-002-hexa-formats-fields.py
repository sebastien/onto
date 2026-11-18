"""Module: hexa formats and fields tests — `$format` reading, format tallies, formats updates and observed fields (spec-06)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import Source, inventoryFromDocuments, loadBinding, loadOntology, observationsToJson, parseFormats, parseInventory, printFormats, printInventory  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, bindingFormatsUpdate, programEncoding  # noqa: E402
from onto.integrations.hexa.stages import classify  # noqa: E402
from tests.helpers import specExample  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
FEED = json.loads(specExample("spec-04-mapping", 0, "json"))
FORMATS = parseFormats(Source("exchange.formats", specExample("spec-04-mapping", 15)))
TEXT = specExample("spec-04-mapping", 2).replace('date(payableDate, "YYYYMMDD")', "date(payableDate, $format)")
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


def test_indexed_formats_survive_save_and_reload():
	ontology = loadOntology([Source("rows.onto", "@ontology Rows\nRow\n  Day Date\n")])
	binding = loadBinding(ontology, Source("rows.bind", "@binding Rows\n@at <- at\nRow <- rows[*][0] {id=id}\n  Day <- date(day, $format)\n"))
	ops = HexaBindingOperator(ontology)
	feed = {"rows": [[{"id": "one", "day": "13/02/2026"}]], "at": "2026-02-14"}
	_, report = readRun(ops, ops.compile(binding), feed)
	path = "rows[*][0].day"
	assert report.formats[path] == {"DD/MM/YYYY": 1}
	learned, _ = ops.formatsUpdate(None, report)
	reloaded = parseFormats(Source("rows.formats", printFormats(learned)))
	feed["rows"][0][0]["day"] = "01/02/2026"
	log, _ = readRun(ops, ops.compile(binding, formats=reloaded), feed)
	assert [claim["v"] for claim in log.claims if claim.get("p") == "Day"] == ["2026-02-01"]


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


@pytest.mark.parametrize(("value", "expected"), [
	(" UPPER ", "padded"), ("\tlower\n", "padded"), (" Mixed ", "padded"),
	("UPPER-123", "case:upper"), ("lower-123", "case:lower"),
	("ÉTÉ", "case:upper"), ("été", "case:lower"),
	("Mixed", "trim"), ("中文", "trim"), ("---", "trim"), ("", "trim"),
	(" ", "padded"), ("123", "decimals:0"), ("-1.230", "decimals:3"),
	(123, None), (None, None), (True, None),
])
def test_writing_format_classification_prefers_padding_then_case(value, expected):
	assert classify(value) == expected


@pytest.mark.parametrize(("original", "formatName", "changed"), [
	("UPPER NAME", "case:upper", "MIXED NAME"),
	("lower name", "case:lower", "mixed name"),
	(" PADDED NAME ", "padded", "Mixed Name"),
	("Mixed Name", "trim", "Mixed Name"),
])
def test_learned_case_formats_write_new_values_but_originals_win(original, formatName, changed):
	ontology = loadOntology([Source("t.onto", "@ontology CaseLearning\nItem\n  Id Text\n  Name Text\n")])
	binding = loadBinding(ontology, Source("t.bind", "@binding CaseLearning\n\nItem <- items[*] {id=id}\n  Id <- id\n  Name <- trim(name)\n"))
	ops = HexaBindingOperator(ontology)
	previous = {"items": [{"id": "x", "name": original}]}
	clock = {"ClockRead": lambda context: "2026-11-16"}
	program = ops.compile(binding, formats=parseFormats(Source("f", "path\tformat\tseen\tpin\n")))
	log, report = ops.result(program, asyncio.run(run(clock, program.stages.BindingRead, [{"src": "s", "document": previous}])))
	path = "items[*].name"
	assert report.formats[path] == {formatName: 1}
	formats, _ = ops.formatsUpdate(None, report)
	assert formats.entries[path].format == formatName
	state = observationsToJson(log)
	for claim in state["claims"]:
		if claim.get("p") == "Name":
			claim["v"] = "Mixed Name"
	writer = ops.compileWrite(binding, formats=formats)
	written = asyncio.run(run(clock | {"DocumentPreviousRead": lambda request, context: None}, writer.stages.BindingWrite, {"src": "s", "state": state}))
	assert written["documents"][0]["document"]["items"][0]["name"] == changed
	# A competing chosen case must not override an unchanged original spelling.
	formats.entries[path].format = "case:lower" if formatName == "case:upper" else "case:upper"
	writer = ops.compileWrite(binding, formats=formats)
	written = asyncio.run(run(clock | {"DocumentPreviousRead": lambda request, context: previous}, writer.stages.BindingWrite,
		{"src": "s", "state": observationsToJson(log)}))
	assert written["documents"][0]["document"]["items"][0]["name"] == original
	assert written["report"]["originals"][path] == 1


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
