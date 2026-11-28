"""Module: session list view tests — spec-09 "List views": a list view's query compiled to its list read, the rows it
reads, each row's facts from the system and the store, and the query tables the bundle carries (DEC0038)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("hexa.shapes")

from onto import Source, loadBinding  # noqa: E402
from onto.handles import sourceQualifiedHandle  # noqa: E402
from onto.integrations.hexa import ListDirection, ListFilter, ListPage, ListRead, ListSort, ViewDocument, ViewRead  # noqa: E402
from onto.integrations.hexa.operations import HexaMappingOperator  # noqa: E402
from onto.integrations.hexa.sessions import SessionViewOperator, sessionBundle  # noqa: E402
from onto.ontology import ViewInput  # noqa: E402

from tests.sessions import BUNDLE, CRM, FINANCE, MAPPING, newStore  # noqa: E402
from tests.store import SCOPE, USER  # noqa: E402

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


CONTACTS = [
	{"id": "c-21", "familyName": "Ngata", "givenNames": "Aroha", "birthDate": "1982-04-11"},
	{"id": "c-22", "familyName": "Ngata", "givenNames": "Mere", "birthDate": "1990-01-02"},
	{"id": "c-23", "familyName": "Smith", "givenNames": "John", "birthDate": "1975-05-05"},
	{"id": "c-24", "familyName": "Nguyen", "givenNames": "Lan", "birthDate": "1988-08-08"},
]
ROW = """
  Id <- id
  BirthDate <- birthDate
  FamilyName <- familyName
  GivenNames <- givenNames
"""
LIST_BINDING = loadBinding(CRM, Source("contacts.bind", "@binding Crm format=json\nContact <- rows[*] {id=id}" + ROW))
CONTACT_BINDING = loadBinding(CRM, Source("contact.bind", "@binding Crm format=json\nContact <- $ {id=id}" + ROW))
# NOTE: The CRM's contact search, as spec-09's example declares it, with a partial match on the family name too.
SEARCH = ListRead("Crm/Contact", [LIST_BINDING],
	request={"method": "POST", "path": "/contacts/search", "body": {"familyName": "{surname}", "familyNameLike": "{surnameLike}",
		"sortBy": "{sort}", "order": "{order}", "page": "{page}", "pageSize": "{size}"}},
	parameters={"surname": ListFilter("FamilyName", "eq"), "surnameLike": ListFilter("FamilyName", "contains"),
		"sort": ListSort({"FamilyName": "familyName", "BirthDate": "birthDate"}), "order": ListDirection("asc", "desc"),
		"page": ListPage("number"), "size": ListPage("size")},
	total="count")
SURNAME, CONFIRMED = "Person.Name.Surname", "IdentityCheck.Confirmed"


def handle(key: str) -> str:
	return sourceQualifiedHandle("Finance/Person", "Crm", "Contact", key)


def searched(body: dict) -> dict:
	"""The CRM's answer to a contact search: matching contacts, sorted, one page of them, and how many matched."""
	rows = [row for row in CONTACTS if body.get("familyName") in (None, row["familyName"])
		and body.get("familyNameLike", "").lower() in row["familyName"].lower()]
	if "sortBy" in body:
		rows.sort(key=lambda row: (row[body["sortBy"]], row["id"]), reverse=body.get("order") == "desc")
	size = body.get("pageSize", 100)
	return {"rows": rows[body.get("page", 0) * size:][:size], "count": len(rows)}


def lister(store=None):
	"""A session operator over the CRM's contact search and its contact read, recording the requests it sends."""
	store, requests = store or newStore(), []

	def send(request, context=None):
		requests.append(request)
		return {"status": 200, "data": searched(request.get("body", {}))}

	access = SimpleNamespace(rootHandle=lambda key, value, kind: sourceQualifiedHandle(kind, "Crm", "Contact", value),
		fetch=lambda step, value: ViewDocument(next(row for row in CONTACTS if row["id"] == value), f"crm:contacts/{value}"),
		storeRead=lambda body: store.stateMany(USER, body), storeAppend=lambda partition, body: store.append(USER, partition, body))
	operator = SessionViewOperator(HexaMappingOperator(CRM, FINANCE), MAPPING,
		{"contact": ViewRead(ViewInput("contactId", "Crm/Contact", "Id"), [CONTACT_BINDING])}, access, BUNDLE, SCOPE,
		operations={"RequestSend": send}, lists={"search": SEARCH})
	return operator, requests, store


def report(operator, query: dict, fields: list[str] | None = None) -> dict:
	return json.loads(json.dumps(asyncio.run(operator.report("ClientList", {"contactIds": query}, fields))))


# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testAQueryCompilesToTheListReadsParameters() -> None:
	operator, requests, _ = lister()
	plan = asyncio.run(operator.plan("ClientList", {"contactIds": {"filter": {"field": SURNAME, "contains": "ng"},
		"sort": [{"field": SURNAME, "direction": "desc"}], "page": {"number": 2, "size": 2}}}))
	first, = (step for step in plan["steps"] if step["step"] == "search")
	assert first["requires"] == []
	assert first["body"] == {"familyNameLike": "ng", "sortBy": "familyName", "order": "desc", "page": 1, "pageSize": 2}
	assert plan["root"]["handle"] is None and requests == []


def testAListPageReadsItsRowsInOrderWithEachRowsFacts() -> None:
	operator, requests, _ = lister()
	result = report(operator, {"filter": {"field": SURNAME, "eq": "Ngata"}, "sort": [{"field": SURNAME, "direction": "asc"}]})
	assert [row["key"] for row in result["rows"]] == ["c-21", "c-22"]
	assert [row["handle"] for row in result["rows"]] == [handle("c-21"), handle("c-22")]
	assert (result["total"], result["page"], result["next"]) == (2, {"number": 1, "size": 25}, None)
	# NOTE: The view's default page is 25; the template leaves out the filters the query does not use.
	assert requests[0]["body"] == {"familyName": "Ngata", "sortBy": "familyName", "order": "asc", "page": 0, "pageSize": 25}
	surnames = {fact["row"]: fact["value"] for fact in result["facts"] if fact["field"] == SURNAME}
	assert surnames == {handle("c-21"): "Ngata", handle("c-22"): "Ngata"}
	assert {fact["holder"] for fact in result["facts"] if fact["field"] == SURNAME} == {"Crm"}


def testTheNextPageFollowsWhileRowsRemain() -> None:
	operator, _, _ = lister()
	first = report(operator, {"sort": [{"field": SURNAME, "direction": "asc"}], "page": {"size": 3}})
	assert ([row["key"] for row in first["rows"]], first["total"], first["next"]) == (["c-21", "c-22", "c-24"], 4, {"number": 2, "size": 3})
	second = report(operator, {"sort": [{"field": SURNAME, "direction": "asc"}], "page": first["next"]})
	assert ([row["key"] for row in second["rows"]], second["next"]) == (["c-23"], None)


def testEachRowsStoreFactsAreReadFromItsPartition() -> None:
	operator, _, store = lister()
	check = sourceQualifiedHandle("Finance/IdentityCheck", SCOPE, "IdentityCheck", "k1")
	store.append(USER, f"Client/{handle('c-22')}", {"requestId": "r1", "observations": {"format": "onto.observations/1",
		"obs": {"ontology": "Finance", "scope": SCOPE}, "sources": {"e": "edit:adviser-app"},
		"instances": {check: {"type": "Finance/IdentityCheck"}, handle("c-22"): {"type": "Finance/Person"}},
		"claims": [{"s": check, "exists": True, "n": 1, "src": "e"}, {"s": check, "p": "Person", "v": {"ref": handle("c-22")}, "n": 2, "src": "e"},
			{"s": check, "p": "Confirmed", "v": True, "n": 3, "src": "e"}], "retractions": []}})
	result = report(operator, {"filter": {"field": SURNAME, "eq": "Ngata"}})
	confirmed, = (fact for fact in result["facts"] if fact["field"] == CONFIRMED)
	assert (confirmed["row"], confirmed["value"], confirmed["holder"], confirmed["partition"]) == (handle("c-22"), True, BUNDLE["store"], f"Client/{handle('c-22')}")
	assert sorted(call["partition"] for call in result["calls"] if "partition" in call) == [f"Client/{handle('c-21')}", f"Client/{handle('c-22')}"]


def testQueriesTheViewCannotRunAreRefused() -> None:
	operator, requests, _ = lister()
	with pytest.raises(ValueError, match="Session.PageTooLarge"):
		report(operator, {"page": {"size": 101}})
	with pytest.raises(ValueError, match="Session.Unfilterable"):
		report(operator, {"filter": {"field": CONFIRMED, "eq": True}})
	with pytest.raises(ValueError, match="Session.Unfilterable"):
		report(operator, {"filter": {"field": SURNAME, "in": ["Ngata"]}})
	with pytest.raises(ValueError, match="Session.Unsortable"):
		report(operator, {"sort": [{"field": CONFIRMED, "direction": "asc"}]})
	assert requests == []


def testAnEndpointRequiringEveryMemberGetsNullForAbsentParameters() -> None:
	# NOTE: The endpoint also requires a sort: without one in the query, the list read's default applies, ascending.
	parameters = {**SEARCH.parameters, "sort": ListSort({"FamilyName": "familyName", "BirthDate": "birthDate"}, default="BirthDate")}
	strict = ListRead(SEARCH.rows, SEARCH.bindings, SEARCH.request, parameters, SEARCH.total, absent="null")
	operator, requests, _ = lister()
	operator = SessionViewOperator(operator.mapper, operator.mapping, {name: read for name, read in operator.reads.items() if name != "search"},
		operator.access, BUNDLE, SCOPE, operations=operator.operations, lists={"search": strict})
	report(operator, {"filter": {"field": SURNAME, "eq": "Ngata"}})
	assert requests[-1]["body"] == {"familyName": "Ngata", "familyNameLike": None, "sortBy": "birthDate", "order": "asc", "page": 0, "pageSize": 25}
	assert operator.listQueries["ClientList"]["sortDefault"] == "birthDate"
	assert sessionBundle(operator)["reads"]["search"]["list"]["absent"] == "null"
	with pytest.raises(ValueError, match="absent"):
		lister()[0].__class__(operator.mapper, operator.mapping, {}, operator.access, BUNDLE, SCOPE,
			lists={"search": ListRead(SEARCH.rows, SEARCH.bindings, SEARCH.request, SEARCH.parameters, absent="empty")})


def testPageViewsDoNotUseListReads() -> None:
	operator, _, _ = lister()
	plan = asyncio.run(operator.plan("ClientPage", {"contactId": "c-21"}))
	assert "search" not in {step["step"] for step in plan["steps"]}


def testTheBundleCarriesTheListReadAndTheViewsQueryTable() -> None:
	operator, _, _ = lister()
	bundle = sessionBundle(operator)
	assert bundle["reads"]["search"]["list"] == {"rows": "Crm/Contact", "total": "count", "parameters": {
		"surname": {"kind": "filter", "attr": "FamilyName", "operator": "eq"},
		"surnameLike": {"kind": "filter", "attr": "FamilyName", "operator": "contains"},
		"sort": {"kind": "sort", "spellings": {"FamilyName": "familyName", "BirthDate": "birthDate"}},
		"order": {"kind": "direction", "asc": "asc", "desc": "desc"},
		"page": {"kind": "page", "part": "number", "first": 0}, "size": {"kind": "page", "part": "size"}}}
	view = bundle["views"]["ClientList"]
	assert (view["input"]["many"], view["page"], view["max"]) == (True, 25, 100)
	assert view["list"] == {"read": "search",
		"filters": {SURNAME: {"eq": {"parameter": "surname"}, "contains": {"parameter": "surnameLike"}}},
		"sorts": {SURNAME: "familyName"}, "sort": "sort", "direction": "order", "page": {"number": "page", "size": "size", "first": 0}}
	assert "list" not in bundle["views"]["ClientPage"]


# EOF
