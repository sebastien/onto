"""Cross-scope assignments update an emitted target, never mint a duplicate."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run
from onto import FormatError, Source, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations
from onto.integrations.hexa.operations import HexaMappingOperator

SOURCE = loadOntology([Source("s.onto", """@ontology S
ANote
  Application App
  * Applications App
  Notes Text
  PrivateNotes Text
  Explained Boolean
  Enabled Boolean
App
  Enabled Boolean
  Name Text
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Engagement
  Name Text
  Notes Text
  PrivateNotes Text
Disclosure of Engagement
  Explained Boolean
Tracking
  Name Text
""")])
MAPPING = """@mapping S -> T
ANote -> Engagement {into=Application}
  Notes <- Notes
  PrivateNotes <- PrivateNotes
  Disclosure.Explained <- Explained
App -> Engagement {when=Enabled:true}
  Name <- Name
App -> Tracking
  Name <- Name
"""


def mapped(fields, text=MAPPING, app="App_42:App\n  Enabled true\n  Name Existing\n"):
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-18\n@scope source\n@src base=fixture:app\n@src base\n" + app +
		"@src note=fixture:note\n@src note\nANote_99:ANote\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-18"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


def test_updates_existing_engagement_with_note_provenance_and_no_new_identity():
	log, report = mapped("  Application App_42\n  Notes Shared\n  PrivateNotes Private\n  Explained false\n")
	assert not report.gaps
	engagements = {h for h, v in log["instances"].items() if v["type"] == "T/Engagement"}
	assert engagements == {"Engagement_source_2FApp_2F42"}
	claims = {c.get("p"): c for c in log["claims"] if c.get("s") in engagements}
	assert claims["Notes"]["v"] == "Shared"
	assert claims["PrivateNotes"]["v"] == "Private"
	assert claims["Disclosure.Explained"]["v"] is False
	assert log["sources"][claims["Notes"]["src"]] == "fixture:note"
	assert log["sources"][claims["Name"]["src"]] == "fixture:app"
	exists = [c for c in log["claims"] if c.get("s") in engagements and c.get("exists")]
	assert len(exists) == 1 and log["sources"][exists[0]["src"]] == "fixture:app"
	assert "ANote_99" not in report.correspondence  # Update scopes are not identity scopes.


@pytest.mark.parametrize("reference", ["", "  Application ?\n", "  Application null\n", "  Application App_7:App\n"])
def test_missing_unknown_null_or_unemitted_destinations_gap_without_minting(reference):
	log, report = mapped(reference + "  Notes Must not attach\n")
	assert report.gaps
	assert not any(c.get("p") == "Notes" for c in log["claims"])
	assert len([v for v in log["instances"].values() if v["type"] == "T/Engagement"]) == 1


def test_condition_excluded_destination_is_not_resurrected():
	log, report = mapped("  Application App_42\n  Notes Must not attach\n", app="App_42:App\n  Enabled false\n")
	assert any(g.reason == "Mapping.ReferenceUnmapped" for g in report.gaps)
	assert not any(v["type"] == "T/Engagement" for v in log["instances"].values())
	assert report.stale


def test_conflicting_destination_does_not_choose_one():
	log, report = mapped("  Application App_42\n  Notes Ambiguous\n@src other=fixture:other\n@src other\nANote_99.Application App_7:App\n")
	assert any(g.reason == "Mapping.InputConflicting" for g in report.gaps)
	assert not any(c.get("p") == "Notes" for c in log["claims"])


@pytest.mark.parametrize("selector, fields", [
	("when=Enabled:true", "  Enabled false\n  Notes Not selected\n"),
	("present=trim(Notes)", "  Notes \"  \"\n"),
])
def test_unselected_update_does_not_require_a_destination(selector, fields):
	log, report = mapped(fields, MAPPING.replace("into=Application", "into=Application, " + selector))
	assert not report.gaps
	assert not any(c.get("p") == "Notes" for c in log["claims"])


@pytest.mark.parametrize("selector, fields", [
	("when=Enabled:true", "  Enabled false\n  Notes Not selected\n"),
	("present=trim(Notes)", "  Notes \"  \"\n"),
])
def test_unselected_update_ignores_a_conflicting_destination(selector, fields):
	fields += "  Application App_42\n@src other=fixture:other\n@src other\nANote_99.Application App_7:App\n"
	log, report = mapped(fields, MAPPING.replace("into=Application", "into=Application, " + selector))
	assert not report.gaps
	assert not any(c.get("p") == "Notes" for c in log["claims"])


def test_into_roundtrips_and_counts_as_coverage():
	from onto.mapping.coverage import mappingCoverage
	mapping = loadMapping(SOURCE, TARGET, Source("m", MAPPING))
	data = mappingToJson(mapping)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data
	assert printMapping(loadMapping(SOURCE, TARGET, Source("m", printMapping(mapping)))) == printMapping(mapping)
	assert any(r.source == "ANote.Application" and r.status == "condition" for r in mappingCoverage(SOURCE, TARGET, mapping).rows)


def test_wrong_target_type_cannot_be_supplied_by_the_update_scope_itself():
	text = MAPPING.replace("App -> Engagement {when=Enabled:true}\n  Name <- Name\n", "")
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("wrong-target", text))


def test_named_self_update_keeps_the_existing_unnamed_identity_stable():
	log, report = mapped("  Application App_42\n", MAPPING + "App -> Engagement {name=AppendNote, into=$}\n  Notes <- Name\n")
	assert not report.gaps
	assert {h for h, v in log["instances"].items() if v["type"] == "T/Engagement"} == {"Engagement_source_2FApp_2F42"}
	assert any(c.get("s") == "Engagement_source_2FApp_2F42" and c.get("p") == "Notes" and c["v"] == "Existing" for c in log["claims"])


def test_conflicting_note_values_retain_their_separate_sources_on_the_same_target():
	log, report = mapped("  Application App_42\n  Notes One\n@src other=fixture:other\n@src other\nANote_99.Notes Two\n")
	assert not report.gaps
	notes = [c for c in log["claims"] if c.get("p") == "Notes"]
	assert {c["v"] for c in notes} == {"One", "Two"}
	assert {log["sources"][c["src"]] for c in notes} == {"fixture:note", "fixture:other"}
	assert {c["s"] for c in notes} == {"Engagement_source_2FApp_2F42"}


@pytest.mark.parametrize(("fields", "reason"), [
	("  Applications [App_42]\n", None),
	("  Applications [App_42, App_7:App]\n", "Mapping.ReferenceAmbiguous"),
	("  Applications [App_42, ...]\n", "Mapping.ReferenceAmbiguous"),
])
def test_a_multi_valued_destination_is_its_one_member_never_the_first(fields, reason):
	log, report = mapped(fields + "  Notes Shared\n", MAPPING.replace("into=Application", "into=Applications"))
	notes = [c for c in log["claims"] if c.get("p") == "Notes"]
	if reason is None:
		assert not report.gaps and [c["s"] for c in notes] == ["Engagement_source_2FApp_2F42"]
	else:
		assert any(g.reason == reason for g in report.gaps) and notes == []


@pytest.mark.parametrize("expr", ['Notes', '"arbitrary-handle"'])
def test_scalar_text_and_literal_destinations_are_rejected(expr):
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("bad", MAPPING.replace("into=Application", "into=" + expr)))

# EOF
