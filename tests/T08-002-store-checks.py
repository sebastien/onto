"""Module: store check tests — spec-08 store files against their ontology and @system mappings, and in the CLI."""

from __future__ import annotations

import json

import pytest

from onto import FormatError, Source, loadFunctions, loadMapping, loadOntology
from onto.referential import loadReferential
from onto.store import Store, StoreOperator
from tests.cli import onto
from tests.helpers import specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


def financeText(extra: str = "") -> str:
	"""Spec-01's Finance with spec-08's additions, under spec-01's header."""
	return specExample("spec-01-ontology") + "\n" + specExample("spec-08-store", 0).split("\n", 1)[1] + extra


# NOTE: A member keeping a personal value about another kind's key entity (spec-08 "Personal facts stay home").
VISIT = """
Visit(Household, Visitor: Person) {kind=event}  -- A home visit
  VisitorAddress Text {privacy=Owner}
"""

FINANCE = loadOntology([Source("finance.onto", financeText(VISIT))])
EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", specExample("spec-04-mapping", 4))])
MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", specExample("spec-04-mapping", 5)), libraries=[MARKETS], referentials=[REFERENTIAL])
OPS = StoreOperator([FINANCE], [MAPPING])
EXAMPLE = specExample("spec-08-store", 1)
HEAD = "@store A rev=1 edit=edit:a\n@use Finance as F\n@system Exchange -> Finance\n"
CLIENT = "@partition Client(client: F/Person)\n  checks: F/IdentityCheck = client <- Person\n  documents: F/Document = checks -> Document\n"


def checked(text: str) -> Store:
	return OPS.load([Source("a.store", text)])


def codes(text: str) -> set[str]:
	with pytest.raises(FormatError) as error:
		checked(text)
	return {item.code for item in error.value.diagnostics if item.level == "error"}


# -----------------------------------------------------------------------------
#
# CHECKS
#
# -----------------------------------------------------------------------------


def testExampleChecks() -> None:
	store = checked(EXAMPLE)
	assert [item.kind for item in store.partitions] == ["Client", "Household"]
	assert OPS.format([Source("a.store", EXAMPLE)]) == EXAMPLE


@pytest.mark.parametrize("text,code", [
	("@store A\n@use Exchange as X\n@partition P(p: X/Issuer)\n", "store"),
	(HEAD + "@partition P(p: F/Nobody)\n", "partition"),
	(HEAD + "@partition P(t: F/Trade)\n", "partition"),
	(HEAD + "@partition P(p: F/Person)\n  d: F/Document = p -> Document\n", "population"),
	(HEAD + "@partition P(p: F/Person)\n  d: F/Nothing = p <- Person\n", "population"),
	(HEAD + "@partition P(p: F/Person)\n  c: F/IdentityCheck = p <- Document\n", "population"),
	("@store A\n@use Finance as F\n@system Exchange -> Sheet\n@partition P(p: F/Person)\n", "system"),
	("@store A\n@use Finance as F\n@system Feed -> Finance\n@partition P(p: F/Person)\n", "system"),
	(HEAD + "@partition A(a: F/Party)\n@partition B(b: F/Person)\n", "kind"),
	(HEAD + CLIENT + "@partition H(h: F/Household)\n  members: F/Person = h -> hasMember\n", "kind"),
	(HEAD + "@partition A(a: F/Account)\n  ownerships: F/Ownership = a <- Account\n"
		"@partition C(c: F/Company)\n  ownerships: F/Ownership = c <- Owner\n", "kind"),
	(HEAD + CLIENT + "- F/Person.Nickname\n", "exclusion"),
	(HEAD + CLIENT + "@index I Client\n  checks.Colour\n", "index"),
	(HEAD + CLIENT + "- F/IdentityCheck.Method\n@index I Client\n  checks.Method\n", "index"),
])
def testCheckErrors(text: str, code: str) -> None:
	assert code in codes(text)


def testPersonalValuesAboutAnotherKeyEntityNeedPrivacyKept() -> None:
	text = HEAD + CLIENT + "@partition Household(household: F/Household)\n  visits: F/Visit = household <- Household\n"
	assert codes(text) == {"privacy"}
	checked(text.replace("<- Household\n", "<- Household {privacy=kept}\n"))
	# NOTE: The visitor's own partition may keep them: Person is its key entity.
	checked(HEAD + CLIENT.replace("  documents", "  visits: F/Visit = client <- Visitor\n  documents"))


def testJsonIsCheckedLikeText() -> None:
	data = OPS.toJson(checked(EXAMPLE))
	assert OPS.print(OPS.fromJson(data)) == EXAMPLE
	with pytest.raises(FormatError):
		OPS.fromJson({**data, "uses": {"F": "Exchange"}})


# -----------------------------------------------------------------------------
#
# CLI
#
# -----------------------------------------------------------------------------


# NOTE: Spec-08's additions to Finance, as one more file of the workspace's Finance ontology.
IDENTITY = "@ontology Finance rev=2026-11-10 src=import card=? cards=assumed\n" + specExample("spec-08-store", 0).split("\n", 1)[1]


def addStore(workspace, text: str = EXAMPLE) -> None:
	(workspace / "finance/identity.onto").write_text(IDENTITY)
	(workspace / "finance/adviser-app.store").write_text(text)


def test_check_loads_the_store_ontology_and_its_system_mappings(workspace):
	addStore(workspace)
	status, _, err = onto("check", "finance/adviser-app.store")
	assert status == 0, err
	assert err.startswith("no problems in 1 file")


def test_ls_lists_stores_by_name(workspace):
	addStore(workspace)
	_, out, _ = onto("ls", "store")
	assert out.splitlines() == ["store\tAdviserApp\t2026-11-26\tfinance/adviser-app.store"]


def test_fmt_json_and_text_round_trip(workspace):
	addStore(workspace, EXAMPLE.replace("Finance                     --", "Finance --"))
	status, out, _ = onto("fmt", "finance/adviser-app.store")
	assert status == 0 and out == EXAMPLE
	status, out, _ = onto("json", "finance/adviser-app.store")
	assert status == 0 and json.loads(out)["format"] == "onto.store/1"
	(workspace / "store.json").write_text(out)
	assert onto("text", "store.json") == (0, EXAMPLE, "")


def test_check_reports_store_errors_in_the_store_file(workspace):
	addStore(workspace, EXAMPLE.replace("F/Household", "F/Nobody"))
	status, _, err = onto("check", "finance/adviser-app.store")
	assert status == 1 and "finance/adviser-app.store:" in err and "error partition" in err


def test_a_store_without_its_mapping_is_reported(workspace):
	addStore(workspace, EXAMPLE.replace("@system Exchange", "@system Feed"))
	status, _, err = onto("check", "finance/adviser-app.store")
	assert status == 1 and "error system" in err


# EOF
