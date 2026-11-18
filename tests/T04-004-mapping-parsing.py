"""Module: mapping tests — spec-04 mapping declarations, static validation and interchange."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

import onto.mapping as mappingApi
from onto import FormatError, Source, loadFunctions, loadOntology, MappingOperator, formatMapping, loadMapping, mappingFromJson, mappingToJson, parseMapping, printMapping, resolveMapping
from onto.referential import loadReferential
from tests._helpers import _schemaValidator, _specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", _specExample("spec-04-mapping", 1))])
FINANCE = loadOntology([Source("finance.onto", _specExample("spec-01-ontology"))])
SHEET = loadOntology([Source("sheet.onto", _specExample("spec-04-mapping", 7))])
SOURCE = loadOntology([Source("source.onto", """@ontology S rev=v1
Name =
  Given Text
  Family Text
Person
  Code Text
  Name Name
  * Tags Text
  Age Integer
  Owner Person
  Context Scenario
  Currency Text
  Pay Amount {cur=USD}
Employee < Person
  Title Text
Scenario
Review of Person {ctx=Scenario}
  Included Boolean
Person -knows/knownBy-> Person 1:*
Event(Who: Person, Other: Person)
Code = X|Y
@map Copy Code -> Code
  X exact X
  Y exact Y
@view Names
  Person.Code
  Person.Name.Given
@view Referenced
  Person.Owner
  Person.Code
@view Nested
  Names
  Person.Tags
""")])
TARGET = loadOntology([Source("target.onto", """@ontology T rev=v2
Label = X|Y
Human
  Code Text
  Name Text
  Age Number
  * Tags Text
  Owner Human
  Cost Amount {cur=EUR}
  Label Label
Scenario
Assessment of Human {ctx=Scenario}
  Included Boolean
Investor of Human
  Rating Text
Human -knows/knownBy-> Human 1:*
Occurrence(Who: Human, Other: Human)
""")])


def load(text: str):
	return loadMapping(SOURCE, TARGET, Source("test.map", "@mapping S -> T\n" + text))


# -----------------------------------------------------------------------------
#
# SPECIFICATION AND INTERCHANGE
#
# -----------------------------------------------------------------------------


def testCompleteExchangeImportFromTheSpecification():
	markets = loadFunctions([FINANCE], [Source("markets.fn", _specExample("spec-04-mapping", 3))])
	ref = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", _specExample("spec-04-mapping", 4))])
	ops = MappingOperator(EXCHANGE, FINANCE, libraries=[markets], referentials=[ref])
	text = _specExample("spec-04-mapping", 5)
	doc = ops.parse(Source("exchange-finance.map", text))
	assert doc.scopes[0].loc.file == "exchange-finance.map"
	mapping = ops.resolve(doc)
	data = ops.toJson(mapping)
	_schemaValidator("mapping").validate(data)
	assert data["format"] == "onto.mapping/1"
	assert data["maps"][0]["path"] == "AssetClassFromCode"
	assert data["maps"][0]["from"] == "Exchange/ClassCode"
	assert data["maps"][0]["to"] == "Dimensions/AssetClass"
	assert ops.print(mapping) == text
	assert ops.toJson(ops.fromJson(data)) == data
	assert ops.format(Source("t", text)) == text


def testCompleteFinanceSheetProjectionFromTheSpecification():
	text = _specExample("spec-04-mapping", 8)
	mapping = loadMapping(FINANCE, SHEET, Source("finance-sheet.map", text))
	data = mappingToJson(mapping)
	_schemaValidator("mapping").validate(data)
	assert data["header"]["view"] == "Finance/PortfolioReview"
	assert printMapping(mapping) == text
	assert mappingToJson(mappingFromJson(FINANCE, SHEET, data)) == data
	assert formatMapping(FINANCE, SHEET, Source("t", text)) == text


def testSpecificationJsonExcerptLoadsWithItsReferencedLocalMap():
	# Supply the excerpt's omitted local map, reference correspondence and referential key assignment.
	data = json.loads(_specExample("spec-04-mapping", 1, "json"))
	markets = loadFunctions([FINANCE], [Source("markets.fn", _specExample("spec-04-mapping", 3))])
	ref = loadReferential([FINANCE, EXCHANGE], [Source("market-ids.ref", _specExample("spec-04-mapping", 4))])
	ops = MappingOperator(EXCHANGE, FINANCE, libraries=[markets], referentials=[ref])
	complete = ops.toJson(ops.load(Source("t", _specExample("spec-04-mapping", 5))))
	data["maps"] = complete["maps"]
	instrument = next(item for item in complete["scopes"] if item["source"] == "Exchange/Instrument")
	data["scopes"][0]["lines"].insert(-1, next(line for line in instrument["lines"] if line.get("target") == "Isin"))
	data["scopes"] += [item for item in complete["scopes"] if item["source"] == "Exchange/Issuer"]
	_schemaValidator("mapping").validate(data)
	assert ops.toJson(ops.fromJson(data)) == data


def testReferencePathsConditionsProvenanceAndProposalFlagsRoundTrip():
	mapping = load('''Person -> Human {when=Code:X} -- People
  [Investor] {candidate, when=Code:X} -- Proposed
  Code <- concat(Code, Owner.Code) {src=Owner.Code, candidate} -- Mixed
  Name <- Owner.Name.Given {reverse}
  Age <- Age
  Owner <- Owner
  knownBy <- Owner
- Person.Currency {reason=out-of-scope} -- Not selected
''')
	data = mappingToJson(mapping)
	_schemaValidator("mapping").validate(data)
	lines = data["scopes"][0]["lines"]
	assert lines[0]["facet"] == "Investor" and lines[0]["candidate"] is True
	assert next(line for line in lines if line.get("target") == "Code")["src"] == "Owner.Code"
	assert next(line for line in lines if line.get("target") == "Name")["reverse"] is True
	assert next(line for line in lines if "verb" in line)["verb"] == "knownBy"
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data
	text = printMapping(mapping)
	assert formatMapping(SOURCE, TARGET, Source("t", text)) == text


def testLocalFunctionAndValueMapSignaturesResolveAgainstTheCorrectOntologies():
	mapping = load('''@use T as O
@fn NameFromCode Code -> Text
  X => Known
@map LabelFromCode Code -> Label -- Local vocabulary map
  Y exact Y
  X exact X
Person -> Human
  Name <- NameFromCode(Copy(Code))
  Label <- LabelFromCode(Copy(Code))
''')
	data = mappingToJson(mapping)
	assert data["functions"][0]["args"] == [{"path": "S/Code"}]
	assert data["maps"][0]["to"] == "T/Label"
	assert next(line for line in data["scopes"][0]["lines"] if line.get("target") == "Name")["expr"]["args"][0]["call"] == "S/Copy"
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data


def testContextsAndAssociationRolesAreDeclarationsNotExecution():
	mapping = load('''Person -> Human {ctx=Context}
  Assessment.Included <- Review.Included
Scenario -> Scenario
Event -> Occurrence
  Who <- Who
''')
	data = mappingToJson(mapping)
	_schemaValidator("mapping").validate(data)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data


def testImplicitContextCorrespondenceAndInheritedInstanceTypesArePreserved():
	mapping = load("Employee -> Human\n  Assessment.Included <- Review.Included\nScenario -> Scenario\n")
	data = mappingToJson(mapping)
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data
	assert not mapping.diagnostics


def testConditionalFacetReadsCanSupplyTheirTranslatedContext():
	mapping = load("Person -> Human\n  [Assessment] {when=Review.Included:true}\nScenario -> Scenario\n")
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, mappingToJson(mapping))) == mappingToJson(mapping)


def testBinaryReferencePathsAndStructuredSelectionsUseTheirDeclaredCardinalities():
	mapping = load("Person -> Human\n  Owner <- knownBy\n  Name <- Name.Given\n")
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, mappingToJson(mapping))) == mappingToJson(mapping)
	with pytest.raises(FormatError, match="collection"):
		load("Person -> Human\n  Owner <- knows\n")


def testSameNamespaceMappingsKeepSourceAndTargetModelsSeparate():
	source = loadOntology([Source("old", "@ontology A rev=old\nPerson\n  Code Text\n")])
	target = loadOntology([Source("new", "@ontology A rev=new\nPerson\n  Code Integer\n")])
	text = "@mapping A -> A from=old to=new\n\nPerson -> Person\n  Code <- number(Code)\n"
	mapping = loadMapping(source, target, Source("t", text))
	assert formatMapping(source, target, Source("t", printMapping(mapping))) == text
	assert mappingToJson(mappingFromJson(source, target, mappingToJson(mapping))) == mappingToJson(mapping)


def testAnUnmappedReferenceCannotSupplyAScalarTarget():
	with pytest.raises(FormatError, match="incompatible"):
		load("Event -> Human\n  Name <- Who\n")


def testSameNamespaceValueMapsUseTheTargetRevisionVocabulary():
	source = loadOntology([Source("old", "@ontology A rev=old\nCode = |Old\nPerson\n  Code Code\n")])
	target = loadOntology([Source("new", "@ontology A rev=new\nCode = |New\nPerson\n  Code Code\n")])
	text = "@mapping A -> A from=old to=new\n@map Convert Code -> Code\n  Old exact New\nPerson -> Person\n  Code <- Convert(Code)\n"
	mapping = loadMapping(source, target, Source("t", text))
	assert mappingToJson(mappingFromJson(source, target, mappingToJson(mapping))) == mappingToJson(mapping)


def testOperatorContextAndAllInterchangeOperationsArePure():
	ops = MappingOperator(SOURCE, TARGET)
	doc = ops.parse(Source("t", "@mapping S -> T\nPerson -> Human\n  Code <- Code\n  Owner <- Owner\n"))
	before = deepcopy(doc)
	mapping = ops.resolve(doc)
	assert doc == before
	before = deepcopy(mapping)
	data = ops.toJson(mapping)
	assert ops.toJson(ops.fromJson(data)) == data
	assert ops.format(Source("t", ops.print(mapping))) == ops.print(mapping)
	assert mapping == before
	data["scopes"][0]["lines"][0]["expr"]["path"].append("Changed")
	assert mapping == before


def testFeatureFacadeAndTopLevelApiShareImplementations():
	assert mappingApi.Operator is mappingApi.MappingOperator is MappingOperator
	assert mappingApi.loadMapping is loadMapping
	assert mappingApi.parseMapping is parseMapping


# -----------------------------------------------------------------------------
#
# STATIC VALIDATION
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
	"Missing -> Human\n", "Person -> Missing\n", "Person -> Human\n  Name <- Missing\n",
	"Person -> Human\n  Missing <- Code\n", "Person -> Human\n  [Missing]\n",
	"Person -> Human\n  Code <- Code\n  Code <- Code {candidate}\n",
	"Person -> Human\n  Name <- Name.Missing\n", "Person -> Human\n  Name <- Owner.Missing\n",
	"Person -> Human\n  Name <- Tags\n", "Person -> Human\n  Age <- Code\n",
	"Person -> Human\n  Cost <- Pay\n", "Person -> Human\n  Code <- Unknown(Code)\n",
	"Person -> Human\n  Code <- Code {src=Currency}\n", "Person -> Human\n  Code <- Code {reverse}\n",
	"Person -> Human\n  Code <- Code {candidate=false}\n", "Person -> Human\n  Code <- Code {null=unknown}\n",
	"Person -> Human\n  Name <- Name.Given {reverse}\n", "Person -> Human\n  Name <- $.name\n",
	"Person -> Human\n  Name <- Code[0]\n", "Person -> Human\n  Name <- ref(Person, Code)\n",
	"Person -> Human\n  Name <- trim(Age)\n", "Person -> Human {when=Missing:X}\n",
	"@map M Code -> Label\n  Missing exact X\n", "@map M Code -> Label\n  X nope X\n",
	"@fn M Text -> Text\n  X => X\n@map M Code -> Label\n  X exact X\n",
	"- Person.Missing {reason=ignore}\n", "- Person.Currency\n", "- Person.Currency {reason=other}\n",
	"Person -> Human\n    Code <- Code\n", "Person -> Human\n\tCode <- Code\n",
])
def testInvalidMappingDeclarationsAreRejected(body: str):
	with pytest.raises(FormatError):
		load(body)


def testStructuredTargetsAreAssignedFieldByField():
	"""A structure has no value of its own, so `Name <- Name` is rejected and its fields are mapped."""
	with pytest.raises(FormatError, match="a structure has no value of its own"):
		loadMapping(SOURCE, SOURCE, Source("t", "@mapping S -> S\nPerson -> Person\n  Name <- Name\n"))
	mapping = loadMapping(SOURCE, SOURCE, Source("t", "@mapping S -> S\nPerson -> Person\n  Name.Given <- Name.Given\n"))
	assert mapping.scopes[0].lines[0].target == "Name.Given"


def testReferenceCorrespondenceCannotBeAmbiguousAndUnmappedReferencesWarn():
	with pytest.raises(FormatError, match="correspondence"):
		load("Person -> Human\n  Owner <- Owner\nPerson -> Human {when=Code:X}\n")
	mapping = load("Event -> Occurrence\n  Who <- Who\n")
	assert any(item.level == "warning" and item.code == "reference" for item in mapping.diagnostics)


@pytest.mark.parametrize("path", ["Age", "Name.Family", "Owner.Code"])
def testViewRestrictionAppliesToEveryReadPath(path: str):
	with pytest.raises(FormatError, match="view"):
		loadMapping(SOURCE, TARGET, Source("t", f"@mapping S -> T view=Names\nPerson -> Human\n  Name <- text({path})\n"))


def testNestedViewsConditionsAndReferenceTraversalUseSelectedSlots():
	mapping = loadMapping(SOURCE, TARGET, Source("t", "@mapping S -> T view=Nested\nPerson -> Human {when=Code:X}\n  Code <- Code\n  Name <- Name.Given\n  Tags <- Tags\n"))
	assert len(mapping.scopes[0].lines) == 3
	with pytest.raises(FormatError, match="view"):
		loadMapping(SOURCE, TARGET, Source("t", "@mapping S -> T view=Referenced\nPerson -> Human\n  Name <- Owner.Name.Given\n"))


@pytest.mark.parametrize("header", ["candidates=yes", "confirm=0", "retract=101%", "view=Missing", "referential=Missing", "complete=record"])
def testInvalidMappingHeadersFail(header: str):
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, Source("t", f"@mapping S -> T {header}\nPerson -> Human\n"))


def testRevisionMismatchesWarnAndCandidateHeaderIsBooleanInJson():
	mapping = loadMapping(SOURCE, TARGET, Source("t", "@mapping S -> T from=old to=old candidates=true confirm=02\nPerson -> Human\n  Name <- Name.Given {candidate}\n"))
	assert len([item for item in mapping.diagnostics if item.code == "revision"]) == 2
	data = mappingToJson(mapping)
	assert data["header"]["candidates"] is True and data["header"]["confirm"] == 2
	assert mappingToJson(mappingFromJson(SOURCE, TARGET, data)) == data


@pytest.mark.parametrize("change", [
	lambda data: data.update(extra=True), lambda data: data.update(header={"candidates": "true"}),
	lambda data: data.update(header={"confirm": True}), lambda data: data.update(maps=[{"kind": "entity", "path": "X"}]),
	lambda data: data["scopes"][0].update(extra=True), lambda data: data["scopes"][0].update(ctx=None),
	lambda data: data["scopes"][0]["lines"][0].update(reverse=False),
	lambda data: data["scopes"][0]["lines"][0].update(candidate=False),
	lambda data: data["scopes"][0]["lines"][0].update(expr={"number": "1.0"}),
	lambda data: data["scopes"][0]["lines"][0].update(doc="line\nbreak"),
	lambda data: data["scopes"][0]["lines"][0].update(verb="knows"),
])
def testStrictJsonRejectsMalformedOrNonRoundTrippableMappings(change):
	data = mappingToJson(load("Person -> Human\n  Code <- Code\n"))
	change(data)
	with pytest.raises(FormatError):
		mappingFromJson(SOURCE, TARGET, data)


# EOF


# -----------------------------------------------------------------------------
#
# MAPPINGS OVER SEVERAL FILES
#
# -----------------------------------------------------------------------------


def testFilesOfOneMappingAreParsedBeforeResolving():
	"""A reference translates through a scope line of another file of the mapping."""
	people = Source("people.map", "@mapping S -> T\n\nPerson -> Human\n  Code <- Code\n")
	owners = Source("owners.map", "@mapping S -> T\n\nEvent -> Occurrence\n  Who <- Who\n- Person.Currency {reason=ignore}\n")
	mapping = loadMapping(SOURCE, TARGET, [owners, people])
	assert [scope.source for scope in mapping.scopes] == ["S/Event", "S/Person"]
	assert not [item for item in mapping.diagnostics if item.code == "reference"]
	alone = loadMapping(SOURCE, TARGET, owners)
	assert any(item.level == "warning" and item.code == "reference" for item in alone.diagnostics)


@pytest.mark.parametrize("second", [
	"@mapping S -> T from=other\nPerson -> Human\n",
	"@mapping S -> T\n- Person.Currency {reason=ignore}\n",
	"@mapping S -> T\n@map Copy2 Code -> Label\n  X exact X\n@map Copy2 Code -> Label\n  X exact X\n",
	"@mapping S -> T\nPerson -> Human\n",
])
def testFilesOfOneMappingMustAgree(second: str):
	first = Source("a.map", "@mapping S -> T from=v1\n@map Copy2 Code -> Label\n  X exact X\nPerson -> Human\n- Person.Currency {reason=ignore}\n")
	with pytest.raises(FormatError):
		loadMapping(SOURCE, TARGET, [first, Source("b.map", second)])
