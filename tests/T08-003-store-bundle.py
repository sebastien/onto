"""Module: store bundle tests — spec-08 "Store bundle", with spec-09's origins and held slots read from it."""

from __future__ import annotations

import json

import pytest

from onto.handles import derivedHandle, sourceQualifiedHandle
from onto.store import ORIGIN_SHARED, ORIGIN_STORE, STORE_BUNDLE_FORMAT, holds, originOf
from tests.cli import onto
from tests.store import EXAMPLE, OPS, addStore, checked

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


BUNDLE = OPS.bundle(checked(EXAMPLE))
HEAD = "@store A rev=1 edit=edit:a\n@use Finance as F\n@system Exchange -> Finance\n"
SCOPE = "adviser-app"


def kind(bundle: dict, name: str) -> dict:
	return next(item for item in bundle["kinds"] if item["kind"] == name)


# -----------------------------------------------------------------------------
#
# COMPILATION
#
# -----------------------------------------------------------------------------


def testHeader() -> None:
	assert (BUNDLE["format"], BUNDLE["store"], BUNDLE["rev"], BUNDLE["edit"], BUNDLE["ontology"]) == (
		STORE_BUNDLE_FORMAT, "AdviserApp", "2026-11-26", "edit:adviser-app", "Finance")
	assert BUNDLE["limits"]["statementsPerBatch"] == 1024 and BUNDLE["limits"]["retries"] == "P7D"
	assert BUNDLE["model"]["types"]["Finance/IdentityCheck"]["association"] is True


def testKindsCompileTheClaimsThatMakeMembers() -> None:
	client = kind(BUNDLE, "Client")
	assert client["root"] == {"name": "client", "type": "Finance/Person"}
	assert client["policies"] == {"orphaned": "never", "archived": "P7Y", "grace": "P30D"}
	assert [(item["name"], item["type"], item["parent"], item["link"]) for item in client["populations"]] == [
		("checks", "Finance/IdentityCheck", "client", {"slot": "Person", "on": "member"}),
		("documents", "Finance/Document", "checks", {"slot": "Document", "on": "parent"})]
	assert kind(BUNDLE, "Household") == {"kind": "Household", "root": {"name": "household", "type": "Finance/Household"},
		"policies": {"orphaned": "never", "archived": "never", "grace": "P30D"}, "populations": []}


def testRelationLinksNameTheirRoles() -> None:
	bundle = OPS.bundle(checked(HEAD + "@partition H(household: F/Household)\n  members: F/Person = household -> hasMember\n"
		"@partition P(person: F/Account)\n  ownerships: F/Ownership = person <- Account {archived=P1Y, privacy=kept}\n"))
	members, = kind(bundle, "H")["populations"]
	assert members["link"] == {"rel": "Finance/Household.hasMember.Finance/Person", "parentRole": "Household", "memberRole": "Person"}
	ownerships, = kind(bundle, "P")["populations"]
	assert (ownerships["policies"]["archived"], ownerships["privacy"]) == ("P1Y", "kept")


def testSystemsListWhatTheirMappingFills() -> None:
	exchange, = BUNDLE["systems"]
	assert (exchange["name"], exchange["scope"]) == ("Exchange", "Exchange")
	assert sorted(exchange["types"]) == ["Finance/Company", "Finance/Dividend", "Finance/Instrument"]
	assert exchange["types"]["Finance/Instrument"] == {
		"attrs": ["AssetClass", "Bond.CouponRate", "Bond.InterestFrequency", "Bond.MaturityDate", "Code", "Isin", "Name"],
		"facets": ["Bond"], "relations": ["Finance/Company.issues.Finance/Instrument"]}


def testIndexesCompileTheirColumns() -> None:
	index, = BUNDLE["indexes"]
	assert index["columns"] == [
		{"name": "checks.Confirmed", "population": "checks", "type": "Finance/IdentityCheck", "path": "Confirmed"},
		{"name": "checks.Method", "population": "checks", "type": "Finance/IdentityCheck", "path": "Method"}]


def testRevisionFollowsTheContent() -> None:
	assert BUNDLE["revision"].startswith("sha256:")
	assert OPS.bundle(checked(EXAMPLE))["revision"] == BUNDLE["revision"]
	assert OPS.bundle(checked(EXAMPLE.replace("P7Y", "P8Y")))["revision"] != BUNDLE["revision"]


# -----------------------------------------------------------------------------
#
# ORIGINS AND HELD SLOTS
#
# -----------------------------------------------------------------------------


def testOriginsOfProducedTypes() -> None:
	origins = BUNDLE["origins"]
	assert origins["Finance/Company"] == {"systems": ["Exchange"], "policy": {"keys": ["Code"], "from": "Exchange"}}
	assert origins["Finance/Instrument"] == {"systems": ["Exchange"], "policy": {"keys": ["Isin"]}}
	assert origins["Finance/Party"] == {"systems": ["Exchange"]}
	assert "Finance/Person" not in origins and "Finance/IdentityCheck" not in origins


@pytest.mark.parametrize("handle,type,origin", [
	("Person_U1", "Finance/Person", ORIGIN_STORE),
	(derivedHandle("Finance/Company", "ACM"), "Finance/Company", "Exchange"),
	(derivedHandle("Finance/Instrument", "US0000000019"), "Finance/Instrument", ORIGIN_SHARED),
	(sourceQualifiedHandle("Finance/Dividend", "Exchange", "Dividend", "D1"), "Finance/Dividend", "Exchange"),
	(sourceQualifiedHandle("Finance/Company", SCOPE, "Company", "0193a6d0-77"), "Finance/Company", ORIGIN_STORE),
	("Dividend_D1", "Finance/Dividend", None),
	("Issuer_ACM", "Finance/Company", None),
])
def testOriginOfAHandle(handle: str, type: str, origin: str | None) -> None:
	assert originOf(BUNDLE, handle, type, SCOPE) == origin


@pytest.mark.parametrize("origin,type,claim,held", [
	(ORIGIN_STORE, "Finance/Company", {"p": "Code"}, True),
	(ORIGIN_STORE, "Finance/Company", {"exists": True}, True),
	("Exchange", "Finance/Company", {"p": "Code"}, False),
	("Exchange", "Finance/Company", {"p": "SuspensionStatus"}, True),
	("Exchange", "Finance/Company", {"exists": True}, False),
	("Exchange", "Finance/Company", {"rel": "Finance/Company.issues.Finance/Instrument"}, False),
	(ORIGIN_SHARED, "Finance/Instrument", {"p": "Isin"}, False),
	(ORIGIN_SHARED, "Finance/Instrument", {"facet": "Bond"}, False),
	(ORIGIN_SHARED, "Finance/Instrument", {"p": "Bond.CouponRate"}, False),
	(ORIGIN_STORE, "Finance/Person", {"same": ["Person_U1", "Person_U2"]}, True),
])
def testHeldSlots(origin: str, type: str, claim: dict, held: bool) -> None:
	assert holds(BUNDLE, origin, type, claim) is held


def testKeyedElementsAreDistinctSlots() -> None:
	exchange, = BUNDLE["systems"]
	types = {**exchange["types"], "Finance/Company": {**exchange["types"]["Finance/Company"], "attrs": ["Code", "Phones[Mobile].Number"]}}
	bundle = {**BUNDLE, "systems": [{**exchange, "types": types}]}
	assert holds(bundle, "Exchange", "Finance/Company", {"p": "Phones[Mobile].Number"}) is False
	assert holds(bundle, "Exchange", "Finance/Company", {"p": "Phones[Core/PhoneType/Mobile].Number"}) is False
	assert holds(bundle, "Exchange", "Finance/Company", {"p": "Phones[Home].Number"}) is True


def testExclusionsAreNeverHeld() -> None:
	bundle = OPS.bundle(checked(EXAMPLE.replace("\n@index", "\n- F/Person.Email {reason=private}\n\n@index", 1)))
	assert holds(bundle, ORIGIN_STORE, "Finance/Person", {"p": "Email"}) is False
	assert holds(bundle, ORIGIN_STORE, "Finance/Person", {"p": "DateOfBirth"}) is True
	excluded = OPS.bundle(checked(EXAMPLE.replace("\n@index", "\n- F/Person.Name.Surname\n\n@index", 1)))
	assert holds(excluded, ORIGIN_STORE, "Finance/Person", {"p": "Name.Surname"}) is False


# -----------------------------------------------------------------------------
#
# CLI
#
# -----------------------------------------------------------------------------


def test_store_bundle_prints_the_bundle(workspace):
	addStore(workspace)
	status, out, err = onto("store", "bundle", "finance/adviser-app.store")
	assert status == 0, err
	data = json.loads(out)
	assert data["format"] == STORE_BUNDLE_FORMAT
	# NOTE: The mapping's referential comes with it, so derived handles have origins.
	assert data["origins"]["Finance/Company"]["policy"] == {"keys": ["Code"], "from": "Exchange"}


def test_store_bundle_of_a_store_with_errors_prints_nothing(workspace):
	addStore(workspace, EXAMPLE.replace("F/Household", "F/Nobody"))
	status, out, err = onto("store", "bundle", "finance/adviser-app.store")
	assert (status, out) == (1, "") and "error partition" in err


# EOF
