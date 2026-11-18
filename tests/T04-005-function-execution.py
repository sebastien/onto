"""Module: function execution tests — exact values, Cartesian application and executable conformance."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, MIN_EMIN, localcontext

import pytest

from onto import FormatError, Source, FunctionsOperator, loadFunctions, loadOntology, FunctionEvaluator, FunctionResult
import onto.functions as functionsApi
from tests.helpers import specExample


def value(name, *args):
	results = FunctionEvaluator().evaluate(name, list(args))
	assert len(results) == 1 and results[0].reason is None, results
	return results[0].value


@pytest.mark.parametrize("name,args,expected", [
	("sum", ["0.1", "0.2"], "0.3"),
	("sum", ["123456789012345678901234567890", "0.00000000001"], "123456789012345678901234567890.00000000001"),
	("sum", ["1e30", "1", "-1e30"], "1"),
	("multiply", ["12345678901234567890", "12345678901234567890"], "152415787532388367501905199875019052100"),
	("multiply", ["0.1", "0.2"], "0.02"),
	("subtract", ["1000000000000000000000000000001", "1e30"], "1"),
	("divide", ["1", "3"], "0.3333333333333333"),
	("divide", ["2", "3"], "0.6666666666666667"),
	("divide", ["1", "1048576"], "0.00000095367431640625"),
	("divide", ["10000000000000000000001", "2"], "5000000000000000000000.5"),
	("number", ["+0005.500"], "5.5"),
])
def testExactDecimalBuiltinsIgnoreAmbientContext(name, args, expected):
	with localcontext() as context:
		context.prec = 2
		context.rounding = "ROUND_UP"
		assert Decimal(value(name, *args)) == Decimal(expected)


@pytest.mark.parametrize("name,args,expected", [
	("concat", ["a", "b"], "ab"), ("trim", [" \tHello\n"], "Hello"),
	("lower", ["ÉCOLE"], "école"), ("upper", ["straße"], "STRASSE"),
	("split", [",b,,a,", ","], {"set": ["a", "b"]}),
	("join", [{"set": ["b", "a"]}, ","], "a,b"),
	("count", [{"set": ["a", "b"]}], "2"),
	("text", [True], "true"), ("text", [{"ref": "p"}], "p"),
	("text", ["a,b"], "a,b"), ("text", ["a=>b"], "a=>b"),
	("date", ["0"], "1970-01-01"), ("date", ["-1"], "1969-12-31"),
	("epoch", ["1970-01-02"], "86400"),
	("date", ["29/02/2024", "DD/MM/YYYY"], "2024-02-29"),
	("datetime", ["2024-02-29 12:30:01Z", "YYYY-MM-DD hh:mm:ssZ"], "2024-02-29T12:30:01Z"),
	("format", ["2024-02-29", "DD.MM.YYYY"], "29.02.2024"),
])
def testBuiltinValues(name, args, expected):
	assert value(name, *args) == expected


@pytest.mark.parametrize("name,args", [
	("divide", ["1", "0"]), ("number", ["NaN"]), ("number", ["1,5"]),
	("sum", [0.1, "0.2"]), ("sum", [True, "1"]), ("split", ["a", ""]),
	("date", ["0.5"]), ("date", ["29/02/2023", "DD/MM/YYYY"]),
	("epoch", ["1970-01-01T01:00:00Z"]), ("count", ["abc"]),
	("epoch", ["1970-W01-1"]), ("count", [{"set": ["a", "a"]}]),
	("sum", [{"set": ["1", "1e0"]}]),
])
def testDomainFailuresAreGapsNotExceptions(name, args):
	result, = FunctionEvaluator().evaluate(name, args)
	assert isinstance(result, FunctionResult) and result.reason
	assert result.value is None


def testUnknownAndNullPropagateWithoutCallingImplementations():
	for absent in (None, {"unknown": True}):
		assert value("lower", absent) == absent
		assert value("sum", "1", absent) == absent
	assert value("sum", None, {"unknown": True}) is None
	assert value("sum", {"unknown": True}, None) is None
	assert value("concat", {"unknown": True}, None) is None


@pytest.mark.parametrize("name,args", [
	("count", [{"set": ["a"], "partial": True}]),
	("join", [{"set": ["a"], "partial": True}, ","]),
])
def testIncompleteCollectionAggregatesAreGaps(name, args):
	assert FunctionEvaluator().evaluate(name, args)[0].reason


def testCartesianApplicationKeepsPerCombinationOutcomesAndDoesNotMutateInputs():
	evaluator = FunctionEvaluator()
	args = [{"set": ["2", "1"]}, {"set": ["10", "20"]}]
	before = deepcopy(args)
	results = evaluator.evaluate("sum", args)
	assert sorted(Decimal(item.value) for item in results) == [Decimal(n) for n in (11, 12, 21, 22)]
	assert args == before
	assert evaluator.evaluate("sum", [{"set": []}, "1"]) == []
	results = evaluator.evaluate("divide", ["1", {"set": ["0", "2"]}])
	assert len(results) == 2 and sum(item.reason is not None for item in results) == 1
	assert next(item.value for item in results if item.reason is None) == "0.5"
	assert all(item.partial for item in evaluator.evaluate("upper", [{"set": ["a"], "partial": True}]))


def testCollectionArgumentsStayWholeAndCollectionResultsStayEncoded():
	results = FunctionEvaluator().evaluate("join", [{"set": ["b", "a"]}, {"set": [",", ";"]}])
	assert {item.value for item in results} == {"a,b", "a;b"}
	assert value("split", "a,a", ",") == {"set": ["a"]}


def testRegisteredSignaturesNullHandlingExceptionsAndDetachedValues():
	library = loadFunctions([], [Source("test.fn", """@functions L
@fn Identity Number -> Number
  1 => 1
@fn NullText Text -> Text {nulls}
  null => missing
@fn Whole Text* -> Integer
  [a, b] => 2
""")])
	seen = []
	def whole(items):
		seen.append(deepcopy(items))
		items["set"].append("mutated")
		return "2"
	evaluator = FunctionEvaluator(libraries=[library], implementations={
		"L/Identity": lambda x: x, "L/NullText": lambda x: "missing", "L/Whole": whole})
	assert evaluator.evaluate("L/Identity", ["1.00"])[0].value == "1"
	assert evaluator.evaluate("L/Identity", ["bad"])[0].reason
	assert evaluator.evaluate("L/NullText", [None])[0].value == "missing"
	args = [{"set": ["a", "b"]}]
	assert evaluator.evaluate("L/Whole", args)[0].value == "2"
	assert args == [{"set": ["a", "b"]}] and len(seen) == 1
	def fail(x):
		raise ValueError("outside domain")
	evaluator.implementations["L/Identity"] = fail
	assert "outside domain" in evaluator.evaluate("L/Identity", ["1"])[0].reason
	evaluator.implementations["L/Identity"] = lambda x: 1.0
	assert evaluator.evaluate("L/Identity", ["1"])[0].reason


def testSpecificationLibraryExamplesAndInverseRoundTripsExecute():
	ontology = loadOntology([Source("d", "@ontology Dimensions\nInterestFrequency = Biannually|Monthly|Quarterly|Yearly\n")])
	library = loadFunctions([ontology], [Source("markets.fn", specExample("spec-04-mapping", 3))])
	forward = {"1": "Monthly", "3": "Quarterly", "6": "Biannually", "12": "Yearly"}
	evaluator = FunctionEvaluator([ontology], [library], implementations={
		"Markets/FrequencyFromInterval": forward.__getitem__,
		"Markets/IntervalFromFrequency": {v: k for k, v in forward.items()}.__getitem__})
	assert evaluator.conformance(library) == 8
	evaluator.implementations["Markets/IntervalFromFrequency"] = lambda x: "1"
	with pytest.raises(FormatError, match="inverse|example"):
		evaluator.conformance(library)


def testConformanceChecksOutputTypesAndSemanticNumericSetEquality():
	library = loadFunctions([], [Source("test.fn", "@functions L\n@fn F Number* -> Number*\n  [1, 2] => [1, 2]\n")])
	evaluator = FunctionEvaluator(libraries=[library], implementations={"L/F": lambda x: {"set": ["2e0", "1.00"]}})
	assert evaluator.conformance(library) == 1
	evaluator.implementations["L/F"] = lambda x: {"set": ["1", "1e0"]}
	with pytest.raises(FormatError):
		evaluator.conformance(library)


def testLocalFunctionsUseLocalNamesAndInverseNeedNotRestoreSpelling():
	library = loadFunctions([], [Source("test.fn", """@functions L
@fn Read Text -> Number {inverse=Write}
  5.50 => 5.5
@fn Write Number -> Text
  5.5 => 5.5
""")])
	evaluator = FunctionEvaluator(functions=library.functions, implementations={"Read": lambda x: x, "Write": lambda x: x})
	assert evaluator.conformance(library.functions) == 2


def testInverseIsExecutedBeyondItsOwnExamples():
	library = loadFunctions([], [Source("test.fn", """@functions L
@fn Forward Text -> Text {inverse=Backward}
  A => a
@fn Backward Text -> Text
  b => B
""")])
	evaluator = FunctionEvaluator(libraries=[library], implementations={"L/Forward": str.lower, "L/Backward": lambda x: "B"})
	with pytest.raises(FormatError, match="inverse round trip"):
		evaluator.conformance(library)


def testValueMapLookupAndMissingValuesProduceGaps():
	ontology = loadOntology([Source("o", """@ontology O
Code = A|B|C
Kind = X|Y
@map Convert Code -> Kind
  A exact X
  B broader Y
""")])
	evaluator = FunctionEvaluator([ontology])
	assert evaluator.evaluate("O/Convert", ["A"])[0].value == "X"
	assert evaluator.evaluate("O/Convert", ["B"])[0].value == "Y"
	assert evaluator.evaluate("O/Convert", ["C"])[0].reason


def testConfigurationErrorsAreNotDomainGaps():
	with pytest.raises(ValueError, match="Unknown"):
		FunctionEvaluator().evaluate("Missing", ["1"])
	with pytest.raises(ValueError, match="argument"):
		FunctionEvaluator().evaluate("sum", [])


def testOperatorAndPublicExportsShareRuntimeAndConformanceIsExplicit():
	assert functionsApi.FunctionEvaluator is FunctionEvaluator
	assert functionsApi.FunctionResult is FunctionResult
	ops = FunctionsOperator([])
	library = ops.load([Source("f", "@functions L\n@fn F Text -> Text\n  a => a\n")])
	before = deepcopy(library)
	assert ops.conformance(library, {"L/F": lambda x: x}) == 1
	assert ops.evaluator().evaluate("sum", ["0.1", "0.2"])[0].value == "0.3"
	assert library == before
	with pytest.raises(FormatError, match="Missing implementation"):
		ops.conformance(library, {})


def testConformanceReportsEveryFailingExampleWithLocations():
	library = loadFunctions([], [Source("examples.fn", "@functions L\n@fn F Number -> Number\n  1 => 1\n  2 => 2\n")])
	evaluator = FunctionEvaluator(libraries=[library], implementations={"L/F": lambda x: "0"})
	with pytest.raises(FormatError) as failure:
		evaluator.conformance(library)
	assert len(failure.value.diagnostics) == 2
	assert {item.loc.line for item in failure.value.diagnostics} == {3, 4}
	assert all(item.loc.file == "examples.fn" for item in failure.value.diagnostics)


@pytest.mark.parametrize("input", [1.0, 1, ["a"], {"unknown": False}, {"set": [None]}, {"set": ["a"], "partial": False}])
def testMalformedValueEncodingFailsAtRuntimeBoundary(input):
	assert FunctionEvaluator().evaluate("text", [input])[0].reason


def testNumericRoundingAcrossSignsAndTinyValues():
	assert Decimal(value("divide", "-2", "3")) == Decimal("-0.6666666666666667")
	assert Decimal(value("divide", "1e-100", "3")) == Decimal("3.333333333333333e-101")
	assert Decimal(value("divide", "2469135780246913.000000000000000001", "2.000000000000000000000000000000000003")) == Decimal("1234567890123457")
	assert Decimal(value("divide", "2469135780246913", "2.000000000000000000000000000000000003")) == Decimal("1234567890123456")


def testUnrepresentableExactProductsAreGapsRatherThanSilentZero():
	tiny = f"1e{MIN_EMIN // 2 - 100}"
	assert FunctionEvaluator().evaluate("multiply", [tiny, tiny])[0].reason


def testDatePatternsHaveLiteralCharactersAndDoNotUseLocaleOrStrftimeEscapes():
	assert value("format", "0001-02-03", "YYYY/MM/DD %Y") == "0001/02/03 %Y"
	assert value("date", "0001/02/03 %Y", "YYYY/MM/DD %Y") == "0001-02-03"
	assert value("datetime", "2024-02-29T01:02:03+02:30", "YYYY-MM-DDThh:mm:ssZ") == "2024-02-29T01:02:03+02:30"
	assert value("format", "2024-02-29T01:02:03+02:30", "YYYY-MM-DDThh:mm:ssZ") == "2024-02-29T01:02:03+02:30"
	for day in ("0001-01-01", "1969-12-31", "2000-02-29", "9999-12-31"):
		assert value("date", value("epoch", day)) == day


def testLocalMapDeclarationsCanBeSuppliedWithoutChangingOntology():
	ontology = loadOntology([Source("o", "@ontology O\nA = X|Y\nB = Z|W\n@map Convert A -> B\n  X exact Z\n")])
	mapping = deepcopy(next(decl for decl in ontology.decls if decl.kind == "map"))
	ontology.decls = [decl for decl in ontology.decls if decl.kind != "map"]
	mapping.path = "LocalMap"
	assert FunctionEvaluator([ontology], maps=[mapping]).evaluate("LocalMap", ["X"])[0].value == "Z"
	assert FunctionEvaluator().evaluate("ref", ["O/Person", "a"])[0].reason


@pytest.mark.parametrize("signature,result", [
	("Text", {"ref": "p"}), ("Integer", "0.5"), ("Boolean", "true"),
	("Text*", "not a collection"),
])
def testImplementationsCannotReturnValuesOutsideTheirSignatures(signature, result):
	example = {"Text": "x", "Integer": "1", "Boolean": "true", "Text*": "[x]"}[signature]
	library = loadFunctions([], [Source("f", f"@functions L\n@fn F {signature} -> {signature}\n  {example} => {example}\n")])
	evaluator = FunctionEvaluator(libraries=[library], implementations={"L/F": lambda x: deepcopy(result)})
	assert evaluator.evaluate("L/F", library.functions[0].examples[0].args)[0].reason


# EOF
