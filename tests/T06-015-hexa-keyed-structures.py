"""Keyed structures through bindings and mappings: `Phones[Mobile].Number <- ...` (spec-01, spec-04)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadBinding, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, HexaMappingOperator  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SOURCE = loadOntology([Source("s.onto", """@ontology S
Client
  Id Integer {key}
  Mobile Text
  Home Text
  Email Text
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Phone/Use = Mobile|Home|Work
Phone =
  1 Use Phone/Use {key}
  1 Number Text
Person
  * Phones Phone
  Email Text
""")])
BINDING = """@binding S
Client <- clients[*] {id=id}
  Home <- home
  Mobile <- mobile
"""
MAPPING = """@mapping S -> T

Client -> Person
  Phones[Home].Number <- Home
  Phones[Mobile].Number <- Mobile
"""


def mapped(fields: str, text: str = MAPPING):
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-18\n@scope s\n@src f=fixture\n@src f\nClient_9:Client\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-18"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


# -----------------------------------------------------------------------------
#
# MAPPINGS
#
# -----------------------------------------------------------------------------


def test_each_line_claims_its_element():
	log, report = mapped("  Mobile 021\n  Home 09\n")
	assert not report.gaps
	assert sorted((claim["p"], claim["v"]) for claim in log["claims"] if "p" in claim) == [("Phones[Home].Number", "09"), ("Phones[Mobile].Number", "021")]
	reconciled = reconcileObservations(TARGET, loadObservations(TARGET, Source("out.obs", "@obs T\n" + "\n".join(
		f"{claim['s']}.{claim['p']} {claim['v']}" for claim in log["claims"] if "p" in claim) + "\n@type Person_s_2FClient_2F9 Person\n")))
	assert len([claim for claim in reconciled.claims if "p" in claim]) == 2


def test_an_absent_value_makes_no_element():
	log, report = mapped("  Mobile 021\n")
	assert not report.gaps
	assert [claim["p"] for claim in log["claims"] if "p" in claim] == ["Phones[Mobile].Number"]


def test_keyed_targets_print_and_round_trip():
	mapping = loadMapping(SOURCE, TARGET, Source("m", MAPPING))
	assert "  Phones[Mobile].Number <- Mobile" in printMapping(mapping)
	data = mappingToJson(mapping)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data


@pytest.mark.parametrize("line", ["Phones.Number <- Mobile", "Phones[Fax].Number <- Mobile", "Phones[Home].Use <- Mobile", "Email[Home] <- Mobile"])
def test_misnamed_elements_are_rejected(line: str):
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("m", f"@mapping S -> T\nClient -> Person\n  {line}\n"))


# -----------------------------------------------------------------------------
#
# BINDINGS
#
# -----------------------------------------------------------------------------


def test_a_binding_reads_document_fields_into_elements():
	binding = loadBinding(TARGET, Source("t.bind", "@binding T\nPerson <- people[*] {id=id}\n  Phones[Home].Number <- home\n  Phones[Mobile].Number <- mobile\n"))
	ops = HexaBindingOperator(TARGET)
	program = ops.compile(binding)
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-18"}, program.stages.BindingRead, [{"src": "doc", "document": {"people": [{"id": "1", "home": "09", "mobile": None}]}}]))
	log, report = ops.result(program, result)
	assert not report.gaps
	assert [(claim["p"], claim["v"]) for claim in observationsToJson(log)["claims"] if "p" in claim] == [("Phones[Home].Number", "09")]


def test_keyed_targets_cover_their_field_and_the_implied_key():
	from onto.mapping.coverage import mappingCoverage
	report = mappingCoverage(SOURCE, TARGET, loadMapping(SOURCE, TARGET, Source("m", MAPPING)))
	assert report.unassigned == ["Person.Email"]


# -----------------------------------------------------------------------------
#
# READING ELEMENTS
#
# -----------------------------------------------------------------------------


PROJECTION = """@mapping T -> S

Person -> Client
  Home <- Phones[Home].Number
  Mobile <- Phones[Mobile].Number
"""


def test_a_mapping_reads_an_element_by_its_key():
	mapping = loadMapping(TARGET, SOURCE, Source("p.map", PROJECTION))
	assert "  Mobile <- Phones[Mobile].Number" in printMapping(mapping)
	ops = HexaMappingOperator(TARGET, SOURCE, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(TARGET, Source("o.obs", "@obs T at=2026-11-18\n@scope t\n@src f=fixture\n@src f\np1:Person\n  Phones[Mobile].Number 021\n  Phones[Home].Number 09\n"))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-18"}, program.stages.MappingRead, observationsToJson(reconcileObservations(TARGET, obs))))
	log, report = ops.result(program, result)
	assert not report.gaps
	assert sorted((claim["p"], claim["v"]) for claim in observationsToJson(log)["claims"] if "p" in claim) == [("Home", "09"), ("Mobile", "021")]


@pytest.mark.parametrize("expr", ["Phones.Number", "Phones[Fax].Number", "Email[Home]"])
def test_reading_a_misnamed_element_is_rejected(expr: str):
	with pytest.raises(FormatError):
		loadMapping(TARGET, SOURCE, Source("p", PROJECTION.replace("Phones[Mobile].Number", expr)))


def test_reading_elements_reverses_to_keyed_targets():
	from onto import mappingReverse
	reversed_, lossy = mappingReverse(loadMapping(TARGET, SOURCE, Source("p", PROJECTION)), TARGET, SOURCE)
	assert not lossy
	assert sorted(line.target for line in reversed_.scopes[0].lines) == ["Phones[Home].Number", "Phones[Mobile].Number"]


def test_a_binding_writes_elements_back_to_their_fields():
	binding = loadBinding(TARGET, Source("t.bind", "@binding T\nPerson <- people[*] {id=id}\n  Phones[Home].Number <- home\n  Phones[Mobile].Number <- mobile\n"))
	state = loadObservations(TARGET, Source("s.obs", "@obs T\n@src f=feed:x\n@src f\nPerson_1:Person\n  Phones[Home].Number 09\n"))
	ops = HexaBindingOperator(TARGET)
	program = ops.compileWrite(binding)
	env = {"ClockRead": lambda context: "2026-11-18", "DocumentPreviousRead": lambda request, context: None}
	documents, report = ops.written(asyncio.run(run(env, program.stages.BindingWrite, {"src": "feed:x", "state": observationsToJson(reconcileObservations(TARGET, state))})))
	assert not report.lossy and documents[0]["document"] == {"people": [{"home": "09"}]}
