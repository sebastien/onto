"""Module: vocabulary extension tests — `{extends=T}` adds a later domain's values to an open vocabulary."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadObservations, loadOntology
from onto.meta import metaObservations
from onto.ontology import Model, Operator, TypeExpr, ontologyFromJson, ontologyToJson

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

HEADER = "@ontology A layering=declared\n@domain Finance\n@domain Nz\n"
BODY = """\
Finance/Measure = Gross|Net|...
Finance/Band = Low|High|... {ordered}
Finance/Product = {hierarchical}
  Investment
    Fund
  Lending
  ...
Finance/Income
  Measure Finance/Measure
  Band Finance/Band
  Product Finance/Product
Nz/Measure = Paye|Esct {extends=Finance/Measure} -- NZ income measures
Nz/Band = Top|Above {ordered, extends=Finance/Band}
Nz/Product = {hierarchical, extends=Finance/Product}
  Investment
    KiwiSaver
@map Nz/MeasureToFinance Nz/Measure -> Finance/Measure
  Paye exact Paye
"""


def load(body: str = BODY, header: str = HEADER):
	return loadOntology([Source("main.onto", header + body)])


def codes(body: str, header: str = HEADER) -> list[str]:
	with pytest.raises(FormatError) as raised:
		load(body, header)
	return [item.code for item in raised.value.diagnostics]


def values(path: str) -> list[str]:
	return Model(load()).resolveType(TypeExpr(path=f"A/{path}")).values or []


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testExtensionValuesJoinTheVocabulary():
	assert values("Finance/Measure") == ["Gross", "Net", "Paye", "Esct"]
	assert values("Nz/Measure") == ["Paye", "Esct"]


def testOrderedExtensionsAppendAtTheEnd():
	assert values("Finance/Band") == ["Low", "High", "Top", "Above"]


def testHierarchicalExtensionsAddChildren():
	assert values("Finance/Product") == ["Investment", "Investment/Fund", "Investment/KiwiSaver", "Lending"]


def testMapsAndObservationsSeeExtensionValues():
	loadObservations(load(), Source("c.obs", "@obs A\ni:Finance/Income\n  Measure Paye\n  Product Investment/KiwiSaver\n"), "strict")


def testNormalFormAndJsonKeepTheExtension():
	ontology = load()
	text = Operator(ontology).print()
	assert "Nz/Measure = Esct|Paye {extends=Finance/Measure}" in text
	assert "Nz/Band = Top|Above {ordered, extends=Finance/Band}" in text or "Nz/Band = Top|Above {extends=Finance/Band, ordered}" in text
	data = ontologyToJson(ontology)
	assert next(decl for decl in data["decls"] if decl["path"] == "A/Nz/Measure")["ann"]["extends"] == "A/Finance/Measure"
	assert ontologyToJson(ontologyFromJson(data)) == data


def testMetaListsMergedValuesAndTheExtendsLink():
	text = metaObservations(load())
	assert "Finance_Measure extends" not in text
	assert "Nz_Measure extends Finance_Measure" in text
	assert "Paye" in text.split("Finance_Measure:Meta/Dimension")[1].split(":Meta/")[0]


@pytest.mark.parametrize("body, code", [
	("Finance/T = A|B\nNz/T = |C {extends=Finance/T}\n", "extends"),
	("Finance/T = A|...\nNz/T = C|... {extends=Finance/T}\n", "extends"),
	("Finance/T = A|...\nNz/T = |A {extends=Finance/T}\n", "extends"),
	("Finance/T = A|...\nNz/T = |B {extends=Finance/T}\nNz/U = |B {extends=Finance/T}\n", "extends"),
	("Finance/T = A|...\nNz/T = |B {hierarchical, extends=Finance/T}\n", "extends"),
	("Finance/T = A|...\nNz/T = |B {extends=Finance/T}\nNz/U = |C {extends=Nz/T}\n", "extends"),
	("Finance/T = Text\nNz/T = |B {extends=Finance/T}\n", "reference"),
	("Finance/T = A|...\nNz/T = |B {extends=Finance/Missing}\n", "reference"),
	("Finance/T = A|...\nNz/E\n  X B|C {extends=Finance/T}\n", "annotation"),
	("Finance/T = A|... {extends=Nz/T}\nNz/T = B|...\n", "layering"),
])
def testInvalidExtensionsAreErrors(body: str, code: str):
	assert code in codes(body)


def testAnExtensionThroughAnAliasExtendsTheVocabulary():
	ontology = load("Finance/T = A|...\nFinance/Alias = Finance/T\nNz/T = |B {extends=Finance/Alias}\n")
	assert Model(ontology).resolveType(TypeExpr(path="A/Finance/Alias")).values == ["A", "B"]


# EOF
