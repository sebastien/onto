"""Module: session tests — spec-09 page views over a CRM and a store: holders, store reads as suppliers, and changes routed
to each slot's holder."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("hexa.shapes")

from onto.store.runtime import ObservationStore  # noqa: E402

from tests.sessions import CLIENT, FINANCE, PARTITION, SEED, newStore, operator, session  # noqa: E402
from tests.store import USER, batch  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


# NOTE: Default fields are spelt by their type path where it is unambiguous, as rooted views name them.
STORE_FIELDS = ("Person.Investor.RiskTolerance", "IdentityCheck.Confirmed", "IdentityCheck.Method")
CRM_FIELDS = ("Person.Name.Surname", "Person.DateOfBirth")


def seeded(checks: int = 1) -> ObservationStore:
	"""The client's risk tolerance (seq 1) and identity checks (each: existence, Person, Method, Confirmed) in the store."""
	store = newStore()
	store.append(USER, PARTITION, {"requestId": "risk", "observations": batch(f"{CLIENT}.Investor.RiskTolerance Medium", {CLIENT: "Person"})})
	for index in range(checks):
		handle = f"IdentityCheck_C{41 + index}"
		store.append(USER, PARTITION, {"requestId": handle,
			"observations": batch(f"{handle}:IdentityCheck\n  Person {CLIENT}\n  Method InPerson\n  Confirmed true", {CLIENT: "Person"})})
	return store


def run(coroutine) -> dict:
	return json.loads(json.dumps(asyncio.run(coroutine)))


def opened(store: ObservationStore):
	item = session(store)
	asyncio.run(item.open("ClientPage", SEED))
	return item


def changed(store: ObservationStore, changes: dict) -> dict:
	"""Open the client page on `store` and apply a change set."""
	return asyncio.run(opened(store).change(changes))


# -----------------------------------------------------------------------------
#
# PLANS AND REPORTS
#
# -----------------------------------------------------------------------------


def testThePlanSuppliesStoreHeldFieldsFromTheStore() -> None:
	plan = run(operator(newStore()).plan("ClientPage", SEED))
	assert plan["holders"] == {**dict.fromkeys(CRM_FIELDS, "Crm"), **dict.fromkeys(STORE_FIELDS, "AdviserApp")}
	assert plan["writable"] == {**dict.fromkeys(CRM_FIELDS, False), **dict.fromkeys(STORE_FIELDS, True)}
	read, = [step for step in plan["steps"] if step.get("kind") == "store"]
	assert (read["step"], read["partitionKind"], read["anchor"], read["wave"]) == ("store:Client", "Client", "client", 0)
	assert {"population": "checks", "slots": ["Confirmed", "Method", "Person"], "page": {"size": 10}} in read["select"]
	assert (plan["fields"]["IdentityCheck.Confirmed"], plan["fields"]["Person.Name.Surname"], plan["gaps"]) == ("store:Client", "contact", [])


def testTheRootsStoreReadRunsBeforeTheSystemsWhenTheSeedGivesItsHandle() -> None:
	item, calls = operator(seeded()), []
	read, fetch = item.access.storeRead, item.access.fetch
	item.access.storeRead = lambda body: calls.append(("store", [entry["partition"] for entry in body["reads"]])) or read(body)
	item.access.fetch = lambda step, value: calls.append(("fetch", step)) or fetch(step, value)
	run(item.report("ClientPage", SEED))
	assert calls == [("store", [PARTITION]), ("fetch", "contact")]


def testAReportGivesEachFactItsHolder() -> None:
	report = run(operator(seeded()).report("ClientPage", SEED))
	facts = {(fact["field"], fact["subject"]): fact for fact in report["facts"]}
	surname = facts["Person.Name.Surname", CLIENT]
	assert (surname["value"], surname["holder"], surname["writable"], "partition" in surname) == ("Ngata", "Crm", False, False)
	risk = facts["Person.Investor.RiskTolerance", CLIENT]
	assert (risk["value"], risk["holder"], risk["partition"], risk["version"]) == ("Medium", "AdviserApp", PARTITION, 1)
	confirmed = facts["IdentityCheck.Confirmed", "IdentityCheck_C41"]
	assert (confirmed["value"], confirmed["holder"], confirmed["version"]) == (True, "AdviserApp", 5)
	assert (report["gaps"], report["offAuthority"]) == ([], [])


def testAClientTheStoreHoldsNothingAboutHasOnlyTheirCrmFacts() -> None:
	report = run(operator(newStore()).report("ClientPage", SEED))
	assert {fact["field"] for fact in report["facts"]} == set(CRM_FIELDS)
	assert {item["field"]: item["statuses"] for item in report["coverage"] if item["field"] == "Person.Investor.RiskTolerance"} == {
		"Person.Investor.RiskTolerance": ["empty"]}


def testAKeyedFieldHasASupplierInEachHolder() -> None:
	plan = run(operator(newStore()).plan("ClientPhones", SEED))
	field = "Person.Phones.Number"
	assert (plan["holders"][field], plan["keyedHolders"], plan["writable"][field]) == ("AdviserApp", {field: {"Phones[Mobile].Number": "Crm"}}, True)
	assert plan["fields"][field] == ["contact", "store:Client"]


def testAKeyedFieldsFactsComeFromEachHolder() -> None:
	store = seeded()
	store.append(USER, PARTITION, {"requestId": "home", "observations": batch(f"{CLIENT}.Phones[Home].Number 095550102", {CLIENT: "Person"}, ontology=FINANCE)})
	report = run(operator(store).report("ClientPhones", SEED))
	facts = {fact["value"]: fact for fact in report["facts"]}
	mobile, home = facts["0215550101"], facts["095550102"]
	assert (mobile["holder"], mobile["writable"], "version" in mobile) == ("Crm", False, False)
	assert (home["holder"], home["writable"], home["partition"], home["version"]) == ("AdviserApp", True, PARTITION, 6)
	assert report["offAuthority"] == []


def testAKeyedFieldTheStoreHoldsNothingOfStillHasTheSystemsElements() -> None:
	report = run(operator(newStore()).report("ClientPhones", SEED))
	assert [(fact["value"], fact["holder"]) for fact in report["facts"]] == [("0215550101", "Crm")]
	assert [item["statuses"] for item in report["coverage"]] == [["supplied"]]


def testStoreReadsPageTheirPopulations() -> None:
	report = run(operator(seeded(12)).report("ClientPage", SEED, ["IdentityCheck.Confirmed"]))
	assert len([fact for fact in report["facts"] if fact["field"] == "IdentityCheck.Confirmed"]) == 10
	assert list(report["pages"]) == ["checks"]


# -----------------------------------------------------------------------------
#
# CHANGES
#
# -----------------------------------------------------------------------------


def testAStoreHeldChangeAppendsAtItsVersion() -> None:
	store = seeded()
	item = opened(store)
	result = asyncio.run(item.change({"claims": [{"s": CLIENT, "p": "Investor.RiskTolerance", "v": "High", "version": 1}]}))
	assert [(fact["value"], fact["version"]) for fact in item.report["facts"] if fact["field"] == "Person.Investor.RiskTolerance"] == [("High", 6)]
	assert result["statements"] == [{"s": CLIENT, "p": "Investor.RiskTolerance", "result": "applied", "partition": PARTITION}]
	claims = store.state(USER, PARTITION, {"select": [{"s": CLIENT}]})["observations"]["claims"]
	assert [claim["v"] for claim in claims if claim.get("p") == "Investor.RiskTolerance"] == ["High"]


def testAStaleVersionConflicts() -> None:
	result = changed(seeded(), {"claims": [{"s": CLIENT, "p": "Investor.RiskTolerance", "v": "High", "version": 0}]})
	statement, = result["statements"]
	assert (statement["result"], statement["moved"]) == ("conflict", [{"s": CLIENT, "p": "Investor.RiskTolerance", "version": 1, "v": "Medium"}])


def testASystemHeldSlotIsReadOnly() -> None:
	result = changed(seeded(), {"claims": [{"s": CLIENT, "p": "Name.Surname", "v": "Ngāta", "was": "Ngata"}]})
	assert [statement["result"] for statement in result["statements"]] == ["readonly"]


def testANewMemberIsHomedByItsLinks() -> None:
	store = seeded()
	new = "IdentityCheck_N1"
	result = changed(store, {"instances": {new: {"type": "Finance/IdentityCheck"}}, "claims": [
		{"s": new, "exists": True, "version": 0}, {"s": new, "p": "Person", "v": {"ref": CLIENT}, "version": 0},
		{"s": new, "p": "Confirmed", "v": True, "version": 0}]})
	assert [(statement["result"], statement["partition"]) for statement in result["statements"]] == [("applied", PARTITION)] * 3
	assert store.partition("adviser-app", PARTITION).members[new] == "checks"


def testATypeNoKindReachesIsUnhomed() -> None:
	result = changed(seeded(), {"instances": {"Account_A1": {"type": "Finance/Account"}},
		"claims": [{"s": "Account_A1", "p": "Number", "v": "12-3456", "version": 0}]})
	assert [statement["result"] for statement in result["statements"]] == ["unhomed"]



def testARetriedAppendWhoseAnswerWasLostAppliesOnce() -> None:
	store = seeded()
	item, requests = opened(store), []

	def lost(partition: str, body: dict) -> dict:
		requests.append(body["requestId"])
		answer = store.append(USER, partition, body)
		if len(requests) == 1:
			raise OSError("answer lost")
		return answer

	item.operator.access.storeAppend = lost
	statement, = asyncio.run(item.change({"claims": [{"s": CLIENT, "p": "Investor.RiskTolerance", "v": "High", "version": 1}]}))["statements"]
	assert (statement["result"], len(requests), len(set(requests))) == ("applied", 2, 1)
	log = store.log(USER, PARTITION)["entries"]
	assert len([entry for entry in log if entry.get("p") == "Investor.RiskTolerance"]) == 2


@pytest.mark.parametrize("failures, outcome", [(1, "applied"), (2, "uncertain")])
def testAnUnansweredAppendIsRetriedOnceWithItsRequestId(failures: int, outcome: str) -> None:
	store = seeded()
	item, requests = opened(store), []

	def flaky(partition: str, body: dict) -> dict:
		requests.append(body["requestId"])
		if len(requests) <= failures:
			raise OSError("no answer")
		return store.append(USER, partition, body)

	item.operator.access.storeAppend = flaky
	statement, = asyncio.run(item.change({"claims": [{"s": CLIENT, "p": "Investor.RiskTolerance", "v": "High", "version": 1}]}))["statements"]
	assert (statement["result"], len(requests), len(set(requests))) == (outcome, 2, 1)
	assert statement.get("requestId", requests[0]) == requests[0]


# EOF
