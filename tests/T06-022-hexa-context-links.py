"""Module: links a context association states — a rooted view reaches a link of a relation with a `context`
whether a relation claim or an instance of its association states it (spec-01 Rooted views, spec-06)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")

from onto import Source, loadBinding, loadMapping, loadOntology  # noqa: E402
from onto.integrations.hexa import HexaViewOperator, ViewDocument, ViewRead  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.ontology import ViewInput  # noqa: E402
from onto.referential import loadReferential  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SOURCE = loadOntology([Source("source.onto", """@ontology Source
Ledger
  Id Text {key}
Person
  Id Text {key}
  Name Text
  Borrowed Loan
Account
  Id Text {key}
  Ledger Ledger
  Owner Person
  Custodian Person
  HoldingFor Loan
Loan
  Id Text {key}
  Ledger Ledger
  Borrower Person
  Joint Boolean
  * Flags Text
""")])
TARGET_TEXT = """@ontology Target
@use Source as S
Ledger
  Id Text {key}
Party
  Id Text {key}
  Name Text
Position
  Id Text {key}
Holding(Holder: * Party, Position) {kind=state}
  Arrangement Text
Ledger -lists/isListedIn-> Position
Party -holds/isHeldBy-> Position {context=Holding, subjectRole=Holder, objectRole=Position}
@view LedgerHolders(ledgerId: S/Ledger.Id)
  ledger: Ledger
  positions: Position = ledger -> lists
  holdings: Holding = positions <- Position
  holders: Party = positions -> isHeldBy
  owners: Party = positions -> isHeldBy through ownership
  positions.isHeldBy
  holdings.Arrangement
  holders.Name
  ? owners.Name
"""
TARGET = loadOntology([Source("target.onto", TARGET_TEXT)], [SOURCE])
BINDING_TEXT = """@binding Source format=json
Ledger <- $ {id=id}
  Id <- id
Person <- people[*] {id=id, valid=holderValid}
  Id <- id
  Name <- name
  Borrowed <- ref(Loan, loan)
Account <- accounts[*] {id=id, valid=positionValid}
  Id <- id
  Ledger <- ^
  Owner <- ref(Person, owner)
  HoldingFor <- ref(Loan, holdingFor)
Loan <- loans[*] {id=id, valid=positionValid}
  Id <- id
  Ledger <- ^
  Borrower <- ref(Person, borrower)
  Joint <- joint
"""
BINDING = loadBinding(SOURCE, Source("ledger.bind", BINDING_TEXT))
REFERENTIAL = loadReferential([TARGET], [Source("keys.ref", """@referential Keys
@use Target as T
T/Ledger key=Id
T/Party key=Id
T/Position key=Id
""")])
MAPPING = """@mapping Source -> Target referential=Keys
Ledger -> Ledger
  Id <- Id

Person -> Party
  Id <- Id
  Name <- Name

Account -> Position
  Id <- Id
  isListedIn <- Ledger
%s
Loan -> Position
  Id <- Id
  isListedIn <- Ledger

Loan -> Holding
  Position <- $
  Holder <- Borrower
  Arrangement <- "Joint" {when=Joint:true}
"""
FORMS = {
	# An account's owner is stated as a link, a loan's borrower as a holding: one relation, two forms.
	"link": "  isHeldBy <- Owner\n",
	# Only holdings state who holds what.
	"association": "\nAccount -> Holding\n  Position <- $\n  Holder <- Owner\n",
}
DOCUMENT = {"id": "L1", "people": [{"id": "p1", "name": "Ana"}, {"id": "p2", "name": "Ben"}],
	"accounts": [{"id": "a1", "owner": "p1"}],
	"loans": [{"id": "n1", "borrower": "p2", "joint": False}, {"id": "n2", "joint": True}]}
SEED = {"ledgerId": "L1"}


LEDGER_KEY = ViewInput("ledgerId", "Source/Ledger", "Id")
SPLIT_MAPPING = (MAPPING % "").replace("  Holder <- Borrower\n", "") + """
Person -> Holding {into=Borrowed, present=Borrowed}
  Holder <- $
"""


def engine(form: str = "link", *, mappingText=None, targetText=TARGET_TEXT, reads=None, documents=None) -> HexaViewOperator:
	target = TARGET if targetText == TARGET_TEXT else loadOntology([Source("target.onto", targetText)], [SOURCE])
	mapping = loadMapping(SOURCE, target, Source("ledger.map", mappingText or MAPPING % FORMS[form]), referentials=[REFERENTIAL])
	access = SimpleNamespace(describe=lambda step, value: {}, rootHandle=lambda key, value, kind: f"{kind.rsplit('/', 1)[-1]}_{value}",
		discover=lambda state, key: (), fetch=lambda step, value: ViewDocument(documents[step] if documents is not None else DOCUMENT, step))
	return HexaViewOperator(HexaMappingOperator(SOURCE, target, REFERENTIAL), mapping,
		reads if reads is not None else {"Ledger": ViewRead(LEDGER_KEY, [BINDING])}, access)


def report(form: str, fields: list[str]) -> dict:
	return json.loads(json.dumps(asyncio.run(engine(form).report("LedgerHolders", SEED, fields))))


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("form", FORMS)
def test_a_link_is_stated_by_its_relation_or_by_an_instance_of_its_context(form):
	result = report(form, ["positions.isHeldBy", "holders.Name"])
	assert result["gaps"] == []
	links = {(fact["subject"], fact["value"]["ref"], fact.get("through", "").startswith("Holding_"))
		for fact in result["facts"] if fact["field"] == "positions.isHeldBy"}
	assert links == {("Position_a1", "Party_p1", form == "association"), ("Position_n1", "Party_p2", True)}
	# The joint loan's holding names no holder: it states no link.
	assert [item["statuses"] for item in result["coverage"] if item["field"] == "positions.isHeldBy" and item["subject"] == "Position_n2"] == [["missing"]]
	names = {fact["value"]: fact["path"][-1] for fact in result["facts"] if fact["field"] == "holders.Name"}
	assert sorted(names) == ["Ana", "Ben"]
	# A hop a holding proves names it, as a fact does.
	assert names["Ben"]["through"].startswith("Holding_") and names["Ben"]["via"] == "Position.isHeldBy"
	assert ("through" in names["Ana"]) is (form == "association")


def test_a_link_only_associations_state_is_planned_from_their_scopes():
	plan = asyncio.run(engine("association").plan("LedgerHolders", SEED, ["positions.isHeldBy"]))
	assert plan["gaps"] == [] and plan["fields"] == {"positions.isHeldBy": "Ledger"}


def test_retrieval_keeps_both_role_claims_of_a_holding_stating_a_link():
	obs = asyncio.run(engine("link").retrieve("LedgerHolders", SEED, ["positions.isHeldBy"]))
	holding, = (handle for handle, item in obs.instances.items() if item["type"] == "Target/Holding")
	assert {claim["p"]: claim["v"] for claim in obs.claims if claim.get("s") == holding} == {
		"Position": {"ref": "Position_n1"}, "Holder": {"ref": "Party_p2"}}
	held = [claim["roles"] for claim in obs.claims if claim.get("rel", "").endswith(".holds.Target/Position")]
	assert held == [{"Party": "Party_p1", "Position": "Position_a1"}]


def test_through_reaches_only_the_links_an_association_states():
	result = report("link", ["owners.Name", "holdings.Arrangement"])
	assert [fact["value"] for fact in result["facts"] if fact["field"] == "owners.Name"] == ["Ben"]
	# A holding's own state is the association's: the joint loan's has an arrangement and no holder.
	assert [fact["value"] for fact in result["facts"] if fact["field"] == "holdings.Arrangement"] == ["Joint"]


@pytest.mark.parametrize("holderValid, expected", [("2021-01-01..", None), ("2020-06-01..", "2020-06-01..2020-12-31")])
def test_split_scope_roles_prove_a_link_only_during_their_shared_validity(holderValid, expected):
	loans = [DOCUMENT["loans"][0] | {"positionValid": "2020-01-01..2020-12-31"}]
	people = [DOCUMENT["people"][1] | {"loan": "n1", "holderValid": holderValid}]
	op = engine(mappingText=SPLIT_MAPPING, documents={"Ledger": DOCUMENT | {"loans": loans, "people": people}})
	fields = ["positions.isHeldBy", "holders.Name", "owners.Name"]
	result = asyncio.run(op.report("LedgerHolders", SEED, fields))
	assert not result["gaps"]
	if expected is None:
		assert not result["facts"]
		assert not asyncio.run(op.retrieve("LedgerHolders", SEED, fields)).claims
	else:
		link, plain, explicit = result["facts"]
		assert [(fact["field"], fact["value"]) for fact in result["facts"]] == [
			("positions.isHeldBy", {"ref": "Party_p2"}), ("holders.Name", "Ben"), ("owners.Name", "Ben")]
		assert link["valid"] == plain["path"][-1]["valid"] == explicit["path"][-1]["valid"] == expected
		obs = asyncio.run(op.retrieve("LedgerHolders", SEED, fields))
		assert {c["p"]: c["valid"] for c in obs.claims if c.get("s") == link["through"]} == {
			"Position": "2020-01-01..2020-12-31", "Holder": holderValid}


def test_role_writers_for_distinct_named_associations_do_not_supply_a_link():
	mapping = (MAPPING % "").replace("Loan -> Holding\n", "Loan -> Holding {name=LoanPosition}\n").replace("  Holder <- Borrower\n", "") + """
Loan -> Holding {name=LoanHolder}
  Holder <- Borrower
"""
	plan = asyncio.run(engine(mappingText=mapping).plan("LedgerHolders", SEED, ["positions.isHeldBy"]))
	assert [gap["reason"] for gap in plan["gaps"]] == ["SelectionRequest.Unmapped"]


def test_guarded_projection_matches_both_role_claims_of_the_path():
	target = TARGET_TEXT.replace("holders: Party = positions -> isHeldBy\n", "holders: Party = positions -> isHeldBy where Name=Ben\n")
	mapping = SPLIT_MAPPING.replace('  Arrangement <- "Joint" {when=Joint:true}\n', "") + """
Account -> Holding {into=HoldingFor, present=HoldingFor}
  Position <- $
  Arrangement <- "Updated"
"""
	update = loadBinding(SOURCE, Source("update.bind", """@binding Source format=json
Account <- accounts[*] {id=id, valid=positionValid}
  Id <- id
  HoldingFor <- ref(Loan, holdingFor)
"""))
	base = loadBinding(SOURCE, Source("ledger.bind", BINDING_TEXT.replace("  HoldingFor <- ref(Loan, holdingFor)\n", "")))
	reads = {"Ledger": ViewRead(LEDGER_KEY, [base]), "Update": ViewRead(LEDGER_KEY, [update])}
	periods = ["2020-01-01..2020-12-31", "2021-01-01.."]
	loans = [DOCUMENT["loans"][0] | {"positionValid": periods[0]}]
	people = [DOCUMENT["people"][1] | {"loan": "n1"}]
	documents = {"Ledger": DOCUMENT | {"loans": loans, "people": people}, "Update": {"accounts": [{"id": "n1", "holdingFor": "n1", "positionValid": periods[1]}]}}
	op = engine(mappingText=mapping, targetText=target, reads=reads, documents=documents)
	result = asyncio.run(op.report("LedgerHolders", SEED, ["positions.isHeldBy", "holdings.Arrangement"]))
	assert not result["gaps"]
	links = [fact for fact in result["facts"] if fact["field"] == "positions.isHeldBy"]
	assert sorted((fact["valid"], fact["path"][-2]["valid"]) for fact in links) == [(period, period) for period in periods]


def test_symmetric_association_link_reaches_a_specialisation_in_the_second_role():
	target = TARGET_TEXT.replace("Party\n", "Party < Thing\n", 1).replace("Position\n  Id", "Position < Thing\n  Id", 1) + """
Thing
Sharing(First: Thing, Second: Thing)
Thing -shares/shares-> Thing {context=Sharing, subjectRole=First, objectRole=Second}
@view Sharers(ledgerId: S/Ledger.Id)
  ledger: Ledger
  positions: Position = ledger -> lists
  peers: Party = positions -> shares
  positions.shares
  peers.Name
"""
	mapping = MAPPING % "" + """
Loan -> Sharing
  First <- Borrower
  Second <- $
"""
	result = asyncio.run(engine(mappingText=mapping, targetText=target).report("Sharers", SEED))
	assert not result["gaps"]
	assert [fact["value"] for fact in result["facts"]] == [{"ref": "Party_p2"}, "Ben"]


def test_reverse_hop_does_not_override_the_first_eligible_leaf_read():
	target = TARGET_TEXT.replace("ledger -> lists", "ledger <- isListedIn")
	binding = loadBinding(SOURCE, Source("owners.bind", """@binding Source format=json
Account <- accounts[*] {id=id}
  Id <- id
  Owner <- ref(Person, owner)
Person <- people[*] {id=id}
  Id <- id
"""))
	reads = {"Owners": ViewRead(LEDGER_KEY, [binding]), "Listing": ViewRead(LEDGER_KEY, [BINDING])}
	documents = {"Owners": DOCUMENT, "Listing": {"id": "L1", "accounts": [{"id": "a1"}], "people": [], "loans": []}}
	op = engine(targetText=target, reads=reads, documents=documents)
	result = asyncio.run(op.report("LedgerHolders", SEED, ["positions.isHeldBy"]))
	assert not result["gaps"] and result["fields"] == {"positions.isHeldBy": "Owners"}
	assert {item["step"] for item in result["steps"]} == {"Owners", "Listing"}
	assert [fact["value"]["ref"] for fact in result["facts"]] == ["Party_p1"]


def test_supplier_filters_binary_endpoint_types_not_just_association_roles():
	target = TARGET_TEXT.replace("Party -holds", "Individual -holds").replace(": Party = positions", ": Individual = positions") + """
Individual < Party
Institution < Party
@view AccountHolder(id: S/Account.Id)
  position: Position
  position.isHeldBy
"""
	mapping = (MAPPING % "").replace("Person -> Party\n", "Person -> Individual\n").replace("  Holder <- Borrower\n", "") + """
Person -> Institution
  Id <- Id
Account -> Holding {name=Custody}
  Position <- $
  Holder <- Custodian {as=Institution}
Account -> Holding {name=Ownership}
  Position <- $
  Holder <- Owner {as=Individual}
"""
	key = ViewInput("id", "Source/Account", "Id")
	reads = {step: ViewRead(key, [loadBinding(SOURCE, Source(f"{step}.bind", f"""@binding Source format=json
Account <- $ {{id=id}}
  Id <- id
  {role} <- ref(Person, holder)
Person <- person {{id=id}}
  Id <- id
"""))]) for step, role in (("Custodian", "Custodian"), ("Owner", "Owner"))}
	documents = {step: {"id": "a1", "holder": "p1", "person": {"id": "p1"}} for step in reads}
	op = engine(targetText=target, mappingText=mapping, reads=reads, documents=documents)
	result = asyncio.run(op.report("AccountHolder", {"id": "a1"}, ["position.isHeldBy"]))
	assert not result["gaps"] and result["fields"] == {"position.isHeldBy": "Owner"}
	assert [fact["value"]["ref"] for fact in result["facts"]] == ["Individual_p1"]


def test_read_selection_can_rule_out_a_supplier_on_a_single_valued_field():
	reads = {name: ViewRead(LEDGER_KEY, [BINDING], selects={"Source/Loan": f"Joint:{value}"})
		for name, value in (("Sole", "false"), ("Joint", "true"))}
	plan = asyncio.run(engine(reads=reads).plan("LedgerHolders", SEED, ["holdings.Arrangement"]))
	assert not plan["gaps"] and plan["fields"] == {"holdings.Arrangement": "Joint"}


def test_read_selection_rejects_multivalued_attributes():
	with pytest.raises(ValueError, match="single-valued attributes, not Flags"):
		engine(reads={"Ledger": ViewRead(LEDGER_KEY, [BINDING], selects={"Source/Loan": "Flags:Active"})})

# EOF
