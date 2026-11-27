"""Target references: `ref(T, Key)` names a target instance by its referential key (spec-04 Instances)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.mapping.reversal import mappingReverse  # noqa: E402
from onto.referential import loadReferential  # noqa: E402

SOURCE = loadOntology([Source("s.onto", """@ontology S
Answer
  1 Id Integer {key}
  Wanted Boolean
  Topic Text
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Question
  Code Text {key}
  Text Text
Reply
  IsYes Boolean
  Question Question
Assessment of Reply {ctx=Question}
  IsYes Boolean
Reply -answers/isAnsweredBy-> Question
""")])
IDS = loadReferential([TARGET], [Source("t.ref", "@referential TIds\n@use T as X\nX/Question key=Code\n")])
MAPPING = """@mapping S -> T referential=TIds
Answer -> Reply
  IsYes <- Wanted
  Question <- ref(Question, "WantsX")
  answers <- ref(Question, Topic)
"""


def load(text=MAPPING):
	return loadMapping(SOURCE, TARGET, Source("m.map", text), referentials=[IDS])


def mapped(fields, text=MAPPING):
	ops = HexaMappingOperator(SOURCE, TARGET, IDS, mode="lenient")
	program = ops.compile(load(text))
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-27\n@src f=fixture\n@src f\nAnswer_1:Answer\n  Id 1\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-27"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


def test_a_key_names_the_target_instance_its_policy_derives():
	log, report = mapped("  Wanted true\n  Topic WantsY\n")
	assert not report.gaps
	reply = next(h for h, item in log["instances"].items() if item["type"] == "T/Reply")
	fields = {c["p"]: c["v"] for c in log["claims"] if c.get("s") == reply and "p" in c}
	assert fields["Question"] == {"ref": "Question_WantsX"}
	link, = [c for c in log["claims"] if ".answers." in c.get("rel", "")]
	assert reply in link["roles"].values() and "Question_WantsY" in link["roles"].values()
	# The questions are reference data kept apart: implicit here, typed, and no claim is made about them.
	assert log["instances"]["Question_WantsX"] == log["instances"]["Question_WantsY"] == {"type": "T/Question"}
	assert not any(c.get("s", "").startswith("Question_") for c in log["claims"])


def test_an_absent_key_names_nothing():
	log, report = mapped("  Wanted true\n")
	assert not report.gaps
	assert not any(".answers." in c.get("rel", "") for c in log["claims"])


def test_coalesced_target_references_supply_attributes_and_links():
	text = MAPPING.replace('ref(Question, "WantsX")', 'ref(Question, Topic) ?? ref(Question, "WantsX")').replace(
		"answers <- ref(Question, Topic)", 'answers <- ref(Question, Topic) ?? ref(Question, "WantsY")')
	log, report = mapped("", text)
	assert not report.gaps
	assert [c["v"] for c in log["claims"] if c.get("p") == "Question"] == [{"ref": "Question_WantsX"}]
	link, = [c for c in log["claims"] if ".answers." in c.get("rel", "")]
	assert "Question_WantsY" in link["roles"].values()


def test_a_scope_context_can_be_a_target_reference():
	text = MAPPING.replace("Answer -> Reply", 'Answer -> Reply {ctx=ref(Question, "WantsX")}').replace(
		"  IsYes <- Wanted", "  Assessment.IsYes <- Wanted")
	log, report = mapped("  Wanted true\n", text)
	assert not report.gaps
	claim, = [c for c in log["claims"] if c.get("p") == "Assessment.IsYes"]
	assert (claim["ctx"], claim["v"]) == ("Question_WantsX", True)


def test_an_update_selector_must_still_name_a_source_reference():
	text = MAPPING + '\nAnswer -> Question {into=ref(Question, "WantsX")}\n  Text <- Topic\n'
	with pytest.raises(FormatError, match="into requires a source instance reference"):
		load(text)


def test_text_and_json_round_trip():
	mapping = load()
	text = printMapping(mapping)
	assert '  Question <- ref(Question, "WantsX")\n' in text
	assert printMapping(load(text)) == text
	data = mappingToJson(mapping)
	assert data["scopes"][0]["lines"][1]["expr"] == {"call": "ref", "args": [{"path": ["T/Question"]}, {"text": "WantsX"}]}
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data, referentials=[IDS])) == data


def test_round_trip_keeps_a_target_alias_when_the_source_has_that_type_name():
	source = loadOntology([Source("s.onto", """@ontology S
Question
Answer
  Wanted Boolean
  Topic Text
""")])
	text = MAPPING.replace("Answer -> Reply", "@use T as Target\nAnswer -> Reply").replace("ref(Question,", "ref(Target/Question,")
	mapping = loadMapping(source, TARGET, Source("m.map", text), referentials=[IDS])
	printed = printMapping(mapping)
	assert 'ref(Target/Question, "WantsX")' in printed
	data = mappingToJson(mapping)
	assert mappingToJson(loadMapping(source, TARGET, Source("m.map", printed), referentials=[IDS])) == data
	assert mappingToJson(mappingFromJson(source, TARGET, data, referentials=[IDS])) == data


@pytest.mark.parametrize("line", [
	'  Question <- ref(Reply, "WantsX")',  # no key policy
	"  Question <- ref(Question, Wanted)",  # not a text or number key
	'  Question <- ref(Nowhere, "WantsX")',  # no such type
])
def test_a_target_reference_needs_a_keyed_type_and_a_text_or_number_key(line):
	with pytest.raises(FormatError):
		load(MAPPING.replace('  Question <- ref(Question, "WantsX")', line))


def test_without_a_referential_a_target_reference_is_an_error():
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("m.map", MAPPING.replace(" referential=TIds", "")))


@pytest.mark.parametrize("coalesced", [False, True])
def test_a_view_reads_a_target_reference_from_the_row_that_states_it(coalesced):
	from types import SimpleNamespace
	from onto import loadBinding
	from onto.integrations.hexa import HexaViewOperator, ViewRead
	from onto.ontology import ViewInput
	view = loadOntology([Source("t.onto", """@ontology T
Question
  Code Text {key}
  Text Text
Reply
  IsYes Boolean
  Question Question
Reply -answers/isAnsweredBy-> Question
@use S as S
@view AnswerReply(answerId: S/Answer.Id)
  reply: Reply
  reply.Question
  reply.answers
""")], [SOURCE])
	ids = loadReferential([view], [Source("t.ref", "@referential TIds\n@use T as X\nX/Question key=Code\n")])
	text = MAPPING.replace('ref(Question, "WantsX")', 'ref(Question, Topic) ?? ref(Question, "WantsX")') if coalesced else MAPPING
	mapping = loadMapping(SOURCE, view, Source("m.map", text), referentials=[ids])
	binding = loadBinding(SOURCE, Source("a.bind", "@binding S format=json\nAnswer <- answers[*] {id=id}\n  Id <- id\n  Wanted <- wanted\n  Topic <- topic\n"))
	reads = {"Answers": ViewRead(ViewInput("answerId", "S/Answer", "Id"), [binding])}
	access = SimpleNamespace(rootHandle=lambda param, value, target: f"Reply_S_2FAnswer_2F{value}", fetch=lambda step, value: None)
	operator = HexaViewOperator(HexaMappingOperator(SOURCE, view, ids, mode="lenient"), mapping, reads, access)
	plan = asyncio.run(operator.plan("AnswerReply", {"answerId": 1}, ["reply.Question", "reply.answers"]))
	assert plan["fields"] == {"reply.Question": "Answers", "reply.answers": "Answers"}
	assert not plan["gaps"]


def test_a_target_reference_writes_nothing_back():
	_, lossy = mappingReverse(load(), SOURCE, TARGET)
	assert {item.line for item in lossy} == {"Question", "answers"}

# EOF
