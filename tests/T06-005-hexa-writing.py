"""Module: hexa writing tests — documents written by bindings, originals, formats, CSV and reversed mappings (spec-06 Writing)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import (  # noqa: E402
	Source, inventoryFromDocuments, loadBinding, loadMapping, loadObservations, loadOntology, mappingReverse, observationsToJson, parseFormats,
	printObservationsState, reconcileObservations,
)
from onto.integrations.hexa.operations import HexaBindingOperator, HexaMappingOperator  # noqa: E402
from onto.referential import loadReferential  # noqa: E402
from tests.helpers import specExample  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
FINANCE = loadOntology([Source("finance.onto", specExample("spec-01-ontology"))])
SHEET = loadOntology([Source("sheet.onto", specExample("spec-04-mapping", 7))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", specExample("spec-04-mapping", 4))])
TEXT = specExample("spec-04-mapping", 2)
BINDING = loadBinding(EXCHANGE, Source("exchange.bind", TEXT))
SHEET_BINDING = loadBinding(SHEET, Source("sheet.bind", specExample("spec-04-mapping", 9)))
SHEET_MAPPING = loadMapping(FINANCE, SHEET, Source("finance-sheet.map", specExample("spec-04-mapping", 8)))
FEED = json.loads(specExample("spec-04-mapping", 0, "json"))
WRITTEN_BOND = json.loads(specExample("spec-06-hexa", 3, "json"))
INVENTORY = inventoryFromDocuments([FEED])
CLOCK = {"ClockRead": lambda context: "2026-11-12"}


def readState(ontology, binding, document, src="feed:x") -> dict:
	ops = HexaBindingOperator(ontology)
	program = ops.compile(binding)
	log, _ = ops.result(program, asyncio.run(run(CLOCK, program.stages.BindingRead, [{"src": src, "document": document}])))
	return observationsToJson(reconcileObservations(ontology, log))


def write(ontology, binding, state, previous=None, **options):
	ops = HexaBindingOperator(ontology)
	program = ops.compileWrite(binding, **options)
	env = CLOCK | {"DocumentPreviousRead": lambda request, context: previous}
	documents, report = ops.written(asyncio.run(run(env, program.stages.BindingWrite, {"src": "feed:x", "state": state})))
	return documents[0]["document"], report, program


# -----------------------------------------------------------------------------
#
# WRITING DOCUMENTS
#
# -----------------------------------------------------------------------------


def test_writing_the_bond_back_matches_spec06():
	document, report, _ = write(EXCHANGE, BINDING, readState(EXCHANGE, BINDING, FEED), previous=FEED, inventory=INVENTORY)
	bond = next(item for item in document["instruments"] if item["isin"] == "US0000000019")
	assert bond == WRITTEN_BOND
	assert document["asOf"] == "2026-11-12"
	assert report.originals["instruments[*].name"] == 2 and report.originals["instruments[*].issuerId"] == 2
	# The feed spelled the bond's code as `ticker`; `code ?? ticker` writes `code`.
	assert report.formatted == {"instruments[*].code": 1}
	assert report.lossy == [] and report.gaps == [] and report.parentless == []


def test_nested_records_are_placed_under_their_parent_in_handle_order():
	document, _, _ = write(EXCHANGE, BINDING, readState(EXCHANGE, BINDING, FEED), inventory=INVENTORY)
	assert [item["isin"] for item in document["instruments"]] == ["US0000000001", "US0000000019"]
	assert document["instruments"][0]["dividends"] == [{"amount": 0.42, "currency": "USD", "payableDate": "20260915", "taxCredit": 0.05}]
	assert "dividends" not in document["instruments"][1]
	assert document["issuers"] == [{"code": "ACME", "id": "C-17", "registeredName": "Acme Corporation Ltd"}]


@pytest.mark.parametrize("parentPath", ["row", "rows[0]", "rows[*]"])
def test_nested_fixed_object_is_written_after_its_parent(parentPath):
	ontology = loadOntology([Source("rows.onto", "@ontology Rows\nParent\n  Id Text {key}\nChild\n  Id Text {key}\n  Parent Parent\n")])
	binding = loadBinding(ontology, Source("rows.bind", f"@binding Rows\nParent <- {parentPath} {{id=id}}\n"
		f"  Id <- id\nChild <- {parentPath}.child {{id=id}}\n  Id <- id\n  Parent <- ^\n"))
	row = {"id": "p", "child": {"id": "c"}}
	previous = {"row": row} if parentPath == "row" else {"rows": [row]}
	document, report, _ = write(ontology, binding, readState(ontology, binding, previous))
	assert document == previous
	assert not report.parentless and not report.gaps


@pytest.mark.parametrize(("path", "previous"), [
	("$", {"id": "1", "name": " a "}),
	("$[*]", [{"id": "1", "name": " a "}]),
	("row", {"row": {"id": "1", "name": " a "}}),
	("row[1]", {"row": [None, {"id": "1", "name": " a "}]}),
	("rows[*][1]", {"rows": [[None, {"id": "1", "name": " a "}]]}),
])
def test_json_writer_keeps_the_scope_shape_and_original_spelling(path, previous):
	ontology = loadOntology([Source("rows.onto", "@ontology Rows\nRow\n  Id Text {key}\n  Name Text\n")])
	binding = loadBinding(ontology, Source("rows.bind", f"@binding Rows\nRow <- {path} {{id=id}}\n  Id <- id\n  Name <- trim(name)\n"))
	state = readState(ontology, binding, previous)
	document, report, _ = write(ontology, binding, state, previous=previous)
	assert document == previous
	assert not report.gaps and sum(report.originals.values()) == 2


def test_without_originals_values_take_their_formats():
	state = readState(EXCHANGE, BINDING, FEED)
	document, report, _ = write(EXCHANGE, BINDING, state)
	bond = next(item for item in document["instruments"] if item["isin"] == "US0000000019")
	assert bond["name"] == "Acme 5.25% 2030"
	# Without an inventory or a previous document, numbers are written as text: the observations encoding.
	assert bond["bond"] == {"couponRate": "0.0525", "interval": "6", "maturity": "1907712000"}
	formats = parseFormats(Source("f", "path\tformat\tseen\tpin\ninstruments[*].bond.couponRate\tdecimals:5\tdecimals:5 3\ninstruments[*].dividends[*].amount\tdecimals:2\tdecimals:2 9\n"))
	document, _, _ = write(EXCHANGE, BINDING, state, formats=formats)
	bond = next(item for item in document["instruments"] if item["isin"] == "US0000000019")
	assert bond["bond"]["couponRate"] == "0.05250"
	assert document["instruments"][0]["dividends"][0]["amount"] == "0.42"


def test_previous_documents_type_numbers_without_an_inventory():
	state = readState(EXCHANGE, BINDING, FEED)
	changed = json.loads(json.dumps(FEED))
	changed["instruments"][1]["bond"]["couponRate"] = 0.05
	document, report, _ = write(EXCHANGE, BINDING, state, previous=changed)
	assert next(item for item in document["instruments"] if item["isin"] == "US0000000019")["bond"]["couponRate"] == 0.0525
	assert report.formatted["instruments[*].bond.couponRate"] == 1


def test_lossy_lines_and_parentless_records():
	text = TEXT.replace("  Name <- trim(name)\n", "  Name <- concat(name, \"!\")\n")
	binding = loadBinding(EXCHANGE, Source("b", text))
	state = readState(EXCHANGE, BINDING, FEED)
	state["claims"] = [claim for claim in state["claims"] if claim.get("s") != "Instrument_US0000000001"]
	document, report, _ = write(EXCHANGE, binding, state)
	assert [(item["type"], item["line"]) for item in report.lossy] == [("Exchange/Instrument", "Name")]
	assert report.parentless == ["Dividend_US0000000001_2F2026_2D09_2D01"]
	assert [gap.reason for gap in report.gaps] == ["Binding.ParentMissing"]
	assert all("name" not in item for item in document["instruments"])


def test_derived_targets_are_read_but_never_written():
	"""A value the source computes on read (`~ CanEdit`) is not written back to it."""
	ontology = loadOntology([Source("d.onto", "@ontology Der rev=v1\nRow\n  Name Text\n  ~ CanEdit Boolean <- Name {rule=?}\n")])
	binding = loadBinding(ontology, Source("d.bind", "@binding Der\nRow <- rows[*] {id=id}\n  CanEdit <- canEdit\n  Name <- name\n"))
	state = readState(ontology, binding, {"rows": [{"id": "1", "name": "A", "canEdit": True}]})
	assert {claim.get("p") for claim in state["claims"]} >= {"CanEdit", "Name"}
	document, report, _ = write(ontology, binding, state)
	assert [(item["line"], item["reason"]) for item in report.lossy] == [("CanEdit", "Binding.PathUnsupported: derived target, not written back")]
	assert document == {"rows": [{"name": "A"}]}


def test_conditions_with_alternatives_or_several_tests_are_not_written_back():
	"""Writing restores a line's `path:value` condition; it cannot choose among alternatives."""
	ontology = loadOntology([Source("w.onto", "@ontology Cond rev=v1\nRow\n  Name Text\n  Kind Text\n")])
	binding = loadBinding(ontology, Source("w.bind", "@binding Cond\nRow <- rows[*] {id=id}\n  Kind <- kind\n  Name <- name {when=kind:A|B}\n"))
	state = readState(ontology, binding, {"rows": [{"id": "1", "name": "N", "kind": "A"}]})
	document, report, _ = write(ontology, binding, state)
	assert [(item["line"], item["reason"]) for item in report.lossy] == [("Name", "Binding.PathUnsupported: A condition with alternatives or several tests cannot be written back")]
	assert document == {"rows": [{"kind": "A"}]}


def test_null_policies_write_json_null():
	text = TEXT.replace("  Class <- class\n", "  Class <- class {null=unknown}\n")
	binding = loadBinding(EXCHANGE, Source("b", text))
	feed = json.loads(json.dumps(FEED))
	feed["instruments"][0]["class"] = None
	state = readState(EXCHANGE, binding, feed)
	document, _, _ = write(EXCHANGE, binding, state)
	assert document["instruments"][0]["class"] is None


# -----------------------------------------------------------------------------
#
# PROJECTIONS
#
# -----------------------------------------------------------------------------


def test_projection_to_csv_and_reading_back_through_the_reverse_mapping():
	finance = observationsToJson(reconcileObservations(FINANCE, loadObservations(FINANCE, Source("x.obs", specExample("spec-02-observations")))))
	forward = HexaMappingOperator(FINANCE, SHEET)
	program = forward.compile(SHEET_MAPPING)
	sheet, _ = forward.result(program, asyncio.run(run(CLOCK, program.stages.MappingRead, finance)))
	rows, report, _ = write(SHEET, SHEET_BINDING, observationsToJson(reconcileObservations(SHEET, sheet)))
	assert rows == [{"date": "2024-03-01", "isin": "US0000000001", "name": "", "asset class": "", "side": "Buy", "quantity": "100", "value": "9850"}]
	assert report.lossy == []
	reverse, lossy = mappingReverse(SHEET_MAPPING, FINANCE, SHEET, referential="MarketIds")
	assert sorted(item.line for item in lossy) == ["AssetClass", "Name", "Value"]
	backward = HexaMappingOperator(SHEET, FINANCE, referential=REFERENTIAL)
	program = backward.compile(reverse)
	trades, report = backward.result(program, asyncio.run(run(CLOCK, program.stages.MappingRead, readState(SHEET, SHEET_BINDING, rows, "sheet:1"))))
	text = printObservationsState(FINANCE, reconcileObservations(FINANCE, trades))
	assert "Trade_Sheet_2FPositionRow_2F2024_2D03_2D01_2FUS0000000001_2FBuy:Trade {valid=2024-03-01, by=map:Sheet->Finance}" in text
	assert "  Instrument Instrument_US0000000001" in text and "  Quantity 100" in text and "  Side Buy" in text
	assert report.gaps == []


def test_reverse_annotations_claim_on_the_referenced_instance():
	text = specExample("spec-04-mapping", 8).replace("  Name <- Instrument.Name\n", "  Name <- Instrument.Name {reverse}\n")
	mapping = loadMapping(FINANCE, SHEET, Source("m", text))
	reverse, lossy = mappingReverse(mapping, FINANCE, SHEET, referential="MarketIds")
	assert "Name" not in [item.line for item in lossy]
	rows = [{"date": "2024-03-01", "isin": "US0000000001", "name": "Acme", "asset class": "Equity", "side": "Buy", "quantity": "100", "value": "1"}]
	backward = HexaMappingOperator(SHEET, FINANCE, referential=REFERENTIAL)
	program = backward.compile(reverse)
	trades, _ = backward.result(program, asyncio.run(run(CLOCK, program.stages.MappingRead, readState(SHEET, SHEET_BINDING, rows, "sheet:1"))))
	assert any(claim.get("s") == "Instrument_US0000000001" and claim.get("p") == "Name" and claim["v"] == "Acme" for claim in trades.claims)


# EOF
