"""Module: static coverage tests — inventories, formats files, default bindings and the coverage table (spec-04)."""

from __future__ import annotations

import json

import pytest

from onto import (
	FormatError, FormatsEntry, Formats, Source, bindingCoverage, defaultBinding, documentFields, formatsUpdate,
	inventoryFromDocuments, loadBinding, loadFunctions, loadMapping, loadOntology, mappingCoverage, parseBinding,
	parseFormats, parseInventory, printBinding, printCoverageTable, printFormats, printInventory,
)
from onto.referential import loadReferential
from tests._helpers import _specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", _specExample("spec-04-mapping", 1))])
FINANCE = loadOntology([Source("finance.onto", _specExample("spec-01-ontology"))])
SHEET = loadOntology([Source("sheet.onto", _specExample("spec-04-mapping", 7))])
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", _specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", _specExample("spec-04-mapping", 4))])
BINDING = loadBinding(EXCHANGE, Source("exchange.bind", _specExample("spec-04-mapping", 2)))
SHEET_BINDING = loadBinding(SHEET, Source("sheet.bind", _specExample("spec-04-mapping", 9)))
MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", _specExample("spec-04-mapping", 5)), libraries=[MARKETS], referentials=[REFERENTIAL])
SHEET_MAPPING = loadMapping(FINANCE, SHEET, Source("finance-sheet.map", _specExample("spec-04-mapping", 8)))
FEED = json.loads(_specExample("spec-04-mapping", 0, "json"))
FORMATS_TEXT = _specExample("spec-04-mapping", 15)
INVENTORY_TEXT = _specExample("spec-04-mapping", 16)
TABLE_TEXT = _specExample("spec-04-mapping", 17)


def table(rows) -> set[str]:
	return set(printCoverageTable(rows).splitlines())


# -----------------------------------------------------------------------------
#
# INVENTORIES
#
# -----------------------------------------------------------------------------


def test_spec_inventory_round_trips():
	inventory = parseInventory(Source("instruments.inventory", INVENTORY_TEXT))
	assert printInventory(inventory) == INVENTORY_TEXT
	assert inventory.types()["instruments[*].bond.couponRate"] == "number"


def test_inventory_from_the_feed_lists_list_items_and_scalars():
	inventory = inventoryFromDocuments([FEED])
	types = inventory.types()
	assert set(INVENTORY_TEXT.splitlines()) <= set(printInventory(inventory).splitlines())
	assert types["instruments[*].dividends[*]"] == "object"
	assert "instruments[*].bond" not in types and "instruments" not in types


def test_inventory_from_csv_rows_and_mixed_types():
	rows = [{"date": "2026-11-10", "asset class": "Equity", "value": 1}, {"date": "2026-11-11", "value": "2"}]
	assert documentFields(rows, csv=True) == {"$[*]": ["object"], '$[*]."asset class"': ["text"], "$[*].date": ["text"], "$[*].value": ["text", "number"]}
	assert inventoryFromDocuments([rows], csv=True).types()["$[*].value"] == "text"
	assert documentFields({"tags": ["a", None], "none": None}) == {"tags[*]": ["text"]}


@pytest.mark.parametrize("text", ["a\ttext\na\tnumber\n", "a\tdate\n", "a.^\ttext\n", "a[0]\ttext\n", "a text\n"])
def test_invalid_inventories_fail(text):
	with pytest.raises(FormatError):
		parseInventory(Source("bad", text))


def test_inventory_paths_are_canonical():
	assert printInventory(parseInventory(Source("i", 'b\ttext\n$[*]."x y"\ttext\n'))) == '$[*]."x y"\ttext\nb\ttext\n'


# -----------------------------------------------------------------------------
#
# FORMATS
#
# -----------------------------------------------------------------------------


def test_spec_formats_round_trip():
	formats = parseFormats(Source("exchange.formats", FORMATS_TEXT))
	assert printFormats(formats) == FORMATS_TEXT
	entry = formats.entries["instruments[*].dividends[*].payableDate"]
	assert (entry.format, entry.seen, entry.pin) == ("YYYYMMDD", {"YYYYMMDD": 412, "YYYY-MM-DD": 3}, False)
	assert formats.entries["instruments[*].dividends[*].amount"].pin


def test_formats_update_counts_chooses_and_reports_changes():
	formats = parseFormats(Source("f", FORMATS_TEXT))
	updated, changes = formatsUpdate(formats, {
		"instruments[*].dividends[*].payableDate": {"YYYY-MM-DD": 500},
		"instruments[*].dividends[*].amount": {"decimals:3": 5000},
		"asOf": {"YYYY-MM-DD": 1},
	})
	assert updated.entries["instruments[*].dividends[*].payableDate"].format == "YYYY-MM-DD"
	assert updated.entries["instruments[*].dividends[*].payableDate"].seen == {"YYYYMMDD": 412, "YYYY-MM-DD": 503}
	assert updated.entries["instruments[*].dividends[*].amount"].format == "decimals:2"
	assert updated.entries["asOf"].format == "YYYY-MM-DD"
	assert [(item.path, item.previous, item.format) for item in changes] == [("instruments[*].dividends[*].payableDate", "YYYYMMDD", "YYYY-MM-DD")]
	assert formats.entries["instruments[*].dividends[*].payableDate"].format == "YYYYMMDD"


def test_formats_ties_choose_by_name():
	updated, changes = formatsUpdate(Formats({"a": FormatsEntry("a", "YYYYMMDD", {"YYYYMMDD": 2})}), {"a": {"DD/MM/YYYY": 2}})
	assert updated.entries["a"].format == "DD/MM/YYYY" and len(changes) == 1


@pytest.mark.parametrize("text", [
	"path\tformat\n",
	"path\tformat\tseen\tpin\na\tbogus\t\n",
	"path\tformat\tseen\tpin\na\ttrim\ttrim x\n",
	"path\tformat\tseen\tpin\na\ttrim\ttrim 1\tyes\n",
	"path\tformat\tseen\tpin\na\ttrim\ttrim 1\na\ttrim\ttrim 1\n",
])
def test_invalid_formats_fail(text):
	with pytest.raises(FormatError):
		parseFormats(Source("bad", text))


# -----------------------------------------------------------------------------
#
# MAPPING COVERAGE
#
# -----------------------------------------------------------------------------


def test_mapping_coverage_reproduces_the_spec_table():
	report = mappingCoverage(EXCHANGE, FINANCE, MAPPING)
	assert set(TABLE_TEXT.splitlines()) <= table(report.rows)
	assert report.unassigned == ["Company.SuspensionStatus"]


def test_mapping_coverage_statuses():
	rows = {(row.source, row.target): row for row in mappingCoverage(EXCHANGE, FINANCE, MAPPING).rows}
	assert rows[("Issuer.Id", None)].status == "ignore"
	assert rows[("Instrument.Issuer", "Dividend.Payer")].status == "direct"
	assert rows[("Instrument.PaymentInterval", "Instrument.Bond.InterestFrequency")].status == "transformed"
	assert ("Instrument.Class", None) not in rows


def test_mapping_coverage_is_limited_to_the_view():
	report = mappingCoverage(FINANCE, SHEET, SHEET_MAPPING)
	sources = {row.source for row in report.rows}
	assert "Trade.Price" in sources and "Instrument.Bond.CouponRate" in sources
	assert not any(source.startswith(("Company.", "Dividend.")) for source in sources)
	assert {row.status for row in report.rows if row.source == "Trade.Counterparty"} == {"unmapped"}


def test_candidates_are_ambiguous_until_enabled():
	text = _specExample("spec-04-mapping", 5).replace("  Name <- Name\n", "  Name <- Name {candidate}\n")
	mapping = loadMapping(EXCHANGE, FINANCE, Source("m", text), libraries=[MARKETS], referentials=[REFERENTIAL])
	rows = {(row.source, row.target): row.status for row in mappingCoverage(EXCHANGE, FINANCE, mapping).rows}
	assert rows[("Instrument.Name", "Instrument.Name")] == "ambiguous"
	assert "Instrument.Name" in mappingCoverage(EXCHANGE, FINANCE, mapping).unassigned


# -----------------------------------------------------------------------------
#
# BINDING COVERAGE
#
# -----------------------------------------------------------------------------


def test_binding_coverage_document_side():
	report = bindingCoverage(EXCHANGE, BINDING, parseInventory(Source("i", printInventory(inventoryFromDocuments([FEED])))))
	rows = {(row.source, row.target): row.status for row in report.rows}
	assert rows[("asOf", None)] == "condition"
	assert rows[("instruments[*].dividends[*].exDate", None)] == "condition"
	assert rows[("instruments[*].dividends[*].payableDate", "Dividend.PayableDate")] == "transformed"
	assert rows[("instruments[*].code", "Instrument.Code")] == "transformed"
	assert rows[("instruments[*].isin", "Instrument.Isin")] == "direct"
	assert rows[("instruments[*]", "Instrument")] == "direct"
	assert report.unassigned == [] and report.uninventoried == []


def test_binding_coverage_ontology_side_and_exclusions():
	text = _specExample("spec-04-mapping", 2).replace("  TaxCredit <- taxCredit\n", "") + "\n- instruments[*].dividends[*].taxCredit {reason=out-of-scope} -- Jurisdiction\n- issuers[*] {reason=ignore}\n"
	binding = loadBinding(EXCHANGE, Source("b", text))
	report = bindingCoverage(EXCHANGE, binding, inventoryFromDocuments([FEED]))
	rows = {(row.source, row.target): row for row in report.rows}
	assert rows[("instruments[*].dividends[*].taxCredit", None)].status == "out-of-scope"
	assert rows[("instruments[*].dividends[*].taxCredit", None)].note == "Jurisdiction"
	# A read field keeps its status; an excluded container still covers its unread fields.
	assert rows[("issuers[*]", "Issuer")].status == "direct"
	assert report.unassigned == ["Dividend.TaxCredit"]
	assert bindingCoverage(EXCHANGE, binding).rows == []


def test_binding_coverage_unmapped_and_uninventoried_fields():
	inventory = parseInventory(Source("i", '$[*]\tobject\n$[*]."asset class"\ttext\n$[*].date\ttext\n$[*].extra\ttext\n'))
	report = bindingCoverage(SHEET, SHEET_BINDING, inventory)
	rows = {(row.source, row.target): row.status for row in report.rows}
	assert rows[("$[*].extra", None)] == "unmapped"
	assert rows[('$[*]."asset class"', "PositionRow.AssetClass")] == "direct"
	assert report.uninventoried == ["$[*].isin", "$[*].name", "$[*].quantity", "$[*].side", "$[*].value"]


# -----------------------------------------------------------------------------
#
# DEFAULT BINDINGS
#
# -----------------------------------------------------------------------------


def test_default_binding_from_the_feed():
	binding = defaultBinding(inventoryFromDocuments([FEED]), "Exchange")
	text = printBinding(binding)
	# `id` prefers `id`/`key`, then a field ending in `Id`: people edit the exceptions.
	assert "Instrument <- instruments[*] {id=issuerId}" in text
	assert "Issuer <- issuers[*] {id=id}" in text
	assert "  CouponRate <- bond.couponRate" in text
	assert "  Amount <- amount" in text
	assert "dividends" not in text.split("Instrument <- instruments[*]")[1].split("\n\n")[0]
	# The default binding is a valid binding document, regenerated identically.
	assert printBinding(defaultBinding(inventoryFromDocuments([FEED]), "Exchange")) == text
	parseBinding(Source("default.bind", text))


def test_default_binding_for_csv_and_name_clashes():
	inventory = parseInventory(Source("i", "$[*]\tobject\n$[*].a.name\ttext\n$[*].b.name\ttext\n$[*].rowId\ttext\n$[*].tags[*]\ttext\n"))
	text = printBinding(defaultBinding(inventory, "Sheet", csv=True))
	assert text.startswith("@binding Sheet format=csv\n")
	assert "Row <- $[*] {id=rowId}" in text
	assert "  AName <- a.name" in text and "  BName <- b.name" in text
	assert "  Tags <- tags[*]" in text


# EOF
