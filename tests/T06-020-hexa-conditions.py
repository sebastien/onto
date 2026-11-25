"""Conditions in runs: alternatives, `&` and `|`, membership in collections, exclusive lines (spec-04 Conditions)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("hexa.shapes")
from hexa.runtime import run  # noqa: E402

from onto import FormatError, Source, loadBinding, loadMapping, loadObservations, loadOntology, mappingFromJson, mappingToJson, observationsToJson, printMapping, reconcileObservations  # noqa: E402
from onto.integrations.hexa.operations import HexaBindingOperator, HexaMappingOperator  # noqa: E402
from onto.mapping.coverage import mappingCoverage  # noqa: E402
from tests.helpers import schemaValidator  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SOURCE = loadOntology([Source("s.onto", """@ontology S
Kind = Home|Investment|Car
Asset
  Kind Kind
  Offered Boolean
  Replaced Boolean
  * Tags Text
  Price Number
  Street Text
  Note Text
""")])
TARGET = loadOntology([Source("t.onto", """@ontology T
Use = Home|Other
Property
  Use Use
  Label Text
Proposal
  Property Property
""")])
MAPPING = """@mapping S -> T
Asset -> Property
  Use <- "Home" {when=Kind:Home|Investment}
  Use <- "Other"
  Label <- "Tagged" {when=Tags:Urgent}
Asset -> Proposal {when=Kind:Home|Investment & (Offered:true | Replaced:true)}
  Property <- $
"""


def mapped(fields: str, text: str = MAPPING):
	mapping = loadMapping(SOURCE, TARGET, Source("m.map", text))
	ops = HexaMappingOperator(SOURCE, TARGET, mode="lenient")
	program = ops.compile(mapping)
	obs = loadObservations(SOURCE, Source("o.obs", "@obs S at=2026-11-25\n@src f=fixture\n@src f\nAsset_1:Asset\n" + fields))
	result = asyncio.run(run({"ClockRead": lambda context: "2026-11-25"}, program.stages.MappingRead, observationsToJson(reconcileObservations(SOURCE, obs))))
	log, report = ops.result(program, result)
	return observationsToJson(log), report


def values(log: dict, member: str) -> list:
	return [claim["v"] for claim in log["claims"] if claim.get("p") == member]


def proposals(log: dict) -> int:
	return sum(item["type"] == "T/Proposal" for item in log["instances"].values() if not item.get("implicit"))


# -----------------------------------------------------------------------------
#
# MAPPINGS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(("fields", "use", "proposed"), [
	("  Kind Home\n  Offered true\n", "Home", 1),
	("  Kind Investment\n  Offered false\n  Replaced true\n", "Home", 1),
	("  Kind Investment\n  Offered false\n  Replaced false\n", "Home", 0),
	("  Kind Car\n  Offered true\n", "Other", 0),
	("  Offered true\n", "Other", 0),
])
def test_alternatives_and_compound_scope_conditions(fields, use, proposed):
	log, report = mapped(fields)
	assert not report.gaps
	assert values(log, "Use") == [use]
	assert proposals(log) == proposed


def test_a_test_on_a_collection_holds_when_a_member_is_listed():
	log, report = mapped("  Tags [Urgent, Other]\n")
	assert not report.gaps and values(log, "Label") == ["Tagged"]
	log, report = mapped("  Tags [Other]\n")
	assert not report.gaps and values(log, "Label") == []


def test_a_conflict_in_any_tested_path_is_a_gap():
	log, report = mapped("  Kind Home\n  Offered true\n  Replaced false\n@src g=other\n@src g\nAsset_1.Replaced true\n")
	assert [(gap.target, gap.reason) for gap in report.gaps] == [("T/Proposal", "Mapping.InputConflicting")]
	assert proposals(log) == 0


@pytest.mark.parametrize("lines", [
	"  Label <- Kind {when=Kind:Home & Offered:true}\n",
	"  Label <- Kind {when=Kind:Home}\n  Label <- Kind\n",
])
def test_a_condition_conflict_cannot_be_replayed_as_source_variants(lines):
	log, report = mapped("  Kind Home\n  Offered true\n@src g=other\n@src g\nAsset_1.Kind Car\n",
		"@mapping S -> T\nAsset -> Property\n" + lines)
	assert not values(log, "Label")
	assert [(gap.target, gap.reason) for gap in report.gaps] == [("T/Property.Label", "Mapping.InputConflicting")] * lines.count("Label")


@pytest.mark.parametrize(("scope", "line", "emits_label"), [
	("{when=$}", "", True),
	("{when=$:Asset_1}", "", True),
	("{when=$:Other}", "", False),
	("", "{when=$:Asset_1 & Offered:true}", True),
	("", "{when=$:Other}", False),
])
def test_mapping_conditions_can_read_the_scope_instance(scope, line, emits_label):
	log, report = mapped("  Offered true\n", f'@mapping S -> T\nAsset -> Property {scope}\n  Label <- "Matched" {line}\n')
	assert not report.gaps
	assert values(log, "Label") == (["Matched"] if emits_label else [])


def test_conditions_print_and_round_trip():
	mapping = loadMapping(SOURCE, TARGET, Source("m", MAPPING))
	text = printMapping(mapping)
	assert "Asset -> Proposal {when=Kind:Home|Investment & (Offered:true | Replaced:true)}" in text
	assert '  Use <- "Home" {when=Kind:Home|Investment}' in text
	assert printMapping(loadMapping(SOURCE, TARGET, Source("m", text))) == text
	data = mappingToJson(mapping)
	schemaValidator("mapping").validate(data)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data


PRESENCE_MAPPING = """@mapping S -> T
Asset -> Property {present=text(Price) ?? trim(Street), when=Price | Offered:true}
  Label <- Street
"""


@pytest.mark.parametrize(("fields", "emitted"), [
	("  Price 500000\n", True),  # bought: a price, whatever else
	("  Price 0\n  Offered false\n", True),  # zero is a value, as present= reads one
	("  Offered true\n  Street \"1 Main Road\"\n", True),  # offered, at an address
	("  Offered true\n  Street \"  \"\n", False),  # offered, undescribed: present= skips it
	("  Offered false\n  Street \"1 Main Road\"\n", False),  # neither bought nor offered
])
def test_a_path_alone_tests_that_it_has_a_value(fields, emitted):
	log, report = mapped(fields, PRESENCE_MAPPING)
	assert not report.gaps
	assert any(item["type"] == "T/Property" for item in log["instances"].values() if not item.get("implicit")) is emitted


@pytest.mark.parametrize(("lines", "message"), [
	('  Use <- "Home" {when=Kind:Home|Investment}\n  Use <- "Other" {when=Kind:Investment}\n', "sharing no value"),
	('  Use <- "Home" {when=Kind:Home & Offered:true}\n  Use <- "Other"\n', "sharing no value"),
	('  Use <- "Home" {when=Kind}\n  Use <- "Other" {when=Kind:Car}\n', "sharing no value"),
	('  Use <- "Home" {when=Tags:A}\n  Use <- "Other" {when=Tags:B}\n', "single-valued path"),
])
def test_exclusive_lines_need_disjoint_tests_of_one_single_valued_path(lines, message):
	with pytest.raises(FormatError, match=message):
		loadMapping(SOURCE, TARGET, Source("bad.map", "@mapping S -> T\nAsset -> Property\n" + lines))


def test_every_tested_path_counts_as_a_condition_read():
	rows = {row.source: row.status for row in mappingCoverage(SOURCE, TARGET, loadMapping(SOURCE, TARGET, Source("m", MAPPING))).rows}
	assert rows["Asset.Offered"] == rows["Asset.Replaced"] == rows["Asset.Tags"] == "condition"


# -----------------------------------------------------------------------------
#
# BINDINGS
#
# -----------------------------------------------------------------------------


BINDING = """@binding S
Asset <- assets[*] {id=id, deleted=status:Deleted|Merged}
  Kind <- kind
  Offered <- offered {when=kind:Home|Investment & offered:true}
  Replaced <- replaced {when=note}
  Tags <- tags[*] {when=tags[*]:Urgent | kind:Car}
"""
DOCUMENT = {"assets": [
	{"id": "1", "kind": "Home", "offered": True, "tags": ["Urgent"], "replaced": False, "note": "sold"},
	{"id": "2", "kind": "Car", "offered": True, "tags": ["Later"], "replaced": True, "note": ""},
	{"id": "3", "kind": "Investment", "offered": False, "tags": ["Later"], "replaced": True},
	{"id": "4", "kind": "Home", "offered": True, "status": "Merged"},
]}


def bound(text: str = BINDING) -> dict:
	ops = HexaBindingOperator(SOURCE)
	program = ops.compile(loadBinding(SOURCE, Source("s.bind", text)))
	log, report = ops.result(program, asyncio.run(run({"ClockRead": lambda context: "2026-11-25"}, program.stages.BindingRead, [{"src": "feed", "document": DOCUMENT}])))
	assert not report.gaps
	return observationsToJson(log)


def test_binding_lines_and_deletions_take_compound_conditions():
	log = bound()
	claims = {(claim["s"], claim["p"]): claim["v"] for claim in log["claims"] if "p" in claim}
	assert claims[("Asset_1", "Offered")] is True and ("Asset_2", "Offered") not in claims and ("Asset_3", "Offered") not in claims
	assert ("Asset_1", "Tags") in claims and ("Asset_2", "Tags") in claims and ("Asset_3", "Tags") not in claims
	# A field alone tests that it has a value: empty text has none
	assert claims[("Asset_1", "Replaced")] is False and ("Asset_2", "Replaced") not in claims and ("Asset_3", "Replaced") not in claims
	assert not any(claim.get("s") == "Asset_4" for claim in log["claims"])


def test_binding_conditions_print_as_written():
	from onto import bindingToJson, printBinding
	binding = loadBinding(SOURCE, Source("s.bind", BINDING))
	assert printBinding(binding) == BINDING.replace("@binding S\n", "@binding S\n\n")
	schemaValidator("mapping").validate(bindingToJson(binding))

# EOF
