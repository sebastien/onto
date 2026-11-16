"""Module: layering tests — `layering=declared` orders domains and checks that references point to earlier ones."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadOntology, ontologyFromJson, ontologyToJson
from onto.meta import metaDeclarations
from onto.ontology import Operator
from tests._helpers import _schemaValidator

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

DOMAINS = "@domain Party\n@domain Lending\n"


def load(body: str, header: str = "layering=declared", *extra: tuple[str, str]):
	"""Load `body` after the header and the Party, Lending domains; `extra` are further (name, text) files."""
	sources = [Source("main.onto", f"@ontology A {header}\n{DOMAINS}{body}")]
	sources += [Source(name, f"@ontology A {header}\n{text}") for name, text in extra]
	return loadOntology(sources)


def errors(body: str, *extra: tuple[str, str]) -> list[str]:
	"""The messages of the layering errors of `body`."""
	with pytest.raises(FormatError) as raised:
		load(body, "layering=declared", *extra)
	return [item.message for item in raised.value.diagnostics if item.code == "layering"]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testReferencesToEarlierDomainsAreAllowed():
	load(
		"Party/Person\nParty/Name = Text\nLending/Loan\n  Borrower Party/Person\n  Name Party/Name\n"
		"Lending/Applicant(Lending/Loan, Party: Party/Person)\nLending/Borrowing of Party/Person {ctx=Lending/Loan}\n"
	)


@pytest.mark.parametrize("body", [
	"Party/Person\n  Loan Lending/Loan\nLending/Loan\n",
	"Lending/Loan\nParty/Debtor < Lending/Loan\n",
	"Party/Person\nLending/Loan\nParty/Credit of Lending/Loan\n",
	"Party/Person\nLending/Loan\nParty/Note of Party/Person {ctx=Lending/Loan}\n",
	"Party/Person\nLending/Loan\nParty/Holding(Party/Person, Lending/Loan)\n",
	"Lending/Rate = Number\nParty/Rate = Lending/Rate\n",
	"Lending/Loan\n  Rate Number\nParty/Person\n  Rate Lending/Loan.Rate\n",
	"Lending/Kind = A|B\nParty/Kind = C|D\n@map Party/KindMap Lending/Kind -> Party/Kind\n  A exact C\n",
])
def testReferencesToLaterDomainsAreErrors(body: str):
	assert errors(body), body


def testDerivedInputsAreReferences():
	assert errors("Lending/Loan\n  Amount Number\nParty/Person\n  ~ Debt Number <- Lending/Loan.Amount\n")


def testBinaryRelationsBelongToTheirLatestEndOrContext():
	load("Party/Person\nLending/Loan\nParty/Person -owes-> Lending/Loan\nLending/Loan -isOwedBy-> Party/Person\n")
	load(
		"Party/Person\nParty/Firm\nLending/Guarantee(Guarantor: Party/Person, Party/Firm)\n"
		"Party/Person -guarantees-> Party/Firm {context=Lending/Guarantee, subjectRole=Guarantor, objectRole=Firm}\n"
	)


def testValuesViewsAndUndeclaredDomainsAreNotReferences():
	load(
		"Party/Area = {hierarchical}\n  Lending\n    Mortgage\nLending/Loan\n"
		"@view Party/All\n  Lending/Loan\nOther/Thing\n  Loan Lending/Loan\n"
	)


def testDomainsMustBeDeclaredInOneFile():
	messages = errors("Party/Person\n", ("more.onto", "@domain Investing\n"))
	assert messages and "one file" in messages[0]


def testTheMetaDomainRanksFirstWherever():
	ontology = load("Party/Person\nLending/Loan\n")
	meta = metaDeclarations(ontology).split("\n", 1)[1]
	load("Party/Question\n  About Meta/Attribute\nLending/Loan\n", "layering=declared", ("meta.onto", meta))


def testWithoutLayeringNothingIsChecked():
	load("Party/Person\n  Loan Lending/Loan\nLending/Loan\n", "")


def testInvalidLayeringIsAHeaderError():
	with pytest.raises(FormatError) as raised:
		load("", "layering=strict")
	assert any(item.code == "header" for item in raised.value.diagnostics)


def testNormalFormAndJsonKeepTheDeclaredOrder():
	ontology = loadOntology([Source("main.onto", "@ontology A layering=declared\n@domain Zeta\n@domain Alpha\nAlpha/Thing\n  Z Zeta/Kind\nZeta/Kind = A|B\n")])
	assert Operator(ontology).print().startswith("@ontology A layering=declared\n\n@domain Zeta\n@domain Alpha\n")
	data = ontologyToJson(ontology)
	assert data["header"]["layering"] == "declared"
	assert [decl["path"] for decl in data["decls"][:2]] == ["A/Zeta", "A/Alpha"]
	_schemaValidator("ontology").validate(data)
	assert ontologyToJson(ontologyFromJson(data)) == data
	unlayered = loadOntology([Source("main.onto", "@ontology A\n@domain Zeta\n@domain Alpha\n")])
	assert Operator(unlayered).print().startswith("@ontology A\n\n@domain Alpha\n@domain Zeta\n")


# EOF
