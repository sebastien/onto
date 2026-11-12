"""Module: hexa mapping tests — handles, unfolding, metadata, conflict variants and re-running of mappings (spec-06)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import (  # noqa: E402
	Source, loadBinding, loadFunctions, loadMapping, loadOntology, observationsToJson, printObservationsState, reconcileObservations,
)
from onto.integrations.hexa.compiler import CompileError  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, HexaMappingOperator, mappingCompile, mappingResult  # noqa: E402
from onto.integrations.hexa.unfold import StateIndex, Unfolder, intersect  # noqa: E402
from onto.referential import loadReferential  # noqa: E402
from tests._helpers import _specExample  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", _specExample("spec-04-mapping", 1))])
FINANCE = loadOntology([Source("finance.onto", _specExample("spec-01-ontology"))])
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", _specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", _specExample("spec-04-mapping", 4))])
BINDING = loadBinding(EXCHANGE, Source("exchange.bind", _specExample("spec-04-mapping", 2)))
MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", _specExample("spec-04-mapping", 5)), libraries=[MARKETS], referentials=[REFERENTIAL])
FEED = json.loads(_specExample("spec-04-mapping", 0, "json"))
TREE = json.loads(_specExample("spec-06-hexa", 1, "json"))
SRC = "feed:instruments/2026-11-10"
FREQUENCIES = {"1": "Monthly", "3": "Quarterly", "6": "Biannually", "12": "Yearly"}
IMPLEMENTATIONS = {
	"Markets/FrequencyFromInterval": lambda value: FREQUENCIES[value],
	"Markets/IntervalFromFrequency": lambda value: {name: key for key, name in FREQUENCIES.items()}[value],
}
CLOCK = {"ClockRead": lambda context: "2026-11-11"}
BOND = "Instrument_US0000000019"


def state(*documents) -> dict:
	"""The reconciled state of the feed's documents, read by the spec-04 binding."""
	ops = HexaBindingOperator(EXCHANGE)
	program = ops.compile(BINDING)
	log, _ = ops.result(program, asyncio.run(run({}, program.stages.BindingRead, list(documents or [{"src": SRC, "document": FEED}]))))
	return observationsToJson(reconcileObservations(EXCHANGE, log))


def operator(mode="strict", referential=REFERENTIAL):
	return HexaMappingOperator(EXCHANGE, FINANCE, referential=referential, mode=mode, libraries=[MARKETS], implementations=IMPLEMENTATIONS)


def mapped(data, ops=None):
	ops = ops or operator()
	program = ops.compile(MAPPING)
	result = asyncio.run(run(CLOCK, program.stages.MappingRead, data))
	return program, result, *ops.result(program, result)


def values(log, handle) -> dict:
	return {claim["p"]: claim["v"] for claim in log.claims if claim.get("s") == handle and "p" in claim}


# -----------------------------------------------------------------------------
#
# UNFOLDING AND HANDLES
#
# -----------------------------------------------------------------------------


def test_bond_unfolds_into_the_spec06_tree():
	program = operator().compile(MAPPING)
	plan = next(item for item in program.plans if item.name == "InstrumentInstrument")
	index = StateIndex(state(), program.model)
	occurrence = Unfolder(index, {"Issuer_C_2D17": "Company_ACME", BOND: BOND}).occurrence(plan, BOND)
	assert occurrence["value"] == TREE
	assert occurrence["meta"]["/Class"] == {"src": SRC, "at": "2026-11-10"}
	assert occurrence["conflicts"] == {} and occurrence["location"] == "/InstrumentInstrument/Instrument_US0000000019"


def test_handles_follow_the_referential_or_are_source_qualified():
	_, result, _, report = mapped(state())
	correspondence = result["value"]["correspondence"]
	assert correspondence["Issuer_C_2D17"] == "Company_ACME"
	assert correspondence[BOND] == BOND
	# Finance/Dividend has no policy: its handle is qualified by the input's scope.
	assert correspondence["Dividend_US0000000001_2F2026_2D09_2D01"] == "Dividend_Exchange_2FUS0000000001_2F2026_2D09_2D01"
	assert report.correspondence == correspondence
	_, result, _, _ = mapped(state(), operator(referential=None))
	assert result["value"]["correspondence"]["Issuer_C_2D17"] == "Company_Exchange_2FC_2D17"


def test_policies_needing_a_registry_are_unsupported():
	minted = loadReferential([FINANCE, EXCHANGE], [Source("m.ref", "@referential Minted rev=2026-11-10\n@use Finance as F\n\nF/Company minted\n")])
	text = _specExample("spec-04-mapping", 5).replace("referential=MarketIds", "referential=Minted")
	mapping = loadMapping(EXCHANGE, FINANCE, Source("m", text), libraries=[MARKETS], referentials=[minted])
	with pytest.raises(CompileError) as error:
		HexaMappingOperator(EXCHANGE, FINANCE, referential=minted, libraries=[MARKETS]).compile(mapping)
	assert str(error.value.code) == "Mapping.PolicyUnsupported"


# -----------------------------------------------------------------------------
#
# CLAIMS
#
# -----------------------------------------------------------------------------


def test_exchange_to_finance_gives_the_spec04_claims():
	_, _, log, report = mapped(state())
	text = printObservationsState(FINANCE, reconcileObservations(FINANCE, log))
	for line in ("Company_ACME:Company", "  Code ACME", "  RegisteredName Acme Corporation Ltd", "Instrument_US0000000019:Instrument[Bond]",
		"  AssetClass Bond", "  Bond.CouponRate 5.25", "  Bond.InterestFrequency Biannually", "  Bond.MaturityDate 2030-06-15",
		"  Code ACM30", "  Isin US0000000019", "  Name Acme 5.25% 2030", "Company_ACME issues Instrument_US0000000019"):
		assert line in text
	data = observationsToJson(log)
	assert {(claim["at"], claim["by"], data["sources"][claim["src"]]) for claim in data["claims"]} == {("2026-11-11", "map:Exchange->Finance", SRC)}
	assert values(log, "Dividend_Exchange_2FUS0000000001_2F2026_2D09_2D01")["Payer"] == {"ref": "Company_ACME"}
	assert report.gaps == [] and report.mixed == []


def test_conditions_qualifiers_and_existence_validity():
	_, _, log, _ = mapped(state())
	equity = values(log, "Instrument_US0000000001")
	assert "Bond.CouponRate" not in equity and equity["AssetClass"] == "Equity"
	assert not any(claim.get("facet") == "Bond" and claim["s"] == "Instrument_US0000000001" for claim in log.claims)
	dividend = next(claim for claim in log.claims if claim.get("exists") and claim["s"].startswith("Dividend_"))
	assert dividend["valid"] == "2026-09-01"


def test_conflicting_class_fans_out_asset_class_and_gaps_the_bond_lines():
	other = json.loads(json.dumps(FEED))
	other["instruments"][1]["class"] = "E"
	data = state({"src": SRC, "document": FEED}, {"src": "feed:other", "document": other})
	_, result, log, report = mapped(data)
	classes = sorted((claim["v"], observationsToJson(log)["sources"][claim["src"]]) for claim in log.claims if claim.get("s") == BOND and claim.get("p") == "AssetClass")
	assert classes == [("Bond", SRC), ("Equity", "feed:other")]
	bond = values(log, BOND)
	assert not any(key.startswith("Bond.") for key in bond)
	assert not any(claim.get("facet") == "Bond" for claim in log.claims if claim.get("s") == BOND)
	assert sorted(gap.target for gap in report.gaps if gap.reason == "Mapping.InputConflicting") == [
		"Finance/Instrument.Bond.CouponRate", "Finance/Instrument.Bond.InterestFrequency", "Finance/Instrument.Bond.MaturityDate", "Finance/Instrument[Bond]"]
	assert all(item["s"] == BOND for item in report.stale)
	reconcileObservations(FINANCE, log)


def test_mixed_provenance_takes_the_source_input_and_is_reported():
	text = _specExample("spec-04-mapping", 5).replace("  Name <- Name\n", "  Name <- concat(Code, Name) {src=Name}\n")
	mapping = loadMapping(EXCHANGE, FINANCE, Source("m", text), libraries=[MARKETS], referentials=[REFERENTIAL])
	data = state()
	for claim in data["claims"]:
		if claim.get("s") == BOND and claim.get("p") == "Name":
			claim["src"] = "n"
	data["sources"]["n"] = "names:1"
	ops = operator()
	program = ops.compile(mapping)
	log, report = ops.result(program, asyncio.run(run(CLOCK, program.stages.MappingRead, data)))
	claim = next(claim for claim in log.claims if claim.get("s") == BOND and claim.get("p") == "Name")
	assert observationsToJson(log)["sources"][claim["src"]] == "names:1"
	assert report.mixed == [{"target": "Finance/Instrument.Name", "handle": BOND, "src": "names:1", "sources": [SRC]}]


def test_unmapped_references_and_failed_functions_are_gaps():
	data = state()
	for claim in data["claims"]:
		if claim.get("s") == BOND and claim.get("p") == "PaymentInterval":
			claim["v"] = "5"
	data["claims"] = [claim for claim in data["claims"] if not (claim.get("s") == "Issuer_C_2D17" and claim.get("p") == "Code")]
	_, _, log, report = mapped(data)
	reasons = {(gap.target, gap.reason) for gap in report.gaps}
	assert ("Finance/Instrument.Bond.InterestFrequency", "Markets.FrequencyFromInterval.Invalid") in reasons
	assert ("Finance/Instrument.issuedBy", "Mapping.ReferenceUnmapped") in reasons
	assert ("Finance/Company", "Binding.KeyMissing") in reasons
	assert not any("rel" in claim for claim in log.claims)


def test_validity_intersection():
	assert intersect(["2026-01-01..2026-12-31", "2026-06-01.."]) == "2026-06-01..2026-12-31"
	assert intersect(["2026-01-01", "2026-01-01"]) == "2026-01-01"
	assert intersect(["..2026-01-01", "2026-02-01.."]) is None


def test_functional_forms_and_json_mappings():
	from onto import mappingToJson
	program = mappingCompile(EXCHANGE, FINANCE, mappingToJson(MAPPING), REFERENTIAL, libraries=[MARKETS], implementations=IMPLEMENTATIONS)
	log, _ = mappingResult(EXCHANGE, FINANCE, program, asyncio.run(run(CLOCK, program.stages.MappingRead, state())))
	assert len(log.claims) == len(mapped(state())[2].claims)


# -----------------------------------------------------------------------------
#
# RE-RUNNING
#
# -----------------------------------------------------------------------------


def test_mapping_runs_retract_what_the_input_no_longer_says():
	ops = operator()
	program = ops.compile(MAPPING)
	first = ops.outcome(program, asyncio.run(run(CLOCK | {"OutputPreviousRead": lambda request, context: None, "RetractionsPendingRead": lambda request, context: []},
		program.stages.MappingRun, state())))
	assert first.status == "Applied" and first.log["retractions"] == []
	changed = json.loads(json.dumps(FEED))
	del changed["instruments"][1]["name"]
	env = CLOCK | {"OutputPreviousRead": lambda request, context: first.log if request == {"by": "map:Exchange->Finance", "src": SRC} else None,
		"RetractionsPendingRead": lambda request, context: []}
	second = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, state({"src": SRC, "document": changed}))))
	assert [(item["s"], item["p"]) for item in second.log["retractions"]] == [(BOND, "Name")]
	assert second.log["claims"] == []


# EOF
