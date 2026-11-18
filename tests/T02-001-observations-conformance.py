"""Module: observations conformance — audit regressions for spec-02."""

from __future__ import annotations

from copy import deepcopy
from random import Random

import pytest

from onto import FormatError, Source, formatObservations, loadObservations, loadOntology, observationsCoverage, observationsFromJson, observationsToJson, printObservationsLog, printObservationsState, reconcileObservations
from onto.observations import Observations
from tests.helpers import semanticClaims

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
Scenario
Investor of Person
  Rating Text
Review of Person {ctx=Scenario}
  Included Boolean
Person -knows-> Person
  Witness Person
  Span Duration
@view Audit
  Person[*]
""")])


def load(text: str) -> Observations:
	return loadObservations(ONTOLOGY, Source("audit.obs", "@obs A\n" + text))


def state(text: str) -> Observations:
	return reconcileObservations(ONTOLOGY, load(text))


# -----------------------------------------------------------------------------
#
# TYPING AND WITHDRAWALS
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


# -----------------------------------------------------------------------------
#
# CHRONOLOGY AND NORMAL FORMS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(("left", "right", "conflict"), [
	("2026-01-01..2026-02-01", "2026-03-01..", False),
	("..2026-02-01", "2026-02-01..", True),
	("2026-02-01", "2026-02-01..2026-03-01", True),
	("2026-01-01T00:00:00.0000001Z", "2026-01-01T00:00:00.0000002Z", False),
	("2026-01-01T01:00:00+01:00", "2026-01-01T00:00:00Z", True),
])
def testHistoricalConflictDetectionAndReplay(left: str, right: str, conflict: bool):
	resolved = state(f"p:Person\np.Name Earlier {{src=a, valid={left}}}\np.Name Later {{src=b, valid={right}}}\n")
	claims = [claim for claim in resolved.claims if claim.get("p") == "Name"]
	assert [claim.get("conflict", False) for claim in claims] == [conflict, conflict]
	assert [claim["valid"] for claim in claims] == [left, right]
	printed = printObservationsState(ONTOLOGY, resolved)
	replayed = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert semanticClaims(replayed) == semanticClaims(resolved)
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


def testWithinSourceSupersessionUsesObservationTimeNotValidity():
	text = ("p:Person\np.Name Later {src=feed, at=2026-04-01, valid=2025-01-01..2025-02-01}\n"
		"p.Name Earlier {src=feed, at=2026-03-01, valid=2026-01-01..}\n")
	resolved = state(text)
	assert [(claim["v"], claim["valid"]) for claim in resolved.claims if claim.get("p") == "Name"] == [("Later", "2025-01-01..2025-02-01")]
	# A withdrawal means the observation should not have been made, revealing earlier evidence.
	resolved = state(text + "- p.Name Later {src=feed, at=2026-05-01}\n")
	assert [claim["v"] for claim in resolved.claims if claim.get("p") == "Name"] == ["Earlier"]


@pytest.mark.parametrize("value", ["Known", "?", "null"])
def testFacetAttributeOnlySubjectsDoNotAcquireExistenceOrExplicitFacets(value: str):
	log = load(f"p:Person.Investor.Rating {value}\n")
	resolved = reconcileObservations(ONTOLOGY, log)
	assert len(resolved.claims) == 1
	assert "exists" not in resolved.claims[0] and "facet" not in resolved.claims[0]
	assert "implicit" not in resolved.instances["p"]
	rows = {(item.path, item.subject, item.ctx): item for item in observationsCoverage(ONTOLOGY, log, "Audit")}
	assert rows[("A/Person", "p", None)].statuses == ("missing",)
	assert rows[("A/Person[Investor]", "p", None)].statuses == ("supplied",)
	printed = printObservationsState(ONTOLOGY, resolved)
	replayed = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert semanticClaims(replayed) == semanticClaims(resolved)
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(resolved))) == observationsToJson(resolved)
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


def testContextOnlyAndReferenceOnlyHandlesRemainImplicitUntilTheirReferencesDisappear():
	text = "@type c Scenario\np:Person.Friends [q:Person]\np.Review.Included true {ctx=c}\n"
	resolved = state(text)
	assert {handle for handle, instance in resolved.instances.items() if instance.get("implicit")} == {"q", "c"}
	assert not any(claim.get("exists") or "facet" in claim for claim in resolved.claims)
	printed = printObservationsState(ONTOLOGY, resolved)
	replayed = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert semanticClaims(replayed) == semanticClaims(resolved)
	assert replayed.instances == resolved.instances
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed
	resolved = state(text + "- p.Friends q\n- p[Review] {ctx=c}\n")
	assert resolved.claims == []
	assert all("implicit" not in instance for instance in resolved.instances.values())
	printed = printObservationsState(ONTOLOGY, resolved)
	assert reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed))).instances == resolved.instances


@pytest.mark.parametrize("partial", ["", ", ..."])
@pytest.mark.parametrize("path", ["Values", "Required"])
def testMemberWithdrawalsPreserveCollectionEvidenceAndOtherProducers(partial: str, path: str):
	text = ("@src feed=system:feed alias=system:feed\np:Person\n"
		+ f"p.{path} 9 {{src=feed, by=earlier}}\n"
		+ f"p.{path} [1, 2{partial}] {{src=feed, by=snapshot}}\n"
		+ f"p.{path} 3 {{src=alias, by=addition}}\n"
		+ f"- p.{path} 2 {{src=curator, of=alias, by=snapshot}}\n")
	log = load(text)
	before = deepcopy(log)
	resolved = reconcileObservations(ONTOLOGY, log)
	assert log == before
	claims = [claim for claim in resolved.claims if claim.get("p") == path]
	collection = {"set": ["1"], **({"partial": True} if partial else {})}
	expected = [("9", "feed", "earlier")] if partial else []
	assert [(claim["v"], claim["src"], claim["by"]) for claim in claims] == expected + [(collection, "feed", "snapshot"), ("3", "alias", "addition")]
	printed = printObservationsState(ONTOLOGY, resolved)
	replayed = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
	assert semanticClaims(replayed) == semanticClaims(resolved)
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(resolved))) == observationsToJson(resolved)
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed
	# A producer-qualified member withdrawal must leave the other producer's member alone.
	resolved = state(text + f"- p.{path} 3 {{src=feed, by=snapshot}}\n")
	assert any(claim.get("v") == "3" and claim.get("by") == "addition" for claim in resolved.claims)
	assert any(item.code == "retraction" for item in resolved.diagnostics)


@pytest.mark.parametrize("withdrawal", ["1", "[1]"])
def testWithdrawingAnEntireSnapshotCanRevealEarlierProducerEvidence(withdrawal: str):
	text = ("p:Person\np.Values [9] {src=feed, by=earlier}\n"
		"p.Values [1] {src=feed, by=snapshot}\n"
		+ f"- p.Values {withdrawal} {{src=feed, by=snapshot}}\n")
	resolved = state(text)
	assert [(claim["v"], claim["by"]) for claim in resolved.claims if claim.get("p") == "Values"] == [({"set": ["9"]}, "earlier")]
	printed = printObservationsState(ONTOLOGY, resolved)
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed
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


# -----------------------------------------------------------------------------
#
# REPLAY AND COLLECTION PROVENANCE
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["strict", "lenient"])
def testRepeatedIdentityLinksAccumulateWithoutChangingCanonicalHandleOnReplay(mode: str):
	log = load("a:Person\nb:Person\nc:Person\na.Name A\nb.Name B\nc.Name C\nc = a\nb = a\nc = a\n")
	before = deepcopy(log)
	resolved = reconcileObservations(ONTOLOGY, log, mode)
	assert log == before
	assert [claim["same"] for claim in resolved.claims if "same" in claim] == [["c", "a"], ["b", "a"], ["c", "a"]]
	assert next(claim for claim in resolved.claims if claim.get("p") == "Name")["s"] == "b"
	printed = printObservationsState(ONTOLOGY, resolved)
	replayed = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)), mode)
	assert semanticClaims(replayed) == semanticClaims(resolved)
	assert formatObservations(ONTOLOGY, Source("t", printed), mode=mode) == printed
	assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(resolved), mode=mode)) == observationsToJson(resolved)


@pytest.mark.parametrize("kind", ["=", "!="])
def testIdentityLinksKeepRepeatedEvidenceAndProducerScopedWithdrawals(kind: str):
	text = f"a:Person\nb:Person\na {kind} b {{by=first}}\na {kind} b {{by=second}}\n"
	key = "same" if kind == "=" else "distinct"
	resolved = state(text)
	assert [claim["by"] for claim in resolved.claims if key in claim] == ["first", "second"]
	resolved = state(text + f"- a {kind} b {{by=second}}\n")
	assert [claim["by"] for claim in resolved.claims if key in claim] == ["first"]
	printed = printObservationsState(ONTOLOGY, resolved)
	assert formatObservations(ONTOLOGY, Source("t", printed)) == printed


def testDeterministicReplayAuditPreservesClaimsAndFormatting():
	random = Random(13)
	statements = ["p.Name A", "p.Name B", "p.Name ?", "p.Name null", "p.Values 1", "p.Values 2",
		"p.Values [1]", "p.Values [2]", "p.Values [1, ...]", "- p.Name", "- p.Values 1"]

	for _ in range(120):
		text = "p:Person\n" + "\n".join(random.choice(statements) + " {src=" + random.choice(["a", "b"]) + "}" for _ in range(random.randrange(1, 9))) + "\n"
		log = load(text)
		resolved = reconcileObservations(ONTOLOGY, log)
		assert observationsToJson(observationsFromJson(ONTOLOGY, observationsToJson(log))) == observationsToJson(log)
		printed = printObservationsState(ONTOLOGY, resolved)
		loaded = reconcileObservations(ONTOLOGY, loadObservations(ONTOLOGY, Source("t", printed)))
		assert semanticClaims(loaded) == semanticClaims(resolved)
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
