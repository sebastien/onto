"""Module: mapping reversal tests — reverse mappings, generated forms and lossy lines (spec-04 Reversal)."""

from __future__ import annotations

import asyncio

import pytest

from onto import Source, loadFunctions, loadMapping, loadOntology, mappingFromJson, mappingReverse, mappingToJson, printMapping
from onto.referential import loadReferential
from tests.helpers import specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
FINANCE = loadOntology([Source("finance.onto", specExample("spec-01-ontology"))])
SHEET = loadOntology([Source("sheet.onto", specExample("spec-04-mapping", 7))])
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", specExample("spec-04-mapping", 4))])
MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", specExample("spec-04-mapping", 5)), libraries=[MARKETS], referentials=[REFERENTIAL])
SHEET_MAPPING = loadMapping(FINANCE, SHEET, Source("finance-sheet.map", specExample("spec-04-mapping", 8)))
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


def collidingMaps():
	model = "Code = A|B\nWord = X|Y\nPerson\n  Code Code\n  Word Word\n  Other Word\n"
	source = loadOntology([Source("old.onto", "@ontology S rev=old\n" + model +
		"@map Convert Word -> Word\n  X exact Y\n  Y exact X\n")])
	target = loadOntology([Source("new.onto", "@ontology S rev=new\n" + model +
		"@map Convert Word -> Word\n  X exact X\n  Y exact Y\n")])
	mapping = loadMapping(source, target, Source("migration.map", """@mapping S -> S from=old to=new
@use S as Self
@map Convert Code -> Code
  A exact A
  B exact B
@fn Convert2 Text -> Text
  x => x

Person -> Person
  Code <- Convert(Code)
  Word <- Self/Convert(Word)
  Other <- Self/Convert(Other)
"""))
	return source, target, mapping


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


@pytest.mark.parametrize("expression", [
	'split(Tags, "")', 'join(split(Tags, ","), "")',
	'join(split(Tags, ""), ",")',
])
def test_empty_split_join_separator_is_statically_lossy(expression):
	target = loadOntology([Source("t", """@ontology RevT rev=v1
Human
  * Tags Text
""")]) if expression.startswith("split(") else TARGET
	mapping = loadMapping(SOURCE, target, Source("m", f"@mapping RevS -> RevT\nPerson -> Human\n  Tags <- {expression}\n"))
	reversed_, lossy = mappingReverse(mapping, SOURCE, target)
	assert not lines(reversed_)
	assert len(lossy) == 1 and "nonempty separator" in lossy[0].reason


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


def test_qualified_and_local_maps_with_the_same_name_get_distinct_inverses():
	source, target, mapping = collidingMaps()
	assert "Word <- Self/Convert(Word)" in printMapping(mapping)
	assert mappingToJson(mappingFromJson(source, target, mappingToJson(mapping))) == mappingToJson(mapping)
	reversed_, lossy = mappingReverse(mapping, source, target)
	assert not lossy
	inverses = {item.path: {line.fromValue: line.toValue for line in item.mapLines} for item in reversed_.maps}
	reverseLines = lines(reversed_)
	code, word, other = (reverseLines[field]["expr"]["call"] for field in ("Code", "Word", "Other"))
	assert code != word and word == other
	assert "Convert2" not in inverses
	assert inverses[code] == {"A": "A", "B": "B"}
	assert inverses[word] == {"X": "Y", "Y": "X"}


def test_same_name_inverses_execute_their_own_conversion_tables():
	pytest.importorskip("hexa.shapes")
	from hexa.runtime import run

	from onto import loadObservations, observationsToJson, reconcileObservations
	from onto.integrations.hexa import HexaMappingOperator

	source, target, mapping = collidingMaps()
	reversed_, _ = mappingReverse(mapping, source, target)
	ops = HexaMappingOperator(target, source)
	program = ops.compile(reversed_)
	log = loadObservations(target, Source("new.obs", "@obs S rev=new\np:Person\n  Code A\n  Word Y\n  Other X\n"))
	state = observationsToJson(reconcileObservations(target, log))
	raw = asyncio.run(run({"ClockRead": lambda context: "2026-11-18"}, program.stages.MappingRead, state))
	converted, report = ops.result(program, raw)
	assert not report.gaps
	assert {claim["p"]: claim["v"] for claim in converted.claims if "p" in claim} == {"Code": "A", "Word": "X", "Other": "Y"}


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


def test_derived_values_are_never_projected_back():
	"""A -> B -> A: a derived target, or a reverse assigning a derived input, is lossy."""
	source = loadOntology([Source("s.onto", "@ontology DerS rev=v1\nPerson\n  Name Text\n  ~ CanEdit Boolean <- Name {rule=?}\n")])
	target = loadOntology([Source("t.onto", "@ontology DerT rev=v1\nHuman\n  Name Text\n  Editable Boolean\n  ~ Label Text <- Name {rule=?}\n")])
	text = "@mapping DerS -> DerT\n\nPerson -> Human\n  Editable <- CanEdit\n  Label <- Name\n  Name <- Name\n"
	reversed_, lossy = mappingReverse(loadMapping(source, target, Source("m", text)), source, target)
	assert sorted((item.line, item.reason) for item in lossy) == [("Editable", "derived target, not written back"), ("Label", "derived target, not written back")]
	assert list(lines(reversed_)) == ["Name"]


# EOF
