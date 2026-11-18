"""Module: range tests — `Range<T>` over an orderable type, written `low..high` with inclusive bounds."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology, reconcileObservations
from onto.meta import metaObservations
from onto.ontology import Model, Operator, TypeExpr, ontologyFromJson, ontologyToJson

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

HEADER = "@ontology A layering=declared\n@domain Core\n@domain Shop\n"
BODY = """\
Core/Currency = EUR|NZD
Core/Money = Amount {cur=?:Core/Currency}
Core/Years = Duration {unit=Year}
Core/Size = Small|Medium|Large {ordered}
Core/Money/Range = Range<Core/Money>            -- A band of money amounts
Shop/Item
  Price Core/Money/Range
  Weight Range<Number>
  Age Range<Core/Years>
  Size Range<Core/Size>
  Made Range<Date>
  Cost Range<Core/Money> {cur=EUR}
  * Bands Range<Integer>
"""


def load(body: str = BODY):
	return loadOntology([Source("main.onto", HEADER + body)])


def codes(body: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		load(body)
	return [item.code for item in raised.value.diagnostics]


def observe(text: str):
	return loadObservations(load(), Source("c.obs", "@obs A\ni:Shop/Item\n" + text), "strict")


def observeCodes(text: str) -> list[str]:
	with pytest.raises(FormatError) as raised:
		observe(text)
	return [item.code for item in raised.value.diagnostics]


def value(text: str):
	return next(claim["v"] for claim in observe(text).claims if "v" in claim)


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testARangeResolvesToItsElement():
	model = Model(load())
	resolved = model.resolveType(TypeExpr(path="A/Core/Money/Range"), [("cur", "NZD")])
	assert resolved.kind == "range" and resolved.element.builtin == "Amount"
	assert resolved.qualifiers == {"cur": "NZD"}


def testNormalFormAndJsonKeepRanges():
	ontology = load()
	text = Operator(ontology).print()
	assert "Core/Money/Range = Range<Core/Money>" in text and "Weight Range<Number>" in text
	data = ontologyToJson(ontology)
	assert next(decl for decl in data["decls"] if decl["path"] == "A/Core/Money/Range")["def"] == {"range": {"path": "A/Core/Money"}}
	assert ontologyToJson(ontologyFromJson(data)) == data


@pytest.mark.parametrize("text, expected", [
	("  Weight 1.50..2\n", "1.5..2"),
	("  Weight 10..\n", "10.."),
	("  Weight ..10\n", "..10"),
	("  Weight 10\n", "10..10"),
	("  Weight -5..-1\n", "-5..-1"),
	("  Age 35..44\n", "35..44"),
	("  Size Small..Large\n", "Small..Large"),
	("  Made 2019-03-01..2020-01-31\n", "2019-03-01..2020-01-31"),
	("  Price 500000..650000 {cur=NZD}\n", "500000..650000"),
	("  Cost 1..2\n", "1..2"),
])
def testRangesAreCanonical(text: str, expected: str):
	assert value(text) == expected


def testRangesInACollection():
	assert value("  Bands [1..5, 6..10]\n")["set"] == ["1..5", "6..10"]


def testEquivalentNumericRangesDoNotConflictOrCountAsDistinctMembers():
	log = observe("  Weight 1000..2000 {src=a}\n  Weight 1e3..2e3 {src=b}\n")
	state = reconcileObservations(load(), log)
	weights = [claim for claim in state.claims if claim.get("p") == "Weight"]
	assert {claim["v"] for claim in weights} == {"1000..2000", "1e3..2e3"}
	assert not any(claim.get("conflict") for claim in weights)
	assert observeCodes("  Bands [1000..2000, 1e3..2e3]\n") == ["value"]


@pytest.mark.parametrize("text, code", [
	("  Weight 2..1\n", "value"),
	("  Size Large..Small\n", "value"),
	("  Made 2020-01-01..2019-01-01\n", "value"),
	("  Weight ..\n", "value"),
	("  Weight a..b\n", "value"),
	("  Size Small..Huge\n", "value"),
	('  Weight "1..2"\n', "value"),
	("  Price 1..2 {cur=GBP}\n", "qualifier"),
	("  Cost 1..2 {cur=NZD}\n", "qualifier"),
])
def testInvalidRangeValuesAreErrors(text: str, code: str):
	assert code in observeCodes(text)


@pytest.mark.parametrize("body, code", [
	("Core/T\n  X Range<Text>\n", "range"),
	("Core/T\n  X Range<Boolean>\n", "range"),
	("Core/V = A|B\nCore/T\n  X Range<Core/V>\n", "range"),
	("Core/S =\n  A Number\nCore/T\n  X Range<Core/S>\n", "range"),
	("Core/T\n  X Range<Range<Number>>\n", "range"),
	("Core/T\n  X Range<A|B>\n", "range"),
	("Core/T\n  X Range<Core/Missing>\n", "reference"),
	("Core/T\n  X Range<Shop/N>\nShop/N = Number\n", "layering"),
])
def testInvalidRangeTypesAreErrors(body: str, code: str):
	assert code in codes(body)


def testMetaDescribesRanges():
	text = metaObservations(load())
	assert "Core_Money_Range:Meta/Dimension\n  Path Core/Money/Range\n  Kind Range" in text
	assert "Number__Range:Meta/Dimension\n  Path Range<Number>\n  Kind Range" in text
	assert "Core_Money_Range isBasedOn Core_Money" in text
	assert "Shop_Item__Weight hasDimension Number__Range" in text


# EOF
