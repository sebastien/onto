"""Module: qualifier vocabulary tests — `{cur=?:V}` takes each value's qualifier from vocabulary `V`."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology
from onto.ontology import Model, Operator, TypeExpr, ontologyFromJson, ontologyToJson

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

HEADER = "@ontology A layering=declared\n@domain Core\n@domain Shop\n"
BODY = """\
Core/Currency = EUR|NZD|USD
Core/Unit = Day|Month|Year {ordered}
Core/Money = Amount {cur=?:Core/Currency}
Core/Euros = Core/Money {cur=EUR}
Core/Duration = Duration {unit=?:Core/Unit}
Shop/Item
  Price Core/Money
  Cost Core/Euros
  Warranty Core/Duration
  Local Core/Money {cur=NZD}
"""


def load(body: str = BODY, header: str = HEADER):
	return loadOntology([Source("main.onto", header + body)])


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


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testTheVocabularyIsResolvedAndInherited():
	model = Model(load())
	resolved = model.resolveType(TypeExpr(path="A/Core/Euros"))
	assert resolved.qualifiers == {"cur": "EUR"}
	assert resolved.qualifierVocabularies == {"cur": "A/Core/Currency"}


def testNormalFormAndJsonKeepTheVocabulary():
	ontology = load()
	assert "Core/Money = Amount {cur=?:Core/Currency}" in Operator(ontology).print()
	data = ontologyToJson(ontology)
	assert next(decl for decl in data["decls"] if decl["path"] == "A/Core/Money")["ann"]["cur"] == "?:A/Core/Currency"
	assert ontologyToJson(ontologyFromJson(data)) == data


def testObservedQualifiersFromTheVocabularyAreAccepted():
	observe("  Price 12 {cur=NZD}\n  Cost 3\n  Warranty 2 {unit=Year}\n  Price ?\n")


@pytest.mark.parametrize("text, code", [
	("  Price 12 {cur=NZ}\n", "qualifier"),
	("  Warranty 2 {unit=Week}\n", "qualifier"),
	("  Cost 3 {cur=USD}\n", "qualifier"),
	("  Local 3 {cur=EUR}\n", "qualifier"),
	("  Price 12 {cur=?:Core/Currency}\n", "meta"),
])
def testObservedQualifiersOutsideTheVocabularyAreErrors(text: str, code: str):
	assert code in observeCodes(text)


@pytest.mark.parametrize("body, code", [
	("Core/Currency = EUR|NZD\nCore/Money = Amount {cur=?:Core/Currency}\nCore/Pounds = Core/Money {cur=GBP}\n", "qualifier"),
	("Core/Currency = EUR|NZD\nShop/Item\n  Price Amount {cur=?:Core/Currency}\n  Cost Shop/Item.Price {cur=GBP}\n", "qualifier"),
	("Core/Money = Amount {cur=?:Core/Missing}\n", "reference"),
	("Core/Money = Amount {cur=?:Text}\n", "reference"),
	("Core/Currency = Euro/EUR {hierarchical}\nCore/Money = Amount {cur=?:Core/Currency}\n", "reference"),
	("Core/Money = Amount {cur=?:Shop/Currency}\nShop/Currency = EUR|NZD\n", "layering"),
	("Core/Ratio = Percent {scale=?:Core/Scale}\nCore/Scale = |One\n", "annotation"),
])
def testInvalidQualifierVocabulariesAreErrors(body: str, code: str):
	assert code in codes(body)


def testAnOpenVocabularyAcceptsOtherValues():
	load("Core/Currency = EUR|NZD|...\nCore/Money = Amount {cur=?:Core/Currency}\nCore/Pounds = Core/Money {cur=GBP}\n")


# EOF
