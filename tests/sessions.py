"""Module: tests.sessions — spec-09's example: a CRM's contacts mapped into Finance, the adviser application's store and
its views, with a recorded contact and an in-memory store."""

from __future__ import annotations

from types import SimpleNamespace

from onto import Source, loadBinding, loadFunctions, loadMapping, loadOntology
from onto.handles import sourceQualifiedHandle
from onto.integrations.hexa import ViewDocument, ViewRead
from onto.integrations.hexa.operations import HexaMappingOperator
from onto.integrations.hexa.sessions import Session, SessionViewOperator
from onto.ontology import ViewInput
from onto.referential import loadReferential
from onto.store import StoreOperator
from onto.store.runtime import ObservationStore

from tests.helpers import specExample
from tests.store import EXCHANGE, EXTRA, SCOPE, USER, authorize, financeText

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


CRM = loadOntology([Source("crm.onto", specExample("spec-09-sessions", 0))])
# NOTE: Spec-09's views, after their `@ontology Finance` and `@use Crm as CRM` lines, added to Finance.
VIEWS = specExample("spec-09-sessions", 3).split("\n", 2)[2]
FINANCE = loadOntology([Source("finance.onto", financeText(EXTRA).replace("@use Dimensions as D\n", "@use Dimensions as D\n@use Crm as CRM\n", 1)
	+ "\n" + VIEWS)], [CRM])
MAPPING = loadMapping(CRM, FINANCE, Source("crm-finance.map", specExample("spec-09-sessions", 1)))
MARKETS = loadFunctions([FINANCE], [Source("markets.fn", specExample("spec-04-mapping", 3))])
REFERENTIAL = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", specExample("spec-04-mapping", 4))])
EXCHANGE_MAPPING = loadMapping(EXCHANGE, FINANCE, Source("exchange-finance.map", specExample("spec-04-mapping", 5)), libraries=[MARKETS],
	referentials=[REFERENTIAL])
STORE = StoreOperator([FINANCE], [MAPPING, EXCHANGE_MAPPING], [REFERENTIAL])
BUNDLE = STORE.bundle(STORE.load([Source("adviser-app.store", specExample("spec-09-sessions", 2))]))

BINDING = loadBinding(CRM, Source("contact.bind", """@binding Crm format=json
Contact <- $ {id=id}
  Id <- id
  BirthDate <- birthDate
  FamilyName <- familyName
  GivenNames <- givenNames
"""))
CONTACT = {"id": "c-21", "familyName": "Ngata", "givenNames": "Aroha", "birthDate": "1982-04-11"}
CLIENT = sourceQualifiedHandle("Finance/Person", "Crm", "Contact", "c-21")
PARTITION = f"Client/{CLIENT}"
SEED = {"contactId": "c-21"}


def newStore() -> ObservationStore:
	return ObservationStore(BUNDLE, FINANCE, authorize)


def operator(store: ObservationStore, request: dict = USER) -> SessionViewOperator:
	"""The adviser application's view operator: the CRM's contact read, recorded, and the store as host operations."""
	access = SimpleNamespace(describe=lambda step, value: {}, fetch=lambda step, value: ViewDocument(CONTACT, f"crm:contacts/{value}"),
		rootHandle=lambda key, value, kind: sourceQualifiedHandle(kind, "Crm", "Contact", value),
		storeRead=lambda body: store.stateMany(request, body), storeAppend=lambda partition, body: store.append(request, partition, body))
	return SessionViewOperator(HexaMappingOperator(CRM, FINANCE), MAPPING, {"contact": ViewRead(ViewInput("contactId", "Crm/Contact", "Id"), [BINDING])},
		access, BUNDLE, SCOPE)


def session(store: ObservationStore) -> Session:
	return Session(operator(store))


__all__ = ["BUNDLE", "CLIENT", "CONTACT", "FINANCE", "PARTITION", "SEED", "newStore", "operator", "session"]

# EOF
