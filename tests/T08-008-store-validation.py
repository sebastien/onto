"""Module: store batch validation — spec-02's strict reading of an appended batch: a batch is accepted exactly as written,
or rejected with the check it fails and, where it can be told, the statement (spec-08 "Batches"). The JavaScript store
replays these cases (conformance)."""

from __future__ import annotations

from copy import deepcopy
from typing import Callable

import pytest

from onto.store.runtime import StoreError
from tests.store import EXAMPLE_BATCH, SCOPE, newStore

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


PARTITION = "Client/Person_U1"
FEE = "Fee_F1"


def claim(n: int) -> Callable[[dict], dict]:
	"""The claim numbered `n` of a batch."""
	return lambda data: next(item for item in data["claims"] if item["n"] == n)


def edit(ordinal: int, **members) -> Callable[[dict], None]:
	"""Set (or with None, remove) members of the claim numbered `ordinal`."""
	def change(data: dict) -> None:
		item = claim(ordinal)(data)
		for key, value in members.items():
			item.pop(key, None) if value is None else item.__setitem__(key, value)
	return change


def add(*claims: dict, instances: dict | None = None) -> Callable[[dict], None]:
	"""Add claims, numbered after the batch's, with the batch's `by`, and instances."""
	def change(data: dict) -> None:
		data["instances"].update(instances or {})
		for item in claims:
			data["claims"].append({"n": len(data["claims"]) + 1, "by": "app:intake", **item})
	return change


def put(*claims: dict, instances: dict | None = None, retract: bool = False) -> Callable[[dict], None]:
	"""Add claims (or retractions) as written, with the batch's `by` and source unless they say otherwise."""
	def change(data: dict) -> None:
		data["instances"].update(instances or {})
		data["retractions" if retract else "claims"].extend({"by": "app:intake", "src": "e", **item} for item in claims)
	return change


HOUSEHOLD = {"Household_H1": {"type": "Finance/Household"}}
MEMBER = "Finance/Household.hasMember.Finance/Person"


def fee(*claims: dict) -> Callable[[dict], None]:
	"""Claims about a fee, which the batch registers and states exists."""
	return add({"s": FEE, "exists": True, "src": "e"}, *({"s": FEE, "src": "e", **item} for item in claims), instances={FEE: {"type": "Finance/Fee"}})


def top(key: str, value) -> Callable[[dict], None]:
	return lambda data: data.__setitem__(key, value)


def header(**members) -> Callable[[dict], None]:
	return lambda data: data["obs"].update(members)


def validate(change: Callable[[dict], None] | None = None):
	"""Validate the example batch, changed, for a new client partition, as an append does before homing it."""
	data = deepcopy(EXAMPLE_BATCH)
	if change:
		change(data)
	store = newStore()
	return store.validate(data, store.partition(SCOPE, PARTITION, create=True))


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


ACCEPTED = {
	"the example batch": None,
	"an exclusive group's one member": fee({"p": "Card", "v": "4111"}),
	"a range": fee({"p": "Ages", "v": "18..65"}),
	"an open range": fee({"p": "Ages", "v": "18.."}),
	"a conditional facet whose condition holds": fee({"p": "Kind", "v": "Waived"}, {"p": "Waived.Reason", "v": "Hardship"}),
	"a keyed element": add({"s": "Person_U1", "p": "Phones[Mobile].Number", "v": "0215550101", "src": "e"}),
	"a retraction without a value": lambda data: data["retractions"].append({"n": 9, "s": "IdentityCheck_C41", "p": "Method", "by": "app:intake", "src": "e"}),
	"an unknown value": edit(4, v={"unknown": True}),
	"a facet stated with its existence": put({"n": 9, "s": "Person_U1", "exists": True}, {"n": 9, "s": "Person_U1", "facet": "Investor"}),
	"a facet's value in its unit": put({"n": 9, "s": "Person_U1", "p": "Investor.Horizon", "v": "10"}),
	"a retracted facet": put({"n": 9, "s": "Person_U1", "facet": "Investor"}, retract=True),
	"a link": put({"n": 9, "rel": MEMBER, "roles": {"Household": "Household_H1", "Person": "Person_U1"}}, instances=HOUSEHOLD),
	"a link whose subject is unknown": put({"n": 9, "rel": MEMBER, "roles": {"Household": "?", "Person": "Person_U1"}}),
	"an integer bound with an exponent": fee({"p": "Ages", "v": "1e1..2e1"}),
}


@pytest.mark.parametrize("change", ACCEPTED.values(), ids=list(ACCEPTED))
def testABatchAsWrittenIsAccepted(change) -> None:
	assert validate(change).claims


REJECTED = {
	# The document's shape (spec-02 JSON form).
	"a member the form lacks": (top("extra", True), "json", None),
	"another format": (top("format", "onto.observations/2"), "observations", None),
	"claims that are no array": (top("claims", {}), "json", None),
	"an ordinal that is no positive integer": (edit(4, n=0), "json", None),
	"two forms": (edit(4, exists=True), "json", None),
	"exists false": (edit(1, exists=False), "json", None),
	"an attribute claim without a value": (edit(4, v=None), "json", None),
	"a JSON number": (edit(4, v=3), "json", None),
	"an unregistered subject": (edit(4, s="IdentityCheck_C99"), "json", None),
	"conflict false": (edit(4, conflict=False), "json", None),
	"conf beyond 1": (edit(4, conf=2), "json", None),
	"gaps in strict mode": (top("gaps", [{"n": 9, "reason": "x", "text": "x"}]), "json", None),
	"an unregistered reference": (edit(3, v={"ref": "Document_D99"}), "json", None),
	"an invalid at": (edit(4, at="2026-13-01"), "json", None),
	# Metadata.
	# NOTE: These two are reported without their statement: Python's text form places them where it cannot tell it.
	"an invalid valid": (edit(1, valid="2026"), "meta", None),
	"an invalid scale": (fee({"p": "Ages", "v": "18..65", "scale": "5"}), "meta", None),
	"of on a claim": (edit(4, of="edit:old"), "meta", 4),
	"a qualifier without a value": (edit(1, unit="kg"), "meta", 1),
	"an observed qualifier spelled ?:V": (fee({"p": "Card", "v": "4111", "unit": "?:kg"}), "meta", 10),
	"an interval on an event": (edit(1, valid="2026-11-26..2026-11-27"), "meta", 1),
	# The header.
	"another ontology": (header(ontology="Shop"), "header", None),
	"another revision": (header(rev="2020-01-01"), "header", None),
	# Statements.
	"a same link naming one handle twice": (add({"same": ["Document_D9", "Document_D9"], "src": "e"}), "identity", 9),
	"a distinct link of incompatible types": (add({"distinct": ["Document_D9", "IdentityCheck_C41"], "src": "e"}), "type", 9),
	"an unknown attribute": (edit(4, p="Colour"), "reference", 4),
	"an unknown facet": (add({"s": "IdentityCheck_C41", "facet": "Audit", "src": "e"}), "reference", 9),
	"a keyed element of a closed key outside its values": (add({"s": "Person_U1", "p": "Phones[Fax].Number", "v": "1", "src": "e"}), "key", 9),
	"a keyed element's key field": (add({"s": "Person_U1", "p": "Phones[Mobile].Use", "v": "Mobile", "src": "e"}), "key", 9),
	"a value outside a closed vocabulary": (edit(4, v="Telepathy"), "value", 4),
	"a malformed date": (add({"s": "Person_U1", "p": "DateOfBirth", "v": "1982-13-01", "src": "e"}), "value", 9),
	"a date-time on a date": (add({"s": "Person_U1", "p": "DateOfBirth", "v": "1982-04-11T10:00", "src": "e"}), "value", 9),
	"a set on a single-valued slot": (edit(4, v={"set": ["InPerson"]}), "value", 4),
	"a reference of another type": (edit(2, v={"ref": "Document_D9"}), "type", 2),
	"a range with its bounds reversed": (fee({"p": "Ages", "v": "65..18"}), "value", 10),
	"an exclusive group's two members": (fee({"p": "Card", "v": "4111"}, {"p": "Account", "v": "12-3456"}), "one", 11),
	"a conditional facet whose condition fails": (fee({"p": "Kind", "v": "Charged"}, {"p": "Waived.Reason", "v": "Hardship"}), "when", 11),
	# Values must already be canonical: the batch is kept as written.
	"a non-canonical range": (fee({"p": "Ages", "v": "18"}), "json", None),
	"a boolean as text": (edit(5, v="true"), "json", None),
	"distinct handles out of order": (add({"distinct": ["Person_U1", "Person_U0"], "src": "e"}, instances={"Person_U0": {"type": "Finance/Person"}}), "json", None),
	"a claim without the header's by": (edit(4, by=None), "json", None),
	"a facet without its existence": (put({"n": 9, "s": "Person_U1", "facet": "Investor"}), "json", None),
	"a facet with a validity": (put({"n": 9, "s": "Person_U1", "exists": True}, {"n": 9, "s": "Person_U1", "facet": "Investor", "valid": "2026-01-01"}), "json", None),
	"a number not in its canonical spelling": (put({"n": 9, "s": "Person_U1", "p": "Investor.Horizon", "v": "10.0"}), "json", None),
	"an ISO duration on a fixed unit": (put({"n": 9, "s": "Person_U1", "p": "Investor.Horizon", "v": "P10Y"}), "value", 9),
	"a unit contradicting the declared one": (put({"n": 9, "s": "Person_U1", "p": "Investor.Horizon", "v": "10", "unit": "Month"}), "qualifier", 9),
	"null on a multi-valued slot": (put({"n": 9, "s": "Person_U1", "p": "Phones", "v": None}), "value", 9),
	"a link from a type its relation does not start from": (put({"n": 9, "rel": MEMBER, "roles": {"Household": "Person_U1", "Person": "Household_H1"}}, instances=HOUSEHOLD), "reference", 9),
	"a link with a context": (put({"n": 9, "rel": MEMBER, "roles": {"Household": "Household_H1", "Person": "Person_U1"}, "ctx": "Household_H1"}, instances=HOUSEHOLD), "json", None),
	"an integer that is not one": (fee({"p": "Ages", "v": "1.5..2"}), "value", 10),
}


@pytest.mark.parametrize(("change", "check", "n"), REJECTED.values(), ids=list(REJECTED))
def testABatchFailingACheckIsRejectedWithIt(change, check: str, n: int | None) -> None:
	with pytest.raises(StoreError) as raised:
		validate(change)
	error = raised.value
	assert (error.status, error.error, error.details.get("check"), error.details.get("n")) == (400, "invalid", check, n)


# EOF
