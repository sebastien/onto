"""Module: store index tests — spec-08 "Changes" and "Indexes": a scope's change feed, and the indexes that find the
partitions whose populations hold values, kept as partitions change, for servers only."""

from __future__ import annotations

import pytest

from onto.store.runtime import Forbidden, ObservationStore, StoreError
from tests.store import BUNDLE, CHECK, FINANCE, NOW, SCOPE, USER, authorize, batch

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SERVER = {"server": True}


def authorizeServer(request):
	"""The host's server callback: only its own requests, in the store's scope."""
	if request is None:
		return None
	if not request.get("server"):
		raise Forbidden("servers only")
	return {"scope": SCOPE, "principal": "server:adviser-app"}


def newStore(**options) -> ObservationStore:
	return ObservationStore(BUNDLE, FINANCE, authorize, clock=lambda: NOW, **({"authorizeServer": authorizeServer} | options))


def check(person: str, check: str, method: str, confirmed: bool, request: str) -> dict:
	"""A batch recording an identity check of `person`."""
	return {"requestId": request, "observations": batch(f"{check}:IdentityCheck\n  Person {person}\n  Method {method}\n"
		f"  Confirmed {'true' if confirmed else 'false'}\n", known={person: "Person"})}


def stocked() -> ObservationStore:
	"""Three clients: U1 confirmed in person, U2 not confirmed electronically, U3 with a document only."""
	store = newStore()
	store.append(USER, "Client/Person_U1", CHECK)
	store.append(USER, "Client/Person_U2", check("Person_U2", "IdentityCheck_C42", "Electronic", False, "r2"))
	store.append(USER, "Client/Person_U3", {"requestId": "r3", "observations": batch("Person_U3\n  Name.Surname Ngata\n", known={"Person_U3": "Person"})})
	return store


def matching(store: ObservationStore, filter: dict, **body) -> list[str]:
	return [row["partition"] for row in store.indexQuery(SERVER, "ClientChecks", {"filter": filter, **body})["partitions"]]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testAnIndexFindsThePartitionsWhosePopulationsHoldAValue() -> None:
	store = stocked()
	assert matching(store, {"eq": ["checks.Confirmed", True]}) == ["Client/Person_U1"]
	assert matching(store, {"eq": ["checks.Confirmed", False]}) == ["Client/Person_U2"]
	assert matching(store, {"in": ["checks.Method", ["InPerson", "Electronic"]]}) == ["Client/Person_U1", "Client/Person_U2"]
	assert matching(store, {"exists": "checks.Method"}) == ["Client/Person_U1", "Client/Person_U2"]
	assert matching(store, {"and": [{"exists": "checks.Method"}, {"eq": ["checks.Method", "Electronic"]}]}) == ["Client/Person_U2"]
	answer = store.indexQuery(SERVER, "ClientChecks", {"filter": {"eq": ["checks.Confirmed", True]}})
	assert answer["partitions"] == [{"partition": "Client/Person_U1", "anchor": "Person_U1", "state": "active"}]
	assert answer["through"] == store.changes(SERVER)["through"]


def testARowFollowsItsPartitionsChanges() -> None:
	store = stocked()
	store.append(USER, "Client/Person_U1", {"requestId": "r4", "observations": batch("- IdentityCheck_C41.Confirmed true\n",
		known={"Person_U1": "Person", "IdentityCheck_C41": "IdentityCheck"})})
	assert matching(store, {"eq": ["checks.Confirmed", True]}) == []
	store.append(USER, "Client/Person_U3", check("Person_U3", "IdentityCheck_C43", "CertifiedCopy", True, "r5"))
	assert matching(store, {"eq": ["checks.Confirmed", True]}) == ["Client/Person_U3"]


def testTheChangeFeedPointsAtEachPartitionsLatestState() -> None:
	store = stocked()
	first = store.changes(SERVER)
	assert [(entry["partition"], entry["head"]) for entry in first["entries"]] == [("Client/Person_U1", 8), ("Client/Person_U2", 4), ("Client/Person_U3", 2)]
	store.append(USER, "Client/Person_U2", check("Person_U2", "IdentityCheck_C44", "InPerson", True, "r6"))
	later = store.changes(SERVER, after=first["through"], epoch=first["epoch"])
	assert [(entry["partition"], entry["head"]) for entry in later["entries"]] == [("Client/Person_U2", 8)]
	# NOTE: The feed is coalesced: a partition appears once, at its latest position.
	assert [entry["partition"] for entry in store.changes(SERVER)["entries"]] == ["Client/Person_U1", "Client/Person_U3", "Client/Person_U2"]


def testAnswersArePagedByPartition() -> None:
	store = stocked()
	page = store.indexQuery(SERVER, "ClientChecks", {"filter": {"exists": "checks.Method"}, "limit": 1})
	assert ([row["partition"] for row in page["partitions"]], page["next"]) == (["Client/Person_U1"], "Client/Person_U1")
	rest = store.indexQuery(SERVER, "ClientChecks", {"filter": {"exists": "checks.Method"}, "after": page["next"]})
	assert ([row["partition"] for row in rest["partitions"]], rest.get("next")) == (["Client/Person_U2"], None)


def testOnlyTheQueriesAnIndexCanAnswerAreRun() -> None:
	store = stocked()
	for body, check in [({"filter": {"eq": ["checks.Digest", "x"]}}, "column"), ({"filter": {"not": {"exists": "checks.Method"}}}, "filter"),
		({"filter": {"eq": ["checks.Confirmed"]}}, "filter"), ({"filter": {"in": ["checks.Method", "InPerson"]}}, "filter"),
		({"filter": {"exists": "checks.Method"}, "limit": 0}, "limit")]:
		with pytest.raises(StoreError) as refused:
			store.indexQuery(SERVER, "ClientChecks", body)
		assert (refused.value.status, refused.value.details["check"]) == (400, check)
	with pytest.raises(StoreError) as missing:
		store.indexQuery(SERVER, "Nowhere", {"filter": {"exists": "checks.Method"}})
	assert missing.value.status == 404


def testIndexesAndTheFeedAreForServersOnly() -> None:
	store = stocked()
	for request, status in [(USER, 403), (None, 401)]:
		for call in (lambda: store.indexQuery(request, "ClientChecks", {"filter": {"exists": "checks.Method"}}), lambda: store.changes(request)):
			with pytest.raises(StoreError) as refused:
				call()
			assert refused.value.status == status
	# NOTE: There is no default access: a store without a server callback refuses them.
	bare = ObservationStore(BUNDLE, FINANCE, authorize, clock=lambda: NOW)
	with pytest.raises(StoreError) as refused:
		bare.changes(SERVER)
	assert refused.value.status == 403


# EOF
