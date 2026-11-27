"""Module: store read tests — spec-08 state reads (selections, pages, asOf, versions), log reads and batch reads."""

from __future__ import annotations

import pytest

from onto.store.runtime import ObservationStore, StoreError
from tests.store import CHECK, USER, appended, batch

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


KNOWN = {"IdentityCheck_C41": "IdentityCheck"}
PARTITION = "Client/Person_U1"


def claims(answer: dict) -> list[tuple]:
	"""A state's claims as (subject, member, value, conflict), in log order."""
	return [(item.get("s"), item.get("p") or (f"[{item['facet']}]" if "facet" in item else "exists"), item.get("v"), item.get("conflict", False))
		for item in answer["observations"]["claims"]]


def edit(text: str, requestId: str, known: dict = KNOWN, **extra) -> dict:
	return {"requestId": requestId, "observations": batch(text, known), **extra}


def refused(call) -> StoreError:
	with pytest.raises(StoreError) as error:
		call()
	return error.value


def checks(store: ObservationStore, *handles: str) -> ObservationStore:
	"""More identity checks of the client, one batch each."""
	for handle in handles:
		store.append(USER, PARTITION, edit(f"{handle}:IdentityCheck\n  Person Person_U1\n  Method Electronic", handle, {"Person_U1": "Person"}))
	return store


# -----------------------------------------------------------------------------
#
# STATE
#
# -----------------------------------------------------------------------------


def testStateIsTheReconciledLog() -> None:
	answer = appended(CHECK).state(USER, PARTITION)
	assert (answer["partition"], answer["generation"], answer["head"], answer["state"]) == (PARTITION, 1, 8, "active")
	assert ("IdentityCheck_C41", "Confirmed", True, False) in claims(answer)
	assert ("Document_D9", "Title", "Passport", False) in claims(answer)
	assert [item["n"] for item in answer["observations"]["claims"]] == list(range(1, 9))
	# NOTE: No existence claim states the anchor in its partition, so its state holds it as implicit.
	assert answer["observations"]["instances"]["Person_U1"] == {"type": "Finance/Person", "implicit": True}
	assert {"s": "IdentityCheck_C41", "p": "Confirmed", "version": 5} in answer["versions"]


def testALaterClaimOfOneSourceSupersedes() -> None:
	store = appended(CHECK, edit("IdentityCheck_C41.Confirmed false", "r2"))
	assert [item for item in claims(store.state(USER, PARTITION)) if item[1] == "Confirmed"] == [("IdentityCheck_C41", "Confirmed", False, False)]
	# NOTE: For one `at`, the record time of the example's claims, the higher `seq` supersedes.
	header = "@obs Finance at=2026-11-26T09:30:00Z\n@src e=edit:adviser-app\n@src e\n@scope adviser-app\n\n"
	store.append(USER, PARTITION, edit(header + "IdentityCheck_C41.Method Electronic", "r3"))
	store.append(USER, PARTITION, edit(header + "IdentityCheck_C41.Method CertifiedCopy", "r4"))
	assert [item for item in claims(store.state(USER, PARTITION)) if item[1] == "Method"] == [("IdentityCheck_C41", "Method", "CertifiedCopy", False)]


def testSourcesThatDisagreeConflict() -> None:
	upload = "@obs Finance\n@src u=upload:document/123\n@src u\n@scope adviser-app\n\nIdentityCheck_C41.Method Electronic"
	store = appended(CHECK, edit(upload, "r2"))
	assert sorted(item for item in claims(store.state(USER, PARTITION)) if item[1] == "Method") == [
		("IdentityCheck_C41", "Method", "Electronic", True), ("IdentityCheck_C41", "Method", "InPerson", True)]


def testRetractionsWithdraw() -> None:
	store = appended(CHECK, edit("- IdentityCheck_C41.Confirmed", "r2"))
	assert not [item for item in claims(store.state(USER, PARTITION)) if item[1] == "Confirmed"]


def testSelectionsKeepTheirSubjectsAndSlots() -> None:
	answer = appended(CHECK).state(USER, PARTITION, {"select": [{"s": "IdentityCheck_C41", "slots": ["Confirmed"]}]})
	assert claims(answer) == [("IdentityCheck_C41", "exists", None, False), ("IdentityCheck_C41", "Confirmed", True, False)]
	assert answer["versions"] == [{"s": "IdentityCheck_C41", "exists": True, "version": 1}, {"s": "IdentityCheck_C41", "p": "Confirmed", "version": 5}]
	assert set(answer["observations"]["instances"]) == {"IdentityCheck_C41"}


@pytest.mark.parametrize("slot, kept", [("Phones.Number", ["0215550101", "095550102"]), ("Phones[Home].Number", ["095550102"])])
def testASlotWithoutKeysKeepsEachElement(slot: str, kept: list[str]) -> None:
	store = appended({"requestId": "phones", "observations": batch("Person_U1.Phones[Mobile].Number 0215550101\nPerson_U1.Phones[Home].Number 095550102")})
	answer = store.state(USER, PARTITION, {"select": [{"s": "Person_U1", "slots": [slot]}]})
	assert sorted(value for _, member, value, _ in claims(answer) if member.startswith("Phones")) == kept
	assert len([item for item in answer["versions"] if item.get("p", "").startswith("Phones")]) == len(kept)


def testPopulationsComeAPageAtATimeNewestFirst() -> None:
	store = checks(appended(CHECK), "IdentityCheck_C42", "IdentityCheck_C43")
	first = store.state(USER, PARTITION, {"select": [{"population": "checks", "page": {"size": 2}}]})
	assert sorted({item[0] for item in claims(first)}) == ["IdentityCheck_C42", "IdentityCheck_C43"]
	cursor = first["pages"]["checks"]
	second = store.state(USER, PARTITION, {"select": [{"population": "checks", "page": {"size": 2, "after": cursor}}]})
	assert {item[0] for item in claims(second)} == {"IdentityCheck_C41"} and "pages" not in second


def testAsOfReadsThePastState() -> None:
	answer = appended(CHECK, edit("IdentityCheck_C41.Confirmed false", "r2")).state(USER, PARTITION, {"asOf": 5})
	assert (answer["asOf"], answer["head"]) == (5, 9)
	assert ("IdentityCheck_C41", "Confirmed", True, False) in claims(answer)
	assert not [item for item in claims(answer) if item[0] == "Document_D9"]


@pytest.mark.parametrize("body,check", [
	({"select": [{"s": "IdentityCheck_C41", "population": "checks"}]}, "select"),
	({"select": [{"population": "visits"}]}, "select"),
	({"include": ["forgotten"]}, "include"),
	({"asOf": 99}, "asOf"),
])
def testInvalidReads(body: dict, check: str) -> None:
	assert refused(lambda: appended(CHECK).state(USER, PARTITION, body)).details["check"] == check


def testAPartitionNeverAppendedToIsNotFound() -> None:
	error = refused(lambda: appended(CHECK).state(USER, "Client/Person_U9"))
	assert (error.status, error.error) == (404, "not_found")


# -----------------------------------------------------------------------------
#
# LOG, SEVERAL PARTITIONS AND AUDIT
#
# -----------------------------------------------------------------------------


def testLogReadsComeInOrderWithTheirStamps() -> None:
	store = appended(CHECK)
	whole = store.log(USER, PARTITION)
	assert (whole["after"], whole["through"], whole["head"], whole["hasMore"]) == (0, 8, 8, False)
	assert [(entry["seq"], entry["kind"], entry["principal"]) for entry in whole["entries"]][:2] == [(1, "statement", "user:adviser"), (2, "statement", "user:adviser")]
	page = store.log(USER, PARTITION, after=2, limit=3)
	assert ([entry["seq"] for entry in page["entries"]], page["through"], page["hasMore"]) == ([3, 4, 5], 5, True)
	assert refused(lambda: store.log(USER, PARTITION, after=9)).details["check"] == "cursor"


def testABatchReadAnswersEachPartition() -> None:
	store = appended(CHECK)
	store.append(USER, "Client/Person_U2", edit("IdentityCheck_C51:IdentityCheck\n  Person Person_U2", "u2", {"Person_U2": "Person"}))
	answer = store.stateMany(USER | {"deny": "Client/Person_U2"}, {"reads": [{"partition": PARTITION, "select": [{"s": "Document_D9"}]},
		{"partition": "Client/Person_U2"}, {"partition": "Client/Person_U9"}]})
	first, denied, missing = answer["results"]
	assert {item[0] for item in claims(first)} == {"Document_D9"}
	assert (denied["status"], denied["error"], missing["status"], missing["error"]) == (403, "forbidden", 404, "not_found")


def testReadsAreAudited() -> None:
	store = appended(CHECK)
	store.state(USER, PARTITION, {"select": [{"s": "Document_D9"}]})
	store.log(USER, PARTITION)
	rows = store.db.execute("SELECT partition, principal, selection FROM reads").fetchall()
	assert rows == [(PARTITION, "user:adviser", '[{"s":"Document_D9"}]'), (PARTITION, "user:adviser", '{"log":0}')]


# EOF
