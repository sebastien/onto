"""Regression tests for compiling incompatible ontology revisions in one Python process."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")

from hexa.runtime import run  # noqa: E402
from hexa.shapes import encode  # noqa: E402

from onto import Source, loadBinding, loadMapping, loadOntology, loadObservations, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, HexaMappingOperator, programEncoding  # noqa: E402


CLOCK = {"ClockRead": lambda context: "2026-11-18"}


def revision(namespace, rev, kind):
	return loadOntology([Source("revision.onto", f"@ontology {namespace} rev={rev}\nRow\n  Value {kind}\n  * Tags Text\n")])


def test_binding_revisions_keep_their_read_and_write_shapes():
	programs = []
	for rev, kind, raw, value, tagsPath, tagsField in (
		("v1", "Text", "hello", "hello", "tagsAll", "tagsAll"),
		("v2", "Integer", "007", "7", "tags[*]", "tags"),
	):
		ontology = revision("SlotBinding", rev, kind)
		binding = loadBinding(ontology, Source("revision.bind",
			f"@binding SlotBinding\nRow <- rows[*] {{id=$.id}}\n  Value <- value\n  Tags <- {tagsPath}\n"))
		operator = HexaBindingOperator(ontology)
		writer = operator.compileWrite(binding)
		assert set(writer.reading.slots) == {"SlotBinding.Row.Value", "SlotBinding.Row.Tags"}
		assert encode(writer.reading.slots["SlotBinding.Row.Value"]) == "$SlotBinding.Row.Value"
		assert writer.reading.selectors["Row"] == "{id?:$Bind.Row.Fields.Root.Id}/rows/*"
		programs.append((operator, writer, {"id": "x", "rows": [{"value": raw, tagsField: ["A"]}]}, value))

	for operator, writer, document, value in programs + programs[:1]:
		reading = writer.reading
		raw = asyncio.run(run(CLOCK, reading.stages.BindingRead, [{"src": "s", "document": document}]))
		log, report = operator.result(reading, raw)
		assert not report.gaps
		assert {claim["p"]: claim["v"] for claim in log.claims if "p" in claim} == {"Value": value, "Tags": {"set": ["A"]}}
		written = asyncio.run(run(CLOCK | {"DocumentPreviousRead": lambda request, context: document}, writer.stages.BindingWrite,
			{"src": "s", "state": observationsToJson(log)}))
		assert written["documents"] == [{"src": "s", "document": {"rows": document["rows"]}}]
		assert not written["report"]["gaps"]
		assert written["report"]["originals"]["rows[*].value"] == 1


def test_mapping_revisions_keep_their_source_shapes():
	target = loadOntology([Source("target.onto", "@ontology SlotTarget\nRow\n  Value Text\n")])
	programs = []
	for rev, kind, value in (("v1", "Text", "hello"), ("v2", "Integer", "7")):
		source = revision("SlotMapping", rev, kind)
		mapping = loadMapping(source, target, Source("revision.map", "@mapping SlotMapping -> SlotTarget\nRow -> Row\n  Value <- text(Value)\n"))
		operator = HexaMappingOperator(source, target)
		program = operator.compile(mapping)
		assert encode(program.slots["SlotMapping.Row.Value"]) == "$SlotMapping.Row.Value"
		assert programEncoding(program) == programEncoding(operator.compile(mapping))
		log = loadObservations(source, Source("source.obs",
			f"@obs SlotMapping at=2026-11-18\n@scope source\n@src s=fixture\n@src s\nRow_x:Row\n  Value {value}\n"))
		programs.append((operator, program, observationsToJson(reconcileObservations(source, log)), value))

	for operator, program, state, value in programs + programs[:1]:
		raw = asyncio.run(run(CLOCK, program.stages.MappingRead, state))
		log, report = operator.result(program, raw)
		assert not report.gaps
		assert [claim["v"] for claim in log.claims if claim.get("p") == "Value"] == [value]


def test_revision_value_maps_use_source_and_target_vocabularies():
	source = loadOntology([Source("old.onto", """@ontology SlotCodes rev=old
Code = |Old
Label = |Shared
@map Lookup Code -> Label
  Old exact Shared
Row
  Value Code
""")])
	target = loadOntology([Source("new.onto", """@ontology SlotCodes rev=new
Code = |New
Label = |Different
@map Lookup Code -> Label
  New exact Different
Row
  Value Code
  Label Text
""")])
	text = """@mapping SlotCodes -> SlotCodes from=old to=new
@use SlotCodes as C
@map Convert Code -> Code
  Old exact New
Row -> Row
  Value <- Convert(Value)
  Label <- text(C/Lookup(Value))
"""
	ops = HexaMappingOperator(source, target)
	obs = loadObservations(source, Source("row.obs",
		"@obs SlotCodes at=2026-11-18\n@src s=fixture\n@src s\nRow_x:Row\n  Value Old\n"))
	state = observationsToJson(reconcileObservations(source, obs))
	mapping = loadMapping(source, target, Source("revision.map", text))
	for item in (mapping, loadMapping(source, target, Source("printed.map", printMapping(mapping)))):
		program = ops.compile(item)
		raw = asyncio.run(run(CLOCK, program.stages.MappingRead, state))
		log, report = ops.result(program, raw)
		assert not report.gaps
		assert {claim["p"]: claim["v"] for claim in log.claims if "p" in claim} == {"Value": "New", "Label": "Shared"}


# EOF
