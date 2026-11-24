"""Module: hexa view read tests — a retrieval as one hexa run: waves of reads, requests, failed reads, journals and retries (spec-06)."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")

from hexa.combinators import backoff  # noqa: E402
from hexa.http import Request, http  # noqa: E402

from onto import Source, loadBinding, loadFunctions, loadMapping, loadOntology  # noqa: E402
from onto.integrations.hexa import HexaViewOperator, ViewDocument, ViewRead, ViewReadError  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.ontology import ViewInput  # noqa: E402
from onto.referential import loadReferential  # noqa: E402
from tests.helpers import specExample  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
FINANCE = loadOntology([Source("finance.onto", specExample("spec-01-ontology"))])
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", specExample("spec-04-mapping", 4))])
MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", specExample("spec-04-mapping", 5)), libraries=[MARKETS], referentials=[REFERENTIAL])
FEED = json.loads(specExample("spec-04-mapping", 0, "json"))
SRC = "feed:instruments/2026-11-10"
FREQUENCIES = {"1": "Monthly", "3": "Quarterly", "6": "Biannually", "12": "Yearly"}
IMPLEMENTATIONS = {
	"Markets/FrequencyFromInterval": lambda value: FREQUENCIES[value],
	"Markets/IntervalFromFrequency": lambda value: {name: key for key, name in FREQUENCIES.items()}[value],
}
TARGET = loadOntology([Source("finance.onto", specExample("spec-01-ontology") + """
@use Exchange as E
@view IssuerBonds(issuerId: E/Issuer.Id)
  issuer: Company
  bonds: Instrument = issuer -> issues where AssetClass=Bond
  issuer.issues: Instrument
  bonds.Name
""")], [EXCHANGE])
# The issuer's holdings link its instruments; each instrument's own read gives its class and name.
HOLDINGS = loadBinding(EXCHANGE, Source("holdings.bind", specExample("spec-04-mapping", 2).replace("  Name <- trim(name)\n", "").replace("  Class <- class\n", "")))
DETAILS = loadBinding(EXCHANGE, Source("details.bind", """@binding Exchange format=json
@at <- asOf
Instrument <- instruments[*] {id=isin}
  Class <- class
  Name <- trim(name)
"""))
ISIN = ViewInput("isin", "Exchange/Instrument", "Isin")
READS = {"Holdings": ViewRead(ViewInput("issuerId", "Exchange/Issuer", "Id"), [HOLDINGS], ISIN), "Instrument": ViewRead(ISIN, [DETAILS])}
SEED, FIELDS, NOW = {"issuerId": "C-17"}, ["bonds.Name"], "2026-11-11"
CODES = {row["id"]: row["code"] for row in FEED["issuers"]}


class OutsideView(ViewReadError):
	reason = "OutsideView"


class Busy(ViewReadError):
	reason = "Busy"
	transient = True


def document(step: str, value: str) -> ViewDocument:
	"""The feed for the holdings read, else the one instrument asked for."""
	if step == "Holdings":
		return ViewDocument(copy.deepcopy(FEED), SRC)
	instrument, = (row for row in FEED["instruments"] if row["isin"] == value)
	return ViewDocument({"asOf": FEED["asOf"], "instruments": [copy.deepcopy(instrument)]}, f"feed:instrument/{value}")


def mapper() -> HexaMappingOperator:
	return HexaMappingOperator(EXCHANGE, TARGET, REFERENTIAL, libraries=[MARKETS], implementations=IMPLEMENTATIONS)


def viewOperator(fetch) -> HexaViewOperator:
	access = SimpleNamespace(fetch=fetch, describe=lambda step, value: {"path": f"/{step.lower()}/{value}"},
		rootHandle=lambda key, value, kind: "Company_" + CODES[value] if key.attr == "Id" else "Instrument_" + value,
		discover=lambda state, provides: sorted({claim["v"] for claim in state["claims"] if claim.get("p") == "Isin"}) if provides else [])
	return HexaViewOperator(mapper(), MAPPING, READS, access)


def readGaps(report: dict) -> list[dict]:
	return [gap for gap in report["gaps"] if "step" in gap and isinstance(gap.get("input"), dict)]


# The same feed as an HTTP API: an issuer's holdings, and each instrument by a POST of its ISIN.
INSTRUMENT_ONLY = """@binding Exchange format=json
@at <- asOf
Instrument <- instruments[*] {id=isin}
  %s
"""
NAMES = loadBinding(EXCHANGE, Source("names.bind", INSTRUMENT_ONLY % "Name <- trim(name)"))
CLASSES = loadBinding(EXCHANGE, Source("classes.bind", INSTRUMENT_ONLY % "Class <- class"))
INSTRUMENT_REQUEST = {"method": "POST", "path": "/instruments", "body": {"isin": "{isin}"}}
REQUESTED = {
	"Holdings": ViewRead(ViewInput("issuerId", "Exchange/Issuer", "Id"), [HOLDINGS], ISIN, request={"path": "/issuers/{issuerId}/holdings"}),
	"Names": ViewRead(ISIN, [NAMES], request=INSTRUMENT_REQUEST, source="instrument/{isin}"),
	"Classes": ViewRead(ISIN, [CLASSES], request=INSTRUMENT_REQUEST, source="instrument/{isin}"),
}


class Api(BaseHTTPRequestHandler):
	"""The feed's API; `missing` ISINs are not found."""

	requests: list = []
	missing: set = set()

	def log_message(self, *args):
		pass

	def answer(self, status, data):
		body = json.dumps(data).encode()
		self.send_response(status)
		self.send_header("content-type", "application/json")
		self.send_header("content-length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def do_GET(self):
		Api.requests.append(("GET", self.path, None))
		self.answer(200, FEED) if self.path == "/v1/issuers/C-17/holdings" else self.answer(404, {"error": "no such issuer"})

	def do_POST(self):
		body = json.loads(self.rfile.read(int(self.headers["content-length"])))
		Api.requests.append(("POST", self.path, body))
		rows = [row for row in FEED["instruments"] if row["isin"] == body.get("isin") and row["isin"] not in Api.missing]
		self.answer(200, {"asOf": FEED["asOf"], "instruments": rows}) if rows else self.answer(404, {"error": "no such instrument"})


@pytest.fixture
def api():
	server = ThreadingHTTPServer(("127.0.0.1", 0), Api)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	Api.requests, Api.missing = [], set()
	yield f"http://127.0.0.1:{server.server_address[1]}/v1"
	server.shutdown()
	server.server_close()


def requestedOperator(base: str, **hooks) -> HexaViewOperator:
	"""A host with only identities (and `hooks`): requests, descriptions and discovered keys come from the catalogue."""
	access = SimpleNamespace(rootHandle=lambda key, value, kind: "Company_" + CODES[value] if key.attr == "Id" else "Instrument_" + value, **hooks)
	return HexaViewOperator(mapper(), MAPPING, REQUESTED, access, operations=http(base))


# -----------------------------------------------------------------------------
#
# READS
#
# -----------------------------------------------------------------------------


def test_reads_of_discovered_keys_run_together_once_their_provider_has_read():
	calls, active, peak = [], 0, 0

	async def fetch(step, value):
		nonlocal active, peak
		calls.append((step, value))
		active += 1
		peak = max(peak, active)
		await asyncio.sleep(0.01)
		active -= 1
		return document(step, value)

	report = asyncio.run(viewOperator(fetch).report("IssuerBonds", SEED, FIELDS, NOW))
	assert calls[0] == ("Holdings", "C-17") and sorted(calls[1:]) == [("Instrument", "US0000000001"), ("Instrument", "US0000000019")]
	assert peak == 2, "the two instrument reads are in flight together"
	# Receipts follow the plan, whatever order the reads completed in.
	assert [(call["step"], call["input"], call["status"]) for call in report["calls"]] == [
		("Holdings", {"issuerId": "C-17"}, "ok"), ("Instrument", {"isin": "US0000000001"}, "ok"), ("Instrument", {"isin": "US0000000019"}, "ok")]
	assert report["calls"][0]["discovered"] == {"isin": ["US0000000001", "US0000000019"]}
	assert [(fact["field"], fact["value"]) for fact in report["facts"]] == [("bonds.Name", "Acme 5.25% 2030")]
	assert readGaps(report) == []


def test_a_failed_read_is_reported_by_reason_and_message_as_the_journal_records_them():
	def fetch(step, value):
		if value == "US0000000001":
			raise OutsideView("an equity, not a bond")
		if value == "US0000000019":
			raise ValueError("garbled instrument")
		return document(step, value)

	journal = []
	report = asyncio.run(viewOperator(fetch).report("IssuerBonds", SEED, FIELDS, NOW, record=journal.append))
	assert [(call["step"], call["status"]) for call in report["calls"]] == [("Holdings", "ok"), ("Instrument", "unavailable"), ("Instrument", "unavailable")]
	# The message helps resolve the failure: the report gives it as the journal records it.
	assert readGaps(report) == [
		{"step": "Instrument", "input": {"isin": "US0000000001"}, "reason": "OutsideView", "detail": "an equity, not a bond"},
		{"step": "Instrument", "input": {"isin": "US0000000019"}, "reason": "UnreadableResponse", "detail": "garbled instrument"},
	]
	assert report["facts"] == []
	failures = {entry["arguments"][1]: (entry["failure"]["code"], entry["failure"]["detail"]) for entry in journal if "failure" in entry}
	assert failures == {"US0000000001": ("ViewRead.OutsideView", "an equity, not a bond"), "US0000000019": ("ViewRead.UnreadableResponse", "garbled instrument")}

	def forbidden(step, value):
		raise AssertionError("a replay read from the host")
	assert asyncio.run(viewOperator(forbidden).report("IssuerBonds", SEED, FIELDS, NOW, replay=journal)) == report


def test_a_transient_read_failure_is_retried_under_the_retry_policy():
	attempts = []

	def fetch(step, value):
		attempts.append(step)
		if attempts == ["Holdings"]:
			raise Busy("the feed is rebuilding")
		return document(step, value)

	journal = []
	policy = {"retry": {"default": True, "attempts": 2, "delay": backoff(0)}}
	observations = asyncio.run(viewOperator(fetch).retrieve("IssuerBonds", SEED, FIELDS, NOW, record=journal.append, policy=policy))
	assert attempts == ["Holdings", "Holdings", "Instrument", "Instrument"]
	assert [(entry["operation"], entry.get("failure", {}).get("code")) for entry in journal[:3]] == [
		("DocumentFetch", "ViewRead.Busy"), ("DelayWait", None), ("DocumentFetch", None)]
	assert [(claim["p"], claim["v"]) for claim in observations.claims if "p" in claim] == [("AssetClass", "Bond"), ("Name", "Acme 5.25% 2030")]
	attempts.clear()
	report = asyncio.run(viewOperator(fetch).report("IssuerBonds", SEED, FIELDS, NOW))
	assert readGaps(report) == [{"step": "Holdings", "input": {"issuerId": "C-17"}, "reason": "Busy", "detail": "the feed is rebuilding"}]
	assert [call["step"] for call in report["calls"]] == ["Holdings"]


# -----------------------------------------------------------------------------
#
# REQUESTS
#
# -----------------------------------------------------------------------------


def test_request_templates_send_each_distinct_request_once_through_hexa_http(api):
	engine = requestedOperator(api)
	plan = asyncio.run(engine.plan("IssuerBonds", SEED, FIELDS))
	assert [{key: step[key] for key in ("step", "method", "path") if key in step} | ({"body": step["body"]} if "body" in step else {}) for step in plan["steps"]] == [
		{"step": "Holdings", "method": "GET", "path": "/issuers/C-17/holdings"},
		{"step": "Names", "method": "POST", "path": "/instruments", "body": {"isin": "{isin}"}},
		{"step": "Classes", "method": "POST", "path": "/instruments", "body": {"isin": "{isin}"}},
	]
	report = asyncio.run(engine.report("IssuerBonds", SEED, FIELDS, NOW))
	# Names and Classes ask for the same documents: each is requested once, and both reads bind it.
	assert Api.requests[0] == ("GET", "/v1/issuers/C-17/holdings", None)
	assert sorted(Api.requests[1:], key=lambda item: item[2]["isin"]) == [("POST", "/v1/instruments", {"isin": isin}) for isin in ("US0000000001", "US0000000019")]
	assert [(call["step"], call["input"], call["status"]) for call in report["calls"]] == [("Holdings", {"issuerId": "C-17"}, "ok"),
		*((step, {"isin": isin}, "ok") for step in ("Names", "Classes") for isin in ("US0000000001", "US0000000019"))]
	assert report["calls"][1] == {"step": "Names", "input": {"isin": "US0000000001"}, "method": "POST", "path": "/instruments", "body": {"isin": "US0000000001"}, "status": "ok"}
	assert report["calls"][0]["discovered"] == {"isin": ["US0000000001", "US0000000019"]}, "the provided key's claims, by default"
	assert [(fact["field"], fact["value"], fact["source"]) for fact in report["facts"]] == [("bonds.Name", "Acme 5.25% 2030", "instrument/US0000000019")]
	observations = asyncio.run(engine.retrieve("IssuerBonds", SEED, FIELDS, NOW))
	assert set(observations.sources.values()) == {"/issuers/C-17/holdings", "instrument/US0000000019"}


def test_a_checked_response_or_a_failed_request_makes_a_read_unavailable(api):
	def check(step, value, response):
		if step == "Classes" and response["data"]["instruments"][0]["class"] == "E":
			raise OutsideView(f"{value} is an equity")
		return ViewDocument(response["data"], response["source"])

	Api.missing = {"US0000000019"}
	engine, journal = requestedOperator(api, check=check), []
	report = asyncio.run(engine.report("IssuerBonds", SEED, FIELDS, NOW))
	gaps = readGaps(report)
	assert [(gap["step"], gap["input"], gap["reason"]) for gap in gaps] == [
		("Names", {"isin": "US0000000019"}, "Request.NotFound"),
		("Classes", {"isin": "US0000000001"}, "OutsideView"),
		("Classes", {"isin": "US0000000019"}, "Request.NotFound"),
	]
	# Each with its message: the check's, and a failed request's, which names the request and quotes the response.
	assert gaps[1]["detail"] == "US0000000001 is an equity"
	for gap in (gaps[0], gaps[2]):
		assert gap["detail"].startswith("POST " + api + "/instruments: 404") and "no such instrument" in gap["detail"]
	assert report["facts"] == []
	# The failures themselves, with their messages: in the read outcomes, and a failed request's in the journal too.
	_, _, outcomes = asyncio.run(engine.runReads("IssuerBonds", SEED, FIELDS, NOW, record=journal.append))
	checked, missing = outcomes["Classes"]
	assert isinstance(checked.failure, OutsideView) and str(checked.failure) == "US0000000001 is an equity"
	assert missing.failure.code is Request.NotFound and "404" in str(missing.failure.__cause__)
	failed, = (entry for entry in journal if "failure" in entry)
	assert (failed["operation"], failed["arguments"][0]["body"], failed["failure"]["code"]) == ("RequestSend", {"isin": "US0000000019"}, "Request.NotFound")
	assert failed["failure"]["detail"].startswith("POST " + api + "/instruments: 404") and "no such instrument" in failed["failure"]["detail"]


def test_a_request_template_must_name_only_its_input():
	for request, source in (({"path": "instruments/{isin}"}, None), ({"path": "/instruments/{id}"}, None), ({"path": "/x", "verb": "GET"}, None),
		({"method": "TRACE", "path": "/x"}, None), (None, "instrument/{isin}")):
		with pytest.raises(ValueError, match="^Bad: "):
			HexaViewOperator(mapper(), MAPPING, {"Bad": ViewRead(ISIN, [NAMES], request=request, source=source)}, SimpleNamespace())


# EOF
