"""Module: session home link tests — a change to members another system links sends the store the links that home
the batch's subjects, and no others (spec-09 "Changes", spec-08 "Home links")."""

from __future__ import annotations

import asyncio
from types import MethodType, SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")

from onto.handles import derivedHandle, sourceQualifiedHandle  # noqa: E402
from onto.integrations.hexa.sessions import Session, SessionViewOperator  # noqa: E402
from tests.store import FINANCE, OPS, SCOPE, USER, checked, newStore  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


# NOTE: The exchange produces dividends and fills their Payer role, so a company's partition cannot state that link.
ISSUERS = OPS.bundle(checked("@store Issuers rev=1 edit=edit:adviser-app\n@use Finance as F\n@system Exchange -> Finance\n\n"
	"@partition Issuer(company: F/Company)\n  dividends: F/Dividend = company <- Payer\n"))
COMPANY = derivedHandle("Finance/Company", "ACM")
DIVIDENDS = [sourceQualifiedHandle("Finance/Dividend", "Exchange", "Dividend", key) for key in ("D1", "D2")]
PARTITION = f"Issuer/{COMPANY}"


def session(store) -> Session:
	"""A session over the exchange's view of a company and its two dividends, appending to `store`."""
	operator = SimpleNamespace(bundle=ISSUERS, storeName="Issuers", scope=SCOPE, system="Exchange", target=FINANCE,
		access=SimpleNamespace(storeAppend=lambda partition, body: store.append(USER, partition, body)))
	operator.subjectOf = MethodType(SessionViewOperator.subjectOf, operator)
	operator.claimHolder = MethodType(SessionViewOperator.claimHolder, operator)
	item = Session(operator)
	item.state = SimpleNamespace(instances={COMPANY: {"type": "Finance/Company"}, **{handle: {"type": "Finance/Dividend"} for handle in DIVIDENDS}},
		claims=[{"n": index + 1, "s": handle, "p": "Payer", "v": {"ref": COMPANY}, "src": "x"} for index, handle in enumerate(DIVIDENDS)])
	return item


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testABatchCarriesOnlyTheLinksThatHomeItsSubjects() -> None:
	store, bodies = newStore(ISSUERS), []
	item = session(store)
	append = item.operator.access.storeAppend
	item.operator.access.storeAppend = lambda partition, body: bodies.append(body) or append(partition, body)
	statement, = asyncio.run(item.change({"claims": [{"s": DIVIDENDS[0], "p": "Audit.Checked", "v": True, "version": 0}]}))["statements"]
	assert (statement["result"], statement["partition"]) == ("applied", PARTITION)
	assert [body.get("links") for body in bodies] == [[{"s": DIVIDENDS[0], "p": "Payer", "v": {"ref": COMPANY}}]]
	assert store.partition(SCOPE, PARTITION).members == {COMPANY: "company", DIVIDENDS[0]: "dividends"}


# EOF
