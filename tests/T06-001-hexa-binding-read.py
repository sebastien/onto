"""Module: hexa binding tests — compiling bindings and reading documents into source observations (spec-06)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import Source, loadBinding, loadFunctions, loadOntology, observationsToJson, printObservationsLog  # noqa: E402
from onto.integrations.hexa import IntegrationUnavailable, vocabularyConformance  # noqa: E402
from onto.integrations.hexa.compiler import CompileError  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, bindingCompile, bindingResult, programEncoding  # noqa: E402
from tests.helpers import ROOT, specExample  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
SHEET = loadOntology([Source("sheet.onto", specExample("spec-04-mapping", 7))])
BINDING = loadBinding(EXCHANGE, Source("exchange.bind", specExample("spec-04-mapping", 2)))
SHEET_BINDING = loadBinding(SHEET, Source("sheet.bind", specExample("spec-04-mapping", 9)))
FEED = json.loads(specExample("spec-04-mapping", 0, "json"))
SRC = "feed:instruments/2026-11-10"
CLOCK = {"ClockRead": lambda context: "2026-11-11T09:00:00Z"}
DIVIDEND_RECORD = json.loads(specExample("spec-06-hexa", 0, "json"))


def read(ops, binding, documents, env=None):
	program = ops.compile(binding)
	result = asyncio.run(run(env or {}, program.stages.BindingRead, documents))
	return program, result, *ops.result(program, result)


def claims(log) -> list[str]:
	return sorted(json.dumps({key: value for key, value in claim.items() if key != "n"}, sort_keys=True) for claim in log.claims)


# -----------------------------------------------------------------------------
#
# INTEGRATION
#
# -----------------------------------------------------------------------------


def test_import_without_hexa_raises_integration_unavailable():
	code = "import sys; sys.modules['hexa'] = None; sys.modules['hexa.shapes'] = None\nimport onto\ntry:\n  import onto.integrations.hexa\nexcept ImportError as e:\n  print(type(e).__name__, e.name)"
	output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src/py")}, check=True).stdout
	assert output.strip() == "IntegrationUnavailable hexa"
	assert issubclass(IntegrationUnavailable, ImportError)


def test_onto_vocabulary_examples_conform():
	assert vocabularyConformance() >= 50


# -----------------------------------------------------------------------------
#
# COMPILING
#
# -----------------------------------------------------------------------------


def test_dividend_scope_compiles_as_spec06_shows():
	program = HexaBindingOperator(EXCHANGE).compile(BINDING)
	dividend = next(scope for scope in program.scopes if scope.name == "Dividend")
	assert dividend.selector == "{asOf?:$Bind.At}/instruments/*/{isin?:$Bind.Dividend.Fields.Outer.Isin}/dividends/*"
	encoded = programEncoding(program)["Dividend"]
	assert encoded["shape"]["$loose"]["payableDate?"] == {"$either": ["$Null", {"$tolerant": {"$": "Exchange.Dividend.PayableDate", "via": {"$": "DatePattern", "arguments": ["YYYYMMDD"]}}}]}
	assert encoded["shape"]["$loose"]["amount?"] == {"$either": ["$Null", {"$tolerant": {"$": "Exchange.Dividend.Amount", "via": "DecimalText"}}]}
	assert encoded["template"]["handle"] == {"$derive": "$Onto.Handle", "arguments": ["Dividend", {"$derive": "$Onto.Concat", "arguments": [
		{"$derive": "$Onto.Present", "arguments": [{"$": "Bind.Dividend.Fields.Outer.Isin", "optional": True}]}, "/",
		{"$": "Bind.Dividend.Fields.ExDate", "optional": True}]}]}
	assert encoded["outer"] == ["Bind.At", "Bind.Dividend.Fields.Outer.Isin"]
	assert {"Exchange.Dividend.Amount", "Exchange.Instrument.CouponRate", "Exchange.Issuer.Id"} <= set(program.slots)


def test_compiling_is_pure_and_repeatable():
	first = programEncoding(bindingCompile(EXCHANGE, BINDING))
	second = programEncoding(bindingCompile(EXCHANGE, BINDING))
	assert first == second
	from onto import bindingToJson
	assert programEncoding(bindingCompile(EXCHANGE, bindingToJson(BINDING))) == first


def test_index_steps_before_a_list_select_one_position():
	# Index steps elsewhere are read by tuple shapes (T06-007); before a list, a selector level keeps one position
	binding = loadBinding(EXCHANGE, Source("b", "@binding Exchange\n\nDividend <- instruments[0].dividends[*] {id=exDate}\n  Amount <- amount\n"))
	program = bindingCompile(EXCHANGE, binding)
	assert [(scope.levels, scope.picks) for scope in program.scopes] == [(["instruments/*", "dividends/*"], [0, None])]


# -----------------------------------------------------------------------------
#
# READING
#
# -----------------------------------------------------------------------------


def test_feed_reads_into_the_exchange_log():
	ops = HexaBindingOperator(EXCHANGE, mode="lenient")
	_, result, log, report = read(ops, BINDING, [{"src": SRC, "document": FEED}])
	data = observationsToJson(log)
	assert data["sources"] == {"d1": SRC}
	assert data["instances"]["Issuer_C_2D17"] == {"type": "Exchange/Issuer"}
	assert all(claim["by"] == "bind:Exchange" and claim["at"] == "2026-11-10" and claim["src"] == "d1" for claim in data["claims"])
	text = printObservationsLog(EXCHANGE, log)
	for line in ("Instrument_US0000000019.Name Acme 5.25% 2030", "Instrument_US0000000019.CouponRate 0.0525",
		"Instrument_US0000000019.MaturityDate 1907712000", "Instrument_US0000000019.Code ACM30", "Issuer_C_2D17.Id C-17",
		"Dividend_US0000000001_2F2026_2D09_2D01.PayableDate 2026-09-15"):
		assert line in text
	assert "Dividend_US0000000001_2F2026_2D09_2D01:Dividend {valid=2026-09-01" in text
	# The bond has no dividends: one gap below that instrument, not a lost scope.
	assert [(gap.target, gap.reason, gap.location) for gap in report.gaps] == [("Exchange/Dividend", "Issue.Missing", "/instruments/1")]
	assert report.stale == []


def test_dividend_record_matches_spec06():
	program = HexaBindingOperator(EXCHANGE).compile(BINDING)
	documents = asyncio.run(run({}, program.stages.DocumentsRead, [{"src": SRC, "document": FEED}]))
	record = next(item for item in documents[0]["records"] if item["type"] == "Exchange/Dividend")
	record = {key: value for key, value in record.items() if key not in ("scope", "at")}
	record["values"]["Instrument"].pop("type")
	assert record == DIVIDEND_RECORD


def test_invalid_payable_date_is_a_hole_for_that_claim_only():
	feed = json.loads(json.dumps(FEED))
	feed["instruments"][0]["dividends"][0]["payableDate"] = "2026-02-30"
	_, _, log, report = read(HexaBindingOperator(EXCHANGE), BINDING, [{"src": SRC, "document": feed}])
	handle = "Dividend_US0000000001_2F2026_2D09_2D01"
	assert not any(claim.get("p") == "PayableDate" for claim in log.claims)
	assert any(claim.get("s") == handle and claim.get("p") == "Amount" for claim in log.claims)
	gap = next(gap for gap in report.gaps if gap.reason == "DatePattern.Invalid")
	assert (gap.target, gap.handle, gap.src, gap.location) == ("Exchange/Dividend.PayableDate", handle, SRC, "/instruments/0/dividends/0")
	assert report.stale == [{"src": SRC, "s": handle, "p": "PayableDate", "reason": "DatePattern.Invalid"}]


def test_records_without_keys_are_skipped_and_reported():
	feed = json.loads(json.dumps(FEED))
	del feed["issuers"][0]["id"]
	_, _, log, report = read(HexaBindingOperator(EXCHANGE), BINDING, [{"src": SRC, "document": feed}])
	assert not any(claim.get("s", "").startswith("Issuer_") for claim in log.claims)
	assert [gap.reason for gap in report.gaps if gap.target == "Exchange/Issuer"] == ["Binding.KeyMissing"]
	# References to the issuer still name it: it is implicit until a document has it.
	assert observationsToJson(log)["instances"]["Issuer_C_2D17"] == {"type": "Exchange/Issuer"}


def test_occurrences_that_are_not_objects_abort_strict_runs_and_drop_lenient_ones():
	feed = json.loads(json.dumps(FEED))
	feed["issuers"].append("not an issuer")
	_, _, log, report = read(HexaBindingOperator(EXCHANGE, mode="lenient"), BINDING, [{"src": SRC, "document": feed}])
	assert [gap.reason for gap in report.gaps if gap.target == "Exchange/Issuer"] == ["Binding.TypeMismatch"]
	assert any(claim.get("s") == "Issuer_C_2D17" for claim in log.claims)
	program = HexaBindingOperator(EXCHANGE).compile(BINDING)
	with pytest.raises(Exception) as failure:
		asyncio.run(run({}, program.stages.BindingRead, [{"src": SRC, "document": feed}]))
	assert str(failure.value.code) == "Binding.TypeMismatch"


def test_values_that_do_not_convert_are_gaps_and_nulls_say_nothing():
	feed = json.loads(json.dumps(FEED))
	feed["instruments"][1]["bond"]["interval"] = "six"
	feed["instruments"][1]["class"] = None
	feed["instruments"][0]["code"] = None
	_, _, log, report = read(HexaBindingOperator(EXCHANGE), BINDING, [{"src": SRC, "document": feed}])
	bond = {claim["p"]: claim["v"] for claim in log.claims if claim.get("s") == "Instrument_US0000000019" and "p" in claim}
	assert "PaymentInterval" not in bond and "Class" not in bond
	# `code ?? ticker` with a null code and no ticker is absent: no claim, no gap.
	assert not any(claim.get("s") == "Instrument_US0000000001" and claim.get("p") == "Code" for claim in log.claims)
	assert [(gap.target, gap.reason) for gap in report.gaps if gap.handle == "Instrument_US0000000019"] == [("Exchange/Instrument.PaymentInterval", "Onto.IntegerText.Invalid")]


def test_null_policies_claim_null_or_unknown():
	text = specExample("spec-04-mapping", 2).replace("  Class <- class\n", "  Class <- class {null=unknown}\n").replace("  Name <- trim(name)\n", "  Name <- trim(name) {null=absent}\n")
	binding = loadBinding(EXCHANGE, Source("b", text))
	feed = json.loads(json.dumps(FEED))
	feed["instruments"][0]["class"] = None
	feed["instruments"][0]["name"] = None
	_, _, log, _ = read(HexaBindingOperator(EXCHANGE), binding, [{"src": SRC, "document": feed}])
	values = {claim["p"]: claim["v"] for claim in log.claims if claim.get("s") == "Instrument_US0000000001" and "p" in claim}
	assert values["Class"] == {"unknown": True} and values["Name"] is None


def test_header_null_applies_to_direct_and_transformed_reads_unless_overridden():
	text = specExample("spec-04-mapping", 2).replace("@binding Exchange", "@binding Exchange null=unknown")
	text = text.replace("  Class <- class\n", "  Class <- class {null=absent}\n")
	feed = json.loads(json.dumps(FEED))
	feed["instruments"][0].update({"class": None, "name": None})
	_, _, log, _ = read(HexaBindingOperator(EXCHANGE), loadBinding(EXCHANGE, Source("b", text)), [{"src": SRC, "document": feed}])
	values = {claim["p"]: claim["v"] for claim in log.claims if claim.get("s") == "Instrument_US0000000001" and "p" in claim}
	assert values["Class"] is None and values["Name"] == {"unknown": True}


def test_documents_of_a_run_are_aliased_in_order_and_keep_their_own_gaps():
	feed = json.loads(json.dumps(FEED))
	second = {"asOf": "2026-11-11", "issuers": [{"code": "NOID"}], "instruments": []}
	_, result, log, report = read(HexaBindingOperator(EXCHANGE), BINDING, [{"src": SRC, "document": feed}, {"src": "feed:b", "document": second}])
	assert observationsToJson(log)["sources"] == {"d1": SRC, "d2": "feed:b"}
	assert {(gap.src, gap.reason) for gap in report.gaps} == {(SRC, "Issue.Missing"), ("feed:b", "Binding.KeyMissing")}


def test_valid_dates_every_claim_of_a_document_and_a_scope_its_own_existence():
	# A snapshot: everything it says holds as at its date; a dividend exists as of its ex-date all the same.
	text = specExample("spec-04-mapping", 2).replace("@at <- asOf\n", "@at <- asOf\n@valid <- asOf\n")
	_, _, log, _ = read(HexaBindingOperator(EXCHANGE), loadBinding(EXCHANGE, Source("b", text)), [{"src": SRC, "document": FEED}])
	dividends = {handle for handle, item in log.instances.items() if item["type"] == "Exchange/Dividend"}
	own = [claim for claim in log.claims if claim.get("exists") and claim["s"] in dividends]
	assert own and all(claim["valid"] != FEED["asOf"] for claim in own)
	assert {claim.get("valid") for claim in log.claims if claim not in own} == {FEED["asOf"]}


def test_json_null_outside_the_record_is_absent():
	# A null document field is not present: `@at` takes the run's time, and `??` falls through it.
	feed = {**FEED, "asOf": None, "published": FEED["asOf"]}
	text = specExample("spec-04-mapping", 2).replace("@at <- asOf\n", "@at <- asOf\n@valid <- asOf ?? published\n")
	ops = HexaBindingOperator(EXCHANGE)
	program = ops.compile(loadBinding(EXCHANGE, Source("b", text)))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-11T09:00:00Z"}, program.stages.BindingRead, [{"src": SRC, "document": feed}]))
	log, report = ops.result(program, result)
	assert {gap.reason for gap in report.gaps} == {"Issue.Missing"}  # the example's bond without dividends
	assert {claim["at"] for claim in log.claims} == {"2026-11-11T09:00:00Z"}
	assert {claim["valid"] for claim in log.claims if not claim.get("exists")} == {FEED["asOf"]}


def test_run_time_comes_from_the_clock_effect_without_at():
	text = specExample("spec-04-mapping", 2).replace("@at <- asOf\n", "")
	binding = loadBinding(EXCHANGE, Source("b", text))
	ops = HexaBindingOperator(EXCHANGE)
	program = ops.compile(binding)
	calls = []
	env = {"ClockRead": lambda context: calls.append(1) or "2026-11-11T09:00:00Z", "record": True}
	result = asyncio.run(run(env, program.stages.BindingRead, [{"src": SRC, "document": FEED}]))
	log, _ = ops.result(program, result)
	assert calls == [1] and {claim["at"] for claim in log.claims} == {"2026-11-11T09:00:00Z"}
	journal = [{"strand": "", "seq": 0, "operation": "ClockRead", "arguments": [], "result": "2026-11-11T09:00:00Z"}]
	replayed = asyncio.run(run({"replay": journal}, program.stages.BindingRead, [{"src": SRC, "document": FEED}]))
	assert replayed["value"]["log"] == result["value"]["log"]


def test_csv_rows_read_under_root_lists():
	rows = [{"date": "2026-11-10", "isin": "US0000000001", "name": "Acme", "asset class": "Equity", "side": "Buy", "quantity": "100", "value": "4200.50"}]
	_, _, log, report = read(HexaBindingOperator(SHEET), SHEET_BINDING, [{"src": "sheet:1", "document": rows}], CLOCK)
	values = {claim["p"]: claim["v"] for claim in log.claims if "p" in claim}
	assert values == {"AssetClass": "Equity", "Date": "2026-11-10", "Isin": "US0000000001", "Name": "Acme", "Quantity": "100", "Side": "Buy", "Value": "4200.5"}
	assert report.gaps == []
	assert {claim["s"] for claim in log.claims} == {"PositionRow_2026_2D11_2D10_2FUS0000000001_2FBuy"}


def test_functions_from_libraries_and_collections():
	ontology = loadOntology([Source("t.onto", "@ontology HexT rev=v1\nKind = A|B\nItem\n  Code Text\n  * Tags Text\n  Kind Kind\n  Label Text\n  Size Integer\n")])
	library = loadFunctions([ontology], [Source("t.fn", "@functions HexLib rev=v1\n@use HexT as T\n@fn KindOf Text -> T/Kind\n  a => A\n")])
	binding = loadBinding(ontology, Source("b", "@binding HexT\n@use HexLib as L\n\nItem <- items[*] {id=code}\n  Code <- upper(code)\n  Kind <- L/KindOf(kind)\n  Label <- concat(code, \"-\", kind)\n  Size <- size\n  Tags <- tags[*]\n"), libraries=[library])
	ops = HexaBindingOperator(ontology, libraries=[library], implementations={"HexLib/KindOf": lambda value: value.upper()})
	document = {"items": [{"code": "x", "kind": "a", "tags": ["b", "a", "b"], "size": 2}, {"code": "y", "kind": "zz", "tags": [], "size": 2.5}]}
	_, _, log, report = read(ops, binding, [{"src": "s", "document": document}], CLOCK)
	values = {(claim["s"], claim["p"]): claim["v"] for claim in log.claims if "p" in claim}
	assert values[("Item_x", "Tags")] == {"set": ["a", "b"]} and values[("Item_y", "Tags")] == {"set": []}
	assert values[("Item_x", "Kind")] == "A" and values[("Item_x", "Code")] == "X" and values[("Item_x", "Label")] == "x-a"
	assert ("Item_y", "Kind") not in values and ("Item_y", "Size") not in values
	assert {(gap.target, gap.reason) for gap in report.gaps} == {("HexT/Item.Kind", "HexLib.KindOf.Invalid"), ("HexT/Item.Size", "Onto.IntegerText.Invalid")}


@pytest.mark.parametrize("withInverse", [False, True])
def test_compiled_programs_keep_their_function_implementations(withInverse):
	ontology = loadOntology([Source("t.onto", "@ontology Isolated\nItem\n  Label Text\n")])
	functions = "@functions IsolatedFunctions\n@fn Convert Text -> Text"
	if withInverse:
		functions += " {inverse=Restore}\n  hello => first:hello\n@fn Restore Text -> Text\n  first:hello => hello"
	else:
		functions += "\n  hello => first:hello"
	library = loadFunctions([ontology], [Source("t.fn", functions + "\n")])
	binding = loadBinding(ontology, Source("t.bind", "@binding Isolated\n@use IsolatedFunctions as F\n\nItem <- items[*] {id=id}\n  Label <- F/Convert(label)\n"), libraries=[library])
	firstOps = HexaBindingOperator(ontology, libraries=[library], implementations={
		"IsolatedFunctions/Convert": lambda value: "first:" + value,
		"IsolatedFunctions/Restore": lambda value: value.removeprefix("first:"),
	})
	first = firstOps.compile(binding)
	encoding = programEncoding(first)
	secondOps = HexaBindingOperator(ontology, libraries=[library], implementations={
		"IsolatedFunctions/Convert": lambda value: "second:" + value,
		"IsolatedFunctions/Restore": lambda value: value.removeprefix("second:"),
	})
	second = secondOps.compile(binding)
	assert programEncoding(first) == programEncoding(second) == encoding
	documents = [{"src": "s", "document": {"items": [{"id": "x", "label": "hello"}]}}]

	async def readBoth():
		return await asyncio.gather(*(run(CLOCK, program.stages.BindingRead, documents) for program in (first, second, first)))

	results = asyncio.run(readBoth())
	assert [[claim["v"] for claim in result["value"]["log"]["claims"] if claim.get("p") == "Label"] for result in results] == [
		["first:hello"], ["second:hello"], ["first:hello"],
	]
	if withInverse:
		writers = [ops.compileWrite(binding) for ops in (firstOps, secondOps)]
		for writer, result in zip(writers, results):
			written = asyncio.run(run(CLOCK | {"DocumentPreviousRead": lambda request, context: None}, writer.stages.BindingWrite,
				{"src": "s", "state": result["value"]["log"]}))
			assert written["documents"][0]["document"] == {"items": [{"label": "hello"}]}


def test_functional_forms_match_the_operator():
	program = bindingCompile(EXCHANGE, BINDING, mode="lenient")
	result = asyncio.run(run({}, program.stages.BindingRead, [{"src": SRC, "document": FEED}]))
	log, report = bindingResult(EXCHANGE, program, result)
	assert claims(log) == claims(read(HexaBindingOperator(EXCHANGE, mode="lenient"), BINDING, [{"src": SRC, "document": FEED}])[2])


# EOF
