"""Module: what a read's request selects — reads of one binding that differ by request key serve each the mapping
lines whose conditions their rows satisfy, and their rows' other obligations (spec-06 Rooted retrieval)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")

from onto import Source, loadBinding, loadMapping, loadOntology  # noqa: E402
from onto.integrations.hexa import HexaViewOperator, ViewDocument, ViewRead, ViewReadError  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.ontology import ViewInput  # noqa: E402
from onto.referential import loadReferential  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


# A note is filed under keys, as a CRM files a comment under a client or a matter; a note list is requested by key.
SOURCE = loadOntology([Source("source.onto", """@ontology Source
Client
  Id Text {key}
  Name Text
Matter
  Id Text {key}
  * Clients Client
Note
  Id Text {key}
  Text Text
  Deleted Boolean
Filing
  Id Text {key}
  Note Note
  Key Text
  Value Text
""")])
TARGET = loadOntology([Source("target.onto", """@ontology Target
@use Source as S
Party
  Id Text {key}
  Name Text
Matter
  Id Text {key}
Note
  Id Text {key}
  Body Text
Matter -concernsClient/hasMatterOnFile-> Party
Note -concerns/hasNote-> Party
Note -concerns/hasNote-> Matter
@view MatterNotes(matterId: S/Matter.Id)
  matter: Matter
  clients: Party = matter -> concernsClient
  clientNotes: Note = clients <- concerns
  matterNotes: Note = matter <- concerns
  clientNotes.Body
  matterNotes.Body
""")], [SOURCE])
MATTER_BINDING = loadBinding(SOURCE, Source("matter.bind", """@binding Source name=matter format=json
Matter <- $ {id=id}
  Id <- id
  Clients <- ref(Client, clients[*].id)
Client <- clients[*] {id=id}
  Id <- id
  Name <- name
"""))
NOTES = """@binding Source name=notes format=json
Note <- notes[*] {id=id}
  Id <- id
  Text <- text
%sFiling <- notes[*].keys[*] {id=concat(^.id, "/", key, "/", value)}
  Note <- ^
  Key <- key
  Value <- value
"""
NOTES_BINDING = loadBinding(SOURCE, Source("notes.bind", NOTES % "  Deleted <- deleted\n"))
REFERENTIAL = loadReferential([TARGET], [Source("keys.ref", """@referential Keys
@use Target as T
T/Party key=Id
T/Matter key=Id
T/Note key=Id
""")])
MAPPING = loadMapping(SOURCE, TARGET, Source("notes.map", """@mapping Source -> Target referential=Keys
Client -> Party
  Id <- Id
  Name <- Name

Matter -> Matter
  Id <- Id
  concernsClient <- Clients

Note -> Note {when=Deleted:false}
  Id <- Id
  Body <- Text

Filing -> Note {into=Note, when=Note.Deleted:false & Note.Text}
  concerns <- ref(Client, Value) {when=Key:ClientId}
  concerns <- ref(Matter, Value) {when=Key:MatterId}
"""), referentials=[REFERENTIAL])
MATTER = ViewInput("matterId", "Source/Matter", "Id")
CLIENT = ViewInput("clientId", "Source/Client", "Id")
DOCUMENTS = {
	("Matter", "m1"): {"id": "m1", "clients": [{"id": "c1", "name": "Ana"}]},
	("MatterNotes", "m1"): {"notes": [{"id": "n1", "text": "Valuation booked", "deleted": False, "keys": [{"key": "MatterId", "value": "m1"}]}]},
	("ClientNotes", "c1"): {"notes": [{"id": "n2", "text": "Prefers email", "deleted": False, "keys": [{"key": "ClientId", "value": "c1"}]}]},
}
SEED = {"matterId": "m1"}
FIELDS = ["clientNotes.Body", "matterNotes.Body"]


def reads(selecting: bool = True, **extra: ViewRead) -> dict[str, ViewRead]:
	"""The matter read first, then its notes; a client's notes only once the matter names the client."""
	selects = (lambda key: {"Source/Filing": f"Key:{key}"}) if selecting else (lambda key: None)
	return {"Matter": ViewRead(MATTER, [MATTER_BINDING], CLIENT), "MatterNotes": ViewRead(MATTER, [NOTES_BINDING], selects=selects("MatterId")),
		**extra, "ClientNotes": ViewRead(CLIENT, [NOTES_BINDING], selects=selects("ClientId"))}


def recorded(step: str, value: str) -> ViewDocument:
	return ViewDocument(DOCUMENTS[step, value], f"{step}:{value}")


def engine(catalogue: dict[str, ViewRead], fetch=recorded) -> HexaViewOperator:
	access = SimpleNamespace(describe=lambda step, value: {}, rootHandle=lambda key, value, kind: "Matter_" + value, fetch=fetch)
	return HexaViewOperator(HexaMappingOperator(SOURCE, TARGET, REFERENTIAL), MAPPING, catalogue, access)


def suppliers(plan: dict) -> dict[str, list[str]]:
	return {field: [hop["supplier"] for hop in path["hops"]] + [plan["fields"][field]] for field, path in plan["paths"].items()}


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def test_each_population_is_read_from_the_read_selecting_its_rows():
	plan = asyncio.run(engine(reads()).plan("MatterNotes", SEED, FIELDS))
	assert plan["gaps"] == []
	assert suppliers(plan) == {"clientNotes.Body": ["Matter", "ClientNotes", "ClientNotes"], "matterNotes.Body": ["MatterNotes", "MatterNotes"]}
	assert [step["step"] for step in plan["steps"]] == ["Matter", "MatterNotes", "ClientNotes"]


def test_without_a_selection_the_first_read_of_the_rows_serves_every_filing():
	plan = asyncio.run(engine(reads(selecting=False)).plan("MatterNotes", SEED, FIELDS))
	assert suppliers(plan)["clientNotes.Body"] == ["Matter", "MatterNotes", "MatterNotes"]
	assert "ClientNotes" not in [step["step"] for step in plan["steps"]]


def test_a_report_reads_each_population_from_its_own_read():
	report = json.loads(json.dumps(asyncio.run(engine(reads()).report("MatterNotes", SEED, FIELDS))))
	assert report["gaps"] == []
	assert sorted((fact["field"], fact["value"], fact["source"]) for fact in report["facts"]) == [
		("clientNotes.Body", "Prefers email", "ClientNotes:c1"), ("matterNotes.Body", "Valuation booked", "MatterNotes:m1")]


def test_a_failed_read_of_other_rows_hides_none_of_these_rows_facts():
	# The client's notes are read on their own: the matter's notes failing leaves them reported (spec-06).
	def fetch(step, value):
		if step == "MatterNotes":
			raise ViewReadError("matter notes are gone")
		return recorded(step, value)
	report = json.loads(json.dumps(asyncio.run(engine(reads(), fetch).report("MatterNotes", SEED, FIELDS))))
	assert [(fact["field"], fact["value"]) for fact in report["facts"]] == [("clientNotes.Body", "Prefers email")]
	assert sorted((item["field"], item["statuses"]) for item in report["coverage"]) == [
		("clientNotes.Body", ["supplied"]), ("matterNotes.Body", ["unavailable"])]


def test_a_compound_condition_needs_a_read_of_every_attribute_it_tests():
	# A client's notes read without their deletion state cannot tell which filings count (`Note.Deleted:false & Note.Text`).
	undeleted = ViewRead(CLIENT, [loadBinding(SOURCE, Source("undeleted.bind", NOTES % ""))])
	plan = asyncio.run(engine(reads(Undeleted=undeleted)).plan("MatterNotes", SEED, ["clientNotes.Body"]))
	assert suppliers(plan)["clientNotes.Body"] == ["Matter", "ClientNotes", "ClientNotes"]


@pytest.mark.parametrize(("selects", "message"), [
	({"Source/Missing": "Key:ClientId"}, "a read selects the rows of a source entity"),
	({"Source/Filing": "Key"}, "values of their own attributes"),
	({"Source/Filing": "Key:ClientId | Value:c1"}, "values of their own attributes"),
	({"Source/Filing": "Note.Deleted:false"}, "values of their own attributes"),
	({"Source/Filing": "Missing:x"}, "values of their own attributes"),
	({"Source/Filing": "Key:ClientId & Key:MatterId"}, "selects Key once"),
	({"Source/Matter": "Clients:c1"}, "single-valued attributes"),
])
def test_a_read_selects_rows_by_values_of_their_own_attributes(selects, message):
	with pytest.raises(ValueError, match=f"ClientNotes: .*{message}"):
		engine({**reads(), "ClientNotes": ViewRead(CLIENT, [NOTES_BINDING], selects=selects)})

# EOF
