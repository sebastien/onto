"""Module: store validation facts — what a store bundle's model adds for spec-02's strict validation (spec-08 "Store
bundle"), so that a store validates batches from its bundle alone."""

from __future__ import annotations

from onto import Source, loadOntology
from onto.ontology.facts import modelJson
from onto.ontology.model import Model
from tests.store import BUNDLE

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SHOP = loadOntology([Source("shop.onto", """@ontology Shop rev=2026-11-28

Currency = NZD|AUD
Size = Small|Large {ordered}
Colour = Warm/Red|Cool|... {hierarchical}
Use = Mobile|Home

Phone =
  1 Use Use {key}
  1 Number Text

Order
  At DateTime
  Total Amount {cur=?:Currency}
  Weight Number {unit=kg}
  Kind Text
  Sizes Range<Size>
  + Lines Text
  * Notes Text
  Shade Colour
  Card Text {one=Payment}
  Account Text {one=Payment}
  * Phones Phone
  Buyer Customer

Customer
  Name Text

Gift of Order {when=Kind:Gift}
  Message Text

Order -isFor/hasOrder-> Customer
Delivery(Order, Courier: Customer) {kind=event}
""")])
FACTS = modelJson(Model(SHOP), validation=True)
ORDER = FACTS["types"]["Shop/Order"]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testAttributesGiveTheirCardinalityTypeAndGroup() -> None:
	attrs = ORDER["attrs"]
	assert (attrs["Lines"]["card"], attrs["Notes"]["card"], attrs["At"]["card"]) == ("+", "*", "?")
	assert attrs["At"]["type"] == {"kind": "builtin", "builtin": "DateTime"}
	assert attrs["Buyer"]["type"] == {"kind": "entity", "path": "Shop/Customer"}
	assert attrs["Phones"]["type"] == {"kind": "struct", "path": "Shop/Phone"}
	assert attrs["Sizes"]["type"] == {"kind": "range", "element": {"kind": "vocab", "path": "Shop/Size", "vocab": "Shop/Size", "ordered": True}}
	assert (attrs["Card"]["one"], attrs["Account"]["one"], "one" in attrs["At"]) == ("Payment", "Payment", False)


def testVocabulariesAreListedOnceWithTheirValues() -> None:
	assert FACTS["vocabs"]["Shop/Size"] == {"values": ["Small", "Large"], "open": False}
	# NOTE: A hierarchical vocabulary lists each value's ancestors too, under a key of its own.
	shade = ORDER["attrs"]["Shade"]["type"]
	assert (shade["vocab"], shade["hierarchical"]) == ("Shop/Colour~hierarchical", True)
	assert FACTS["vocabs"]["Shop/Colour~hierarchical"] == {"values": ["Cool", "Warm", "Warm/Red"], "open": True}


def testQualifiersNameTheVocabularyTheirValuesComeFrom() -> None:
	total = ORDER["attrs"]["Total"]
	assert (total["qualifiers"], total["qualifierVocabs"]) == ({"cur": "?"}, {"cur": "Shop/Currency"})
	assert FACTS["vocabs"]["Shop/Currency"] == {"values": ["NZD", "AUD"], "open": False}
	assert ORDER["attrs"]["Weight"]["qualifiers"] == {"unit": "kg"}


def testDeclarationsSayWhatValidationNeeds() -> None:
	assert FACTS["rev"] == "2026-11-28"
	assert (FACTS["types"]["Shop/Delivery"].get("event"), ORDER.get("event")) == (True, None)
	assert FACTS["structs"]["Shop/Phone"]["key"] == "Use"
	gift, = FACTS["facets"]["Shop/Order"]
	assert gift["when"] == {"attr": "Kind", "value": "Gift"}


def testWithoutValidationTheFactsAreTheViewBundlesOnes() -> None:
	plain = modelJson(Model(SHOP))
	assert "vocabs" not in plain and "card" not in plain["types"]["Shop/Order"]["attrs"]["Lines"]


def testAStoreBundleCarriesTheValidationFacts() -> None:
	model = BUNDLE["model"]
	assert "vocabs" in model and model["types"]["Finance/IdentityCheck"]["event"] is True
	assert model["types"]["Finance/Person"]["attrs"]["Phones"]["card"] == "*"


# EOF
