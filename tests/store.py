"""Module: tests.store — spec-08 fixtures: Finance with the store example's types, the exchange mapping and the store file."""

from __future__ import annotations

from pathlib import Path

from onto import Source, loadFunctions, loadMapping, loadOntology
from onto.referential import loadReferential
from onto.store import Store, StoreOperator
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


# EOF
