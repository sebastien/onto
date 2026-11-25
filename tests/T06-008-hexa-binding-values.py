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


DEPOSITS = loadOntology([Source("deposits.onto", "@ontology Deposits\nDeposit\n  Cash Number\n  Gift Number\n  Count Integer\n  Kind Text\n  Known Boolean\n")])
DEPOSIT_BINDING = """@binding Deposits
Deposit <- $ {id=id}
  Cash <- cash {unset=0}
  Count <- count {unset=0}
  Gift <- gift {unset=0}
  Kind <- kind {unset=None}
  Known <- known {unset=false}
"""


@pytest.mark.parametrize(("document", "expected"), [
	({"id": 1, "cash": 0.0, "count": "0", "gift": 25000, "kind": "None", "known": False}, ["Deposit_1.Gift 25000"]),
	({"id": 1, "cash": 1e3, "count": 2, "gift": 0, "kind": "Cash", "known": True},
		["Deposit_1.Cash 1000", "Deposit_1.Count 2", "Deposit_1.Kind Cash", "Deposit_1.Known true"]),
	({"id": 1, "kind": "Cash"}, ["Deposit_1.Kind Cash"]),
])
def test_a_value_the_source_writes_for_not_given_says_nothing(document, expected):
	# spec-04: `{unset=V}` reads V as an absent value: no claim, no gap
	ops = HexaBindingOperator(DEPOSITS, mode="lenient")
	program = ops.compile(loadBinding(DEPOSITS, Source("deposits.bind", DEPOSIT_BINDING)))
	log, report = ops.result(program, asyncio.run(run(CLOCK, program.stages.BindingRead, [{"src": SRC, "document": document}])))
	text = printObservationsLog(DEPOSITS, log)
	assert report.gaps == []
	assert sorted(line.strip().split(" {")[0] for line in text.splitlines() if line.strip().startswith("Deposit_1.")) == expected


@pytest.mark.parametrize("sentinel", ["", "not given, see note"])
def test_a_quoted_text_sentinel_suppresses_only_the_matching_value(sentinel):
	text = DEPOSIT_BINDING.replace("{unset=None}", f'{{unset="{sentinel}"}}')
	ops = HexaBindingOperator(DEPOSITS, mode="lenient")
	program = ops.compile(loadBinding(DEPOSITS, Source("deposits.bind", text)))
	cases = [{"src": SRC, "document": {"id": identifier, "kind": kind}} for identifier, kind in [(1, sentinel), (2, "Cash")]]
	log, report = ops.result(program, asyncio.run(run(CLOCK, program.stages.BindingRead, cases)))
	assert not report.gaps
	assert "Deposit_1.Kind" not in printObservationsLog(DEPOSITS, log)
	assert "Deposit_2.Kind Cash" in printObservationsLog(DEPOSITS, log)

# EOF
