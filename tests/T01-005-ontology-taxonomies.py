"""Module: taxonomy tests — hierarchical vocabulary parsing, interchange and observations."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadOntology, ontologyFromJson, ontologyToJson
from onto.ontology import Model, Operator, TypeExpr
from onto.observations import loadObservations, observationsFromJson, observationsToJson, printObservationsLog
from tests._helpers import _schemaValidator


def load(body: str):
	return loadOntology([Source("taxonomy.onto", "@ontology A\n" + body)])


def testCompactAndTreeHaveTheSameCanonicalRepresentation():
	compact = load("Category = Food/Fruit/Pear|Food/Fruit/Apple|Clothing/Shirts {hierarchical}\n")
	tree = load("Category = {hierarchical}\n  Food\n    Fruit\n      Pear\n      Apple\n  Clothing\n    Shirts\n")
	expected = (
		"@ontology A\n\nCategory = {hierarchical}\n"
		"  Clothing\n    Shirts\n  Food\n    Fruit\n      Apple\n      Pear\n"
	)
	assert Operator(compact).print() == Operator(tree).print() == expected
	assert Operator(load(expected.removeprefix("@ontology A\n"))).print() == expected
	data = ontologyToJson(compact)
	assert data == ontologyToJson(tree)
	assert data["decls"][0]["def"]["values"] == [
		"Clothing", "Clothing/Shirts", "Food", "Food/Fruit", "Food/Fruit/Apple", "Food/Fruit/Pear",
	]
	_schemaValidator("ontology").validate(data)
	assert ontologyToJson(ontologyFromJson(data)) == data
	data["decls"][0]["def"]["values"] = ["Food/Fruit/Apple"]
	assert ontologyToJson(ontologyFromJson(data))["decls"][0]["def"]["values"] == ["Food", "Food/Fruit", "Food/Fruit/Apple"]


def testOrderedTreesPreserveSiblingFirstAppearanceAndAliases():
	ontology = load(
		"Category = Z/B/Leaf|A/C|Z/A {ordered, hierarchical}\n"
		"Alias = Category\nP\n  Value Alias\n  Copy P.Value\n"
	)
	expected = ["Z", "Z/B", "Z/B/Leaf", "Z/A", "A", "A/C"]
	model = Model(ontology)
	for type in (TypeExpr(path="A/Alias"), TypeExpr(path="A/P", attr="Copy")):
		resolved = model.resolveType(type)
		assert resolved.hierarchical and resolved.ordered
		assert resolved.values == expected
	assert ontologyToJson(ontology)["decls"][1]["def"]["values"] == expected
	assert "  Z\n    B\n      Leaf\n    A\n  A\n    C\n" in Operator(ontology).print()


def testInlineTaxonomiesDefaultsAndMapsUseAncestorPaths():
	ontology = load(
		"Category = |Food/Fruit/Apple {hierarchical}\nOther = |Plant/Apple {hierarchical}\n"
		"P\n  Value Category {default=Food/Fruit}\n"
		"  Inline Food/Fruit/Apple|Clothing/Shirts {hierarchical}\n"
		"@map Convert Category -> Other\n  Food/Fruit exact Plant\n  Food/Fruit/Apple exact Plant/Apple\n"
	)
	text = Operator(ontology).print()
	assert "Inline Clothing|Clothing/Shirts|Food|Food/Fruit|Food/Fruit/Apple {hierarchical}" in text
	assert ontologyToJson(ontologyFromJson(ontologyToJson(ontology))) == ontologyToJson(ontology)
	_schemaValidator("ontology").validate(ontologyToJson(ontology))
	assert "Food/Fruit exact Plant" in text


@pytest.mark.parametrize("body", [
	"Category = Food/Fruit|Clothing\n",
	"Category = |Food//Fruit {hierarchical}\n",
	"Category = |/Food {hierarchical}\n",
	"Category = |Food/ {hierarchical}\n",
	"Category = |Food-Fruit {hierarchical}\n",
	"Category = {hierarchical}\n",
	"Category = {hierarchical}\n  ...\n",
	"Category = {hierarchical}\n    Food\n",
	"Category = {hierarchical}\n  Food\n      Fruit\n",
	"Category = {hierarchical}\n  Food\n   Fruit\n",
	"Category = {hierarchical}\n  Food\n  Food\n",
	"Category = {hierarchical}\n  Food/Fruit\n",
	"Category = {hierarchical}\n  Food\n    ...\n",
	"Category = {hierarchical}\n  Food\n  ...\n  Clothing\n",
	"Category = Food|Clothing {hierarchical}\n  Fruit\n",
	"Category = Food|Clothing {hierarchical=no}\n",
	"Category = Text {hierarchical}\n",
	"Category =\n  Food\n    Fruit\n",
])
def testInvalidTaxonomiesAreRejected(body):
	with pytest.raises(FormatError):
		load(body)


@pytest.mark.parametrize("value", ["Food//Fruit", "/Food", "Food/", "Food-Fruit", ""])
def testInvalidJsonPathsAreNotRepaired(value):
	data = {
		"format": "onto.ontology/1", "namespace": "A",
		"decls": [{"kind": "type", "path": "A/Category", "def": {"values": [value], "open": False}, "ann": {"hierarchical": True}}],
	}
	with pytest.raises(FormatError):
		ontologyFromJson(data)


@pytest.mark.parametrize("openVocabulary", [False, True])
def testObservationsUseExactPathsAndRoundTrip(openVocabulary):
	body = "Category = |Food/Fruit/Apple" + ("|..." if openVocabulary else "") + " {hierarchical}\n"
	ontology = load(body + "Alias = Category\nP\n  * Categories Alias\n  Inline Food/Fruit|Other {hierarchical}\n")
	text = "@obs A\np:P\np.Categories [Food/Fruit, Food/Fruit/Apple]\np.Inline Food\n"
	log = loadObservations(ontology, Source("taxonomy.obs", text))
	assert [claim["v"] for claim in log.claims if claim.get("p") == "Categories"] == [{"set": ["Food/Fruit", "Food/Fruit/Apple"]}]
	data = observationsToJson(log)
	assert observationsToJson(observationsFromJson(ontology, data)) == data
	assert observationsToJson(loadObservations(ontology, Source("printed.obs", printObservationsLog(ontology, log))))["claims"] == data["claims"]
	for invalid in ("Apple", "Food//Fruit", "Food/", "/Food"):
		if invalid == "Apple" and openVocabulary:
			continue
		with pytest.raises(FormatError):
			loadObservations(ontology, Source("bad.obs", f"@obs A\np:P\np.Categories {invalid}\n"))
	newValue = "@obs A\np:P\np.Categories Other/New\n"
	if openVocabulary:
		assert loadObservations(ontology, Source("open.obs", newValue)).claims[-1]["v"] == "Other/New"
	else:
		with pytest.raises(FormatError):
			loadObservations(ontology, Source("closed.obs", newValue))


def testOpenTreeAndRepeatedLeafNames():
	ontology = load("Category = {hierarchical}\n  Food\n    Other\n  Clothing\n    Other\n  ...\n")
	assert Model(ontology).resolveType(TypeExpr(path="A/Category")).open
	assert Operator(ontology).print().endswith("  Food\n    Other\n  ...\n")


# EOF
