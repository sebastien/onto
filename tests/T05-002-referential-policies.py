"""Module: referential policy tests — spec-05 declarations, inheritance and mapping key checks."""

from __future__ import annotations

from copy import deepcopy
import json
import re

import pytest

import onto.referential as referentialApi
from onto import FormatError, Source, loadMapping, loadOntology, ReferentialOperator, ReferentialPolicy, formatReferential, loadReferential, parseReferential, printReferential, referentialFromJson, referentialImplicit, referentialPolicy, referentialToJson, validateReferential
from tests._helpers import _schemaValidator, _specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


FINANCE = loadOntology([Source("finance.onto", _specExample("spec-01-ontology"))])
EXCHANGE = loadOntology([Source("exchange.onto", _specExample("spec-04-mapping", 1))])
TARGET = loadOntology([Source("t.onto", """@ontology T rev=v1
Party
  Code Text {key}
  Email Text {key}
  Name Text
Person < Party
Employee < Person
Company < Party
Scenario
Review of Person {ctx=Scenario}
  Included Boolean
Person -knows-> Person
Membership(Party, Person)
  Code Text {key}
Scalar = Text
""")])
SOURCE = loadOntology([Source("s.onto", "@ontology S rev=v2\nRow\n  Code Text\n  Email Text\n  Name Text\n")])
ONTOLOGIES = [TARGET, SOURCE]


def load(text: str):
	return loadReferential(ONTOLOGIES, [Source("test.ref", "@referential Ids rev=v1\n@use T as T\n" + text)])


# -----------------------------------------------------------------------------
#
# SPECIFICATION AND INTERCHANGE
#
# -----------------------------------------------------------------------------


def testCompleteSpecReferentialAndJsonExcerptRoundTrip():
	text = _specExample("spec-05-identities")
	ref = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", text)])
	assert ref.policies[0].loc.file == "market-ids.ref"
	data = referentialToJson(ref)
	_schemaValidator("referential").validate(data)
	assert data["policies"][-1]["minted"] is True
	assert printReferential(ref) == re.sub(r"[ \t]+--", " --", text)
	assert referentialToJson(referentialFromJson([FINANCE, EXCHANGE], data)) == data
	excerpt = json.loads(_specExample("spec-05-identities", kind="json"))
	assert referentialToJson(referentialFromJson([FINANCE, EXCHANGE], excerpt)) == excerpt


def testFilesUseLocalAliasesAndCanonicalOutputIsIndependentOfFileOrder():
	a = Source("a.ref", "@referential Ids rev=v1\n@use T as Z\nZ/Person key=Email,Code from=S implicit=PT0.5S -- Person\n")
	b = Source("b.ref", "@referential Ids rev=v1\n@use T as A\nA/Company key=Code\n")
	first = loadReferential(ONTOLOGIES, [a, b])
	second = loadReferential(ONTOLOGIES, [b, a])
	assert printReferential(first) == printReferential(second)
	assert "A/Person key=Email,Code from=S implicit=PT0.5S" in printReferential(first)
	assert referentialToJson(first)["policies"][1]["keys"] == ["Email", "Code"]
	assert formatReferential(ONTOLOGIES, [Source("t", printReferential(first))]) == printReferential(first)


def testIdentityPoliciesAndImplicitAgesInheritIndependently():
	ref = load("T/Party key=Code implicit=P7D\nT/Person implicit=P2D\nT/Employee implicit=never\n")
	assert referentialPolicy(ONTOLOGIES, ref, "T/Employee").type == "T/Party"
	assert referentialImplicit(ONTOLOGIES, ref, "T/Employee") == "never"
	assert referentialImplicit(ONTOLOGIES, ref, "T/Person") == "P2D"
	assert referentialImplicit(ONTOLOGIES, ref, "T/Company") == "P7D"
	assert referentialPolicy(ONTOLOGIES, ref, "T/Scenario") is None
	assert referentialImplicit(ONTOLOGIES, ref, "T/Scenario") is None


def testASeparateAgeLineDoesNotBecomeASecondIdentityPolicy():
	ref = load("T/Person implicit=P2D -- Age\nT/Person key=Email -- Identity\n")
	assert referentialPolicy(ONTOLOGIES, ref, "T/Person").keys == ["Email"]
	assert referentialImplicit(ONTOLOGIES, ref, "T/Employee") == "P2D"
	data = referentialToJson(ref)
	assert referentialToJson(referentialFromJson(ONTOLOGIES, data)) == data
	assert formatReferential(ONTOLOGIES, [Source("t", printReferential(ref))]) == printReferential(ref)


def testAssociationPoliciesAreDeclarationsAndDoNotAllocateAnything():
	ref = load("T/Membership minted key=Code implicit=PT0S\n")
	assert referentialPolicy(ONTOLOGIES, ref, "T/Membership").minted is True
	assert referentialToJson(ref)["policies"][0]["keys"] == ["Code"]
	assert referentialToJson(referentialFromJson(ONTOLOGIES, referentialToJson(ref))) == referentialToJson(ref)


def testOperatorAndValidationArePureAndJsonIsDetached():
	ops = ReferentialOperator(ONTOLOGIES)
	doc = ops.parse([Source("t", "@referential Ids\n@use T as T\nT/Party key=Code\n")])
	before = deepcopy(doc)
	ref = ops.validate(doc)
	assert doc == before
	before = deepcopy(ref)
	data = ops.toJson(ref)
	assert ops.toJson(ops.fromJson(data)) == data
	assert ops.format([Source("t", ops.print(ref))]) == ops.print(ref)
	assert ops.policy(ref, "T/Person").keys == ["Code"]
	ops.policy(ref, "T/Person").keys.append("Changed")
	assert ops.implicit(ref, "T/Person") is None
	assert ref == before
	data["policies"][0]["keys"].append("Changed")
	assert ref == before


def testFeatureFacadeAndTopLevelApiShareImplementations():
	assert referentialApi.Operator is referentialApi.ReferentialOperator is ReferentialOperator
	assert referentialApi.Policy is ReferentialPolicy
	assert referentialApi.loadReferential is loadReferential


# -----------------------------------------------------------------------------
#
# VALIDATION
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
	"", "T/Person key=Code\n", "@referential Bad/\n", "@referential Ids extra=yes\n",
	"@referential Ids\r\n", "@referential Ids\n@use T as T\n@use T as T\n",
	"@referential Ids\n@at 2026-11-12\n",
])
def testHeaderDirectiveAndLfErrorsRemainFatal(text: str):
	with pytest.raises(FormatError):
		loadReferential(ONTOLOGIES, [Source("t", text)])


@pytest.mark.parametrize("line", [
	"T/Missing key=Code", "T/Scalar key=Code", "T/Review key=Included", "T/Person.knows.T/Person key=Code",
	"T/Person key=Name", "T/Person key=Missing", "T/Person key=Code,Code", "T/Person key=Code.Name",
	"T/Person key=", "T/Person", "T/Person from=S", "T/Person minted from=S",
	"T/Person key=Code from=Unknown", "T/Person key=Code implicit=P", "T/Person implicit=PT",
	"T/Person implicit=PT.5S", "T/Person implicit=P2DT", "T/Person implicit=P0.5D",
	"T/Person implicit=never implicit=P2D", "T/Person minted minted", "T/Person key=Code extra=yes",
	"T/Person key=Code\nT/Person minted", "T/Person implicit=P2D\nT/Person implicit=P3D",
	"T/Party key=Code\nT/Person key=Email", "T/Person minted\nT/Party key=Code",
	"  T/Person key=Code", "\tT/Person key=Code",
])
def testInvalidPoliciesAreRejected(line: str):
	with pytest.raises(FormatError):
		load(line + "\n")


@pytest.mark.parametrize("second", [
	"@referential Other rev=v1\n", "@referential Ids rev=v2\n",
	"@referential Ids rev=v1\n@use S as T\n",
])
def testIncompatibleFilesAndAliasRedefinitionsFail(second: str):
	with pytest.raises(FormatError):
		loadReferential(ONTOLOGIES, [Source("first", "@referential Ids rev=v1\n@use T as T\nT/Person key=Code\n"), Source("second", second)])


def testUnknownOntologiesAndUnscopedKeysAreNotGuessed():
	with pytest.raises(FormatError):
		loadReferential([TARGET], [Source("t", "@referential Ids\n@use Unknown as U\n")])
	with pytest.raises(FormatError):
		loadReferential(ONTOLOGIES, [Source("t", "@referential Ids\nPerson key=Code\n")])
	with pytest.raises(FormatError):
		referentialPolicy(ONTOLOGIES, load("T/Party key=Code\n"), "T/Missing")


def testRevisionWarningsCompareCoveredTypesNotUnrelatedSourceOntologies():
	ref = load("T/Party key=Code from=S\n")
	assert not ref.diagnostics
	ref = loadReferential(ONTOLOGIES, [Source("t", "@referential Ids rev=old\n@use T as T\nT/Party key=Code from=S\n")])
	assert len([item for item in ref.diagnostics if item.code == "revision"]) == 1
	assert len([item for item in validateReferential(ONTOLOGIES, ref).diagnostics if item.code == "revision"]) == 1


@pytest.mark.parametrize("change", [
	lambda data: data.update(extra=True), lambda data: data.update(header={"rev": None}),
	lambda data: data.update(policies={}), lambda data: data["policies"][0].update(extra=True),
	lambda data: data["policies"][0].update(keys=[]), lambda data: data["policies"][0].update(keys=["Code", "Code"]),
	lambda data: data["policies"][0].update(minted=False), lambda data: data["policies"][0].update(implicit=None),
	lambda data: data["policies"][0].update(doc="a\nb"), lambda data: data["policies"][0].pop("keys"),
])
def testStrictJsonRejectsInvalidShapesAndPolicyVariants(change):
	data = referentialToJson(load("T/Person key=Code\n"))
	change(data)
	with pytest.raises(FormatError):
		referentialFromJson(ONTOLOGIES, data)


# -----------------------------------------------------------------------------
#
# MAPPING KEY VALIDATION
#
# -----------------------------------------------------------------------------


def testMappingsRequireAnAssignedKeyFromTheEffectiveInheritedPolicy():
	ref = load("T/Party key=Code,Email\n")
	text = "@mapping S -> T referential=Ids\nRow -> Employee\n  Name <- Name\n"
	with pytest.raises(FormatError, match="key"):
		loadMapping(SOURCE, TARGET, Source("t", text), referentials=[ref])
	for key in ("Code", "Email"):
		mapping = loadMapping(SOURCE, TARGET, Source("t", text + f"  {key} <- {key}\n"), referentials=[ref])
		assert mapping.header["referential"] == "Ids"


def testCandidatesOnlySupplyKeysWhenEnabled():
	ref = load("T/Party key=Code\n")
	text = "@mapping S -> T referential=Ids\nRow -> Person\n  Code <- Code {candidate}\n"
	with pytest.raises(FormatError, match="key"):
		loadMapping(SOURCE, TARGET, Source("t", text), referentials=[ref])
	assert loadMapping(SOURCE, TARGET, Source("t", text.replace("referential=Ids", "referential=Ids candidates=true")), referentials=[ref])


def testMintedAndAgeOnlyDeclarationsDoNotRequireDerivedKeys():
	text = "@mapping S -> T referential=Ids\nRow -> Person\n  Name <- Name\n"
	for declarations in ("T/Party minted key=Email\n", "T/Party implicit=P2D\n"):
		assert loadMapping(SOURCE, TARGET, Source("t", text), referentials=[load(declarations)])


def testSourceRestrictionsAreRetainedWithoutSkippingStaticKeyValidation():
	ref = load("T/Party key=Code from=T\n")
	text = "@mapping S -> T referential=Ids\nRow -> Person\n  Name <- Name\n"
	with pytest.raises(FormatError, match="key"):
		loadMapping(SOURCE, TARGET, Source("t", text), referentials=[ref])
	assert loadMapping(SOURCE, TARGET, Source("t", text + "  Code <- Code\n"), referentials=[ref])
	assert ref.policies[0].fromNamespace == "T"


def testMappingsRevalidatePoliciesAgainstTheirActualTargetRevision():
	ref = load("T/Party key=Code\n")
	changed = loadOntology([Source("changed", "@ontology T rev=v1\nParty\n  Code Text\nPerson < Party\n")])
	with pytest.raises(FormatError, match="key"):
		loadMapping(SOURCE, changed, Source("t", "@mapping S -> T referential=Ids\nRow -> Person\n  Code <- Code\n"), referentials=[ref])


def testDuplicateLoadedReferentialNamesAreAnError():
	ref = load("T/Party key=Code\n")
	with pytest.raises(FormatError, match="Duplicate loaded referential"):
		loadMapping(SOURCE, TARGET, Source("t", "@mapping S -> T referential=Ids\nRow -> Person\n  Code <- Code\n"), referentials=[ref, ref])


def testNamesAloneNoLongerPretendToValidateReferentialPolicies():
	with pytest.raises(FormatError, match="loaded"):
		loadMapping(SOURCE, TARGET, Source("t", "@mapping S -> T referential=Ids\nRow -> Person\n"), referentials={"Ids"})


# EOF
