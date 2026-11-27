"""Filters in read choice: a population's filter narrows its rows to the source types a mapping line can give the tested
value, so that catalogue order does not decide which read supplies them (spec-06 Rooted retrieval)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")

from onto import Source, loadBinding, loadMapping, loadOntology  # noqa: E402
from onto.integrations.hexa import HexaViewOperator, ViewRead  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.ontology import ViewInput  # noqa: E402

# A CRM files notes (comments) and logged contacts (records) under clients, and lists a household's clients and
# dependants in separate rows.
SOURCE = loadOntology([Source("s.onto", """@ontology S
Kind = Email|Meeting
Client
  1 Id Integer {key}
  Name Text
Comment
  Client Client
  Note Text
Record
  Client Client
  Kind Kind
  Notes Text
Household
  Client Client
HouseholdClient
  Household Household
  Client Client
Dependant
  FirstName Text
HouseholdDependant
  Household Household
  Dependant Dependant
""")])
TARGET = """@ontology T
@use S as S
Interaction/Type = FileNote|Email|Meeting
Person
  Name Text
Household
Interaction
  Type Interaction/Type
  Body Text
Membership(Household, Member: Person)
  Role Adult|Dependant
Interaction -concerns/isConcernedBy-> Person
Person -isClientOf/hasClientHousehold-> Household
@view ClientNotes(clientId: S/Client.Id)
  client: Person
  notes: Interaction = client <- concerns where Type=FileNote
  notes.Body
@view ClientMeetings(clientId: S/Client.Id)
  client: Person
  meetings: Interaction = client <- concerns where Type=Meeting
  meetings.Body
@view ClientDependants(clientId: S/Client.Id)
  client: Person
  household: Household = client -> isClientOf
  dependantMemberships: Membership = household <- Household where Role=Dependant
  dependants: Person = dependantMemberships -> Member
  dependants.Name
"""
MAPPING = """@mapping S -> T
@map Kinds Kind -> Interaction/Type
  Email exact Email
  Meeting exact Meeting

Client -> Person
  Name <- Name
Comment -> Interaction
  Type <- "FileNote"
  Body <- Note
  concerns <- Client
Record -> Interaction
  Type <- Kinds(Kind)
  Body <- Notes
  concerns <- Client
Household -> Household
  hasClientHousehold <- Client
HouseholdClient -> Membership
  Household <- Household
  Member <- Client
Dependant -> Person
  Name <- FirstName
HouseholdDependant -> Membership
  Household <- Household
  Member <- Dependant
  Role <- "Dependant"
"""
CLIENT = ViewInput("clientId", "S/Client", "Id")


def binding(text):
	return loadBinding(SOURCE, Source("b.bind", "@binding S format=json\n" + text))


# Each read is listed before the one a filtered population needs.
READS = {
	"Records": ViewRead(CLIENT, [binding("Record <- rows[*] {id=id}\n  Client <- ref(Client, clientId)\n  Kind <- kind\n  Notes <- notes\n")]),
	"Comments": ViewRead(CLIENT, [binding("Comment <- rows[*] {id=id}\n  Client <- ref(Client, clientId)\n  Note <- note\n")]),
	"Households": ViewRead(CLIENT, [binding("Household <- households[*] {id=id}\n  Client <- ref(Client, clientId)\n"
		"HouseholdClient <- households[*].clients[*] {id=id}\n  Household <- ref(Household, householdId)\n  Client <- ref(Client, clientId)\n"
		"HouseholdDependant <- households[*].dependants[*] {id=id}\n  Household <- ref(Household, householdId)\n  Dependant <- ref(Dependant, dependantId)\n")]),
	"Clients": ViewRead(CLIENT, [binding("Client <- $ {id=id}\n  Id <- id\n  Name <- name\n")]),
	"Dependants": ViewRead(CLIENT, [binding("Dependant <- dependants[*] {id=id}\n  FirstName <- firstName\n")]),
}


def operator(reads=READS):
	target = loadOntology([Source("t.onto", TARGET)], [SOURCE])
	mapping = loadMapping(SOURCE, target, Source("m.map", MAPPING))
	access = SimpleNamespace(rootHandle=lambda param, value, kind: f"Person_S_2FClient_2F{value}", fetch=lambda step, value: None)
	return HexaViewOperator(HexaMappingOperator(SOURCE, target, mode="lenient"), mapping, reads, access)


def plan(view, field, reads=READS):
	result = asyncio.run(operator(reads).plan(view, {"clientId": 9}, [field]))
	return result["fields"][field], [step["step"] for step in result["steps"]]


def test_a_value_map_without_the_tested_value_gives_no_rows():
	# Records map their kind through a map whose values never include FileNote: the notes are the comments'.
	assert plan("ClientNotes", "notes.Body") == ("Comments", ["Comments"])


def test_a_value_map_with_the_tested_value_still_gives_rows():
	assert plan("ClientMeetings", "meetings.Body") == ("Records", ["Records"])


def test_a_scope_with_no_line_for_the_filtered_member_gives_no_rows():
	# Clients have names too, from a read listed first. A client's membership states no role: only dependant memberships pass Role=Dependant, so the dependants are the
	# dependant rows, whose names the Dependants read supplies.
	field, steps = plan("ClientDependants", "dependants.Name")
	assert field == "Dependants"
	assert "Dependants" in steps


def test_without_a_filter_catalogue_order_still_decides():
	reads = {name: READS[name] for name in ("Records", "Comments")}
	target = loadOntology([Source("t.onto", TARGET.replace(" where Type=FileNote", ""))], [SOURCE])
	mapping = loadMapping(SOURCE, target, Source("m.map", MAPPING))
	access = SimpleNamespace(rootHandle=lambda param, value, kind: f"Person_S_2FClient_2F{value}", fetch=lambda step, value: None)
	op = HexaViewOperator(HexaMappingOperator(SOURCE, target, mode="lenient"), mapping, reads, access)
	assert asyncio.run(op.plan("ClientNotes", {"clientId": 9}, ["notes.Body"]))["fields"] == {"notes.Body": "Records"}

# EOF
