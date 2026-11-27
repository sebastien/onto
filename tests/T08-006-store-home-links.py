"""Module: store home link tests — spec-08 "Home links": members whose link another system holds."""

from __future__ import annotations

import pytest

from onto.handles import derivedHandle, sourceQualifiedHandle
from onto.store.runtime import ObservationStore, StoreError
from tests.store import OPS, SCOPE, USER, batch, checked, newStore

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


# NOTE: The exchange produces dividends and fills their Payer role, so a company's partition cannot state that link.
ISSUERS = OPS.bundle(checked("@store Issuers rev=1 edit=edit:adviser-app\n@use Finance as F\n@system Exchange -> Finance\n\n"
	"@partition Issuer(company: F/Company)\n  dividends: F/Dividend = company <- Payer\n"))
COMPANY = derivedHandle("Finance/Company", "ACM")
DIVIDEND = sourceQualifiedHandle("Finance/Dividend", "Exchange", "Dividend", "D1")
PARTITION = f"Issuer/{COMPANY}"
LINK = {"s": DIVIDEND, "p": "Payer", "v": {"ref": COMPANY}}
KNOWN = {COMPANY: "Company"}


def audit(requestId: str, links: list | None = None, known: dict = KNOWN) -> dict:
	"""An adviser's check of the dividend: a fact only the store holds."""
	return {"requestId": requestId, "observations": batch(f"{DIVIDEND}.Audit.Checked true", known, {DIVIDEND: "Dividend"}),
		**({"links": links} if links is not None else {})}


def refused(store: ObservationStore, body: dict) -> StoreError:
	with pytest.raises(StoreError) as error:
		store.append(USER, PARTITION, body)
	return error.value


# -----------------------------------------------------------------------------
#
# HOME LINKS
#
# -----------------------------------------------------------------------------


def testWithoutItsLinkAMemberFromAnotherSystemHasNoHome() -> None:
	assert refused(newStore(ISSUERS), audit("r")).details["check"] == "home.unlinked"


def testTheLinkCannotBeAStatement() -> None:
	body = {"requestId": "r", "observations": batch(f"{DIVIDEND}.Audit.Checked true\n{DIVIDEND}.Payer {COMPANY}", KNOWN, {DIVIDEND: "Dividend"})}
	assert refused(newStore(ISSUERS), body).details["check"] == "slot.not-held"


def testAHomeLinkHomesTheMemberButStaysOutOfTheState() -> None:
	store = newStore(ISSUERS)
	answer = store.append(USER, PARTITION, audit("r", [LINK]))
	assert (answer["from"], answer["through"]) == (1, 2)
	assert store.partition(SCOPE, PARTITION).members == {COMPANY: "company", DIVIDEND: "dividends"}
	state = store.state(USER, PARTITION)
	assert [(item["s"], item["p"]) for item in state["observations"]["claims"]] == [(DIVIDEND, "Audit.Checked")]
	entries = store.log(USER, PARTITION)["entries"]
	assert [(entry["seq"], entry["kind"]) for entry in entries] == [(1, "link"), (2, "statement")]
	assert {key: entries[0][key] for key in ("s", "p", "v", "principal")} == LINK | {"principal": "user:adviser"}
	# NOTE: Once homed, the member needs no link.
	store.append(USER, PARTITION, audit("r2", known=KNOWN | {DIVIDEND: "Dividend"}))
	assert store.partition(SCOPE, PARTITION).head == 3


@pytest.mark.parametrize("link,check", [
	({"s": DIVIDEND, "p": "Instrument", "v": {"ref": derivedHandle("Finance/Instrument", "US0000000019")}}, "link"),
	({"s": DIVIDEND, "p": "Audit.Checked", "v": True}, "link"),
	({"s": "Dividend_D9", "p": "Payer", "v": {"ref": COMPANY}}, "link"),
	({"rel": "Finance/Company.issues.Finance/Instrument"}, "link"),
])
def testOnlyTheLinksOfPopulationsOnSlotsTheStoreDoesNotHold(link: dict, check: str) -> None:
	assert refused(newStore(ISSUERS), audit("r", [link])).details["check"] == check


def testLinksAreRetriedWithTheirBatch() -> None:
	store = newStore(ISSUERS)
	first = store.append(USER, PARTITION, audit("r", [LINK]))
	assert store.append(USER, PARTITION, audit("r", [LINK])) == first
	assert refused(store, audit("r", [LINK | {"v": {"ref": derivedHandle("Finance/Company", "XYZ")}}])).error == "request_reused"


# EOF
