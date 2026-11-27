"""Module: compositions in rooted retrieval — a read names the link it discovers its key along (`via`); a view takes a
key along the links it follows and the compositions (`{part}`) of what it reaches, never along another link
(spec-01 Binary shorthand, spec-06 Rooted retrieval)."""

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


# An application is made on one needs analysis, which it is part of; the analysis states its clients' names. A
# client's analyses are listed by client: an ordinary link, as a person collects analyses without belonging to them.
SOURCE = loadOntology([Source("source.onto", """@ontology Source
Client
  Id Text {key}
  Name Text
Analysis
  Id Text {key}
  Date Date
  * Clients Client
Application
  Id Text {key}
  Analysis Analysis
  * Clients Client
""")])
TARGET = """@ontology Target
@use Source as S
Party
  Id Text {key}
  Name Text
Engagement
  Id Text {key}
  Date Date
Application
  Id Text {key}
Engagement -resultsIn/resultsFromEngagement-> Application ?:*%s
Engagement -hasClient/isClientIn-> Party
Application -concernsClient/hasApplication-> Party
@view ApplicationClients(applicationId: S/Application.Id)
  application: Application
  clients: Party = application -> concernsClient
  clients.Name
@view ClientHistory(clientId: S/Client.Id)
  client: Party
  engagements: Engagement = client -> isClientIn
  engagements.Date
"""
COMPOSED = TARGET % " {part}"
APPLICATION_BINDING = loadBinding(SOURCE, Source("application.bind", """@binding Source name=application format=json
Analysis <- analysis {id=id}
  Id <- id
Application <- $ {id=id}
  Analysis <- ref(Analysis, analysis.id)
  Clients <- ref(Client, clients[*].id)
  Id <- id
Client <- clients[*] {id=id}
  Id <- id
"""))
ANALYSES_BINDING = loadBinding(SOURCE, Source("analyses.bind", """@binding Source name=analyses format=json
Analysis <- analyses[*] {id=id}
  Clients <- ref(Client, clients[*].id)
  Id <- id
"""))
ANALYSIS_BINDING = loadBinding(SOURCE, Source("analysis.bind", """@binding Source name=analysis format=json
Analysis <- $ {id=id}
  Clients <- ref(Client, clients[*].id)
  Date <- date
  Id <- id
Client <- clients[*] {id=id}
  Id <- id
  Name <- name
"""))
APPLICATION = ViewInput("applicationId", "Source/Application", "Id")
ANALYSIS = ViewInput("analysisId", "Source/Analysis", "Id")
CLIENT = ViewInput("clientId", "Source/Client", "Id")
# Ana's later analysis states her married name: a view that does not follow her analyses must not read it.
DOCUMENTS = {
	("application", "app1"): {"id": "app1", "analysis": {"id": "a1"}, "clients": [{"id": "c1"}]},
	("analyses", "c1"): {"analyses": [{"id": "a1", "clients": [{"id": "c1"}]}, {"id": "a2", "clients": [{"id": "c1"}]}]},
	("analysis", "a1"): {"id": "a1", "date": "2026-09-21", "clients": [{"id": "c1", "name": "Ana"}]},
	("analysis", "a2"): {"id": "a2", "date": "2026-09-29", "clients": [{"id": "c1", "name": "Ana Smith"}]},
}
DOCUMENT = {"Application": "application", "ApplicationClients": "application", "ClientAnalyses": "analyses", "Analysis": "analysis"}


def reads(**changed: ViewRead) -> dict[str, ViewRead]:
	"""The application names its analysis, its whole, and its clients; a client's analyses are listed by client."""
	return {"Application": ViewRead(APPLICATION, [APPLICATION_BINDING], ANALYSIS, via="Target/Application.resultsFromEngagement"),
		"ApplicationClients": ViewRead(APPLICATION, [APPLICATION_BINDING], CLIENT, via="Target/Application.concernsClient"),
		"ClientAnalyses": ViewRead(CLIENT, [ANALYSES_BINDING], ANALYSIS, via="Target/Party.isClientIn"),
		"Analysis": ViewRead(ANALYSIS, [ANALYSIS_BINDING]), **changed}


def engine(target: str = COMPOSED, **changed: ViewRead) -> HexaViewOperator:
	targetOntology = loadOntology([Source("target.onto", target)], [SOURCE])
	referential = loadReferential([targetOntology], [Source("keys.ref", """@referential Keys
@use Target as T
T/Party key=Id
T/Engagement key=Id
T/Application key=Id
""")])
	mapping = loadMapping(SOURCE, targetOntology, Source("analyses.map", """@mapping Source -> Target referential=Keys
Analysis -> Engagement
  Date <- Date
  Id <- Id
  hasClient <- Clients

Application -> Application
  Id <- Id
  concernsClient <- Clients
  resultsFromEngagement <- Analysis

Client -> Party
  Id <- Id
  Name <- Name
"""), referentials=[referential])
	access = SimpleNamespace(describe=lambda step, value: {}, rootHandle=lambda key, value, kind: kind.rsplit("/", 1)[-1] + "_" + value,
		fetch=lambda step, value: ViewDocument(DOCUMENTS[DOCUMENT[step], value], f"{DOCUMENT[step]}:{value}"))
	return HexaViewOperator(HexaMappingOperator(SOURCE, targetOntology, referential), mapping, reads(**changed), access)


def report(view: str, seed: dict, target: str = COMPOSED) -> dict:
	return json.loads(json.dumps(asyncio.run(engine(target).report(view, seed))))


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def test_a_view_reaches_the_whole_its_records_are_part_of():
	# The names are in the analysis the application is part of: the view reads it without following the link, and
	# not the client's other analyses, which only an ordinary link it does not follow leads to.
	result = report("ApplicationClients", {"applicationId": "app1"})
	assert result["gaps"] == []
	assert [(fact["field"], fact["value"]) for fact in result["facts"]] == [("Party.Name", "Ana")]
	assert [(call["step"], call["input"]) for call in result["calls"]] == [
		("Application", {"applicationId": "app1"}), ("Analysis", {"analysisId": "a1"})]
	plan = asyncio.run(engine().plan("ApplicationClients", {"applicationId": "app1"}))
	assert [(step["step"], step["requires"]) for step in plan["steps"]] == [("Application", []), ("Analysis", ["Application"])]


@pytest.mark.parametrize("qualifier", ["", ": Target/Engagement"])
def test_the_provided_keys_target_type_disambiguates_a_read_link(qualifier):
	target = COMPOSED.replace("Engagement -resultsIn", "Checklist\nApplication -resultsFromEngagement-> Checklist\nEngagement -resultsIn", 1)
	read = ViewRead(APPLICATION, [APPLICATION_BINDING], ANALYSIS, via="Target/Application.resultsFromEngagement" + qualifier)
	operator = engine(target, Application=read)
	plan = asyncio.run(operator.plan("ApplicationClients", {"applicationId": "app1"}))
	assert [(step["step"], step["requires"]) for step in plan["steps"]] == [("Application", []), ("Analysis", ["Application"])]
	assert not plan["gaps"]


def test_without_a_composition_a_view_reaches_no_record_it_does_not_follow():
	result = report("ApplicationClients", {"applicationId": "app1"}, TARGET % "")
	assert result["facts"] == [] and "Analysis" not in [call["step"] for call in result["calls"]]
	assert [gap["field"] for gap in result["gaps"]] == ["Party.Name"]


def test_a_view_follows_an_ordinary_link_its_definition_follows():
	# Every analysis of the client, each with its date.
	result = report("ClientHistory", {"clientId": "c1"})
	assert result["gaps"] == []
	assert sorted((fact["subject"], fact["value"]) for fact in result["facts"]) == [
		("Engagement_a1", "2026-09-21"), ("Engagement_a2", "2026-09-29")]


def test_a_view_follows_a_link_through_its_context():
	# In by one selected role of the association, out by the other: the view follows the link it carries.
	target = COMPOSED.replace("Engagement -hasClient/isClientIn-> Party\n",
		"Participation(Engagement, Client: Party)\nEngagement -hasClient/isClientIn-> Party {context=Participation, subjectRole=Engagement, objectRole=Client}\n")
	through = target.replace("engagements: Engagement = client -> isClientIn\n", "engagements: Engagement = client -> isClientIn through participations\n")
	assert engine(through).steps["ClientHistory"]["Analysis"]["requires"] == ["ClientAnalyses"]
	# In by one role only: the participations, not the engagements they lead to.
	roles = target.replace("engagements: Engagement = client -> isClientIn\n  engagements.Date\n",
		"participations: Participation = client <- Client\n  participations.Engagement\n")
	assert "Analysis" not in engine(roles).steps["ClientHistory"]


def test_two_links_a_view_takes_one_key_along_are_ambiguous():
	history = "@view ApplicationHistory(applicationId: S/Application.Id)\n  application: Application\n" \
		"  clients: Party = application -> concernsClient\n  analyses: Engagement = clients -> isClientIn\n  analyses.Date\n"
	with pytest.raises(ValueError, match="ApplicationHistory: ambiguous providers of Source/Analysis.Id: Application, ClientAnalyses"):
		engine(COMPOSED + history)


def test_a_read_without_a_link_provides_its_key_to_every_view():
	with pytest.raises(ValueError, match="ApplicationClients: ambiguous providers of Source/Analysis.Id: Application, ClientAnalyses"):
		engine(ClientAnalyses=ViewRead(CLIENT, [ANALYSES_BINDING], ANALYSIS))


@pytest.mark.parametrize(("via", "provides", "message"), [
	("Target/Application.missing", ANALYSIS, "expected one directed relation"),
	("Target/Application.Id", ANALYSIS, "a link is a binary relation"),
	("Target/Application.concernsClient", ANALYSIS, "does not lead from Source/Application to Source/Analysis"),
	("Target/Application.resultsFromEngagement", None, "a link discovers a provided key"),
])
def test_a_read_names_a_link_from_its_input_to_the_key_it_provides(via, provides, message):
	with pytest.raises(ValueError, match=f"Application: via {via}: .*{message}"):
		engine(Application=ViewRead(APPLICATION, [APPLICATION_BINDING], provides, via=via))

# EOF
