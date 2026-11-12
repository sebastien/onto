"""Module: mapping reversal tests — reverse mappings, generated forms and lossy lines (spec-04 Reversal)."""

from __future__ import annotations

from onto import Source, loadFunctions, loadMapping, loadOntology, mappingReverse, mappingToJson
from onto.referential import loadReferential
from tests._helpers import _specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", _specExample("spec-04-mapping", 1))])
FINANCE = loadOntology([Source("finance.onto", _specExample("spec-01-ontology"))])
SHEET = loadOntology([Source("sheet.onto", _specExample("spec-04-mapping", 7))])
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", _specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", _specExample("spec-04-mapping", 4))])
MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", _specExample("spec-04-mapping", 5)), libraries=[MARKETS], referentials=[REFERENTIAL])
SHEET_MAPPING = loadMapping(FINANCE, SHEET, Source("finance-sheet.map", _specExample("spec-04-mapping", 8)))
SOURCE = loadOntology([Source("s.onto", """@ontology RevS rev=v1
Code = X|Y
Kind = A|B
Person
  Born Date
  Code Code
  Label Text
  Name Text
  Owner Person
  Seconds Integer
  Tags Text
  Stamp Text
Person -knows/knownBy-> Person
""")])
TARGET = loadOntology([Source("t.onto", """@ontology RevT rev=v1
Kind = A|B
Human
  Born Date
  Key Text {key}
  Kind Kind
  Label Text
  OwnerName Text
  OwnerKey Text
  Stamp Text
  Tags Text
  When Date
Human -knows/knownBy-> Human
""")])


def reverse(body: str, header: str = "", maps: str = ""):
	text = f"@mapping RevS -> RevT{header}\n{maps}\nPerson -> Human\n{body}"
	mapping = loadMapping(SOURCE, TARGET, Source("m", text))
	return mappingReverse(mapping, SOURCE, TARGET)


def lines(mapping):
	return {line.get("target") or line.get("verb"): line for line in mappingToJson(mapping)["scopes"][0].get("lines", [])}


# -----------------------------------------------------------------------------
#
# SPEC EXAMPLES
#
# -----------------------------------------------------------------------------


def test_reverse_of_exchange_finance_loses_what_the_spec_lists():
	reversed_, lossy = mappingReverse(MAPPING, EXCHANGE, FINANCE, [MARKETS], referential="MarketIdsReverse")
	data = mappingToJson(reversed_)
	assert (data["from"], data["to"], data["header"]) == ("Finance", "Exchange", {"from": "2026-11-10", "to": "2026-11-10", "referential": "MarketIdsReverse"})
	assert {(item.target, item.line) for item in lossy} == {
		("Finance/Dividend", "Amount"), ("Finance/Dividend", "Payer"), ("Finance/Instrument", "[Bond]"),
		("Finance/Instrument", "AssetClass"), ("Finance/Instrument", "Bond.CouponRate"),
		("Finance/Instrument", "Bond.InterestFrequency"), ("Finance/Instrument", "Bond.MaturityDate"),
	}
	scopes = {scope["source"]: scope for scope in data["scopes"]}
	instrument = {line["target"]: line["expr"] for line in scopes["Finance/Instrument"]["lines"]}
	assert instrument == {"Code": {"path": ["Code"]}, "Isin": {"path": ["Isin"]}, "Issuer": {"path": ["issuedBy"]}, "Name": {"path": ["Name"]}}
	assert scopes["Finance/Company"]["target"] == "Exchange/Issuer"


def test_reverse_of_finance_sheet_keeps_the_instrument_through_its_key():
	reversed_, lossy = mappingReverse(SHEET_MAPPING, FINANCE, SHEET)
	scope = mappingToJson(reversed_)["scopes"][0]
	assert (scope["source"], scope["target"], scope["valid"]) == ("Sheet/PositionRow", "Finance/Trade", {"path": ["Date"]})
	assert {line["target"]: line["expr"] for line in scope["lines"]} == {
		"Instrument": {"call": "ref", "args": [{"path": ["Finance/Instrument"]}, {"path": ["Isin"]}]},
		"Quantity": {"path": ["Quantity"]}, "Side": {"path": ["Side"]},
	}
	assert sorted(item.line for item in lossy) == ["AssetClass", "Name", "Value"]


def test_reversal_does_not_mutate_its_input():
	before = mappingToJson(MAPPING)
	mappingReverse(MAPPING, EXCHANGE, FINANCE, [MARKETS])
	assert mappingToJson(MAPPING) == before


# -----------------------------------------------------------------------------
#
# LINE FORMS
#
# -----------------------------------------------------------------------------


def test_spelling_functions_and_builtin_inverses_reverse():
	reversed_, lossy = reverse('  Born <- date(Stamp, "YYYYMMDD")\n  Label <- trim(Label)\n  When <- date(Seconds)\n  Tags <- join(split(Tags, ","), ";")\n')
	got = lines(reversed_)
	assert got["Stamp"]["expr"] == {"call": "format", "args": [{"path": ["Born"]}, {"text": "YYYYMMDD"}]}
	assert got["Label"]["expr"] == {"path": ["Label"]}
	assert got["Seconds"]["expr"] == {"call": "epoch", "args": [{"path": ["When"]}]}
	assert got["Tags"]["expr"] == {"call": "join", "args": [{"call": "split", "args": [{"path": ["Tags"]}, {"text": ";"}]}, {"text": ","}]}
	assert lossy == []


def test_incomplete_date_formats_and_other_functions_are_lossy():
	_, lossy = reverse('  Born <- date(Stamp, "YYYYMMDD")\n  Stamp <- format(Born, "YYYY-MM")\n  Label <- concat(Name, Label)\n  OwnerName <- Name ?? Label\n  Tags <- "x"\n')
	assert {item.line: item.reason for item in lossy}.keys() == {"Stamp", "Label", "OwnerName", "Tags"}


def test_maps_reverse_only_when_exact_and_one_to_one():
	maps = "@map Kinds Code -> Kind\n  X exact A\n  Y exact B\n"
	reversed_, lossy = reverse("  Kind <- Kinds(Code)\n", maps=maps)
	assert lines(reversed_)["Code"]["expr"] == {"call": "Kinds", "args": [{"path": ["Kind"]}]}
	assert [(line.mapFrom, line.mapTo, [(item.fromValue, item.toValue) for item in line.mapLines]) for line in reversed_.maps] == [
		("RevT/Kind", "RevS/Code", [("A", "X"), ("B", "Y")])]
	_, lossy = reverse("  Kind <- Kinds(Code)\n", maps="@map Kinds Code -> Kind\n  X exact A\n  Y exact A\n")
	assert [item.line for item in lossy] == ["Kind"]


def test_references_reverse_through_keys_or_reverse_annotations():
	reversed_, lossy = reverse("  Key <- Name\n  OwnerKey <- Owner.Name\n  OwnerName <- Owner.Label {reverse}\n  Label <- Owner.Code\n")
	got = lines(reversed_)
	assert got["Name"]["expr"] == {"path": ["Key"]}
	assert got["Owner.Label"]["expr"] == {"path": ["OwnerName"]}
	# Owner.Name is not a key of Person, so it is lossy without {reverse}.
	assert sorted(item.line for item in lossy) == ["Label", "OwnerKey"]


def test_conditions_reverse_through_direct_lines_only():
	reversed_, lossy = reverse("  Label <- Label {when=Code:X}\n  Stamp <- Stamp {when=Name:a}\n  OwnerName <- Name\n")
	got = lines(reversed_)
	assert got["Stamp"]["when"] == {"path": ["OwnerName"], "value": "a"}
	assert [item.line for item in lossy] == ["Label"]
	reversed_, lossy = reverse("  Label <- Label\n", header="", maps="")
	assert lossy == []


def test_verbs_and_valid_reverse():
	reversed_, lossy = reverse("  knows <- knows\n  When <- $valid\n  Label <- $at\n")
	data = mappingToJson(reversed_)["scopes"][0]
	assert data["valid"] == {"path": ["When"]}
	assert data["lines"] == [{"verb": "knows", "expr": {"path": ["knows"]}}]
	assert [item.line for item in lossy] == ["Label"]


def test_scope_conditions_that_cannot_reverse_lose_the_scope():
	text = "@mapping RevS -> RevT\n\nPerson -> Human {when=Code:X}\n  Label <- Label\n"
	mapping = loadMapping(SOURCE, TARGET, Source("m", text))
	reversed_, lossy = mappingReverse(mapping, SOURCE, TARGET)
	assert reversed_.scopes == [] and [item.line for item in lossy] == ["Label"]


# EOF
