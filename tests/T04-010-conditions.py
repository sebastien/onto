"""Conditions of bindings and mappings: tests with alternatives, `&`, `|` and groups (spec-04 Conditions)."""

from __future__ import annotations

import pytest
from jsonschema import ValidationError

from onto.conditions import conditionFromJson, conditionOutcome, conditionPaths, parseCondition, printCondition
from tests.helpers import schemaValidator

# -----------------------------------------------------------------------------
#
# TEXT
#
# -----------------------------------------------------------------------------


def test_a_single_test_keeps_its_form():
	assert parseCondition("Class:F", binding=False) == {"path": ["Class"], "value": "F"}
	assert parseCondition("Class : F", binding=False) == {"path": ["Class"], "value": "F"}


def test_alternatives_are_values_of_one_test():
	assert parseCondition("AssetType:Home|Investment", binding=False) == {"path": ["AssetType"], "values": ["Home", "Investment"]}


def test_and_binds_tighter_than_or():
	assert parseCondition("A:x | B:y & C:z", binding=False) == {"any": [
		{"path": ["A"], "value": "x"}, {"all": [{"path": ["B"], "value": "y"}, {"path": ["C"], "value": "z"}]}]}


def test_groups_and_flattening():
	assert parseCondition("Kind:Home|Investment & (Offered:true | Replaced:true)", binding=False) == {"all": [
		{"path": ["Kind"], "values": ["Home", "Investment"]},
		{"any": [{"path": ["Offered"], "value": "true"}, {"path": ["Replaced"], "value": "true"}]}]}
	# A group of the same operator adds nothing; a group of one test is the test.
	assert parseCondition("A:x & (B:y & C:z)", binding=False) == {"all": [
		{"path": ["A"], "value": "x"}, {"path": ["B"], "value": "y"}, {"path": ["C"], "value": "z"}]}
	assert parseCondition("(A:x)", binding=False) == {"path": ["A"], "value": "x"}


@pytest.mark.parametrize("text", [
	"Class:F",
	"AssetType:Home|Investment",
	"A:x | B:y",
	"A:x & B:y",
	"A:x | B:y & C:z",
	"Kind:Home|Investment & (Offered:true | Replaced:true)",
	"Application.Deleted:false & (Advice.Type:Mortgage|Both | Assets.Provider:AMP)",
])
def test_normal_form_is_stable(text):
	condition = parseCondition(text, binding=False)
	assert printCondition(condition, binding=False) == text
	assert parseCondition(printCondition(condition, binding=False), binding=False) == condition


def test_binding_conditions_read_document_paths():
	assert parseCondition('row."asset class":Home|Car', binding=True) == {"path": ["row", "asset class"], "values": ["Home", "Car"]}
	assert parseCondition("^.status:Closed & items[*].kind:A", binding=True) == {"all": [
		{"path": [{"up": 1}, "status"], "value": "Closed"}, {"path": ["items", {"each": True}, "kind"], "value": "A"}]}
	assert printCondition(parseCondition('"asset class":Home', binding=True), binding=True) == '"asset class":Home'


def test_paths_are_listed_in_order():
	assert conditionPaths(parseCondition("A:x | B.C:y & D:z", binding=False)) == [["A"], ["B", "C"], ["D"]]


def test_a_path_alone_tests_that_it_has_a_value():
	assert parseCondition("Details.PurchasePrice", binding=False) == {"path": ["Details", "PurchasePrice"]}
	assert parseCondition("Price | New:true & Street", binding=False) == {"any": [
		{"path": ["Price"]}, {"all": [{"path": ["New"], "value": "true"}, {"path": ["Street"]}]}]}
	assert printCondition(parseCondition("Price | New:true & Street", binding=False), binding=False) == "Price | New:true & Street"
	assert conditionFromJson({"path": ["Price"]}, binding=False) == {"path": ["Price"]}


@pytest.mark.parametrize("text", [
	"Class:",  # empty value
	"A:x|B:y",  # alternatives cannot hide a second test: `:` is not part of a value
	"A:x| B:y",  # an operator needs whitespace on both sides
	"A:x |B:y",
	"A:x & ",
	"(A:x | B:y",  # unclosed group
	"A:x | B:y)",
	"A:x|x",  # a value listed twice
	"concat(A):x",  # a test reads a path
	"A:x\nB:y",
])
def test_invalid_conditions_are_rejected(text):
	with pytest.raises(ValueError):
		parseCondition(text, binding=False)


# -----------------------------------------------------------------------------
#
# JSON
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("data", [
	{"path": ["Class"], "value": "F"},
	{"path": ["Class"]},
	{"path": ["Kind"], "values": ["Home", "Investment"]},
	{"all": [{"path": ["A"], "value": "x"}, {"any": [{"path": ["B"], "value": "y"}, {"path": ["C"], "value": "z"}]}]},
])
def test_json_round_trips(data):
	assert conditionFromJson(data, binding=False) == data


@pytest.mark.parametrize("data", [
	{"path": ["Kind"], "values": ["Home"]},  # one value is `value`
	{"path": ["Kind"], "value": "A", "values": ["B", "C"]},
	{"path": ["Kind"], "values": []},  # a test of having a value lists none
	{"path": ["Kind"], "value": "a b"},
	{"path": ["Kind"], "value": "A|B"},
	{"all": [{"path": ["A"], "value": "x"}]},  # one operand
	{"all": [{"path": ["A"], "value": "x"}, {"all": [{"path": ["B"], "value": "y"}, {"path": ["C"], "value": "z"}]}]},  # not flat
	{"any": [], "all": []},
	{"path": ["A"], "value": "x", "extra": True},
])
def test_invalid_json_is_rejected(data):
	with pytest.raises(ValueError):
		conditionFromJson(data, binding=False)


@pytest.mark.parametrize("operator", ["all", "any"])
def test_schema_rejects_direct_nesting_of_the_same_operator(operator):
	test = {"path": ["Price"]}
	data = {operator: [test, {operator: [test, test]}]}
	validator = schemaValidator("mapping").evolve(schema={"$ref": "#/$defs/when"})
	assert validator.is_valid({operator: [test, test]})
	with pytest.raises(ValidationError):
		validator.validate(data)


# -----------------------------------------------------------------------------
#
# OUTCOMES
#
# -----------------------------------------------------------------------------


# What a read selects: `Key` is ClientId, `Kind` Home or Investment, `Note` nothing; anything else is unknown.
KNOWN = {"Key": {"ClientId"}, "Kind": {"Home", "Investment"}, "Note": set()}


@pytest.mark.parametrize(("text", "outcome"), [
	("Key:ClientId", True),
	("Key:MortgageApplicationId", False),
	("Key:ClientId|GroupId", True),
	("Kind:Home", None),  # Home or Investment: it may be Home
	("Kind:Car", False),
	("Key", True),  # a known value is a value
	("Note", False),  # known to have none
	("Note:x", False),
	("Status:Active", None),  # not known
	("Key:ClientId & Status:Active", None),
	("Key:GroupId & Status:Active", False),  # one test fails the conjunction
	("Key:GroupId | Status:Active", None),
	("Key:GroupId | Kind:Car", False),
	("Key:ClientId | Status:Active", True),  # one test settles the alternative
	("(Key:GroupId | Kind:Car) & Status:Active", False),
])
def test_a_condition_holds_fails_or_may_hold_knowing_some_values(text, outcome):
	assert conditionOutcome(parseCondition(text, binding=False), lambda path: KNOWN.get(".".join(path))) is outcome

# EOF
