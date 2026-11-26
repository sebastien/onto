"""Module: store file tests — spec-08 parsing, normal form and JSON form."""

from __future__ import annotations

import pytest

from onto import FormatError, Source
from onto.store import Store, parseStore, printStore, storeFromJson, storeToJson
from tests.helpers import schemaValidator, specExample

EXAMPLE = specExample("spec-08-store", 1)

SHUFFLED = """\
@store AdviserApp rev=1 edit=edit:app
@index ByBirth Client -- Clients by date of birth
  client.DateOfBirth
@use Finance as F
@partition Household(household: F/Household)
- F/Person.Email {reason=private}
@system Exchange -> Finance {scope=exchange}
@partition Client(client: F/Person) {orphaned=never}
  checks: F/IdentityCheck = client <- Person {privacy=kept, archived=P10Y}
"""

NORMAL = """\
@store AdviserApp rev=1 edit=edit:app
@use Finance as F
@system Exchange -> Finance {scope=exchange}

@partition Client(client: F/Person) {orphaned=never}
  checks: F/IdentityCheck = client <- Person {archived=P10Y, privacy=kept}

@partition Household(household: F/Household)

- F/Person.Email {reason=private}

@index ByBirth Client                           -- Clients by date of birth
  client.DateOfBirth
"""


def load(*texts: str) -> Store:
	return parseStore([Source(f"file{index}.store", text) for index, text in enumerate(texts)])


def codes(*texts: str) -> set[str]:
	with pytest.raises(FormatError) as error:
		load(*texts)
	return {item.code for item in error.value.diagnostics if item.level == "error"}


# -----------------------------------------------------------------------------
#
# PARSING
#
# -----------------------------------------------------------------------------


def testExampleParses() -> None:
	store = load(EXAMPLE)
	assert (store.name, store.header, store.uses) == ("AdviserApp", {"rev": "2026-11-26", "edit": "edit:adviser-app"}, {"F": "Finance"})
	assert [(item.fromNamespace, item.toNamespace, item.scope, item.doc) for item in store.systems] == [
		("Exchange", "Finance", None, "The exchange holds what its import fills")]
	client, household = store.partitions
	assert (client.kind, client.root.name, client.root.type, client.keys) == ("Client", "client", "Finance/Person", {"archived": "P7Y"})
	assert [(item.name, item.type, item.parent, item.via, item.reverse) for item in client.populations] == [
		("checks", "Finance/IdentityCheck", "client", "Person", True),
		("documents", "Finance/Document", "checks", "Document", False)]
	assert (household.kind, household.root.type, household.populations, household.keys) == ("Household", "Finance/Household", [], {})
	index, = store.indexes
	assert (index.name, index.kind, [(column.population, column.path) for column in index.columns]) == (
		"ClientChecks", "Client", [("checks", "Confirmed"), ("checks", "Method")])


def testFilesShareOneHeader() -> None:
	store = load("@store A rev=1\n@use Finance as F\n@partition P(p: F/Person)\n",
		"@store A rev=1\n@use Finance as F\n@partition H(h: F/Household)\n")
	assert [item.kind for item in store.partitions] == ["P", "H"]
	assert codes("@store A rev=1\n", "@store A rev=2\n") == {"header"}


@pytest.mark.parametrize("text,code", [
	("@use Finance as F\n", "header"),
	("@store A colour=red\n", "header"),
	("@store A\n@use Finance as F\n@use Other as F\n", "use"),
	("@store A\n@use Finance as F\n@system Exchange -> Finance {scope=a, mode=b}\n", "system"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person) {privacy=kept}\n", "policy"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person) {archived=P7}\n", "policy"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person) {colour=red}\n", "policy"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n  d: F/Document = p -> Document {privacy=shared}\n", "policy"),
	("@store A\n@use Finance as F\n@partition P(p: Person)\n", "store"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n@partition P(q: F/Household)\n", "partition"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n  d: F/Document = q -> Document\n", "population"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n  p: F/Document = p -> Document\n", "population"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n  d: F/Document = p -> Document where Title=A\n", "population"),
	("@store A\n@use Finance as F\n  d: F/Document = p -> Document\n", "syntax"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n@index I P\n  Confirmed\n", "index"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n@index I P\n  p.Email\n@index I P\n  p.Email\n", "index"),
	("@store A\n@use Finance as F\n@partition P(p: F/Person)\n@index I P\n", "index"),
	("@store A\n@use Finance as F\n- F/Person {reason=private}\n", "exclusion"),
	("@store A\n@use Finance as F\nPerson\n", "syntax"),
])
def testStructuralErrors(text: str, code: str) -> None:
	assert code in codes(text)


# -----------------------------------------------------------------------------
#
# FORMS
#
# -----------------------------------------------------------------------------


def testExampleIsInNormalForm() -> None:
	assert printStore(load(EXAMPLE)) == EXAMPLE


def testNormalFormOrdersSections() -> None:
	assert printStore(load(SHUFFLED)) == NORMAL
	assert printStore(load(NORMAL)) == NORMAL


@pytest.mark.parametrize("text", [EXAMPLE, NORMAL])
def testJsonRoundTrip(text: str) -> None:
	data = storeToJson(load(text))
	schemaValidator("store").validate(data)
	assert storeToJson(storeFromJson(data)) == data
	assert printStore(storeFromJson(data)) == text


def testJsonIsStrict() -> None:
	data = storeToJson(load(EXAMPLE))
	with pytest.raises(FormatError):
		storeFromJson({**data, "colour": "red"})
	with pytest.raises(FormatError):
		storeFromJson({**data, "format": "onto.store/2"})
	partition = {**data["partitions"][0], "orphaned": "sometimes"}
	with pytest.raises(FormatError):
		storeFromJson({**data, "partitions": [partition, *data["partitions"][1:]]})


# EOF
