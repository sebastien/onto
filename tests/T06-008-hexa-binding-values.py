"""Module: hexa binding value tests — spec-04 presence and collection rules in binding runs (spec-06)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import Source, loadBinding, loadOntology, printObservationsLog  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator  # noqa: E402
from onto.integrations.hexa.vocabulary import reference  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


CRM = loadOntology([Source("crm.onto", """@ontology Crm

Adviser
  Id Integer {key}
  Name Text

Client
  * Advisers Adviser
  Id Integer {key}
  Owner Adviser
  * Tags Text
""")])

BINDING = """@binding Crm

Adviser <- owner {id=id}
  Id <- id
  Name <- name

Client <- $ {id=id}
  Advisers <- ref(Adviser, advisers[*].id)
  Id <- id
  Owner <- ref(Adviser, ownerId)
  Tags <- tags
"""

SRC = "crm:client/1"
CLOCK = {"ClockRead": lambda context: "2026-11-17T09:00:00Z"}


def read(document: dict):
	ops = HexaBindingOperator(CRM, mode="lenient")
	program = ops.compile(loadBinding(CRM, Source("crm.bind", BINDING)))
	result = asyncio.run(run(CLOCK, program.stages.BindingRead, [{"src": SRC, "document": document}]))
	log, report = ops.result(program, result)
	return printObservationsLog(CRM, log), report


# -----------------------------------------------------------------------------
#
# COLLECTIONS
#
# -----------------------------------------------------------------------------


def test_ref_applies_to_each_member_of_a_collection():
	# spec-04: a function given a collection where it expects one value applies to each member
	text, report = read({"id": 1, "ownerId": 7, "advisers": [{"id": 3}, {"id": 4}], "owner": None})
	assert "Client_1.Advisers [Adviser_3:Adviser, Adviser_4:Adviser]" in text
	assert "Client_1.Owner Adviser_7:Adviser" in text
	assert report.gaps == []


def test_ref_of_a_collection_skips_null_members_and_keeps_partial_sets():
	assert reference("Crm/Adviser", [3, None]) == [{"ref": "Adviser_3", "type": "Crm/Adviser"}]
	assert reference("Crm/Adviser", {"set": [3], "partial": True}) == {"set": [{"ref": "Adviser_3", "type": "Crm/Adviser"}], "partial": True}


def test_a_collection_member_type_mismatch_is_a_field_gap():
	text, report = read({"id": 1, "owner": None, "ownerId": 7, "advisers": [], "tags": ["valid", False]})
	assert "Client_1.Owner Adviser_7:Adviser" in text and "Client_1.Tags" not in text
	assert [(gap.target, gap.reason) for gap in report.gaps] == [("Crm/Client.Tags", "Binding.TypeMismatch")]


# -----------------------------------------------------------------------------
#
# PRESENCE
#
# -----------------------------------------------------------------------------


def test_a_null_record_makes_no_instance_and_no_gap():
	# spec-04: a value is present when the field exists and is not null
	text, report = read({"id": 1, "ownerId": 7, "advisers": [], "owner": None})
	assert "Client_1:Client" in text and "Adviser_7.Name" not in text
	assert report.gaps == []


def test_a_present_record_is_read():
	text, _ = read({"id": 1, "ownerId": 7, "advisers": [], "owner": {"id": 7, "name": "Kelly"}})
	assert "Adviser_7.Name Kelly" in text


def test_a_missing_record_is_still_a_gap():
	_, report = read({"id": 1, "ownerId": 7, "advisers": []})
	assert [gap.target for gap in report.gaps] == ["Crm/Adviser"]

# EOF
