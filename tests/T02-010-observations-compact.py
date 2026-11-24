"""Module: compact observation tests — claim-neutral blocks and lossless local handle spellings."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, formatObservations, loadObservations, loadOntology, observationsFromJson, observationsToJson, printObservationsCompact, printObservationsLog


MODEL = loadOntology([Source("model.onto", """@ontology A
Person
  Name Text
  Code Adult|...
  * Peers Person
  Pay Amount {cur=?}
Family
  Name Text
Family -hasMember/memberOf-> Person
  Role Text
Membership(Group: Family, Member: Person)
Scenario
Estimate of Person {ctx=Scenario}
  Included Boolean
""")])
HEADER = "@obs A at=2026-01-01 by=import\n@src x=fixture:one y=fixture:two\n@scope shared\n"


def load(body: str, mode: str = "strict"):
	return loadObservations(MODEL, Source("sample.obs", HEADER + body), mode)


def testEntityBlocksExpandToExactlyTheOriginalClaimsAndRegistry():
	compact = """@src x
@entity person1=Source_Client_First Person
  Name family1
  Code family1
  Peers [person2, ...]
@entity Source_Membership_123 Membership
  Group family1
  Member person1
@src y
@entity family1=Source_Family_45 Family
  Name person1
  -> hasMember person1
@entity person2=Source_Client_Second Person
  Name Second
"""
	flat = """@src x
Source_Client_First:Person.Name family1
Source_Client_First.Code family1
Source_Client_First.Peers [Source_Client_Second:Person, ...]
Source_Membership_123:Membership.Group Source_Family_45:Family
Source_Membership_123.Member Source_Client_First
@src y
Source_Family_45.Name person1
Source_Family_45 hasMember Source_Client_First
Source_Client_Second.Name Second
"""
	log = load(flat)
	assert load(compact) == log
	assert not any(c.get("exists") for c in log.claims)
	text = printObservationsCompact(MODEL, log)
	assert all(text.count(h) == 1 for h in log.instances)
	assert "  -> hasMember person1\n" in text
	assert "@entity Source_Membership_123 Membership\n  Group family1\n  Member person1" in text
	assert loadObservations(MODEL, Source("compact.obs", text)) == log
	assert formatObservations(MODEL, Source("compact.obs", text), "compact") == text


def testMixedLogKeepsRetractionsNamedLinksContextsAndTiedStatementsInOrder():
	log = load("""@type person1 Person
@entity p=Long_Person_Handle Person
  Name First
  Pay 99.5 {cur=USD}
  -> memberOf ?
@ctx sc
p[Estimate]
p.Estimate.Included false
@ctx none
p.Estimate.Included true {ctx=sc}
link: f hasMember p
@entity link=Long_Link_Handle Family.hasMember.Person
  Role p
@entity f=Long_Family_Handle Family
  Name Family
@entity sc=Long_Scenario_Handle Scenario
@src y
p = other:Person
- link
- p.Name First
@entity p Person
  Name Second
  Name Third
""")
	flat = printObservationsLog(MODEL, log)
	text = printObservationsCompact(MODEL, log)
	assert "@entity person2=Long_Person_Handle Person" in text  # person1 is already a canonical handle.
	assert "- person2.Name First" in text and "  -> memberOf ?" in text
	replayed = loadObservations(MODEL, Source("compact.obs", text))
	assert replayed == loadObservations(MODEL, Source("flat.obs", flat))
	assert printObservationsLog(MODEL, replayed) == flat
	assert printObservationsCompact(MODEL, replayed) == text


def testRepeatedReferenceOnlyTargetGetsOneDeclarationAndNoExistenceClaim():
	handle = "A_Long_Scoped_Handle_That_Appears_Only_In_References"
	log = load(f"m1:Membership.Member {handle}:Person\nm2:Membership.Member {handle}\nm3:Membership.Member {handle}\n")
	text = printObservationsCompact(MODEL, log)
	assert text.count(handle) == 1 and f"@entity person1={handle} Person\n" in text
	assert text.count(".Member person1\n") == 3
	assert loadObservations(MODEL, Source("refs.obs", text)) == log


@pytest.mark.parametrize("body", [
	"@entity x=one Person\n@entity x=two Person",
	"@entity x=y Person\n@entity y=z Person",
	"@type x Person\n@entity x=long Person",
	"@entity x=x Person",
	"@entity p Person {src=x}",
	"@entity none=p Person",
	"@entity p= Person",
	"@entity p Unknown",
	"@entity p Person\n  -> = q",
	"@entity p Person\n@src x\n  Name Dangling",
	"@type p Person\n  Name NotABlock",
])
def testInvalidBlocksAndAmbiguousDeclarationsAreFatalEvenInLenientMode(body: str):
	with pytest.raises(FormatError):
		load(body + "\n", "lenient")


def testGapJsonKeepsRawCompactLineAndReplaysWithOnlyCanonicalHandles():
	log = load("""@entity f=Long_Family Family
@entity p=Long_Person Person
  Peers [p, f] // includes a family
  -> unknown f
- p.Unknown p
""", "lenient")
	assert [g.text for g in log.gaps] == [
		"Long_Person.Peers [Long_Person, Long_Family]", "Long_Person unknown Long_Family", "- Long_Person.Unknown p"]
	assert log.gaps[0].raw == "  Peers [p, f] // includes a family"
	data = observationsToJson(log)
	assert observationsToJson(observationsFromJson(MODEL, data, mode="lenient")) == data
	with pytest.raises(ValueError, match="gaps"):
		printObservationsCompact(MODEL, log)


# EOF
