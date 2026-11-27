"""Lookups: a reference a mapping reads between rows that name the same records without naming each other (spec-04 Lookups)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadBinding, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa import HexaViewOperator, ViewRead  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.mapping.coverage import mappingCoverage  # noqa: E402
from onto.mapping.operations import parseMappings  # noqa: E402
from onto.mapping.reversal import mappingReverse  # noqa: E402
from onto.ontology import ViewInput  # noqa: E402
from tests.helpers import schemaValidator  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

# A needs analysis lists each client's personal details and, apart, each client's addresses: both name the client and
# the analysis, neither names the other.
SOURCE = loadOntology([Source("s.onto", """@ontology S
Client
  1 Id Integer {key}
Advice
  1 Id Integer {key}
Individual
  Client Client
  Advice Advice
  Situation Text
Address
  Client Client
  Application Advice
  Street Text
  Years Integer
  Kind Text
Note
  Individual Individual
""")])
TARGET_TEXT = """@ontology T
Person
Residence
  Resident Person
  Situation Text
  Street Text
  Years Integer
Remark
  Street Text
"""
TARGET = loadOntology([Source("t.onto", TARGET_TEXT)])
LOOKUP = """@lookup Individual.Home -> Address -- The client's address in the same analysis
  Application <- Advice
  Client <- Client
"""
MAPPING = f"""@mapping S -> T

{LOOKUP}
Client -> Person

Individual -> Residence
  Resident <- Client
  Situation <- Situation
  Street <- Home.Street
  Years <- Home.Years {{when=Home.Kind:Current}}
"""
STATE = """@obs S at=2026-11-27
@src p=fixture:personal
@src p
Client_9:Client
  Id 9
Advice_2:Advice
  Id 2
Advice_4:Advice
  Id 4
Individual_15:Individual
  Client Client_9
  Advice Advice_2
  Situation Own
@src a=fixture:addresses
@src a
Address_7:Address
  Client Client_9
  Application Advice_4
  Street Elsewhere
  Years 1
  Kind Current
"""
HOME = """Address_6:Address
  Client Client_9
  Application Advice_2
  Street 123 Park Lane
  Years 18
  Kind Current
"""


def load(text=MAPPING):
	return loadMapping(SOURCE, TARGET, Source("m.map", text))


def mapped(extra="", text=MAPPING, *, state=STATE):
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(load(text))
	obs = loadObservations(SOURCE, Source("o.obs", state + extra))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-27"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	log = observationsToJson(log)
	residence, = [h for h, item in log["instances"].items() if item["type"] == "T/Residence"]
	return {c["p"]: c for c in log["claims"] if c.get("s") == residence and "p" in c}, log, report


# -----------------------------------------------------------------------------
#
# EXECUTION
#
# -----------------------------------------------------------------------------


def test_the_one_row_of_the_same_client_and_analysis_is_read_through_the_lookup():
	claims, log, report = mapped(HOME)
	assert not report.gaps
	assert {p: c["v"] for p, c in claims.items()} == {"Resident": {"ref": "Person_S_2FClient_2F9"}, "Situation": "Own", "Street": "123 Park Lane", "Years": "18"}
	# Each value keeps the provenance of the row it was read from.
	sources = {alias: token for alias, token in log["sources"].items()}
	assert (sources[claims["Street"]["src"]], sources[claims["Situation"]["src"]]) == ("fixture:addresses", "fixture:personal")


def test_without_such_a_row_the_lookup_reads_nothing():
	claims, _, report = mapped()
	assert not report.gaps
	assert set(claims) == {"Resident", "Situation"}


@pytest.mark.parametrize(("owner", "candidate"), [
	("Client_9", "?"),
	("Client_9", "null"),
	("?", "Client_9"),
	("?", "null"),
	("null", "null"),
])
def test_a_lookup_compares_only_known_values(owner, candidate):
	state = STATE.replace("Individual_15:Individual\n  Client Client_9", f"Individual_15:Individual\n  Client {owner}")
	claims, _, report = mapped(HOME.replace("Client Client_9", f"Client {candidate}"),
		MAPPING.replace("  Resident <- Client\n", ""), state=state)
	assert not report.gaps
	assert set(claims) == {"Situation"}


def test_literal_null_text_is_a_known_value_not_confirmed_absence():
	text = MAPPING.replace("Client <- Client\n", "Kind <- Situation\n", 1)
	state = STATE.replace("Situation Own", 'Situation "null"')
	absent = HOME.replace("Kind Current", "Kind null").replace("Street 123 Park Lane", "Street No match")
	literal = HOME.replace("Kind Current", 'Kind "null"').replace("Address_6", "Address_8")
	claims, _, report = mapped(absent + literal, text, state=state)
	assert not report.gaps
	assert claims["Street"]["v"] == "123 Park Lane"


def test_several_rows_are_ambiguous_never_the_first():
	claims, _, report = mapped(HOME + HOME.replace("Address_6", "Address_8").replace("123 Park Lane", "1 Other Road"))
	assert set(claims) == {"Resident", "Situation"}
	# A condition reading through an ambiguous lookup holds for no row: its line demands nothing.
	assert [(gap.target, gap.reason) for gap in report.gaps] == [("T/Residence.Street", "Mapping.ReferenceAmbiguous")]


def test_a_compared_value_in_conflict_is_ambiguous():
	claims, _, report = mapped(HOME + "@src o=fixture:other\n@src o\nIndividual_15.Client Client_10:Client\n")
	assert "Street" not in claims
	assert ("T/Residence.Street", "Mapping.ReferenceAmbiguous") in {(gap.target, gap.reason) for gap in report.gaps}


def test_conditions_read_through_the_lookup():
	claims, _, report = mapped(HOME.replace("Kind Current", "Kind Previous"))
	assert not report.gaps
	assert (claims["Street"]["v"], "Years" in claims) == ("123 Park Lane", False)


def test_a_contextual_value_keeps_its_context_when_read_through_a_lookup():
	source = loadOntology([Source("s.onto", """@ontology S
Scenario
Individual
  Key Text
Address
  Key Text
Treatment of Address {ctx=Scenario}
  Included Boolean
""")])
	target = loadOntology([Source("t.onto", """@ontology T
Scenario
Residence
Treatment of Residence {ctx=Scenario}
  Included Boolean
""")])
	mapping = loadMapping(source, target, Source("m.map", """@mapping S -> T
@lookup Individual.Home -> Address
  Key <- Key
Scenario -> Scenario
Individual -> Residence
  Treatment.Included <- Home.Treatment.Included
"""))
	obs = loadObservations(source, Source("o.obs", """@obs S at=2026-11-27
@src f=fixture
@src f
Scenario_1:Scenario
Scenario_2:Scenario
Individual_1:Individual
  Key same
Address_1:Address
  Key same
  Treatment.Included true {ctx=Scenario_1}
  Treatment.Included false {ctx=Scenario_2}
"""))
	ops = HexaMappingOperator(source, target, mode="lenient")
	program = ops.compile(mapping)
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-27"}, program.stages.MappingRead, observationsToJson(reconcileObservations(source, obs))))
	log, report = ops.result(program, result)
	assert not report.gaps
	assert {c["ctx"]: c["v"] for c in log.claims if c.get("p") == "Treatment.Included"} == {
		report.correspondence["Scenario_1"]: True,
		report.correspondence["Scenario_2"]: False,
	}


# -----------------------------------------------------------------------------
#
# DECLARATIONS
#
# -----------------------------------------------------------------------------


def test_text_and_json_round_trip():
	mapping = load()
	text = printMapping(mapping)
	assert "\n@lookup Individual.Home -> Address " in text and "\n  Application <- Advice\n  Client <- Client\n" in text
	assert printMapping(load(text)) == text
	data = mappingToJson(mapping)
	assert data["lookups"] == [{"owner": "S/Individual", "name": "Home", "type": "S/Address", "doc": "The client's address in the same analysis",
		"lines": [{"attr": "Application", "from": "Advice"}, {"attr": "Client", "from": "Client"}]}]
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data
	schemaValidator("mapping").validate(data)


@pytest.mark.parametrize("change", [
	("@lookup Individual.Home", "@lookup Individual.Situation"),  # the owner's own attribute
	("  Client <- Client\n", "  Client <- Situation\n"),  # values of different types
	("  Client <- Client\n", "  Owner <- Client\n"),  # no such attribute
	("Application <- Advice\n  Client <- Client\n", ""),  # no line
	("-> Address", "-> Nowhere"),
	("Street <- Home.Street", "Street <- Home.Nowhere"),
])
def test_invalid_lookups_are_rejected(change):
	with pytest.raises(FormatError):
		load(MAPPING.replace(*change))


def test_a_lookup_is_read_from_the_scope_instance_only():
	with pytest.raises(FormatError):
		load(MAPPING + "\nNote -> Remark\n  Street <- Individual.Home.Street\n")


def test_a_lookup_is_declared_once_across_files():
	with pytest.raises(FormatError):
		parseMappings([Source("a.map", MAPPING), Source("b.map", "@mapping S -> T\n\n" + LOOKUP)])


def test_the_nearest_lookup_declaration_wins_before_and_after_formatting():
	source = loadOntology([Source("s.onto", """@ontology S
ZBase
  Key Text
Child < ZBase
BroadAddress
  Key Text
  Street Text
SpecificAddress
  Key Text
  Street Text
""")])
	text = """@mapping S -> T
@lookup ZBase.Home -> BroadAddress
  Key <- Key
@lookup Child.Home -> SpecificAddress
  Key <- Key
Child -> Residence
  Street <- Home.Street
"""
	def loadChild(body):
		return loadMapping(source, TARGET, Source("m.map", body))

	original = loadChild(text)
	for mapping in (original, loadChild(printMapping(original))):
		rows = {row.source: row.status for row in mappingCoverage(source, TARGET, mapping).rows}
		assert rows["SpecificAddress.Street"] == "direct"
		assert rows["BroadAddress.Street"] == "unmapped"


def test_coverage_counts_compared_attributes_as_conditions_and_the_paths_read_through():
	rows = {row.source: row.status for row in mappingCoverage(SOURCE, TARGET, load()).rows}
	assert (rows["Address.Street"], rows["Address.Years"]) == ("direct", "direct")
	assert (rows["Address.Client"], rows["Address.Application"], rows["Address.Kind"], rows["Individual.Advice"]) == ("condition",) * 4
	assert rows["Individual.Client"] == "direct"


def test_lines_read_through_a_lookup_write_nothing_back():
	_, lossy = mappingReverse(load(), SOURCE, TARGET)
	assert {item.line for item in lossy if item.target == "T/Residence"} == {"Street", "Years"}


# -----------------------------------------------------------------------------
#
# ROOTED VIEWS
#
# -----------------------------------------------------------------------------


VIEW = loadOntology([Source("t.onto", TARGET_TEXT + """@use S as S
@view Homes(clientId: S/Client.Id)
  person: Person
  residences: Residence = person <- Resident
  residences.Street
""")], [SOURCE])
PERSONAL = """@binding S format=json
Individual <- individuals[*] {id=id}
  Client <- ref(Client, clientId)
  Advice <- ref(Advice, adviceId)
  Situation <- situation
"""
ADDRESSES = """Address <- addresses[*] {id=id}
  Client <- ref(Client, clientId)
  Application <- ref(Advice, adviceId)
  Street <- street
  Years <- years
  Kind <- kind
"""


def plan(binding):
	mapping = loadMapping(SOURCE, VIEW, Source("m.map", MAPPING))
	reads = {"Personal": ViewRead(ViewInput("clientId", "S/Client", "Id"), [loadBinding(SOURCE, Source("p.bind", binding))])}
	access = SimpleNamespace(rootHandle=lambda param, value, target: f"Person_S_2FClient_2F{value}", fetch=lambda step, value: None)
	operator = HexaViewOperator(HexaMappingOperator(SOURCE, VIEW, mode="lenient"), mapping, reads, access)
	return asyncio.run(operator.plan("Homes", {"clientId": 9}, ["residences.Street"]))


def test_a_view_reads_the_rows_it_looks_up():
	assert plan(PERSONAL + ADDRESSES)["fields"] == {"residences.Street": "Personal"}
	missing = plan(PERSONAL)
	assert missing["fields"] == {"residences.Street": None}
	assert [gap["reason"] for gap in missing["gaps"]] == ["SelectionRequest.NotSupplied"]

# EOF
