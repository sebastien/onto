"""Module: observations conformance — audit regressions for spec-02."""

from __future__ import annotations

import json
from copy import deepcopy
from random import Random

import pytest

from onto import FormatError, Source, formatObservations, loadObservations, loadOntology, observationsFromJson, observationsToJson, printObservationsLog, printObservationsState, reconcileObservations

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------

ONTOLOGY = loadOntology([Source("t", """@ontology A
Money = Amount {cur=USD}
Person
  Name Text
  Count Integer
  Money Money
  Span Duration
  * Values Number
  + Required Number
  * Labels Text
  * Friends Person
Person -knows-> Person
  Witness Person
  Span Duration
""")])


def load(text: str):
	return loadObservations(ONTOLOGY, Source("audit.obs", "@obs A\n" + text))


def state(text: str):
	return reconcileObservations(ONTOLOGY, load(text))


# -----------------------------------------------------------------------------
#
# AUDIT REGRESSIONS
#
# -----------------------------------------------------------------------------


def testTypedReferencesOnNamedBinaryAttributesCanSupplyLaterEndpoints():
	log = load("p:Person\nq:Person\nr: p knows q\nr.Witness x:Person\np knows x\n")
	assert log.instances["x"]["type"] == "A/Person"
	assert len([claim for claim in log.claims if "rel" in claim]) == 2
	text = printObservationsLog(ONTOLOGY, log)
	assert formatObservations(ONTOLOGY, Source("t", text), "log") == text


def testNamedBinaryEndpointCanBeTypedInItsOwnReferenceAttribute():
	log = load("p:Person\nr: p knows q\nr.Witness q:Person\n")
	assert log.instances["q"]["type"] == "A/Person"
	assert next(claim for claim in log.claims if "rel" in claim)["roles"] == {"Subject": "p", "Object": "q"}
	with pytest.raises(FormatError):
		load("p:Person\np knows q\n")


@pytest.mark.parametrize("card", ["Values", "Required"])
def testWithdrawingLastMemberDoesNotInventConfirmedAbsence(card: str):
	log = state(f"p:Person\np.{card} [1]\n- p.{card} 1\n")
	assert not any(claim.get("p") == card for claim in log.claims)
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)
	text = printObservationsState(ONTOLOGY, log)
	assert "[]" not in text
	assert formatObservations(ONTOLOGY, Source("t", text)) == text


@pytest.mark.parametrize(("raw", "canonical"), [("1e3", "1e3"), ("2.00", "2"), ("200e-2", "200e-2")])
def testIntegralDecimalSpellingsAreValidIntegerValues(raw: str, canonical: str):
	log = load(f"p:Person\np.Count {raw}\n")
	assert log.claims[-1]["v"] == canonical
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)


def testFractionalIntegerAndUnrepresentableExponentsFailAsFormatErrors():
	for path, raw in (("Count", "2e-1"), ("Values", "[1e99999999999999999999]"), ("Money", "1e99999999999999999999")):
		with pytest.raises(FormatError):
			state(f"p:Person\np.{path} {raw}\n")


def testUnknownLocalQualifierDoesNotOverrideAKnownInheritedValue():
	log = state("p:Person\np.Money 1 {src=a, cur=?}\np.Money 1 {src=b}\n")
	assert all(not claim.get("conflict") for claim in log.claims)
	assert len([claim for claim in log.claims if claim.get("p") == "Money"]) == 2


def testLocalDurationUnitIsUsedDuringValueTyping():
	with pytest.raises(FormatError):
		load("p:Person\np.Span P2Y {unit=Year}\n")
	assert load("p:Person\np.Span 2 {unit=Year}\n").claims[-1]["v"] == "2"
	assert load("p:Person\np.Span P2Y {unit=?}\n").claims[-1]["v"] == "P2Y"


def testReconciliationRemainsPureForAuditCases():
	log = load("p:Person\np.Values [1, 2]\n- p.Values 2\n")
	before = deepcopy(log)
	resolved = reconcileObservations(ONTOLOGY, log)
	assert log == before
	assert observationsToJson(reconcileObservations(ONTOLOGY, resolved)) == observationsToJson(resolved)


def testSubMicrosecondTimesOrderExactlyRatherThanByStatementPosition():
	log = state("p:Person\np.Name Later {at=2026-01-01T00:00:00.0000002Z}\np.Name Earlier {at=2026-01-01T00:00:00.0000001Z}\n")
	assert next(claim for claim in log.claims if claim.get("p") == "Name")["v"] == "Later"
	with pytest.raises(FormatError):
		load("p:Person {valid=2026-01-01T00:00:00.0000002Z..2026-01-01T00:00:00.0000001Z}\n")
	log = load("p:Person {at=0001-01-01T00:00:00+01:00}\n")
	assert log.claims[0]["at"] == "0001-01-01T00:00:00+01:00"


@pytest.mark.parametrize("member", ["1", "[1, ...]", "[...]", "?"])
def testStatePrintingPreservesMembersAfterCompleteCollections(member: str):
	log = load(f"p:Person\np.Values [2]\np.Values {member}\n")
	resolved = reconcileObservations(ONTOLOGY, log)
	printed = printObservationsState(ONTOLOGY, resolved)
	loaded = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert [claim["v"] for claim in loaded.claims if claim.get("p") == "Values"] == [claim["v"] for claim in resolved.claims if claim.get("p") == "Values"]
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(resolved))) == observationsToJson(resolved)
	printed = printObservationsLog(ONTOLOGY, log)
	assert observationsToJson(reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))) == observationsToJson(resolved)


def testCollectionChronologySurvivesWhenTimesDiffer():
	log = state("p:Person\np.Values [2] {at=2026-01-01}\np.Values 1 {at=2026-01-02}\n")
	text = printObservationsState(ONTOLOGY, log)
	assert formatObservations(ONTOLOGY, Source("t", text)) == text


@pytest.mark.parametrize("mode", ["strict", "lenient"])
def testScopeCannotBeSilentlyReplacedWithinADocument(mode: str):
	with pytest.raises(FormatError, match="Scope cannot change"):
		loadObservations(ONTOLOGY, Source("t", "@obs A\n@scope first\np:Person\n@scope second\n"), mode)
	assert loadObservations(ONTOLOGY, Source("t", "@obs A\n@scope first\n@scope first\np:Person\n"), mode).obs["scope"] == "first"


def testDirectiveSeparatorsAcceptWhitespaceButIndentationStillRequiresSpaces():
	log = loadObservations(ONTOLOGY, Source("t", "@obs\tA\tat=2026-01-01\n@scope\tfeed\n@src\ta=source:a\n@src\ta\np:Person\n"))
	assert log.obs["scope"] == "feed"
	assert log.claims[0]["src"] == "a"
	assert log.claims[0]["at"] == "2026-01-01"


@pytest.mark.parametrize("form", ["log", "state"])
def testCollectionsSortByEncodedValueWithoutLosingTypedReferenceMentions(form: str):
	text = "@obs A\np:Person\np.Labels [a, \"z,\"]\np.Friends [a0:Person, a:Person]\n"
	printed = formatObservations(ONTOLOGY, Source("t", text), form)
	assert '["z,", a]' in printed
	assert "[a:Person, a0:Person]" in printed
	assert formatObservations(ONTOLOGY, Source("t", printed), form) == printed


def testDeterministicReplayAuditPreservesClaimsAndFormatting():
	random = Random(13)
	statements = ["p.Name A", "p.Name B", "p.Name ?", "p.Name null", "p.Values 1", "p.Values 2",
		"p.Values [1]", "p.Values [2]", "p.Values [1, ...]", "- p.Name", "- p.Values 1"]

	def content(log) -> list[str]:
		return sorted(json.dumps({key: value for key, value in claim.items() if key != "n"}, sort_keys=True) for claim in log.claims)

	for _ in range(120):
		text = "p:Person\n" + "\n".join(random.choice(statements) + " {src=" + random.choice(["a", "b"]) + "}" for _ in range(random.randrange(1, 9))) + "\n"
		log = load(text)
		resolved = reconcileObservations(ONTOLOGY, log)
		assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)
		printed = printObservationsState(ONTOLOGY, resolved)
		loaded = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
		assert content(loaded) == content(resolved)
		assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


def testCollectionOrderingKeepsProvenanceAndStillSortsIndependentMembers():
	log = state("""@src a=feed alias=feed b=other
p:Person
p.Values [2] {src=a, by=snapshot, at=2026-01-01}
p.Values 1 {src=alias, by=addition, at=2026-01-01}
p.Values 3 {src=b, by=other, at=2026-01-01}
p.Labels z
p.Labels a
""")
	printed = printObservationsState(ONTOLOGY, log)
	loaded = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	claims = [claim for claim in loaded.claims if claim.get("p") == "Values"]
	assert [(claim["v"], claim["src"], claim["by"], claim["at"]) for claim in claims] == [
		({"set": ["2"]}, "a", "snapshot", "2026-01-01"),
		("1", "alias", "addition", "2026-01-01"), ("3", "b", "other", "2026-01-01")]
	assert printed.index("Labels a") < printed.index("Labels z")
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


@pytest.mark.parametrize(("header", "path", "context"), [
	("p:Person", "p.Values", ""),
	("g:Group", "g.Values", ""),
	("r: p knows q", "r.Values", ""),
	("p[Review] {ctx=c}", "p.Review.Values", "ctx=c, "),
])
def testCollectionLogOrderAppliesToEveryOwnerKind(header: str, path: str, context: str):
	ontology = loadOntology([Source("t", """@ontology A
Person
  * Values Number
Scenario
Review of Person {ctx=Scenario}
  * Values Number
Group(Left: Person, Right: Person)
  * Values Number
Person -knows-> Person
  * Values Number
""")])
	text = ("@obs A src=feed at=2026-01-01\np:Person\nq:Person\nc:Scenario\n" + header + "\n"
		+ path + " [2] {" + context + "by=snapshot}\n" + path + " 1 {" + context + "by=addition}\n")
	printed = formatObservations(ontology, Source("t", text))
	loaded = loadObservations(ontology, Source("t", printed))
	claims = [claim for claim in loaded.claims if claim.get("p") == path.partition(".")[2]]
	assert [(claim["v"], claim["by"]) for claim in claims] == [({"set": ["2"]}, "snapshot"), ("1", "addition")]
	assert formatObservations(ontology, Source("t", printed)) == printed


# EOF
