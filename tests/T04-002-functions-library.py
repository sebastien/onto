"""Module: function library tests — spec-04 declarations, signatures and interchange."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

import onto.functions as functions
from onto import FormatError, Source, loadOntology, FunctionsOperator, formatFunctions, functionsFromJson, functionsToJson, loadFunctions, parseFunctions, printFunctions, resolveFunctions
from onto.functions.operations import Operator
from tests._helpers import _schemaValidator, _specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


DIMENSIONS = loadOntology([Source("dimensions.onto", """@ontology Dimensions
InterestFrequency = Biannually|Monthly|Quarterly|Yearly
Months = Integer {unit=Month}
Person
Scenario
Review of Person {ctx=Scenario}
""")])
ONTOLOGIES = [DIMENSIONS]


def load(text: str):
	return loadFunctions(ONTOLOGIES, [Source("test.fn", text)])


# -----------------------------------------------------------------------------
#
# SPECIFICATION AND NORMAL FORMS
#
# -----------------------------------------------------------------------------


def testCompleteMarketsLibraryFromTheSpecification():
	text = _specExample("spec-04-mapping", 3)
	doc = parseFunctions([Source("markets.fn", text)])
	assert doc.functions[0].loc.file == "markets.fn"
	assert doc.functions[0].result.path == "Dimensions/InterestFrequency"
	library = resolveFunctions(ONTOLOGIES, doc)
	data = functionsToJson(library)
	_schemaValidator("mapping").validate(data)
	assert data["format"] == "onto.functions/1"
	assert data["functions"][0]["examples"] == [
		{"args": ["1"], "result": "Monthly"}, {"args": ["12"], "result": "Yearly"},
		{"args": ["3"], "result": "Quarterly"}, {"args": ["6"], "result": "Biannually"}]
	printed = printFunctions(library)
	assert printed == text
	assert formatFunctions(ONTOLOGIES, [Source("t", printed)]) == printed
	assert functionsToJson(functionsFromJson(ONTOLOGIES, data)) == data


def testJsonExcerptFromSpecificationRequiresItsOmittedInverse():
	# This structurally valid excerpt is not a complete executable library.
	data = _specExample("spec-04-mapping", 2, "json")
	value = json.loads(data)
	_schemaValidator("mapping").validate(value)
	with pytest.raises(FormatError, match="inverse"):
		functionsFromJson(ONTOLOGIES, value)


def testLibrarySpansFilesWithForwardInversesAndFileLocalAliases():
	first = Source("one.fn", "@functions Markets rev=v1\n@use Dimensions as D\n@fn Forward Integer -> D/InterestFrequency {inverse=Backward}\n  6 => Biannually\n")
	second = Source("two.fn", "@functions Markets rev=v1\n@use Dimensions as Other\n@fn Backward Other/InterestFrequency -> Integer {inverse=Forward}\n  Biannually => 6\n")
	library = loadFunctions(ONTOLOGIES, [first, second])
	assert len(library.functions) == 2
	printed = printFunctions(library)
	assert "@use Dimensions as D\n@use Dimensions as Other\n" in printed
	assert printed.index("@fn Backward") < printed.index("@fn Forward")
	assert functionsToJson(loadFunctions(ONTOLOGIES, [Source("t", printed)])) == functionsToJson(library)


def testAliasChoiceIsIndependentOfDeclarationAndFileOrder():
	first = Source("a", "@functions Markets\n@use Dimensions as Z\n@fn F Z/Person -> Z/Person\n  p => p\n")
	second = Source("b", "@functions Markets\n@use Dimensions as A\n@fn G A/Scenario -> A/Scenario\n  q => q\n")
	text = formatFunctions(ONTOLOGIES, [first, second])
	assert text == formatFunctions(ONTOLOGIES, [second, first])
	assert "@fn F A/Person -> A/Person" in text
	assert formatFunctions(ONTOLOGIES, [Source("t", text)]) == text


@pytest.mark.parametrize(("signature", "example", "expected"), [
	("Integer -> Number", "+0002.00 => 2e0", {"args": ["2"], "result": "2"}),
	("Text, Text -> Text", '"a,b", "=>" => "a,b => x"', {"args": ["a,b", "=>"], "result": "a,b => x"}),
	("Boolean -> Boolean", "true => false", {"args": [True], "result": False}),
	("Date -> DateTime", "2026-11-12 => 2026-11-12T00:00:00Z", {"args": ["2026-11-12"], "result": "2026-11-12T00:00:00Z"}),
	("Number* -> Number*", "[2, 1e3, ...] => []", {"args": [{"set": ["1e3", "2"], "partial": True}], "result": {"set": []}}),
	("D/Person -> D/Person", "p => q", {"args": [{"ref": "p"}], "result": {"ref": "q"}}),
	("Text -> Text", '"?" => "null"', {"args": ["?"], "result": "null"}),
	("Text -> Text", '" -- doc" => " {value}"', {"args": [" -- doc"], "result": " {value}"}),
	("Number -> Number", "? => null", {"args": [{"unknown": True}], "result": None}),
])
def testTypedExampleValuesRoundTrip(signature: str, example: str, expected: dict):
	library = load(f"@functions Markets\n@use Dimensions as D\n@fn Convert {signature} {{nulls}}\n  {example}\n")
	data = functionsToJson(library)
	assert data["functions"][0]["examples"] == [expected]
	_schemaValidator("mapping").validate(data)
	assert functionsToJson(functionsFromJson(ONTOLOGIES, data)) == data
	printed = printFunctions(library)
	assert formatFunctions(ONTOLOGIES, [Source("t", printed)]) == printed


def testJsonCollectionOrderIsNotExampleMeaning():
	library = load("@functions Markets\n@fn F Text* -> Number*\n  [a, b] => [1, 2]\n")
	data = functionsToJson(library)
	data["functions"][0]["examples"][0]["args"][0]["set"].reverse()
	data["functions"][0]["examples"][0]["result"]["set"].reverse()
	assert functionsToJson(functionsFromJson([], data)) == functionsToJson(library)


@pytest.mark.parametrize("value", ["a[b", "a]b", "a,b", "a => b", "a -- doc", "a // comment", "a {value}", "...", "line\nbreak"])
def testExampleDelimitersRemainLiteralText(value: str):
	library = load(f"@functions Markets\n@fn F Text -> Text\n  {json.dumps(value)} => {json.dumps(value)}\n")
	data = functionsToJson(library)
	assert functionsToJson(functionsFromJson([], data)) == data
	text = printFunctions(library)
	assert formatFunctions([], [Source("t", text)]) == text


def testOperatorRetainsOntologyContextAndOperationsArePure():
	ops = FunctionsOperator(ONTOLOGIES)
	library = ops.load([Source("markets.fn", _specExample("spec-04-mapping", 3))])
	before = deepcopy(library)
	data = ops.toJson(library)
	assert ops.print(library) == ops.format([Source("t", ops.print(library))])
	assert ops.toJson(ops.fromJson(data)) == data
	assert ops.resolve(ops.parse([Source("t", ops.print(library))])).namespace == "Markets"
	assert library == before
	data["functions"][0]["examples"][0]["args"][0] = "changed"
	assert library == before
	with pytest.raises(FormatError, match="Dimensions"):
		FunctionsOperator([]).load([Source("t", _specExample("spec-04-mapping", 3))])


def testFeatureFacadeAndModuleApiAreCompatible():
	assert functions.FunctionsOperator is functions.Operator is FunctionsOperator is Operator
	assert functions.loadFunctions is loadFunctions


# -----------------------------------------------------------------------------
#
# ERRORS AND STRICT JSON
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
	"", "@functions Markets\n", "@fn F Integer -> Integer\n  1 => 1\n",
	"@functions Markets extra=v\n@fn F Integer -> Integer\n  1 => 1\n",
	"@functions Markets\n@fn F Integer -> Integer\n",
	"@functions Markets\n@fn lower Text -> Text\n  X => x\n",
	"@functions Markets\n@fn F Integer -> Integer {unknown}\n  1 => 1\n",
	"@functions Markets\n@fn F Integer -> Integer {nulls=false}\n  1 => 1\n",
	"@functions Markets\n@fn F Integer -> Integer {inverse=Nope}\n  1 => 1\n",
	"@functions Markets\n@fn F Integer -> Integer\n  1, 2 => 1\n",
	"@functions Markets\n@fn F Integer -> Integer\n  1.5 => 1\n",
	"@functions Markets\n@fn F Number* -> Number\n  [1000, 1e3] => 1\n",
	"@functions Markets\n@fn F Missing -> Integer\n  X => 1\n",
	"@functions Markets\n@use Dimensions as D\n@fn F D/Review -> Integer\n  X => 1\n",
	"@functions Markets\n@use Dimensions as D\n@fn F D/InterestFrequency -> Integer\n  Unknown => 1\n",
	"@functions Markets\n@use Dimensions as D\n@fn F D/Missing -> Integer\n  X => 1\n",
	"@functions Markets\n@fn F Text -> Text\n  a, => b\n",
	"@functions Markets\n@fn F Text -> Text\n  a => b => c\n",
	"@functions Markets\n@fn F Text -> Text\n    a => b\n",
	"@functions Markets\n@fn F Text -> Text\n\ta => b\n",
	"@functions Markets\r\n@fn F Text -> Text\r\n  a => b\r\n",
	"@functions Markets\n@fn F Text -> Text\n  a => b\n@fn F Text -> Text\n  a => b\n",
])
def testInvalidLibrariesFailWithDiagnostics(text: str):
	with pytest.raises(FormatError) as caught:
		load(text)
	assert caught.value.diagnostics


@pytest.mark.parametrize("second", [
	"@functions Other rev=v1\n@fn G Integer -> Integer\n  1 => 1\n",
	"@functions Markets rev=v2\n@fn G Integer -> Integer\n  1 => 1\n",
	"@functions Markets rev=v1\n@fn F Integer -> Integer\n  1 => 1\n",
])
def testIncompatibleFilesAreRejected(second: str):
	with pytest.raises(FormatError):
		loadFunctions([], [Source("a", "@functions Markets rev=v1\n@fn F Integer -> Integer\n  1 => 1\n"), Source("b", second)])


def testInverseSignaturesMustBeReversedButImplementationsAreNotExecuted():
	with pytest.raises(FormatError, match="signature"):
		load("@functions Markets\n@fn F Text -> Integer {inverse=G}\n  one => 1\n@fn G Integer -> Boolean\n  1 => true\n")
	# These examples would fail an executable conformance run; declarations do not implement functions.
	assert len(load("@functions Markets\n@fn F Text -> Integer {inverse=G}\n  one => 1\n@fn G Integer -> Text\n  1 => two\n").functions) == 2


def testExampleReferenceTypingIsCheckedWithoutSharingRegistriesBetweenFixtures():
	library = load("@functions Markets\n@use Dimensions as D\n@fn First D/Person -> D/Person\n  p:D/Person => p\n@fn Second D/Scenario -> D/Scenario\n  p:D/Scenario => p\n")
	assert len(library.functions) == 2
	assert functionsToJson(functionsFromJson(ONTOLOGIES, functionsToJson(library))) == functionsToJson(library)
	with pytest.raises(FormatError, match="incompatible"):
		load("@functions Markets\n@use Dimensions as D\n@fn F D/Person -> D/Scenario\n  p:D/Person => p\n")


def testDuplicateOntologyContextsDoNotSilentlyResolveAmbiguousTypes():
	with pytest.raises(FormatError, match="distinct namespaces"):
		loadFunctions([DIMENSIONS, DIMENSIONS], [Source("t", _specExample("spec-04-mapping", 3))])


@pytest.mark.parametrize("signature", ["any -> Text", "Text -> any", "any* -> Text", "Text -> any*"])
def testDeclaredFunctionsRequireConcreteSignatures(signature: str):
	with pytest.raises(FormatError, match="reserved for built-ins"):
		parseFunctions([Source("t", f"@functions Markets\n@fn F {signature}\n  p => p\n")])


@pytest.mark.parametrize("change", [
	lambda data: data.update(extra=True),
	lambda data: data.update(header={"rev": None}),
	lambda data: data.update(functions=[]),
	lambda data: data["functions"][0].update(extra=True),
	lambda data: data["functions"][0].update(args=[]),
	lambda data: data["functions"][0]["args"][0].update(collection=False),
	lambda data: data["functions"][0]["args"][0].update(path="Dimensions/Months"),
	lambda data: data["functions"][0].update(args=[{"any": True}]),
	lambda data: data["functions"][0].update(ann={"nulls": False}),
	lambda data: data["functions"][0].update(doc="line\nbreak"),
	lambda data: data["functions"][0]["examples"][0].update(args=[1]),
	lambda data: data["functions"][0]["examples"][0].update(args=["1.0"]),
	lambda data: data["functions"][0]["examples"][0].update(extra=True),
])
def testJsonRejectsInvalidShapesAndNonCanonicalExamples(change):
	data = functionsToJson(load("@functions Markets\n@fn F Integer -> Text\n  1 => One\n"))
	change(data)
	with pytest.raises(FormatError):
		functionsFromJson(ONTOLOGIES, data)


# EOF
