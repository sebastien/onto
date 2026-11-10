"""Module: ontology parsing tests — parsing, validation and normal form (spec-01)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from onto.ontology import Model, TypeExpr, formatOntology, loadOntology
from onto.text import FormatError, Source

# -----------------------------------------------------------------------------
#
# HELPERS
#
# -----------------------------------------------------------------------------

SPEC = (Path(__file__).parent.parent / "docs/specs/spec-01-ontology.md").read_text()
# NOTE: The first `text` block of spec-01 is the complete example; later blocks are snippets.
EXAMPLE = re.findall(r"```text\n(.*?)```", SPEC, re.S)[0]
HEAD = "@ontology A\n@use Dimensions as D\n"


def load(*texts: str):
	return loadOntology([Source(f"t{index}.onto", text) for index, text in enumerate(texts)])


def fmt(text: str) -> str:
	return formatOntology([Source("t.onto", text)])


def errors(*texts: str) -> list[str]:
	try:
		load(*texts)
	except FormatError as error:
		return [item.code for item in error.diagnostics if item.level == "error"]
	return []


def decl(ontology, path: str):
	return next(item for item in ontology.decls if item.path == path)


def withoutComments(text: str) -> str:
	lines = (re.sub(r"\s+//.*$|^//.*$", "", line) for line in text.split("\n"))
	return re.sub(r"\n{3,}", "\n\n", "\n".join(re.sub(r"\s+-- ", " -- ", line) for line in lines))


# -----------------------------------------------------------------------------
#
# SPEC EXAMPLE
#
# -----------------------------------------------------------------------------


def testExampleIsInNormalFormExceptCommentsAndDocAlignment():
	assert fmt(EXAMPLE) == withoutComments(EXAMPLE).strip("\n") + "\n"


def testExampleResolvesPaths():
	ontology = load(EXAMPLE)
	assert ontology.namespace == "Finance"
	assert decl(ontology, "Finance/Person").base == "Finance/Party"
	assert decl(ontology, "Finance/Investing/Investor").subject == "Finance/Person"
	assert decl(ontology, "Dimensions/Money/USD").definition == TypeExpr(builtin="Amount")
	household = decl(ontology, "Finance/Household.hasMember.Finance/Person")
	assert [item.role for item in household.participants] == ["Household", "Person"]


def testSnippetsLoadWithTheExample():
	extra = (
		"Income(Payer: Party, Recipient: + Person)\n  Amount D/Money/USD\n"
		"Planning/Scenario\n  Name Text\n"
		"Planning/IncomeTreatment of Income {ctx=Planning/Scenario}\n  IsIncluded Boolean\n  ShadingPercent Percent {scale=100}\n"
		"Person -directs/directedBy-> Company {context=Directorship, subjectRole=Director, objectRole=Company}\n"
		"@view IssuerProfile\n  Company.Code\n  Company.issues\n  Directorship\n  Dividend\n  Instrument[Bond]\n"
	)
	assert errors(EXAMPLE + extra) == []


def testLocationsPointAtSourceLines():
	with pytest.raises(FormatError) as raised:
		load("@ontology A\nPerson\n  Name Missing\n")
	assert [(item.loc.file, item.loc.line) for item in raised.value.diagnostics] == [("t0.onto", 3)]


# -----------------------------------------------------------------------------
#
# NORMAL FORM
#
# -----------------------------------------------------------------------------


def testNormalFormSortsStripsDefaultsAndComments():
	text = (
		"@ontology A card=? rel=*:*\n// comment\nPerson -- A person\n  ? Name Text\n  Email Text {src=X, key}\n"
		"  Status B | A | C\nHousehold -hasMember-> Person *:*\nOrg\nHousehold\nDoc\n"
	)
	out = fmt(text)
	assert out == (
		"@ontology A card=? rel=*:*\n\nDoc\nHousehold\nOrg\n\nPerson -- A person\n  Email Text {key, src=X}\n"
		"  Name Text\n  Status A|B|C\n\nHousehold -hasMember-> Person\n"
	)
	assert fmt(out) == out


def testNamesPrintRelativeOrThroughAliases():
	out = fmt(f"{HEAD}@use Dimensions/Money as M\nD/Money/USD = Amount {{cur=USD}}\nD/Rate = Percent\nPerson\n  Income D/Money/USD\n  Rate D/Rate\n")
	assert "M/USD = Amount {cur=USD}" in out
	assert "  Income M/USD" in out
	assert "  Rate D/Rate" in out


def testVocabularyForms():
	out = fmt("@ontology A\nT1 = |Only\nT2 = B|A|...\nT3 = ...\nT4 = Low|High {ordered}\nP\n  S High|Low {ordered}\n")
	assert "T1 = |Only\nT2 = A|B|...\nT3 = ...\nT4 = Low|High {ordered}" in out
	assert "  S High|Low {ordered}" in out


def testRelationsNaryAndBinary():
	text = "@ontology A\n\nParty\nPerson < Party\nProperty\n\nPurchase(Buyer: + Person, Property, Seller: * Party) {kind=event}\n  Price Amount\n"
	assert fmt(text) == text
	relation = decl(load("@ontology A\nPerson\nPerson -knows-> Person\n"), "A/Person.knows.A/Person")
	assert [item.role for item in relation.participants] == ["Subject", "Object"]


def testAssociationParticipantsSortAndFacetsFollow():
	base = "@ontology A\nPerson\nOrg\nIncome(Recipient: + Person, Payer: Org)\n  Gross Amount\n"
	assert fmt(f"{base}Lending/Servicing of Income\nZ\n") == (
		"@ontology A\n\nOrg\nPerson\nZ\n\nIncome(Payer: Org, Recipient: + Person)\n  Gross Amount\n\nLending/Servicing of Income\n"
	)


def testDomainsMapsAndAnnotations():
	text = (
		"@ontology A\n@use Dimensions as D\n@domain Society -- People\n@domain Money\n"
		"D/Society/Freq = Weekly|Fortnightly|Monthly\nD/Money/Basis = Monthly|Yearly\nSociety/Person\n"
		"  Email Text {privacy=Owner+Adviser, id=key, key}\nMoney/Org\n"
		"Money/Employment(Employee: Society/Person, Employer: Money/Org) {kind=state}\n"
		"Society/Person -employedBy/employs-> Money/Org {context=Money/Employment}\n"
		"@map Money/FreqToBasis D/Society/Freq -> D/Money/Basis {rule=x26} -- conv\n"
		"  Weekly broader Monthly\n  Monthly exact Monthly\n  Fortnightly broader Monthly -- approx\n"
	)
	out = fmt(text)
	assert out == (
		"@ontology A\n@use Dimensions as D\n\n@domain Money\n@domain Society -- People\n\n"
		"D/Money/Basis = Monthly|Yearly\nD/Society/Freq = Fortnightly|Monthly|Weekly\n\n"
		"Money/Org\n\nSociety/Person\n  Email Text {key, id=key, privacy=Adviser+Owner}\n\n"
		"Money/Employment(Employee: Society/Person, Employer: Money/Org) {kind=state}\n"
		"Society/Person -employedBy/employs-> Money/Org {context=Money/Employment}\n\n"
		"@map Money/FreqToBasis D/Society/Freq -> D/Money/Basis {rule=x26} -- conv\n"
		"  Fortnightly broader Monthly -- approx\n  Monthly exact Monthly\n  Weekly broader Monthly\n"
	)
	assert fmt(out) == out
	ontology = load(text)
	assert next(item for item in ontology.decls if item.arrow).ann == [("context", "A/Money/Employment")]
	assert decl(ontology, "A/Money/FreqToBasis").mapFrom == "Dimensions/Society/Freq"


def testDependenciesSortInputsFirstAndEllipsisLast():
	out = fmt("@ontology A\nP\n  B Date\n  A Date\n  ~ X Number <- B, $AsOf, A, ...\n")
	assert "  ~ X Number <- $AsOf, A, B, ..." in out


def testContextualFacetsPrintShortest():
	text = (
		f"{HEAD}Person\nD/Review\nAssessment(Person, D/Review)\n"
		"Servicing of Person {src=X, ctx=Assessment}\n  IsIncluded Boolean\nRating of Person {ctx=D/Review}\n"
	)
	out = fmt(text)
	assert "Servicing of Person {ctx=Assessment, src=X}" in out
	assert "Rating of Person {ctx=D/Review}" in out
	assert fmt(out) == out
	assert decl(load(text), "A/Rating").ann == [("ctx", "Dimensions/Review")]


def testViewsSelectBinaryRelationsByPath():
	text = f"{HEAD}H\nD/P\nH -has-> D/P\n@view V\n  H.has.D/P\n  H.has\n"
	assert errors(text) == []
	out = fmt(text)
	assert "  H.has\n  H.has.D/P\n" in out
	assert fmt(out) == out
	assert errors(f"{HEAD}H\nD/P\nH -has-> D/P\n@view V\n  H.has.H\n") == ["reference"]
	assert errors("@ontology A\nH\nP\nH -has/of-> P\n@view V\n  P.of\n") == []


# -----------------------------------------------------------------------------
#
# MODEL
#
# -----------------------------------------------------------------------------


def testFacetsAreAddressedThroughTheirSubject():
	model = Model(load("@ontology A\nPerson\n  Name Text\nLending/Borrower of Person\n  Status Active|Closed\nEmployee < Person\n"))
	assert model.lookup("A/Person", "Borrower.Status").name == "Status"
	assert model.lookup("A/Employee", "Borrower.Status").name == "Status"
	assert model.lookup("A/Person", "Status") is None


def testStructuresAreReachableThroughAttributePaths():
	model = Model(load("@ontology A\nName =\n  Surname Text\nPerson\n  Name Name\n"))
	assert model.lookup("A/Person", "Name.Surname").name == "Surname"


def testQualifiersInheritThroughAliasesAndReuse():
	model = Model(load("@ontology A\nMoney = Amount {cur=?}\nSalary = Money {cur=USD, period=Year}\nPerson\n  Pay Salary\n  Other Person.Pay\n"))
	resolved = model.resolveType(TypeExpr(path="A/Salary"))
	assert (resolved.kind, resolved.builtin, resolved.qualifiers) == ("builtin", "Amount", {"cur": "USD", "period": "Year"})
	assert model.resolveType(TypeExpr(path="A/Person", attr="Other")).qualifiers["cur"] == "USD"


def testAssociationsHaveFacetsAndRolesActAsAttributes():
	base = "@ontology A\nPerson\nOrg\nIncome(Recipient: + Person, Payer: Org)\n  Gross Amount\n"
	model = Model(load(f"{base}Lending/Servicing of Income\n  IsIncluded Boolean\n@view V\n  Income[Servicing]\n  Income.Servicing.IsIncluded\n"))
	assert model.lookup("A/Income", "Servicing.IsIncluded").name == "IsIncluded"
	assert model.lookup("A/Income", "Payer").type == TypeExpr(path="A/Org")
	assert list(model.facets("A/Income")) == ["Servicing"]
	assert model.lineage("A/Income") == ["A/Income"]


# -----------------------------------------------------------------------------
#
# ERRORS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
	("text", "code"),
	[
		("Person\n", "header"),
		("@ontology A\n@ontology A\n", "header"),
		("@ontology A colour=red\n", "header"),
		("@ontology A card=2\n", "header"),
		("@ontology A\n@frob X\n", "directive"),
		("@ontology A\nPerson\n   Name Text\n", "indent"),
		("@ontology A\nPerson\n Name Text\n", "indent"),
		("@ontology A\nPerson\n\tName Text\n", "indent"),
		("@ontology A\n  Name Text\n", "indent"),
		("@ontology A\r\nPerson\r\n", "syntax"),
		("@ontology A\nPerson\n  Name Text {a=b c}\n", "annotation"),
		("@ontology A\nPerson\n  Name Text {key, key}\n", "annotation"),
		("@ontology A\nPerson\n  Name Missing\n", "reference"),
		("@ontology A\nPerson\nPerson\n", "duplicate"),
		("@ontology A\nPerson\n  Name Text\n  Name Text\n", "duplicate"),
		("@ontology A\nPerson\n  ~ Age Number\n", "derived"),
		("@ontology A\nPerson\n  Age Number <- Dob\n", "derived"),
		("@ontology A\nPerson\n  ~ Age Number <- Dob\n", "reference"),
		("@ontology A\nPerson\n  ~ Age Number <- ..., Dob\n", "derived"),
		("@ontology A\nPerson\n  Name Text {colour=red}\n", "annotation"),
		("@ontology A\nPerson\n  Borrower Text\nBorrower of Person\n", "collision"),
		("@ontology A\nA1 = B1\nB1 = A1\n", "cycle"),
		("@ontology A\nT = T\n", "cycle"),
		("@ontology A\nPerson < Person\n", "cycle"),
		("@ontology A\nP < Q\nQ < P\n", "cycle"),
		("@ontology A\nH\nP\nH -has/of-> P\nP -of-> H\n", "collision"),
		("@ontology A\nText = Number\n", "reserved"),
		("@ontology A\nP\nQ\nP -has-> Q\nP -has-> Q\n", "duplicate"),
		("@ontology A\nP\nR(P)\n", "relation"),
		("@ontology A\nP\nR(P, Q)\n", "reference"),
		("@ontology A\nP\nR(X: P, X: P)\n", "duplicate"),
		("@ontology A\nP\nQ\nR(P, Q)\n  P Text\n", "collision"),
		("@ontology A\nP\n@view V\n  P[Missing]\n", "reference"),
		("@ontology A\nP\nQ\nP -Has-> Q\n", "name"),
		("@ontology A\nP\nQ\nP -has-> Q 2:*\n", "syntax"),
		("@ontology A\nT = A|B|A\n", "vocabulary"),
		("@ontology A\nT = A|b c\n", "vocabulary"),
		("@ontology A\nT = Text\n  F Text\n", "syntax"),
		("@ontology A\nP\n  E Text {id=yes}\n", "annotation"),
		("@ontology A\nP\n  E Text {privacy=Owner+Owner}\n", "annotation"),
		("@ontology A\nP\n  E Text {scale=10}\n", "annotation"),
		("@ontology A\nP\nQ\nP -has-> Q {context=Missing}\n", "reference"),
		("@ontology A\nP\nQ\nP -has-> Q\nP -of-> Q {context=P.has.Q}\n", "name"),
		("@ontology A\nP\nQ\nP -of-> Q {context=P}\n", "reference"),
		("@ontology A\nPerson\nF of Person {ctx=Missing}\n", "reference"),
		("@ontology A\nPerson\nT = Text\nF of Person {ctx=T}\n", "reference"),
		("@ontology A\nP\nQ\nP -has-> Q\nF of P.has.Q\n", "name"),
		("@ontology A\n@domain A/B\n", "name"),
		("@ontology A\n@domain S\n@domain S\n", "duplicate"),
		("@ontology A\n@use Dimensions as D\n@use Other as D\n", "duplicate"),
		("@ontology A\nP\n  Name Other/Thing\n", "reference"),
	],
)
def testErrors(text: str, code: str):
	assert code in errors(text)


def testSharedVerbsNeedUnrelatedTypes():
	assert errors("@ontology A\nP\nQ\nR\nP -has-> Q\nP -has-> R\n") == []
	assert "collision" in errors("@ontology A\nP\nQ\nR < Q\nP -has-> Q\nP -has-> R\n")
	assert "collision" in errors("@ontology A\nP\nS < P\nQ\nP -has-> Q\nS -has-> Q\n")
	assert errors("@ontology A\nP\nP -partnerOf/partnerOf-> P\n") == []


def testMaps():
	types = "@ontology A\nF = W|M\nB = M|Y\nN = Text\nO = M|...\n"
	assert errors(f"{types}@map X F -> B\n  W broader M\n") == []
	assert errors(f"{types}@map X F -> O\n  W broader M\n") == []
	assert "reference" in errors(f"{types}@map X F -> N\n")
	assert "reference" in errors(f"{types}@map X F -> Missing\n")
	assert "reference" in errors(f"{types}@map X F -> B\n  Q broader M\n")
	assert "syntax" in errors(f"{types}@map X F -> B\n  W wider M\n")
	assert "duplicate" in errors(f"{types}@map X F -> B\n  W broader M\n  W exact M\n")
	assert "annotation" in errors(f"{types}@map X F -> B {{kind=event}}\n")
	assert "syntax" in errors(f"{types}@map X F B\n")


def testAssociationsAsParticipantsObjectsAndTypes():
	base = "@ontology A\nP\nQ\nE(P, Q)\n"
	assert errors(f"{base}V(E, Verifier: P) {{kind=event}}\n") == []
	assert errors(f"{base}V(E, Verifier: P)\nP -verifies-> E {{context=V}}\n") == []
	assert errors(f"{base}V(P, Q)\n  Job E\n") == []
	assert "name" in errors(f"{base}P -has-> Q\nV(P.has.Q, P)\n")
	assert "reference" in errors(f"{base}P -has-> Q\nV(P, Q)\n  Link P.has.Q\n")


def testContextRoleSelectors():
	base = "@ontology A\nPerson\nCompany\nDirectorship(Company, Director: Person, Members: * Person)\n"
	assert errors(f"{base}Person -directs-> Company {{context=Directorship, subjectRole=Director, objectRole=Company}}\n") == []
	assert "reference" in errors(f"{base}Person -directs-> Company {{context=Directorship, subjectRole=Company}}\n")
	assert "reference" in errors(f"{base}Person -knows-> Person {{context=Directorship, subjectRole=Director, objectRole=Director}}\n")
	assert errors(f"{base}Person -knows-> Person {{context=Directorship, subjectRole=Members, objectRole=Members}}\n") == []


def testFacetCollisions():
	base = "@ontology A\nPerson\nInvestor of Person\nClient < Person\n"
	assert "collision" in errors(f"{base}  Investor Text\n")
	assert "collision" in errors(f"{base}X/Investor of Client\n")
	assert "collision" in errors("@ontology A\nP\nX/F of P\nY/F of P\n")
	assert errors("@ontology A\nP\nF of P\n  N Text\nG of P\n  N Text\n") == []
	assert "collision" in errors("@ontology A\nP\nQ\nI(Owner: P, Q)\nX/Owner of I\n")


def testAttributeReuseCyclesAreErrorsNotHangs():
	assert "cycle" in errors("@ontology A\nP\n  A P.B\n  B P.A\n")
	assert "cycle" in errors("@ontology A\nT = P.A\nP\n  A T\n")
	assert errors("@ontology A\nP\n  A P.A.X\n") != []
	assert errors("@ontology A\nP\n  A Text\n  B P.A\n") == []


def testMeasurementQualifiersMustNotContradict():
	base = "@ontology A\nMoney = Amount {cur=USD}\nAny = Amount {cur=?}\n"
	assert errors(f"{base}P\n  Pay Money\n  Fee Any {{cur=EUR}}\n  Tip Money {{cur=USD}}\n") == []
	assert "qualifier" in errors(f"{base}P\n  Pay Money {{cur=EUR}}\n")
	assert "qualifier" in errors(f"{base}Euro = Money {{cur=EUR}}\n")
	assert "qualifier" in errors(f"{base}P\n  Pay Money\n  Fee P.Pay {{cur=EUR}}\n")


def testAnnotationPlacement():
	assert "annotation" in errors("@ontology A\nP {key}\n")
	assert "annotation" in errors("@ontology A\nP\n  N Text {kind=event}\n")
	assert "annotation" in errors("@ontology A\nP\n  N Text {ordered}\n")
	assert "annotation" in errors("@ontology A\nP\n  N Text {rule=x}\n")
	assert "annotation" in errors("@ontology A\nP\nQ\nR(P, Q) {context=R}\n")
	assert "annotation" in errors("@ontology A\nP\nF of P {kind=event}\n")
	assert "annotation" in errors("@ontology A\nT = Text {elided=3}\n")
	assert errors("@ontology A\nT = A|B {elided=3, src=x, check=q}\nP {status=assumed}\n  N A|B {ordered}\n  ~ M Number <- N {deps=candidate, rule=?}\n") == []


def testViews():
	base = "@ontology A\nP\n  N Text\nF of P\n  M Text\n"
	assert errors(f"{base}@view V\n  P[F]\n  P.N\n  P.F.M\n  P[*]\n@view W\n  V\n") == []
	assert "cycle" in errors(f"{base}@view V\n  W\n@view W\n  V\n")
	assert "cycle" in errors(f"{base}@view V\n  V\n")
	assert "reference" in errors(f"{base}@view V\n  P.Missing\n")
	assert "reference" in errors(f"{base}@view V\n  P\n@view W\n  V[F]\n")
	assert "reference" in errors(f"{base}T = Text\n@view V\n  T\n")
	assert "syntax" in errors(f"{base}@view V\n  P[]\n")


def testMultipleFilesCombine():
	assert len(load("@ontology A rev=1\nPerson\n", "@ontology A rev=1\nBorrower of Person\n").decls) == 2
	assert "duplicate" in errors("@ontology A\nPerson\n", "@ontology A\nPerson\n")
	assert "header" in errors("@ontology A rev=1\n", "@ontology A rev=2\n")
	assert "header" in errors("@ontology A rev=1\n", "@ontology B rev=1\n")
	# NOTE: Defaults must agree in effect, whatever their spelling.
	assert errors("@ontology A rev=1 card=? cards=stated\n", "@ontology A cards=stated rev=1\n") == []
	assert "header" in errors("@ontology A rev=1 card=*\n", "@ontology A rev=1\n")


def testAliasesAreFileLocal():
	assert "reference" in errors("@ontology A\n@use Dimensions as D\nD/T = Text\n", "@ontology A\nP\n  N D/T\n")
	assert errors("@ontology A\n@use Dimensions as D\nD/T = Text\n", "@ontology A\n@use Dimensions as X\nP\n  N X/T\n") == []
	assert "alias" in errors("@ontology A\n@use Dimensions as D\n", "@ontology A\n@use Other as D\n")


# EOF
