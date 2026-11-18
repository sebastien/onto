"""Exclusive lines: one target assigned by lines with exclusive `when` conditions and a default (spec-04 Instances)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingReverse, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.compiler import CompileError  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.referential import loadReferential  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SOURCE = loadOntology([Source("s.onto", """@ontology S
Status = Open|Closed|Migrated
Review
  Status Status
  Reason Text
  Note Text
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Review
  StoppedReason Text {key}
""")])
MAPPING = """@mapping S -> T

Review -> Review
  StoppedReason <- Reason
  StoppedReason <- "Other" {when=Status:Migrated}
  StoppedReason <- Note {when=Status:Closed}
"""


def mapped(fields: str, text: str = MAPPING):
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-18\n@src f=fixture\n@src f\nReview_1:Review\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-18"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return [claim["v"] for claim in observationsToJson(log)["claims"] if claim.get("p") == "StoppedReason"], report


# -----------------------------------------------------------------------------
#
# EXECUTION
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(("fields", "expected"), [
	("  Status Migrated\n  Reason Lost\n", ["Other"]),
	("  Status Closed\n  Reason Lost\n  Note Moved\n", ["Moved"]),
	("  Status Closed\n  Reason Lost\n", []),
	("  Status Open\n  Reason Lost\n", ["Lost"]),
	("  Reason Lost\n", ["Lost"]),
])
def test_at_most_one_exclusive_line_applies(fields: str, expected: list):
	printed = printMapping(loadMapping(SOURCE, TARGET, Source("m.map", MAPPING)))
	for text in (MAPPING, printed):
		values, report = mapped(fields, text)
		assert values == expected and not report.gaps


def test_a_conflicting_condition_is_a_conflicting_input_for_every_line():
	"""No line can tell whether it applies, the default included: none chooses a value."""
	values, report = mapped("  Status Open\n  Reason Lost\n@src g=other\n@src g\nReview_1.Status Migrated\n")
	assert values == []
	assert {(gap.target, gap.reason) for gap in report.gaps} == {("T/Review.StoppedReason", "Mapping.InputConflicting")}


def test_exclusive_identity_key_is_rejected_before_execution():
	referential = loadReferential([SOURCE, TARGET], [Source("identity.ref", "@referential Identity\n@use T as Target\nTarget/Review key=StoppedReason from=S\n")])
	text = MAPPING.replace("S -> T", "S -> T referential=Identity")
	ops = HexaMappingOperator(SOURCE, TARGET, referential=referential, mode="lenient")
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text), referentials=[referential])
	for item in (mapping, loadMapping(SOURCE, TARGET, Source("printed.map", printMapping(mapping)), referentials=[referential])):
		with pytest.raises(CompileError, match="Mapping.PolicyUnsupported: Exclusive assignments to referential key 'StoppedReason'"):
			ops.compile(item)


# -----------------------------------------------------------------------------
#
# DECLARATIONS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
	"  StoppedReason <- Reason\n  StoppedReason <- Note\n",
	"  StoppedReason <- Reason {when=Status:Open}\n  StoppedReason <- Note {when=Status:Open}\n",
	"  StoppedReason <- Reason {when=Status:Open}\n  StoppedReason <- Note {when=Note:x}\n",
])
def test_overlapping_assignments_are_rejected(body: str):
	with pytest.raises(FormatError, match="exclusive conditions"):
		loadMapping(SOURCE, TARGET, Source("m", "@mapping S -> T\nReview -> Review\n" + body))


def test_exclusive_lines_print_default_first_then_by_condition_value():
	printed = printMapping(loadMapping(SOURCE, TARGET, Source("m", MAPPING)))
	assert printed.splitlines()[3:] == [
		"  StoppedReason <- Reason", "  StoppedReason <- Note {when=Status:Closed}", "  StoppedReason <- \"Other\" {when=Status:Migrated}",
	]


def test_the_default_is_lossy_under_reversal():
	reversed_, lossy = mappingReverse(loadMapping(SOURCE, TARGET, Source("m", MAPPING)), SOURCE, TARGET)
	assert sorted(item.reason for item in lossy) == [
		"condition 'Status' is not read back by a direct line", "literals, metadata and '??' are not reversible",
		"the default of exclusive lines has no reversible condition",
	]
	assert reversed_.scopes[0].lines == []
