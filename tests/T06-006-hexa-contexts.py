"""Module: hexa contexts tests — context-preserving mapping, overrides and re-running."""

from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402

from onto import Source, loadMapping, loadObservations, loadOntology, observationsToJson, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402


SOURCE = loadOntology([Source("s.onto", """@ontology ContextSource
Scenario
  Code Text
Person
  Name Text
  Context Scenario
  Context2 Scenario
  Owner Person
Review of Person {ctx=Scenario}
  Score Integer
  Label Text
  * Tags Text
""")])
TARGET = loadOntology([Source("t.onto", """@ontology ContextTarget
Scenario
  Code Text
Human
  Name Text
Assessment of Human {ctx=Scenario}
  Score Integer
  Label Text
""")])
CLOCK = {"ClockRead": lambda context: "2026-11-17"}
TEXT = """@obs ContextSource
@src s=feed:1
@src s
@at 2026-11-16
a:Scenario
  Code A
b:Scenario
  Code B
p:Person
  Name Person
  Context b
  Owner q:Person
q:Person
  Name Owner
p[Review] {ctx=a}
  Review.Score 1 {ctx=a}
  Review.Label Alpha {ctx=a}
p[Review] {ctx=b}
  Review.Score 2 {ctx=b}
  Review.Label Beta {ctx=b}
q[Review] {ctx=a}
  Review.Score 10 {ctx=a}
q[Review] {ctx=b}
  Review.Score 20 {ctx=b}
"""


def state(text: str = TEXT) -> dict:
	return observationsToJson(reconcileObservations(SOURCE, loadObservations(SOURCE, Source("s.obs", text))))


def compileMapping(lines: str, scope: str = "Person -> Human", scenarios: bool = True):
	text = f"@mapping ContextSource -> ContextTarget retract=100%\n{scope}\n{lines}"
	if scenarios:
		text += "Scenario -> Scenario\n  Code <- Code\n"
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET)
	return ops, ops.compile(mapping)


def read(ops, program, data):
	result = asyncio.run(run(CLOCK, program.stages.MappingRead, data))
	return ops.result(program, result), result["value"]


def slots(log, path: str) -> list[tuple]:
	return sorted((claim.get("ctx"), claim["v"]) for claim in log.claims if claim.get("s") == "Human_ContextSource_2FPerson_2Fp" and claim.get("p") == path)


def test_contexts_are_separate_and_global_lines_run_once():
	ops, program = compileMapping("  Name <- Name\n  Assessment.Score <- Review.Score\n  Assessment.Label <- Review.Label\n")
	data = state()
	before = deepcopy(data)
	(log, report), raw = read(ops, program, data)
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "1"), ("Scenario_ContextSource_2FScenario_2Fb", "2")]
	assert slots(log, "Assessment.Label") == [("Scenario_ContextSource_2FScenario_2Fa", "Alpha"), ("Scenario_ContextSource_2FScenario_2Fb", "Beta")]
	assert slots(log, "Name") == [(None, "Person")]
	assert all("ctx" not in claim for claim in log.claims if claim.get("exists") or claim.get("p") == "Name")
	assert report.gaps == [] and data == before
	assert raw["correspondence"]["a"] == "Scenario_ContextSource_2FScenario_2Fa"
	reconcileObservations(TARGET, log)


def test_reference_paths_and_conditional_facets_use_the_same_context():
	ops, program = compileMapping("  Assessment.Score <- sum(Review.Score, Owner.Review.Score)\n  [Assessment] {when=Review.Label:Alpha}\n")
	(log, report), _ = read(ops, program, state())
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "11"), ("Scenario_ContextSource_2FScenario_2Fb", "22")]
	assert [(claim["s"], claim["ctx"]) for claim in log.claims if claim.get("facet") == "Assessment"] == [
		("Human_ContextSource_2FPerson_2Fp", "Scenario_ContextSource_2FScenario_2Fa"),
	]
	assert report.gaps == []


def test_scope_context_replaces_inherited_context_without_changing_global_claims():
	ops, program = compileMapping("  Name <- Name\n  Assessment.Label <- Review.Label\n", scope="Person -> Human {ctx=Context}")
	(log, _), _ = read(ops, program, state())
	assert slots(log, "Assessment.Label") == [("Scenario_ContextSource_2FScenario_2Fb", "Alpha"), ("Scenario_ContextSource_2FScenario_2Fb", "Beta")]
	assert slots(log, "Name") == [(None, "Person")]


def test_explicit_context_can_supply_a_literal_contextual_value():
	ops, program = compileMapping('  Assessment.Label <- "Included"\n', scope="Person -> Human {ctx=Context}")
	(log, report), _ = read(ops, program, state())
	assert slots(log, "Assessment.Label") == [("Scenario_ContextSource_2FScenario_2Fb", "Included")]
	# q has no Context: it cannot acquire p's context.
	assert not any(claim.get("s") == "Human_ContextSource_2FPerson_2Fq" and claim.get("p") == "Assessment.Label" for claim in log.claims)
	assert any(gap.reason == "Mapping.ReferenceUnmapped" for gap in report.gaps)


def test_missing_context_correspondence_is_a_gap_not_an_uncontextual_claim():
	ops, program = compileMapping("  Name <- Name\n  Assessment.Score <- Review.Score\n", scenarios=False)
	(log, report), _ = read(ops, program, state())
	assert slots(log, "Assessment.Score") == []
	assert slots(log, "Name") == [(None, "Person")]
	assert all(gap.reason == "Mapping.ReferenceUnmapped" for gap in report.gaps)
	assert report.gaps


def test_contextual_conflicts_fan_out_only_inside_their_context():
	data = state()
	data["sources"]["other"] = "feed:other"
	conflicting = next(claim for claim in data["claims"] if claim.get("s") == "p" and claim.get("p") == "Review.Score" and claim.get("ctx") == "a")
	conflicting["conflict"] = True
	data["claims"].append({**conflicting, "n": max(claim["n"] for claim in data["claims"]) + 1, "v": "3", "src": "other"})
	ops, program = compileMapping("  Assessment.Score <- Review.Score\n")
	(log, report), _ = read(ops, program, data)
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "1"), ("Scenario_ContextSource_2FScenario_2Fa", "3"), ("Scenario_ContextSource_2FScenario_2Fb", "2")]
	assert report.gaps == []


def test_rerun_keeps_a_stale_context_but_retracts_an_absent_other_context():
	ops, program = compileMapping("  Name <- Name\n  Assessment.Score <- number(Review.Label)\n")
	firstData = state(TEXT.replace("Review.Label Alpha", "Review.Label 1").replace("Review.Label Beta", "Review.Label 2"))
	env = CLOCK | {"OutputPreviousRead": lambda request, context: None, "RetractionsPendingRead": lambda request, context: []}
	first = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, firstData)))
	nextData = deepcopy(firstData)
	for claim in nextData["claims"]:
		if claim.get("s") == "p" and claim.get("p") == "Review.Label" and claim.get("ctx") == "a":
			claim["v"] = "not a number"
	nextData["claims"] = [claim for claim in nextData["claims"] if not (claim.get("s") == "p" and claim.get("p") == "Review.Label" and claim.get("ctx") == "b")]
	env["OutputPreviousRead"] = lambda request, context: first.log
	second = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, nextData)))
	assert [(item["s"], item["p"], item["ctx"]) for item in second.log["retractions"]] == [
		("Human_ContextSource_2FPerson_2Fp", "Assessment.Score", "Scenario_ContextSource_2FScenario_2Fb"),
	]
	assert any(item.get("ctx") == "Scenario_ContextSource_2FScenario_2Fa" for item in second.report.stale)


@pytest.mark.parametrize("value", [None, {"unknown": True}, "0"])
def test_contextual_null_unknown_and_zero_are_not_missing(value):
	data = state()
	for claim in data["claims"]:
		if claim.get("s") == "p" and claim.get("p") == "Review.Score" and claim.get("ctx") == "a":
			claim["v"] = value
	ops, program = compileMapping("  Assessment.Score <- Review.Score\n")
	(log, report), _ = read(ops, program, data)
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", value), ("Scenario_ContextSource_2FScenario_2Fb", "2")]
	assert report.gaps == []


def test_context_inventory_follows_references_without_requiring_local_context_values():
	ops, program = compileMapping("  Assessment.Score <- Owner.Review.Score\n")
	data = state()
	data["claims"] = [claim for claim in data["claims"] if not (claim.get("s") == "p" and "ctx" in claim)]
	(log, report), _ = read(ops, program, data)
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "10"), ("Scenario_ContextSource_2FScenario_2Fb", "20")]
	assert report.gaps == []


def test_contextual_collections_are_not_merged_across_contexts():
	data = state(TEXT + "p.Review.Tags [A, B] {ctx=a}\np.Review.Tags [C] {ctx=b}\n")
	ops, program = compileMapping("  Assessment.Score <- count(Review.Tags)\n")
	(log, report), _ = read(ops, program, data)
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "2"), ("Scenario_ContextSource_2FScenario_2Fb", "1")]
	assert report.gaps == []


def test_context_only_handles_remain_typed_without_invented_existence():
	data = state()
	data["claims"] = [claim for claim in data["claims"] if claim.get("s") not in ("a", "b")]
	ops, program = compileMapping("  Assessment.Score <- Review.Score\n")
	(log, report), _ = read(ops, program, data)
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "1"), ("Scenario_ContextSource_2FScenario_2Fb", "2")]
	assert observationsToJson(log)["instances"]["Scenario_ContextSource_2FScenario_2Fa"] == {"type": "ContextTarget/Scenario"}
	assert not any(claim.get("exists") and claim["s"].startswith("Scenario_") for claim in log.claims)
	assert report.gaps == []


def test_contextual_scope_condition_filters_each_context_separately():
	ops, program = compileMapping("  Assessment.Score <- Review.Score\n", scope="Person -> Human {when=Review.Label:Alpha}")
	(log, report), _ = read(ops, program, state())
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "1")]
	assert report.gaps == []


def test_conflicting_scope_condition_preserves_its_context_on_rerun():
	ops, program = compileMapping("  Assessment.Score <- Review.Score\n", scope="Person -> Human {when=Review.Label:Alpha}")
	env = CLOCK | {"OutputPreviousRead": lambda request, context: None, "RetractionsPendingRead": lambda request, context: []}
	first = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, state())))
	data = state()
	data["sources"]["other"] = "feed:other"
	label = next(claim for claim in data["claims"] if claim.get("s") == "p" and claim.get("p") == "Review.Label" and claim.get("ctx") == "a")
	label["conflict"] = True
	data["claims"].append({**label, "n": max(claim["n"] for claim in data["claims"]) + 1, "v": "Other", "src": "other"})
	env["OutputPreviousRead"] = lambda request, context: first.log if request["src"] == "feed:1" else None
	second = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, data)))
	assert second.log["retractions"] == []
	assert any(gap.reason == "Mapping.InputConflicting" for gap in second.report.gaps)
	assert any(item.get("ctx") == "Scenario_ContextSource_2FScenario_2Fa" for item in second.report.stale)


def test_retractions_preserve_types_for_contexts_absent_from_new_input():
	ops, program = compileMapping("  Assessment.Score <- Review.Score\n")
	env = CLOCK | {"OutputPreviousRead": lambda request, context: None, "RetractionsPendingRead": lambda request, context: []}
	first = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, state())))
	data = state()
	data["instances"].pop("b")
	data["claims"] = [claim for claim in data["claims"] if claim.get("s") != "b" and claim.get("ctx") != "b" and claim.get("p") != "Context"]
	env["OutputPreviousRead"] = lambda request, context: first.log
	second = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, data)))
	assert any(item.get("p") == "Assessment.Score" and item.get("ctx") == "Scenario_ContextSource_2FScenario_2Fb" for item in second.log["retractions"])
	assert second.log["instances"]["Scenario_ContextSource_2FScenario_2Fb"] == {"type": "ContextTarget/Scenario"}


def test_stale_context_uses_the_value_source_not_the_existence_source():
	ops, program = compileMapping("  Assessment.Score <- number(Review.Label)\n")
	data = state(TEXT.replace("Review.Label Alpha", "Review.Label 1").replace("Review.Label Beta", "Review.Label 2"))
	data["sources"]["labels"] = "labels:1"
	for claim in data["claims"]:
		if claim.get("s") == "p" and claim.get("p") == "Review.Label":
			claim["src"] = "labels"
	env = CLOCK | {"OutputPreviousRead": lambda request, context: None, "RetractionsPendingRead": lambda request, context: []}
	first = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, data)))
	for claim in data["claims"]:
		if claim.get("s") == "p" and claim.get("p") == "Review.Label" and claim.get("ctx") == "a":
			claim["v"] = "invalid"
	env["OutputPreviousRead"] = lambda request, context: {**first.log,
		"claims": [claim for claim in first.log["claims"] if first.log["sources"][claim["src"]] == request["src"]]}
	second = ops.outcome(program, asyncio.run(run(env, program.stages.MappingRun, data)))
	assert second.log["retractions"] == []
	assert any(item.get("ctx") == "Scenario_ContextSource_2FScenario_2Fa" and item["src"] == "labels:1" for item in second.report.stale)


def test_failed_conflict_variant_is_reported_and_kept_stale_for_its_source():
	data = state(TEXT.replace("Review.Label Alpha", "Review.Label 1"))
	data["sources"]["other"] = "labels:other"
	claim = next(claim for claim in data["claims"] if claim.get("s") == "p" and claim.get("p") == "Review.Label" and claim.get("ctx") == "a")
	claim["conflict"] = True
	data["claims"].append({**claim, "n": max(item["n"] for item in data["claims"]) + 1, "src": "other", "v": "invalid"})
	ops, program = compileMapping("  Assessment.Score <- number(Review.Label)\n")
	(log, report), _ = read(ops, program, data)
	assert slots(log, "Assessment.Score") == [("Scenario_ContextSource_2FScenario_2Fa", "1")]
	assert any(item.get("ctx") == "Scenario_ContextSource_2FScenario_2Fa" and item["src"] == "labels:other" for item in report.stale)
	assert any(gap.reason == "Onto.Number.Invalid" for gap in report.gaps)


def test_context_override_cannot_coalesce_past_a_conflicting_reference():
	data = state(TEXT.replace("  Context b", "  Context b\n  Context2 a"))
	data["sources"]["other"] = "contexts:other"
	context = next(claim for claim in data["claims"] if claim.get("s") == "p" and claim.get("p") == "Context")
	context["conflict"] = True
	data["claims"].append({**context, "n": max(item["n"] for item in data["claims"]) + 1, "src": "other", "v": {"ref": "a"}})
	ops, program = compileMapping("  Name <- Name\n  Assessment.Score <- Review.Score\n", scope="Person -> Human {ctx=Context ?? Context2}")
	(log, report), _ = read(ops, program, data)
	assert slots(log, "Assessment.Score") == []
	assert slots(log, "Name") == [(None, "Person")]
	assert any(gap.reason == "Mapping.InputConflicting" and gap.handle == "Human_ContextSource_2FPerson_2Fp" for gap in report.gaps)


# EOF
