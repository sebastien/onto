"""Module: contextual facets in rooted views — a member of `F of E {ctx=C}` is read within the nearest population of
type `C` bound before its subject (spec-01 Rooted views, spec-02 Contexts)."""

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
from onto.text import FormatError  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


# A salary is counted in a household's base scenario and excluded from its early-retirement scenario (spec-01).
SOURCE = loadOntology([Source("source.onto", """@ontology Source
Household
  Id Text {key}
Scenario
  Id Text {key}
  Household Household
  Name Text
Income
  Id Text {key}
  Household Household
  Amount Number
Treatment
  Id Text {key}
  Scenario Scenario
  Income Income
  Included Boolean
""")])
TARGET = """@ontology Target
@use Source as S
Household
  Id Text {key}
Scenario
  Id Text {key}
  Name Text
Income
  Id Text {key}
  Amount Number
IncomeTreatment of Income {ctx=Scenario}
  IsIncluded Boolean
Household -plans/isPlanOf-> Scenario
Household -earns/isEarnedBy-> Income
Scenario -considers/isConsideredIn-> Income
@view Scenarios(householdId: S/Household.Id)
  household: Household
  scenarios: Scenario = household -> plans
  incomes: Income = scenarios -> considers
  counted: Income = scenarios -> considers where IncomeTreatment.IsIncluded=true
  scenarios.Name
  incomes.IncomeTreatment.IsIncluded
  counted.Amount
"""
BINDING = loadBinding(SOURCE, Source("household.bind", """@binding Source format=json
Household <- $ {id=id}
  Id <- id
Scenario <- scenarios[*] {id=id}
  Id <- id
  Household <- ^
  Name <- name
Income <- incomes[*] {id=id}
  Id <- id
  Household <- ^
  Amount <- amount
Treatment <- treatments[*] {id=id}
  Id <- id
  Scenario <- ref(Scenario, scenario)
  Income <- ref(Income, income)
  Included <- included
"""))
MAPPING = """@mapping Source -> Target referential=Keys
Household -> Household
  Id <- Id

Scenario -> Scenario
  Id <- Id
  Name <- Name
  isPlanOf <- Household

Income -> Income
  Id <- Id
  Amount <- Amount
  isEarnedBy <- Household

Treatment -> Income {into=Income, ctx=Scenario}
  IncomeTreatment.IsIncluded <- Included
  isConsideredIn <- Scenario
"""
DOCUMENT = {"id": "h1", "scenarios": [{"id": "s1", "name": "Base"}, {"id": "s2", "name": "EarlyRetirement"}],
	"incomes": [{"id": "i1", "amount": 100000}],
	"treatments": [{"id": "t1", "scenario": "s1", "income": "i1", "included": True}, {"id": "t2", "scenario": "s2", "income": "i1", "included": False}]}
SEED = {"householdId": "h1"}


def engine(view: str = TARGET) -> HexaViewOperator:
	target = loadOntology([Source("target.onto", view)], [SOURCE])
	referential = loadReferential([target], [Source("keys.ref", "@referential Keys\n@use Target as T\nT/Household key=Id\nT/Scenario key=Id\nT/Income key=Id\n")])
	mapping = loadMapping(SOURCE, target, Source("household.map", MAPPING), referentials=[referential])
	access = SimpleNamespace(describe=lambda step, value: {}, rootHandle=lambda key, value, kind: "Household_" + value,
		fetch=lambda step, value: ViewDocument(DOCUMENT, "household:h1"))
	return HexaViewOperator(HexaMappingOperator(SOURCE, target, referential), mapping,
		{"Household": ViewRead(ViewInput("householdId", "Source/Household", "Id"), [BINDING])}, access)


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def test_a_contextual_member_is_read_within_its_context_population():
	report = json.loads(json.dumps(asyncio.run(engine().report("Scenarios", SEED, ["incomes.IncomeTreatment.IsIncluded"]))))
	assert report["gaps"] == []
	# The salary under each scenario: the value stated within that scenario, never the other's.
	facts = sorted((fact["path"][0]["to"], fact["ctx"], fact["value"]) for fact in report["facts"])
	assert facts == [("Scenario_s1", "Scenario_s1", True), ("Scenario_s2", "Scenario_s2", False)]


def test_a_filter_on_a_contextual_member_tests_it_within_its_context():
	report = json.loads(json.dumps(asyncio.run(engine().report("Scenarios", SEED, ["counted.Amount"]))))
	# The salary counts in the base scenario only.
	assert [(fact["path"][0]["to"], fact["value"]) for fact in report["facts"]] == [("Scenario_s1", "100000")]
	assert {item["subject"]: item["statuses"] for item in report["coverage"] if item.get("stoppedAt") == "Income.IncomeTreatment.IsIncluded"} == {
		"Income_i1": ["notMatched"]}


def test_retrieval_keeps_each_claim_within_its_context():
	obs = asyncio.run(engine().retrieve("Scenarios", SEED, ["incomes.IncomeTreatment.IsIncluded"]))
	assert sorted((claim["ctx"], claim["v"]) for claim in obs.claims if "ctx" in claim) == [("Scenario_s1", True), ("Scenario_s2", False)]
	assert {"Scenario_s1", "Scenario_s2"} <= set(obs.instances)


def test_a_contextual_member_needs_a_population_of_its_context_before_its_subject():
	# Reached from the household, a salary is in no scenario: which one's treatment would it be?
	view = TARGET.replace("  counted.Amount\n", "  earned.IncomeTreatment.IsIncluded\n").replace(
		"  counted: Income", "  earned: Income = household -> earns\n  counted: Income")
	with pytest.raises(FormatError, match="Income.IncomeTreatment.IsIncluded holds within a Scenario: expected a population of that type before it"):
		loadOntology([Source("target.onto", view)], [SOURCE])

# EOF
