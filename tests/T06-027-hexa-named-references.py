"""Named-reference selection: a line's `{name=N}` translates a reference through the scope named N (spec-04 Instances)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.mapping.reversal import mappingReverse  # noqa: E402
from tests.helpers import schemaValidator  # noqa: E402

SOURCE = loadOntology([Source("s.onto", """@ontology S
Row
  Main Text
  Short Text
  Flag Boolean
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Goal
  Description Text
Review
  Goal Goal
  Note Text
Review -follows/isFollowedBy-> Goal
""")])
# One row states two goals and a review of them: the review names which goal it means.
MAPPING = """@mapping S -> T
Row -> Goal {name=Main, present=trim(Main)}
  Description <- Main
Row -> Goal {name=Short, present=trim(Short)}
  Description <- Short
Row -> Review {present=Flag}
  Goal <- $ {name=Short}
  follows <- $ {name=Main}
"""


def load(text=MAPPING):
	return loadMapping(SOURCE, TARGET, Source("m.map", text))


def mapped(fields, text=MAPPING):
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(load(text))
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-27\n@src f=fixture\n@src f\nRow_1:Row\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-27"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


def goal(log, name):
	return next(h for h, item in log["instances"].items() if item["type"] == "T/Goal" and f"_40{name}" in h)


def test_a_named_reference_is_the_target_of_the_scope_it_names():
	log, report = mapped("  Main General\n  Short Specific\n  Flag true\n")
	assert not report.gaps
	review = next(h for h, item in log["instances"].items() if item["type"] == "T/Review")
	assert {c["p"]: c["v"] for c in log["claims"] if c.get("s") == review and "p" in c}["Goal"] == {"ref": goal(log, "Short")}
	link, = [c for c in log["claims"] if ".follows." in c.get("rel", "")]
	assert set(link["roles"].values()) == {review, goal(log, "Main")}


def test_a_target_its_scope_skips_is_a_gap_never_another_target():
	log, report = mapped("  Main General\n  Flag true\n")
	assert [(gap.target, gap.reason) for gap in report.gaps] == [("T/Review.Goal", "Mapping.ReferenceUnmapped")]
	assert not any(c.get("p") == "Goal" for c in log["claims"])
	assert any(".follows." in c.get("rel", "") for c in log["claims"])


def test_distinct_named_scopes_never_share_a_compiled_handle_template():
	source = loadOntology([Source("s.onto", """@ontology S
A
  Label Text
AB
  Label Text
""")])
	target = loadOntology([Source("t.onto", """@ontology T
BC
  Label Text
C
  Label Text
Review
  Pick BC
""")])
	mapping = loadMapping(source, target, Source("m.map", """@mapping S -> T
A -> BC {name=Pick}
  Label <- Label
AB -> C {name=Pick}
  Label <- Label
A -> Review
  Pick <- $ {name=Pick}
"""))
	obs = loadObservations(source, Source("o.obs", """@obs S at=2026-11-27
@src f=fixture
@src f
A_1:A
  Label first
AB_1:AB
  Label second
"""))
	ops = HexaMappingOperator(source, target, mode="lenient")
	program = ops.compile(mapping)
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-27"}, program.stages.MappingRead, observationsToJson(reconcileObservations(source, obs))))
	log, report = ops.result(program, result)
	assert not report.gaps
	assert {c["s"]: c["v"] for c in log.claims if c.get("p") == "Label"} == {
		"BC_S_2F_40Pick_2FA_2F1": "first",
		"C_S_2F_40Pick_2FAB_2F1": "second",
	}
	assert [c["v"] for c in log.claims if c.get("p") == "Pick"] == [{"ref": "BC_S_2F_40Pick_2FA_2F1"}]
	assert len({plan.name for plan in program.plans}) == len(program.plans)


def test_text_and_json_round_trip():
	mapping = load()
	text = printMapping(mapping)
	assert "  Goal <- $ {name=Short}\n" in text
	assert printMapping(load(text)) == text
	data = mappingToJson(mapping)
	assert {"target": "Goal", "expr": {"path": [{"root": True}]}, "name": "Short"} in data["scopes"][2]["lines"]
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data
	schemaValidator("mapping").validate(data)


@pytest.mark.parametrize("line", [
	"  Goal <- $ {name=Other}",  # no scope of that name
	"  Goal <- $",  # two named goals: ambiguous without a name
	"  Goal <- $ {name=Short, as=Goal}",  # the name already chooses the type
	"  Note <- Main {name=Main}",  # not a reference
])
def test_a_name_chooses_exactly_one_scope_of_a_reference(line):
	with pytest.raises(FormatError):
		load(MAPPING.replace("  Goal <- $ {name=Short}", line))


KEYED = loadOntology([Source("s.onto", """@ontology S
Row
  Id Integer {key}
  Main Text
  Short Text
  Flag Boolean
""")])
VIEW = loadOntology([Source("t.onto", """@ontology T
Goal
  Description Text
Review
  Goal Goal
  Note Text
Review -follows/isFollowedBy-> Goal
@use S as S
@view RowReview(rowId: S/Row.Id)
  review: Review
  goal: Goal = review -> Goal
  goal.Description
""")], [KEYED])


def test_a_view_follows_a_named_reference_to_the_scope_it_names():
	from types import SimpleNamespace
	from onto import loadBinding
	from onto.integrations.hexa import HexaViewOperator, ViewRead
	from onto.ontology import ViewInput
	mapping = loadMapping(KEYED, VIEW, Source("m.map", MAPPING))
	binding = loadBinding(KEYED, Source("r.bind", "@binding S format=json\nRow <- rows[*] {id=id}\n  Id <- id\n  Main <- main\n  Short <- short\n  Flag <- flag\n"))
	reads = {"Rows": ViewRead(ViewInput("rowId", "S/Row", "Id"), [binding])}
	access = SimpleNamespace(rootHandle=lambda param, value, target: f"Review_S_2FRow_2F{value}", fetch=lambda step, value: None)
	operator = HexaViewOperator(HexaMappingOperator(KEYED, VIEW, mode="lenient"), mapping, reads, access)
	plan = asyncio.run(operator.plan("RowReview", {"rowId": 1}, ["goal.Description"]))
	assert plan["fields"] == {"goal.Description": "Rows"}


def test_a_named_reference_writes_nothing_back():
	# A scope without presence, so that only the lines' names make them lossy.
	_, lossy = mappingReverse(load(MAPPING.replace("Row -> Review {present=Flag}", "Row -> Review")), SOURCE, TARGET)
	reasons = {item.line: item.reason for item in lossy if item.target == "T/Review"}
	assert set(reasons) == {"Goal", "follows"}
	assert all("named" in reason for reason in reasons.values()), reasons

# EOF
