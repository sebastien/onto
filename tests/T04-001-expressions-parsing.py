"""Module: expression tests — shared spec-04 binding and mapping expressions."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from onto import expressionFromJson, parseExpression, printExpression
from onto.text import splitAnnotations

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


SCHEMA = json.loads(Path("src/json/mapping.schema.json").read_text())
VALIDATOR = Draft202012Validator({"$ref": "#/$defs/expr", "$defs": SCHEMA["$defs"]})


# -----------------------------------------------------------------------------
#
# PARSING AND NORMAL FORMS
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
	("Instrument.Isin", {"path": ["Instrument", "Isin"]}),
	("$valid", {"meta": "valid"}),
	("$at", {"meta": "at"}),
	("$src", {"meta": "src"}),
	("?", {"unknown": True}),
	("null", {"null": True}),
	("true", {"boolean": True}),
	("false", {"boolean": False}),
	("+005.2500", {"number": "5.25"}),
	("-0e10", {"number": "0"}),
	("1.250e+03", {"number": "1.25e3"}),
	('"text, with ?? syntax"', {"text": "text, with ?? syntax"}),
	('""', {"text": ""}),
	("multiply(Price, Quantity)", {"call": "multiply", "args": [{"path": ["Price"]}, {"path": ["Quantity"]}]}),
	("M/FrequencyFromInterval(PaymentInterval)", {"call": "M/FrequencyFromInterval", "args": [{"path": ["PaymentInterval"]}]}),
	("Local()", {"call": "Local", "args": []}),
	("A ?? B ?? ?", {"coalesce": [{"path": ["A"]}, {"path": ["B"]}, {"unknown": True}]}),
])
def testMappingExpressionsMatchTheirJsonEncoding(text: str, expected: dict):
	parsed = parseExpression(text)
	assert parsed == expected
	VALIDATOR.validate(parsed)
	assert parseExpression(printExpression(parsed)) == parsed
	assert expressionFromJson(parsed) == parsed


@pytest.mark.parametrize(("text", "expected"), [
	("instruments[*].dividends[*]", {"path": ["instruments", {"each": True}, "dividends", {"each": True}]}),
	("$[*]", {"path": [{"root": True}, {"each": True}]}),
	("$.rows[0].code", {"path": [{"root": True}, "rows", {"index": 0}, "code"]}),
	("^", {"path": [{"up": 1}]}),
	("^.^.isin", {"path": [{"up": 2}, "isin"]}),
	('row."asset class"', {"path": ["row", "asset class"]}),
	('"asset class"', {"path": ["asset class"]}),
	('"true"', {"path": ["true"]}),
	("$format", {"meta": "format"}),
	("ref(Issuer, issuerId)", {"call": "ref", "args": [{"path": ["Issuer"]}, {"path": ["issuerId"]}]}),
	('date(payableDate, "YYYYMMDD")', {"call": "date", "args": [{"path": ["payableDate"]}, {"text": "YYYYMMDD"}]}),
	('code ?? "fallback"', {"coalesce": [{"path": ["code"]}, {"text": "fallback"}]}),
])
def testBindingPathsAndStringContexts(text: str, expected: dict):
	parsed = parseExpression(text, binding=True)
	assert parsed == expected
	VALIDATOR.validate(parsed)
	assert parseExpression(printExpression(parsed, binding=True), binding=True) == parsed


def testBindingAnnotationStringsAreLiteralsNotQuotedFields():
	assert parseExpression('"fixed key"', binding=True, field=False) == {"text": "fixed key"}
	assert printExpression({"text": "fixed key"}, binding=True, field=False) == '"fixed key"'


def testNestedCallsKeepCommasCoalescingAndEscapedQuotesInsideStrings():
	text = 'concat(^.isin, "/, ??", trim(name ?? ticker), "a\\\"b")'
	parsed = parseExpression(text, binding=True)
	assert parsed["args"][1] == {"text": "/, ??"}
	assert parsed["args"][2] == {"call": "trim", "args": [{"coalesce": [{"path": ["name"]}, {"path": ["ticker"]}]}]}
	assert parsed["args"][3] == {"text": 'a"b'}
	assert printExpression(parsed, binding=True) == text


@pytest.mark.parametrize("binding", [False, True])
def testWhitespaceNormalisesWithoutChangingExpressionMeaning(binding: bool):
	parsed = parseExpression('  concat( A  ,trim( B ?? C ) )  ', binding=binding)
	assert printExpression(parsed, binding=binding) == "concat(A, trim(B ?? C))"


def testEveryAssignedExpressionInTheFourSpecExampleFilesRoundTrips():
	spec = Path("docs/specs/spec-04-mapping.md").read_text()
	files = []
	for block in spec.split("```text\n")[1:]:
		text = block.split("```", 1)[0]
		if not text.startswith(("@binding Exchange rev=", "@binding Sheet rev=", "@mapping Exchange -> Finance from=", "@mapping Finance -> Sheet from=")):
			continue
		files.append(text)
		binding = text.startswith("@binding")
		for line in text.splitlines():
			if " <- " not in line:
				continue
			_, value = line.split(" <- ", 1)
			value, _ = splitAnnotations(value)
			parsed = parseExpression(value, binding=binding)
			VALIDATOR.validate(parsed)
			assert parseExpression(printExpression(parsed, binding=binding), binding=binding) == parsed
	assert len(files) == 4


# -----------------------------------------------------------------------------
#
# VALIDATION
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
	"", " ", "A B", "A.", ".A", "A..B", "f(A,)", "f(,A)", "f(A", "f(A))",
	"f(A)B", "A ??", "?? A", "A ? B", "(A)", "A + B", "A, B", "1e", "NaN!",
	'"unterminated', '"bad\\x"', "A\nB", "A\r", "A {candidate}", "A // comment",
	"1e99999999999999999999",
])
def testMalformedExpressionsAreRejected(text: str):
	with pytest.raises(ValueError):
		parseExpression(text, binding=True)


@pytest.mark.parametrize("text", ["a[*]", "a[0]", "$", "$.a", "^", "^.a", 'row."quoted"', '"quoted".field', "$format"])
def testMappingExpressionsRejectDocumentOnlySyntax(text: str):
	with pytest.raises(ValueError):
		parseExpression(text)


@pytest.mark.parametrize("text", ["$valid", "$at", "$src", "a[-1]", "a[1.0]", "a[]", "[*]", "a.^", "a.$", "$.$", '"".a'])
def testBindingExpressionsRejectInvalidPathsAndMappingMetadata(text: str):
	with pytest.raises(ValueError):
		parseExpression(text, binding=True)


@pytest.mark.parametrize("data", [
	None, "A", [], {}, {"path": []}, {"path": [""]}, {"path": [1]},
	{"path": [{"index": True}]}, {"path": [{"index": -1}]}, {"path": [{"each": False}]},
	{"path": [{"up": 0}]}, {"path": [{"root": 1}]}, {"path": ["a", {"root": True}]},
	{"number": "5.0"}, {"number": "+5"}, {"number": "-0"}, {"number": 5},
	{"text": 1}, {"boolean": 1}, {"null": False}, {"unknown": 1},
	{"call": "f"}, {"call": "bad.name", "args": []}, {"call": "f", "args": {"path": ["A"]}},
	{"coalesce": [{"path": ["A"]}]}, {"meta": "invalid"},
	{"path": ["A"], "doc": "extra"}, {"text": "x", "number": "1"},
	{"call": "f", "args": [{"unknown": False}]},
])
def testJsonRejectsMalformedNonCanonicalAndExtraMembers(data: object):
	with pytest.raises(ValueError):
		expressionFromJson(data, binding=True)


def testJsonAndPrintingNeverMutateTheInputOrRetainItsContainers():
	data = {"call": "f", "args": [{"path": ["a", {"index": 0}]}]}
	before = deepcopy(data)
	loaded = expressionFromJson(data, binding=True)
	assert printExpression(data, binding=True) == "f(a[0])"
	assert data == before
	loaded["args"][0]["path"][1]["index"] = 1
	assert data == before


def testWholeBindingStringLiteralCannotMasqueradeAsAQuotedField():
	with pytest.raises(ValueError, match="field"):
		expressionFromJson({"text": "constant"}, binding=True)
	assert expressionFromJson({"text": "constant"}, binding=True, field=False) == {"text": "constant"}


# EOF
