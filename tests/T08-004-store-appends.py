"""Module: store append tests — spec-08 batches: homes, origins, held slots, stamping, preconditions, retries and limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from onto import Source, loadObservations, observationsToJson
from onto.handles import sourceQualifiedHandle
from onto.store.runtime import Forbidden, ObservationStore, StoreError
from tests.helpers import specExample
from tests.store import EXAMPLE, FINANCE, OPS, checked

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SCOPE = "adviser-app"
NOW = datetime(2026, 11, 26, 9, 30, tzinfo=UTC)
USER = {"principal": "user:adviser"}
BUNDLE = OPS.bundle(checked(EXAMPLE))
ISSUERS = OPS.bundle(checked("@store Issuers rev=1 edit=edit:adviser-app\n@use Finance as F\n@system Exchange -> Finance\n\n"
	"@partition Issuer(company: F/Company)\n"))
HEADER = "@obs Finance by=app:intake\n@src e=edit:adviser-app\n@src e\n@scope adviser-app\n"


def authorize(request, partition, access):
	if request is None:
		return None
	if request.get("deny"):
		raise Forbidden("not this client")
	return {"scope": request.get("scope", SCOPE), "principal": request["principal"]}


def newStore(bundle: dict = BUNDLE, clock=lambda: NOW) -> ObservationStore:
	return ObservationStore(bundle, FINANCE, authorize, clock=clock)


def batch(text: str, known: dict[str, str] | None = None, typed: dict[str, str] | None = None) -> dict:
	"""The JSON form of statements, without the types of the handles the store already knows (`known`), with those
	of handles new to it that the statements only mention (`typed`)."""
	known = {"Person_U1": "Person"} if known is None else known
	header, _, body = text.partition("\n\n") if text.startswith("@obs") else (HEADER, "", text)
	declared = "".join(f"@type {handle} {type}\n" for handle, type in (known | (typed or {})).items())
	data = observationsToJson(loadObservations(FINANCE, Source("batch.obs", f"{header}\n{declared}\n{body}")))
	for handle in known:
		data["instances"].pop(handle, None)
	return data


def refused(store: ObservationStore, partition: str, body: dict, request=USER) -> StoreError:
	with pytest.raises(StoreError) as error:
		store.append(request, partition, body)
	return error.value


EXAMPLE_BATCH = batch(specExample("spec-08-store", 2))
CHECK = {"requestId": "3fe1c31e-24ad-4ca1-88d9-729045834e51", "observations": EXAMPLE_BATCH,
	"expect": [{"s": "IdentityCheck_C41", "exists": True, "version": 0}]}


def appended(*bodies: dict, store: ObservationStore | None = None) -> ObservationStore:
	store = store or newStore()
	for body in bodies:
		store.append(USER, "Client/Person_U1", body)
	return store


# -----------------------------------------------------------------------------
#
# BATCHES
#
# -----------------------------------------------------------------------------


def testTheExampleBatchIsStamped() -> None:
	store = newStore()
	answer = store.append(USER, "Client/Person_U1", CHECK)
	assert answer == {"partition": "Client/Person_U1", "generation": 1, "from": 1, "through": 8, "head": 8, "recorded": "2026-11-26T09:30:00.000Z"}
	entries = store.statements(store.partition(SCOPE, "Client/Person_U1"))
	assert [entry["seq"] for entry in entries] == list(range(1, 9))
	first = entries[0]
	assert {key: first[key] for key in ("s", "exists", "src", "at", "by", "valid", "principal", "requestId", "bundle", "recorded")} == {
		"s": "IdentityCheck_C41", "exists": True, "src": "edit:adviser-app", "at": "2026-11-26T09:30:00.000Z", "by": "app:intake",
		"valid": "2026-11-26", "principal": "user:adviser", "requestId": CHECK["requestId"], "bundle": BUNDLE["revision"],
		"recorded": "2026-11-26T09:30:00.000Z"}


def testARetryReturnsTheOriginalAnswer() -> None:
	store = appended(CHECK)
	later = {"requestId": "r2", "observations": batch("IdentityCheck_C41.Confirmed false", {"IdentityCheck_C41": "IdentityCheck"})}
	store.append(USER, "Client/Person_U1", later)
	assert store.append(USER, "Client/Person_U1", CHECK)["through"] == 8
	assert store.partition(SCOPE, "Client/Person_U1").head == 9
	assert refused(store, "Client/Person_U1", {**later, "expect": [{"s": "IdentityCheck_C41", "p": "Confirmed", "version": 9}]}).error == "request_reused"


def testRetryRecordsExpireAfterSevenDays() -> None:
	clock = [NOW]
	store = appended(CHECK, store=newStore(clock=lambda: clock[0]))
	clock[0] = NOW + timedelta(days=8)
	error = refused(store, "Client/Person_U1", CHECK)
	assert (error.status, error.error) == (409, "precondition")


def testAMovedSlotRejectsTheBatchWhole() -> None:
	store = appended(CHECK)
	error = refused(store, "Client/Person_U1", {**CHECK, "requestId": "r2"})
	assert (error.status, error.error, error.details["versions"]) == (409, "precondition", [{"s": "IdentityCheck_C41", "exists": True, "version": 1}])
	assert store.partition(SCOPE, "Client/Person_U1").head == 8


def testWritersOfDifferentSlotsDoNotConflict() -> None:
	store = appended(CHECK)
	known = {"IdentityCheck_C41": "IdentityCheck"}
	store.append(USER, "Client/Person_U1", {"requestId": "a", "observations": batch("IdentityCheck_C41.Confirmed false", known),
		"expect": [{"s": "IdentityCheck_C41", "p": "Confirmed", "version": 5}]})
	store.append(USER, "Client/Person_U1", {"requestId": "b", "observations": batch("IdentityCheck_C41.Method Electronic", known),
		"expect": [{"s": "IdentityCheck_C41", "p": "Method", "version": 4}]})
	assert store.partition(SCOPE, "Client/Person_U1").head == 10


def testRetractionsMoveTheSlotsTheyWithdraw() -> None:
	store = appended(CHECK)
	known = {"IdentityCheck_C41": "IdentityCheck", "Document_D9": "Document"}
	store.append(USER, "Client/Person_U1", {"requestId": "r", "observations": batch("- IdentityCheck_C41.Confirmed\n- Document_D9", known)})
	partition = store.partition(SCOPE, "Client/Person_U1")
	keys = ['["IdentityCheck_C41","Confirmed",""]', '["IdentityCheck_C41","Method",""]', '["Document_D9","Title",""]', '["Document_D9","",""]']
	assert store.versions(partition, keys) == dict(zip(keys, [9, 4, 10, 10]))


# -----------------------------------------------------------------------------
#
# HOMES, ORIGINS AND HELD SLOTS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("text,typed,check,n", [
	("IdentityCheck_C42:IdentityCheck\n  Person Person_U2\n  Method InPerson", {"Person_U2": "Person"}, "home.mismatch", 1),
	("Document_D7:Document\n  Title Lease", {}, "home.unlinked", 1),
	("Household_H1:Household", {}, "home.none", 1),
	("Person_U2.Email u2@example.com", {"Person_U2": "Person"}, "home.mismatch", 1),
])
def testStatementsAreAboutMembers(text: str, typed: dict, check: str, n: int) -> None:
	error = refused(newStore(), "Client/Person_U1", {"requestId": "r", "observations": batch(text, typed=typed)})
	assert (error.status, error.error, error.details["check"], error.details["n"]) == (400, "invalid", check, n)


def testAStoredLinkMakesALaterSubjectAMember() -> None:
	store = appended({"requestId": "a", "observations": batch("IdentityCheck_C41:IdentityCheck\n  Person Person_U1\n  Document Document_D8",
		typed={"Document_D8": "Document"})})
	store.append(USER, "Client/Person_U1", {"requestId": "b", "observations": batch("Document_D8.Title Lease", {"Document_D8": "Document"})})
	assert store.partition(SCOPE, "Client/Person_U1").members == {"Person_U1": "client", "IdentityCheck_C41": "checks", "Document_D8": "documents"}


@pytest.mark.parametrize("anchor,text,check", [
	("Company_ACM", "Company_ACM.SuspensionStatus Halted", None),
	("Company_ACM", "Company_ACM.RegisteredName Acme", "slot.not-held"),
	("Company_ACM", "Company_ACM:Company", "slot.not-held"),
	("Issuer_ACM", "Issuer_ACM.SuspensionStatus Halted", "origin.unknown"),
	(sourceQualifiedHandle("Finance/Company", SCOPE, "Company", "7f3a"), "{anchor}:Company\n  RegisteredName Acme", None),
])
def testOriginsDecideHeldSlots(anchor: str, text: str, check: str | None) -> None:
	body = {"requestId": "r", "observations": batch(text.replace("{anchor}", anchor), {anchor: "Company"})}
	if check is None:
		assert newStore(ISSUERS).append(USER, f"Issuer/{anchor}", body)["through"] >= 1
	else:
		assert refused(newStore(ISSUERS), f"Issuer/{anchor}", body).details["check"] == check


# -----------------------------------------------------------------------------
#
# VALIDATION, LIMITS AND AUTHORIZATION
#
# -----------------------------------------------------------------------------


def testSpecTwoErrorsNameTheStatement() -> None:
	data = batch("IdentityCheck_C41:IdentityCheck\n  Person Person_U1\n  Method InPerson")
	data["claims"][2]["v"] = "ByPost"
	error = refused(newStore(), "Client/Person_U1", {"requestId": "r", "observations": data})
	assert (error.error, error.details["n"]) == ("invalid", 3)


@pytest.mark.parametrize("change,check", [
	(lambda data: data["claims"][0].update(at="2026-12-01"), "at"),
	(lambda data: data["obs"].update(scope="elsewhere"), "scope"),
	(lambda data: (data.update(sources={}), [claim.pop("src") for claim in data["claims"]]), "src"),
])
def testStoreChecks(change, check: str) -> None:
	data = batch("IdentityCheck_C41:IdentityCheck\n  Person Person_U1")
	change(data)
	assert refused(newStore(), "Client/Person_U1", {"requestId": "r", "observations": data}).details["check"] == check


def testATypeKnownToThePartitionStays() -> None:
	store = appended(CHECK)
	data = batch("IdentityCheck_C41.Method Electronic", {"IdentityCheck_C41": "IdentityCheck"})
	data["instances"]["IdentityCheck_C41"] = {"type": "Finance/Dividend"}
	assert refused(store, "Client/Person_U1", {"requestId": "r", "observations": data}).details["check"] == "type"


def testLimits() -> None:
	small = {**BUNDLE, "limits": {**BUNDLE["limits"], "statementsPerBatch": 2}}
	error = refused(newStore(small), "Client/Person_U1", CHECK)
	assert (error.status, error.error) == (413, "too_large")


@pytest.mark.parametrize("request_,partition,status,error", [
	(None, "Client/Person_U1", 401, "unauthorized"),
	({"principal": "user:other", "deny": True}, "Client/Person_U1", 403, "forbidden"),
	(USER, "Nobody/Person_U1", 400, "invalid"),
	(USER, "Client/Person-U1", 400, "invalid"),
])
def testRequestsAreAuthorizedAndNamed(request_, partition: str, status: int, error: str) -> None:
	refusal = refused(newStore(), partition, CHECK, request_)
	assert (refusal.status, refusal.error) == (status, error)


# EOF
