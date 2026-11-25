"""Set-valued maps in runs: several counterparts for a value, none for an excluded one (spec-01 Maps, spec-04)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, mappingReverse, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from tests.helpers import schemaValidator  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SOURCE = loadOntology([Source("s.onto", """@ontology S
Scope = Mortgage|Insurance|Both|Other
Review
  Scope Scope
  * Scopes Scope
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Area = Lending|Insurance
Review
  * Areas Area
  * AllAreas Area
  Area Area
""")])
MAPPING = """@mapping S -> T
@map Areas Scope -> Area
  Both narrower Insurance
  Both narrower Lending
  Insurance exact Insurance
  Mortgage exact Lending
  - Other -- no line of business

Review -> Review
  AllAreas <- Areas(Scopes)
  Areas <- Areas(Scope)
"""


def mapped(fields: str, text: str = MAPPING):
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-25\n@src f=fixture\n@src f\nReview_1:Review\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-25"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return {claim["p"]: claim["v"] for claim in observationsToJson(log)["claims"] if "p" in claim}, report


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(("fields", "expected"), [
	("  Scope Both\n", {"Areas": {"set": ["Insurance", "Lending"]}}),
	("  Scope Mortgage\n", {"Areas": {"set": ["Lending"]}}),
	("  Scope Other\n", {"Areas": {"set": []}}),
	("  Scopes [Both, Other]\n", {"AllAreas": {"set": ["Insurance", "Lending"]}}),
	("  Scopes [Mortgage, Other]\n", {"AllAreas": {"set": ["Lending"]}}),
])
def test_a_set_valued_map_gives_every_counterpart(fields, expected):
	claims, report = mapped(fields)
	assert not report.gaps
	assert claims == expected


def test_an_unlisted_value_is_still_a_gap():
	claims, report = mapped("  Scopes [Mortgage]\n", MAPPING.replace("  Mortgage exact Lending\n", ""))
	assert [gap.target for gap in report.gaps] == ["T/Review.AllAreas"]


def test_a_set_valued_map_needs_a_multi_valued_target():
	with pytest.raises(FormatError, match="Area"):
		loadMapping(SOURCE, TARGET, Source("bad.map", MAPPING + "  Area <- Areas(Scope)\n"))


def test_set_valued_maps_print_round_trip_and_are_lossy_under_reversal():
	mapping = loadMapping(SOURCE, TARGET, Source("m", MAPPING))
	text = printMapping(mapping)
	assert "  - Other" in text and printMapping(loadMapping(SOURCE, TARGET, Source("m", text))) == text
	data = mappingToJson(mapping)
	schemaValidator("mapping").validate(data)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data
	_, lossy = mappingReverse(mapping, SOURCE, TARGET)
	assert sorted(item.line for item in lossy) == ["AllAreas", "Areas"]

# EOF
