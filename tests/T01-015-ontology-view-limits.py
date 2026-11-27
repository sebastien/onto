"""Module: list views and limit hints — `*` parameters, `{page, max}` on list views and `{page}` on populations (spec-01
Rooted views, spec-09 Limits and pages)."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadOntology, normaliseOntology, ontologyFromJson, ontologyToJson, printOntology
from onto.ontology.rooted import RootedView
from onto.ontology.model import Model
from onto.text import annotation
from tests.helpers import schemaValidator, specExample
from tests.store import EXTRA, financeText

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


CRM = loadOntology([Source("crm.onto", specExample("spec-09-sessions", 0))])
# NOTE: Spec-09's views, after their `@ontology Finance` and `@use Crm as CRM` lines, added to Finance.
VIEWS = specExample("spec-09-sessions", 3).split("\n", 2)[2]
TEXT = financeText(EXTRA).replace("@use Dimensions as D\n", "@use Dimensions as D\n@use Crm as CRM\n", 1) + "\n" + VIEWS


def load(text: str = TEXT):
	return loadOntology([Source("finance.onto", text)], [CRM])


def view(ontology, name: str):
	return next(decl for decl in ontology.decls if decl.path == f"Finance/{name}")


def errors(text: str) -> list[str]:
	with pytest.raises(FormatError) as error:
		load(text)
	return [item.message for item in error.value.diagnostics if item.level == "error"]


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testListViewsAndHintsParse() -> None:
	ontology = load()
	page, rows = view(ontology, "ClientPage"), view(ontology, "ClientList")
	assert (page.viewInput.many, rows.viewInput.many) == (False, True)
	assert (annotation(rows.ann, "page"), annotation(rows.ann, "max")) == ("25", "100")
	assert [population.page for population in page.viewPopulations] == [None, 10]
	rooted = RootedView(Model(ontology), rows)
	assert (rooted.many, rooted.page, rooted.max) == (True, 25, 100)
	assert RootedView(Model(ontology), page).pages == {"checks": 10}


def testTheNormalFormKeepsThem() -> None:
	printed = printOntology(normaliseOntology(load()))
	assert "@view ClientList(contactIds: * CRM/Contact.Id) {page=25, max=100}" in printed
	assert "  checks: IdentityCheck = client <- Person {page=10}\n" in printed
	assert printOntology(normaliseOntology(load(printed))) == printed


def testTheJsonFormKeepsThem() -> None:
	data = ontologyToJson(load())
	schemaValidator("ontology").validate(data)
	decls = {decl["path"]: decl for decl in data["decls"]}
	rows, page = decls["Finance/ClientList"], decls["Finance/ClientPage"]
	assert (rows["input"]["many"], rows["ann"]) == (True, {"page": "25", "max": "100"})
	assert page["populations"][1]["ann"] == {"page": "10"} and "many" not in page["input"]
	assert printOntology(normaliseOntology(ontologyFromJson(data, ontologies=[CRM]))) == printOntology(normaliseOntology(load()))


@pytest.mark.parametrize("old,new,message", [
	("{page=25, max=100}", "{page=0, max=100}", "page and max are positive integers"),
	("{page=25, max=100}", "{page=200, max=100}", "page is no larger than max"),
	("{page=10}", "{page=ten}", "page and max are positive integers"),
	("{page=10}", "{max=10}", "'max' applies to view, not here"),
	("Person {page=10}", "Person {page=10, colour=red}", "Unknown annotation 'colour'"),
	("(contactId: CRM/Contact.Id)", "(contactId: CRM/Contact.Id) {page=5}", "only a list view (a * parameter) takes page and max"),
])
def testHintsAreChecked(old: str, new: str, message: str) -> None:
	assert any(message in item for item in errors(TEXT.replace(old, new, 1)))


# EOF
