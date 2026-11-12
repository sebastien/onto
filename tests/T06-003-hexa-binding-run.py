"""Module: hexa re-running tests — retractions, stale slots, completeness, safeguards, confirmation and outcomes (spec-06)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import Source, loadBinding, loadOntology, observationsToJson, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, bindingApprove  # noqa: E402
from onto.integrations.hexa.runs import outputLog  # noqa: E402
from tests._helpers import _specExample  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", _specExample("spec-04-mapping", 1))])
TEXT = _specExample("spec-04-mapping", 2)
FEED = json.loads(_specExample("spec-04-mapping", 0, "json"))
SRC = "feed:instruments"
BOND = "Instrument_US0000000019"
EQUITY = "Instrument_US0000000001"
DIVIDEND = "Dividend_US0000000001_2F2026_2D09_2D01"


class Store:
	"""A host store: appended logs and pending retractions per (by, src)."""

	def __init__(self):
		self.logs: dict[str, list[dict]] = {}
		self.pending: dict[str, list[dict]] = {}
		self.requests: list[dict] = []

	def env(self) -> dict:
		return {"OutputPreviousRead": self.previous, "RetractionsPendingRead": lambda request, context: self.pending.get(request["src"], []),
			"ClockRead": lambda context: "2026-11-12T00:00:00Z"}

	def previous(self, request, context):
		self.requests.append(request)
		logs = self.logs.get(request["src"])
		if not logs:
			return None
		claims, retractions = [], []
		for log in logs:
			sources = log["sources"]
			claims += [{**item, "src": sources[item["src"]], **({"of": sources[item["of"]]} if "of" in item else {})} for item in log["claims"]]
			retractions += [{**item, "src": sources[item["src"]], **({"of": sources[item["of"]]} if "of" in item else {})} for item in log["retractions"]]
		instances = {}
		for log in logs:
			instances |= log["instances"]
		return outputLog({**logs[-1], "instances": instances, "sources": {}}, claims, retractions)

	def apply(self, outcome, src=SRC):
		if outcome.status == "Applied":
			self.logs.setdefault(src, []).append(outcome.log)
			self.pending[src] = outcome.held


def binding(text: str = TEXT):
	return loadBinding(EXCHANGE, Source("exchange.bind", text))


def feed(**changes) -> dict:
	data = json.loads(json.dumps(FEED))
	for key, value in changes.items():
		data[key] = value
	return data


def runOnce(store, document, mode="strict", text=TEXT, src=SRC, replaces=None):
	ops = HexaBindingOperator(EXCHANGE, mode=mode)
	program = ops.compile(binding(text))
	item = {"src": src, "document": document} | ({"replaces": replaces} if replaces else {})
	result = asyncio.run(run(store.env(), program.stages.BindingRun, [item]))
	return ops, ops.outcome(program, result)


def retractions(outcome) -> list[tuple]:
	return sorted((item.get("s") or item.get("rel"), item.get("p") or item.get("facet") or ("exists" if item.get("exists") else "")) for item in outcome.log["retractions"])


# -----------------------------------------------------------------------------
#
# RE-RUNNING
#
# -----------------------------------------------------------------------------


def test_first_run_claims_everything_and_an_unchanged_rerun_nothing():
	store = Store()
	_, first = runOnce(store, feed())
	assert first.status == "Applied" and first.held == [] and first.log["retractions"] == []
	assert len(first.log["claims"]) == 25
	store.apply(first)
	_, second = runOnce(store, feed())
	assert second.log["claims"] == [] and second.log["retractions"] == []
	assert store.requests[-1] == {"by": "bind:Exchange", "src": SRC}


def test_changed_values_are_claimed_and_removed_fields_retracted():
	store = Store()
	store.apply(runOnce(store, feed())[1])
	data = feed()
	data["instruments"][1]["name"] = "Acme 5.30% 2030"
	del data["instruments"][0]["dividends"][0]["taxCredit"]
	_, outcome = runOnce(store, data)
	assert [(claim["s"], claim["p"], claim["v"]) for claim in outcome.log["claims"]] == [(BOND, "Name", "Acme 5.30% 2030")]
	assert retractions(outcome) == [(DIVIDEND, "TaxCredit")]
	retraction = outcome.log["retractions"][0]
	assert (outcome.log["sources"][retraction["src"]], retraction["by"], retraction["at"]) == (SRC, "bind:Exchange", "2026-11-10")


def test_completeness_decides_what_absence_retracts():
	data = feed()
	data["instruments"] = data["instruments"][:1]
	del data["instruments"][0]["name"]
	store = Store()
	store.apply(runOnce(store, feed())[1])
	_, outcome = runOnce(store, data, mode="lenient")
	assert retractions(outcome) == [(EQUITY, "Name"), (BOND, "exists")]
	store = Store()
	store.apply(runOnce(store, feed(), text=TEXT.replace("format=json", "format=json complete=record"))[1])
	_, outcome = runOnce(store, data, text=TEXT.replace("format=json", "format=json complete=record"))
	assert retractions(outcome) == [(EQUITY, "Name")]
	store = Store()
	store.apply(runOnce(store, feed(), text=TEXT.replace("format=json", "format=json complete=none"))[1])
	_, outcome = runOnce(store, data, text=TEXT.replace("format=json", "format=json complete=none"))
	assert retractions(outcome) == []


def test_stale_slots_are_kept_and_reported():
	store = Store()
	store.apply(runOnce(store, feed())[1])
	data = feed()
	data["instruments"][0]["dividends"][0]["payableDate"] = "2026-02-30"
	_, outcome = runOnce(store, data)
	assert retractions(outcome) == []
	assert outcome.report.stale == [{"src": SRC, "s": DIVIDEND, "p": "PayableDate", "reason": "DatePattern.Invalid"}]


def test_unidentified_records_protect_their_type_from_instance_retractions():
	store = Store()
	store.apply(runOnce(store, feed())[1])
	data = feed()
	del data["instruments"][1]["isin"]
	_, outcome = runOnce(store, data)
	assert (BOND, "exists") not in retractions(outcome)
	assert [gap.reason for gap in outcome.report.gaps if gap.target == "Exchange/Instrument"] == ["Binding.KeyMissing"]


def test_deleted_records_retract_their_instance_whatever_completeness_says():
	text = TEXT.replace("format=json", "format=json complete=none").replace("Issuer <- issuers[*] {id=id}", "Issuer <- issuers[*] {id=id, deleted=status:gone}")
	store = Store()
	store.apply(runOnce(store, feed(), text=text)[1])
	data = feed()
	data["issuers"][0]["status"] = "gone"
	_, outcome = runOnce(store, data, text=text)
	assert retractions(outcome) == [("Issuer_C_2D17", "exists")]


# -----------------------------------------------------------------------------
#
# SAFEGUARDS AND APPROVAL
#
# -----------------------------------------------------------------------------


CEILING = TEXT.replace("format=json", "format=json retract=10%")


def test_retractions_over_the_ceiling_are_held():
	store = Store()
	store.apply(runOnce(store, feed(), text=CEILING)[1])
	data = feed(instruments=[])
	_, strict = runOnce(store, data, text=CEILING)
	assert strict.status == "Pending" and strict.log["retractions"] == [] and len(strict.held) == 3
	assert "retract" in strict.report.safeguards
	# 3 instance retractions of 25 previous slots stay under the default 20% ceiling.
	assert runOnce(store, data)[1].status == "Applied"
	_, lenient = runOnce(store, data, mode="lenient", text=CEILING)
	assert lenient.status == "Applied" and lenient.log["retractions"] == [] and len(lenient.held) == 3


def test_lenient_confirmation_admits_repeated_retractions_and_lapses_others():
	store = Store()
	store.apply(runOnce(store, feed(), text=CEILING)[1])
	_, held = runOnce(store, feed(instruments=[]), mode="lenient", text=CEILING)
	store.apply(held)
	_, confirmed = runOnce(store, feed(instruments=[]), mode="lenient", text=CEILING)
	assert confirmed.held == [] and len(confirmed.report.confirmed) == 3
	assert {item["approved"] for item in confirmed.log["retractions"]} == {"confirm:1"}
	assert all(item["at"] == "2026-11-10" for item in confirmed.log["retractions"])
	store2 = Store()
	store2.apply(runOnce(store2, feed(), text=CEILING)[1])
	store2.apply(runOnce(store2, feed(instruments=[]), mode="lenient", text=CEILING)[1])
	_, recovered = runOnce(store2, feed(), mode="lenient", text=CEILING)
	assert len(recovered.lapsed) == 3 and recovered.log["retractions"] == []


def test_a_person_approves_a_pending_strict_run():
	store = Store()
	store.apply(runOnce(store, feed(), text=CEILING)[1])
	ops, pending = runOnce(store, feed(instruments=[]), text=CEILING)
	log = ops.approve(pending, "person:curator")
	assert {claim["approved"] for claim in observationsToJson(log)["retractions"]} == {"person:curator"}
	state = reconcileObservations(EXCHANGE, log)
	assert bindingApprove(EXCHANGE, pending, "person:curator").retractions == log.retractions
	assert all(not claim.get("s", "").startswith("Instrument_") for claim in state.claims)


def test_empty_input_and_older_snapshots():
	store = Store()
	store.apply(runOnce(store, feed())[1])
	empty = {"asOf": "2026-11-11", "instruments": [], "issuers": []}
	with pytest.raises(Exception) as failure:
		runOnce(store, empty)
	assert str(failure.value.code) == "Binding.InputEmpty"
	_, lenient = runOnce(store, empty, mode="lenient")
	assert lenient.log["retractions"] == [] and lenient.held == [] and "Binding.InputEmpty" in lenient.report.safeguards
	older = feed(asOf="2026-11-09")
	older["instruments"][1]["name"] = "Changed"
	older["instruments"] = older["instruments"][1:]
	with pytest.raises(Exception) as failure:
		runOnce(store, older)
	assert str(failure.value.code) == "Binding.SnapshotOlder"
	_, lenient = runOnce(store, older, mode="lenient")
	assert lenient.log["claims"] == [] and lenient.log["retractions"] == []


def test_snapshots_replacing_a_previous_token():
	store = Store()
	store.apply(runOnce(store, feed(), src="feed:2026-11-10")[1], src="feed:2026-11-10")
	data = feed(asOf="2026-11-11")
	del data["instruments"][1]["name"]
	_, outcome = runOnce(store, data, src="feed:2026-11-11", replaces="feed:2026-11-10")
	assert store.requests[-1] == {"by": "bind:Exchange", "src": "feed:2026-11-10"}
	assert retractions(outcome) == [(BOND, "Name")]
	retraction = outcome.log["retractions"][0]
	assert outcome.log["sources"][retraction["of"]] == "feed:2026-11-10" and outcome.log["sources"][retraction["src"]] == "feed:2026-11-11"


# EOF
