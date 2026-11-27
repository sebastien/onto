"""Module: tests.store — spec-08 fixtures: Finance with the store example's types, the exchange mapping and the store file."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onto import Source, loadFunctions, loadMapping, loadObservations, loadOntology, observationsToJson
from onto.referential import loadReferential
from onto.store import Store, StoreOperator
from onto.store.runtime import Forbidden, ObservationStore
from tests.helpers import specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


def financeText(extra: str = "") -> str:
	"""Spec-01's Finance with spec-08's additions, under spec-01's header."""
	return specExample("spec-01-ontology") + "\n" + specExample("spec-08-store", 0).split("\n", 1)[1] + extra


# NOTE: A member keeping a personal value about another kind's key entity (spec-08 "Personal facts stay home").
VISIT = """
Visit(Household, Visitor: Person) {kind=event}  -- A home visit
  VisitorAddress Text {privacy=Owner}
"""

FINANCE = loadOntology([Source("finance.onto", financeText(VISIT))])
EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", specExample("spec-04-mapping", 4))])
MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", specExample("spec-04-mapping", 5)), libraries=[MARKETS], referentials=[REFERENTIAL])
OPS = StoreOperator([FINANCE], [MAPPING], [REFERENTIAL])
EXAMPLE = specExample("spec-08-store", 1)
# NOTE: Spec-08's additions to Finance, as one more file of the CLI workspace's Finance ontology.
IDENTITY = "@ontology Finance rev=2026-11-10 src=import card=? cards=assumed\n" + specExample("spec-08-store", 0).split("\n", 1)[1]


def checked(text: str) -> Store:
	"""Parse and check one store file against Finance and the exchange mapping."""
	return OPS.load([Source("a.store", text)])


def addStore(workspace: Path, text: str = EXAMPLE) -> None:
	"""Add the store example, and the types it needs, to the CLI workspace."""
	(workspace / "finance/identity.onto").write_text(IDENTITY)
	(workspace / "finance/adviser-app.store").write_text(text)


# -----------------------------------------------------------------------------
#
# RUNTIME
#
# -----------------------------------------------------------------------------


SCOPE = "adviser-app"
NOW = datetime(2026, 11, 26, 9, 30, tzinfo=UTC)
USER = {"principal": "user:adviser"}
BUNDLE = OPS.bundle(checked(EXAMPLE))
HEADER = "@obs Finance by=app:intake\n@src e=edit:adviser-app\n@src e\n@scope adviser-app\n"


def authorize(request, partition, access):
	"""The host's callback: no request is unauthenticated; `deny` names a partition, or `True` for all, that the principal may not use."""
	if request is None:
		return None
	if request.get("deny") in (True, partition):
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


EXAMPLE_BATCH = batch(specExample("spec-08-store", 2))
CHECK = {"requestId": "3fe1c31e-24ad-4ca1-88d9-729045834e51", "observations": EXAMPLE_BATCH,
	"expect": [{"s": "IdentityCheck_C41", "exists": True, "version": 0}]}


def appended(*bodies: dict, store: ObservationStore | None = None, partition: str = "Client/Person_U1") -> ObservationStore:
	"""A store with `bodies` appended to `partition`, in order."""
	store = store or newStore()
	for body in bodies:
		store.append(USER, partition, body)
	return store


# EOF
