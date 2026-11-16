"""Module: hexa index step tests — binding list positions (`rows[*][0]`, `pair[1].name`) through tuple shapes (spec-06)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import Source, loadBinding, loadOntology, printObservationsLog  # noqa: E402
from onto.integrations.hexa.compiler import CompileError  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, programEncoding  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


# A CRM returning each member of a group with its client, as [member, client] pairs
CRM = loadOntology([Source("crm.onto", """@ontology Crm

Address =
  City Text

Client
  Address Address
  FirstName Text
  Id Integer {key}

Group
  FirstClientName Text
  Id Integer {key}
  Name Text

Member
  Client Client
  Group Group
  Id Integer {key}
  KeyPerson Boolean
""")])

BINDING = """@binding Crm

Client <- clients[*][1] {id=id}
  Address.City <- address.city
  FirstName <- firstName
  Id <- id

Group <- $ {id=id}
  FirstClientName <- clients[0][1].firstName
  Id <- id
  Name <- name

Member <- clients[*][0] {id=id}
  Client <- ref(Client, clientId)
  Group <- ref(Group, groupId)
  Id <- id
  KeyPerson <- keyPerson
"""

GROUP = {
	"id": 1,
	"name": "Smith Family",
	"clients": [
		[{"id": 11, "groupId": 1, "clientId": 9, "keyPerson": True}, {"id": 9, "firstName": "Sam", "address": {"city": "Auckland"}}],
		[{"id": 12, "groupId": 1, "clientId": 10, "keyPerson": False}, {"id": 10, "firstName": "Sarah", "address": None}, "ignored"],
	],
}
SRC = "crm:group/1"
CLOCK = {"ClockRead": lambda context: "2026-11-17T09:00:00Z"}


def read(binding: str, document: dict):
	ops = HexaBindingOperator(CRM, mode="lenient")
	program = ops.compile(loadBinding(CRM, Source("crm.bind", binding)))
	result = asyncio.run(run(CLOCK, program.stages.BindingRead, [{"src": SRC, "document": document}]))
	return program, *ops.result(program, result)


# -----------------------------------------------------------------------------
#
# COMPILING
#
# -----------------------------------------------------------------------------


def test_scope_index_steps_select_the_list_and_read_the_position_by_a_tuple():
	program, _, _ = read(BINDING, GROUP)
	scopes = {scope.name: scope for scope in program.scopes}
	assert scopes["Member"].selector == "clients/*"
	assert scopes["Client"].selector == "clients/*"
	member = programEncoding(program)["Member"]["shape"]
	assert member["$tuple"][-1] == {"$rest": "$Any"}
	first = member["$tuple"][0]["$either"][1]["$tolerant"]["$loose"]
	assert set(first) == {"clientId?", "groupId?", "id?", "keyPerson?"}
	assert first["clientId?"] == {"$either": ["$Null", {"$tolerant": "$Bind.Member.Fields.At0ClientId"}]}
	client = programEncoding(program)["Client"]["shape"]
	assert client["$tuple"][0] == "$Any"


def test_index_steps_before_a_list_are_unsupported():
	binding = BINDING + "\nClient <- clients[0][*] {id=id}\n  Id <- id\n"
	with pytest.raises(CompileError, match="before"):
		read(binding, GROUP)


def test_a_value_read_as_a_position_and_a_field_is_unsupported():
	binding = BINDING.replace("  Name <- name", "  Name <- clients.name")
	with pytest.raises(CompileError, match="list position and as a field"):
		read(binding, GROUP)


# -----------------------------------------------------------------------------
#
# READING
#
# -----------------------------------------------------------------------------


def test_pairs_read_into_both_types():
	_, log, report = read(BINDING, GROUP)
	text = printObservationsLog(CRM, log)
	for line in ("Member_11.Client Client_9", "Member_11.Group Group_1", "Member_11.KeyPerson true", "Member_12.KeyPerson false",
		"Client_9.FirstName Sam", "Client_9.Address.City Auckland", "Client_10.FirstName Sarah", "Group_1.Name Smith Family"):
		assert line in text
	# The items past the pair are ignored; a null structure says nothing
	assert "Client_10.Address" not in text
	assert report.gaps == []


def test_body_index_steps_read_one_position():
	_, log, _ = read(BINDING, GROUP)
	assert "Group_1.FirstClientName Sam" in printObservationsLog(CRM, log)


def test_a_list_too_short_is_a_gap_for_that_record_only():
	group = json.loads(json.dumps(GROUP))
	group["clients"][1] = group["clients"][1][:1]
	_, log, report = read(BINDING, group)
	text = printObservationsLog(CRM, log)
	assert "Member_12.KeyPerson false" in text and "Client_9.FirstName Sam" in text
	assert "Client_10.FirstName" not in text
	assert [(gap.target, gap.location) for gap in report.gaps] == [("Crm/Client", "/clients/1")]


def test_a_missing_body_position_is_absent():
	group = json.loads(json.dumps(GROUP))
	group["clients"] = []
	_, log, _ = read(BINDING, group)
	text = printObservationsLog(CRM, log)
	assert "Group_1.Name Smith Family" in text and "FirstClientName" not in text

# EOF
