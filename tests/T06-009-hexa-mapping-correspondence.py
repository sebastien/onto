"""Module: hexa mapping correspondence tests — one source instance with several target instances, and `$` (spec-04 Instances)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadBinding, loadMapping, loadOntology, observationsToJson, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, HexaMappingOperator  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


# A CRM row of a client is both a person and the practice's relationship with them
CRM = loadOntology([Source("crm.onto", """@ontology Crm

Client
  Company Company
  Id Integer {key}
  Name Text
  Status Text

Company
  Id Integer {key}
  Name Text

Member
  Client Client
  Id Integer {key}
""")])

OS = loadOntology([Source("os.onto", """@ontology Os

Membership
  Member Party

Organisation < Party
  Name Text

Party

Person < Party
  Name Text

Relationship(Practice: Organisation, Client: Party) {kind=state}
  Status Text

Membership -concerns/isConcernedBy-> Party
""")])

BINDING = """@binding Crm

Client <- clients[*] {id=id}
  Company <- ref(Company, companyId)
  Id <- id
  Name <- name
  Status <- status

Company <- companies[*] {id=id}
  Id <- id
  Name <- name

Member <- members[*] {id=id}
  Client <- ref(Client, clientId)
  Id <- id
"""

MAPPING = """@mapping Crm -> Os

Client -> Person
  Name <- Name

Client -> Relationship
  Client <- $
  Practice <- Company
  Status <- Status

Company -> Organisation
  Name <- Name

Member -> Membership
  Member <- Client
  concerns <- Client
"""

DOCUMENT = {
	"companies": [{"id": 1, "name": "LFG"}],
	"clients": [{"id": 9, "companyId": 1, "name": "Sam", "status": "Client"}],
	"members": [{"id": 11, "clientId": 9}],
}
CLOCK = {"ClockRead": lambda context: "2026-11-17"}


def state() -> dict:
	ops = HexaBindingOperator(CRM)
	program = ops.compile(loadBinding(CRM, Source("crm.bind", BINDING)))
	log, _ = ops.result(program, asyncio.run(run(CLOCK, program.stages.BindingRead, [{"src": "crm:1", "document": DOCUMENT}])))
	return observationsToJson(reconcileObservations(CRM, log))


def mapped(text: str = MAPPING):
	ops = HexaMappingOperator(CRM, OS)
	program = ops.compile(loadMapping(CRM, OS, Source("crm-os.map", text)))
	result = asyncio.run(run(CLOCK, program.stages.MappingRead, state()))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


def instances(data: dict, typePath: str) -> list[str]:
	return sorted(handle for handle, item in data["instances"].items() if item["type"] == typePath)


def values(data: dict, handle: str) -> dict:
	return {claim["p"]: claim["v"] for claim in data["claims"] if claim.get("s") == handle and "p" in claim}


# -----------------------------------------------------------------------------
#
# STATIC
#
# -----------------------------------------------------------------------------


def test_references_choose_the_scope_whose_target_the_receiver_accepts():
	mapping = loadMapping(CRM, OS, Source("crm-os.map", MAPPING))
	assert [scope.target for scope in mapping.scopes if scope.source == "Crm/Client"] == ["Os/Person", "Os/Relationship"]


def test_a_receiver_no_scope_fits_is_an_error():
	# An organisation is neither the client's person nor their relationship
	with pytest.raises(FormatError, match="none of Os/Person, Os/Relationship fits"):
		loadMapping(CRM, OS, Source("crm-os.map", MAPPING.replace("  Practice <- Company", "  Practice <- $")))


def test_two_scopes_with_the_same_target_stay_ambiguous():
	text = MAPPING + "\nClient -> Person {when=Status:Lead}\n  Name <- Name\n"
	with pytest.raises(FormatError, match="several"):
		loadMapping(CRM, OS, Source("crm-os.map", text))


def test_dollar_is_only_the_whole_instance():
	with pytest.raises(FormatError):
		loadMapping(CRM, OS, Source("crm-os.map", MAPPING.replace("  Client <- $", "  Client <- $.Company")))


# -----------------------------------------------------------------------------
#
# RUNNING
#
# -----------------------------------------------------------------------------


def test_each_scope_makes_its_own_target_instance():
	data, report = mapped()
	assert data["instances"] == {
		"Membership_Crm_2FMember_2F11": {"type": "Os/Membership"},
		"Organisation_Crm_2FCompany_2F1": {"type": "Os/Organisation"},
		"Person_Crm_2FClient_2F9": {"type": "Os/Person"},
		"Relationship_Crm_2FClient_2F9": {"type": "Os/Relationship"},
	}
	assert values(data, "Person_Crm_2FClient_2F9") == {"Name": "Sam"}
	assert report.gaps == []


def test_references_and_dollar_resolve_to_the_accepted_target():
	data, _ = mapped()
	# `$` and `Company` in the relationship; the client's person, not the relationship itself
	assert values(data, "Relationship_Crm_2FClient_2F9") == {"Client": {"ref": "Person_Crm_2FClient_2F9"}, "Practice": {"ref": "Organisation_Crm_2FCompany_2F1"}, "Status": "Client"}
	# A role accepting a Party, and a verb to a Party
	assert values(data, "Membership_Crm_2FMember_2F11") == {"Member": {"ref": "Person_Crm_2FClient_2F9"}}
	relations = [claim["roles"] for claim in data["claims"] if claim.get("rel") == "Os/Membership.concerns.Os/Party"]
	assert relations == [{"Membership": "Membership_Crm_2FMember_2F11", "Party": "Person_Crm_2FClient_2F9"}]

def test_a_reference_to_an_instance_its_scope_skips_is_an_implicit_typed_instance():
	# The company's scope skips it; the relationship still refers to its organisation
	data, _ = mapped(MAPPING.replace("Company -> Organisation", "Company -> Organisation {when=Name:Other}"))
	assert data["instances"]["Organisation_Crm_2FCompany_2F1"] == {"type": "Os/Organisation"}
	assert not any(claim.get("s") == "Organisation_Crm_2FCompany_2F1" for claim in data["claims"])
	assert values(data, "Relationship_Crm_2FClient_2F9")["Practice"] == {"ref": "Organisation_Crm_2FCompany_2F1"}

def test_an_absent_reference_to_a_type_with_several_targets_says_nothing():
	# The member's client is absent: no claim, no gap, no failure
	global DOCUMENT
	saved = DOCUMENT
	DOCUMENT = {**saved, "members": [{"id": 11}]}
	try:
		data, report = mapped()
	finally:
		DOCUMENT = saved
	assert values(data, "Membership_Crm_2FMember_2F11") == {}
	assert not any(claim.get("rel") == "Os/Membership.concerns.Os/Party" for claim in data["claims"])
	assert report.gaps == []

# EOF
