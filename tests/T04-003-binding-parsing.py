"""Module: binding tests — spec-04 source declarations, normal form and JSON."""

from __future__ import annotations

from copy import deepcopy

import pytest

import onto.binding as bindingApi
from onto import FormatError, Source, loadFunctions, loadOntology, BindingOperator, bindingFromJson, bindingToJson, formatBinding, loadBinding, parseBinding, printBinding, resolveBinding
from tests.helpers import schemaValidator, specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


EXCHANGE = loadOntology([Source("exchange.onto", specExample("spec-04-mapping", 1))])
SHEET = loadOntology([Source("sheet.onto", specExample("spec-04-mapping", 7))])
ONTOLOGY = loadOntology([Source("a.onto", """@ontology A rev=v1
Person
  Name Text
  Count Integer
  * Tags Text
  Owner Person
Scenario
Review of Person {ctx=Scenario}
  Included Boolean
Investor of Person
  Rating Text
Person -knows/knownBy-> Person
Meeting(Host: Person, Guest: Person)
@map Copy Code -> Code
  X exact X
Code = X|Y
""")])


def load(text: str):
	return loadBinding(ONTOLOGY, Source("test.bind", "@binding A rev=v1\n" + text))


# -----------------------------------------------------------------------------
#
# SPECIFICATION AND INTERCHANGE
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(("ontology", "index"), [(EXCHANGE, 2), (SHEET, 9)])
def testCompleteSpecBindingFilesRoundTrip(ontology, index: int):
	text = specExample("spec-04-mapping", index)
	doc = parseBinding(Source("example.bind", text))
	assert doc.scopes[0].loc.file == "example.bind"
	binding = resolveBinding(ontology, doc)
	data = bindingToJson(binding)
	schemaValidator("mapping").validate(data)
	assert data["format"] == "onto.binding/1"
	assert all(scope["type"].startswith(ontology.namespace + "/") for scope in data["scopes"])
	assert printBinding(binding) == text
	assert formatBinding(ontology, Source("t", text)) == text
	assert bindingToJson(bindingFromJson(ontology, data)) == data


def testExpressionsAnnotationsDocsFacetsRolesAndInverseVerbsAreRetained():
	binding = load('''@at <- snapshot.at
Person <- people[*] {id=concat(id, ",", "}"), ctx=scenario, valid=period, deleted=flags.deleted:true} -- People
  [Investor] {when=kind:I} -- Applies
  Name <- name ?? nickname {null=unknown, when=active:true} -- Full name
  Review.Included <- included
  knownBy <- ref(Person, owner)
Meeting <- meetings[*] {id=id}
  Host <- ref(Person, host)
  Guest <- ref(Person, guest)
- people[*].unused {reason=ignore} -- Deliberate
''')
	data = bindingToJson(binding)
	schemaValidator("mapping").validate(data)
	person = next(scope for scope in data["scopes"] if scope["type"] == "A/Person")
	assert person["id"]["args"][1:] == [{"text": ","}, {"text": "}"}]
	assert person["deleted"] == {"path": ["flags", "deleted"], "value": "true"}
	assert next(line for line in person["lines"] if "verb" in line)["verb"] == "knownBy"
	assert next(line for line in person["lines"] if line.get("target") == "Name")["null"] == "unknown"
	printed = printBinding(binding)
	assert formatBinding(ONTOLOGY, Source("t", printed)) == printed
	assert bindingToJson(bindingFromJson(ONTOLOGY, data)) == data


def testLocalFunctionsReuseLibraryDeclarationsAndExamples():
	binding = load('''@fn Rename Text -> Text {inverse=Restore} -- One-off
  Old => New
@fn Restore Text -> Text {inverse=Rename}
  New => Old
Person <- people[*] {id=id}
  Name <- Rename(name)
''')
	data = bindingToJson(binding)
	assert len(data["functions"]) == 2
	assert data["functions"][0]["name"] == "Rename"
	assert data["scopes"][0]["lines"][0]["expr"]["call"] == "Rename"
	schemaValidator("mapping").validate(data)
	assert bindingToJson(bindingFromJson(ONTOLOGY, data)) == data


def testScopeOrderDoesNotDetermineEnclosingRecordResolution():
	binding = load("Person <- people[*].children[*] {id=concat(^.id, id)}\n  Owner <- ^\nPerson <- people[*] {id=id}\n")
	assert len(binding.scopes) == 2
	printed = printBinding(binding)
	assert formatBinding(ONTOLOGY, Source("t", printed)) == printed


@pytest.mark.parametrize(("parent", "child"), [("$", "children[*]"), ("people[0]", "people[0].children[*]"), ("$.people[*]", "people[*].children[*]")])
def testEnclosingRecordsSupportRootObjectsIndexesAndEquivalentRootPaths(parent: str, child: str):
	binding = load(f"Person <- {child} {{id=concat(^.id, id)}}\n  Owner <- ^\nPerson <- {parent} {{id=id}}\n")
	printed = printBinding(binding)
	assert formatBinding(ONTOLOGY, Source("t", printed)) == printed
	assert bindingToJson(bindingFromJson(ONTOLOGY, bindingToJson(binding))) == bindingToJson(binding)


def testImportedLibraryCallsAreQualifiedAndLocalSignatureAliasesUseTheirOwnContext():
	library = loadFunctions([], [Source("markets.fn", "@functions Markets\n@fn Rename Text -> Text\n  Old => New\n")])
	dimensions = loadOntology([Source("dimensions.onto", "@ontology Dimensions\nCode = X|Y\n")])
	text = "@binding A\n@use Markets as M\n@use Dimensions as D\n@fn Label D/Code -> Text\n  X => Known\nPerson <- people[*] {id=id}\n  Name <- M/Rename(Label(code))\n"
	ops = BindingOperator(ONTOLOGY, libraries=[library], ontologies=[dimensions])
	binding = ops.load(Source("t", text))
	expr = bindingToJson(binding)["scopes"][0]["lines"][0]["expr"]
	assert expr["call"] == "Markets/Rename"
	assert expr["args"][0]["call"] == "Label"
	schemaValidator("mapping").validate(ops.toJson(binding))
	assert ops.toJson(ops.fromJson(ops.toJson(binding))) == ops.toJson(binding)
	assert ops.format(Source("t", ops.print(binding))) == ops.print(binding)
	with pytest.raises(FormatError):
		BindingOperator(ONTOLOGY, libraries=[library]).load(Source("t", text))
	with pytest.raises(FormatError):
		BindingOperator(ONTOLOGY, libraries=[library]).load(Source("t", "@binding A\nPerson <- people[*] {id=id}\n  Name <- Markets/Rename(name)\n"))


def testHeaderDomainsDefaultsAndRevisionWarning():
	binding = loadBinding(ONTOLOGY, Source("t", "@binding A rev=old format=json scope=feed null=absent complete=record retract=0% confirm=02\nPerson <- people[*] {id=id}\n"))
	assert binding.header["confirm"] == 2
	assert any(item.level == "warning" and item.code == "revision" for item in binding.diagnostics)
	assert "confirm=2" in printBinding(binding)
	assert load("Person <- people[*] {id=id}\n").header == {"rev": "v1"}


def testWhitespaceAndConditionalQuotedFieldsHaveCanonicalSpellings():
	text = '@binding\tA\trev=v1\n@at\t<-  asOf\n@columns\tfirst, "asset class"\nPerson   <-   people[*] {id=concat(id, ",", "}"), deleted="flag:deleted":yes}\n  Name   <-   name {when="flag:active":yes}\n'
	binding = loadBinding(ONTOLOGY, Source("t", text))
	printed = printBinding(binding)
	assert "@at <- asOf" in printed
	assert 'when="flag:active":yes' in printed
	assert formatBinding(ONTOLOGY, Source("t", printed)) == printed
	assert bindingToJson(bindingFromJson(ONTOLOGY, bindingToJson(binding))) == bindingToJson(binding)


def testEmptyAnnotationBlocksFollowTheSharedLexicalRules():
	binding = load("Person <- people[*] {id=id}\n  [Investor] {}\n  Name <- name {}\n")
	assert "{}" not in printBinding(binding)
	assert bindingToJson(bindingFromJson(ONTOLOGY, bindingToJson(binding))) == bindingToJson(binding)


def testOntologyMapsAndCollectionFunctionSignaturesResolveWithoutExecuting():
	binding = load('''Person <- people[*] {id=id}
  Name <- Copy(code)
  Tags <- split(tags, ",")
  Count <- count(split(tags, ","))
''')
	data = bindingToJson(binding)
	assert next(line for line in data["scopes"][0]["lines"] if line["target"] == "Name")["expr"]["call"] == "A/Copy"
	assert bindingToJson(bindingFromJson(ONTOLOGY, data)) == data


def testBindingOperatorAndAllOperationsAreNonMutating():
	ops = BindingOperator(ONTOLOGY)
	doc = ops.parse(Source("t", "@binding A\nPerson <- people[*] {id=id}\n  Name <- trim(name)\n"))
	before = deepcopy(doc)
	binding = ops.resolve(doc)
	assert doc == before
	before = deepcopy(binding)
	data = ops.toJson(binding)
	assert ops.toJson(ops.fromJson(data)) == data
	assert ops.format(Source("t", ops.print(binding))) == ops.print(binding)
	assert ops.load(Source("t", ops.print(binding))).ontology == "A"
	assert binding == before
	data["scopes"][0]["id"]["path"].append("changed")
	assert binding == before


def testFeatureFacadeAndTopLevelApiShareImplementations():
	assert bindingApi.Operator is bindingApi.BindingOperator is BindingOperator
	assert bindingApi.loadBinding is loadBinding
	assert bindingApi.parseBinding is parseBinding


# -----------------------------------------------------------------------------
#
# VALIDATION
#
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
	"Person <- people[*]\n", "Person <- trim(people) {id=id}\n", "Missing <- people[*] {id=id}\n",
	"Person <- people[*] {id=id}\n  Missing <- name\n",
	"Person <- people[*] {id=id}\n  Name <- name\n  Name <- nickname\n",
	"Person <- people[*] {id=id}\n  [Missing]\n",
	"Person <- people[*] {id=id}\n  [Investor]\n  [Investor]\n",
	"Person <- people[*] {id=id}\n  Name <- noSuchFunction(name)\n",
	"Person <- people[*] {id=id}\n  Name <- trim(name, other)\n",
	"Person <- people[*] {id=id}\n  Name <- ref(Missing, id)\n",
	"Person <- people[*] {id=id}\n  Name <- ref(Person, id)\n",
	"Person <- people[*] {id=id}\n  Name <- tags[*]\n",
	"Person <- people[*] {id=id}\n  Count <- count(1)\n",
	"Person <- people[*] {id=id}\n  Name <- join(\"text\", \",\")\n",
	"Person <- people[*] {id=id}\n  Review.Included <- included\n",
	"Person <- people[*] {id=id, ctx=ref(Person, scenario)}\n  Review.Included <- included\n",
	"Person <- people[*] {id=id}\n  Owner <- ref(Person, 1)\n",
	"Person <- people[*] {id=id}\n  Owner <- ^\n",
	"Person <- people[*].children[*] {id=id}\n  Owner <- ^\n",
	"Person <- people[*] {id=id}\n  Name <- $valid\n",
	"Person <- people[*] {id=id, id=other}\n",
	"Person <- people[*] {id=concat(a, b}\n",
	"Person <- people[*] {id=id, when=active:true}\n",
	"Person <- people[*] {id=id}\n  Name <- name {src=name}\n",
	"Person <- people[*] {id=id}\n  Name <- name {null=invalid}\n",
	"Person <- people[*] {id=id}\n  Name <- name {when=name:}\n",
	"Person <- people[*] {id=id}\n    Name <- name\n",
	"Person <- people[*] {id=id}\n\tName <- name\n",
	"- unused\n", "- unused {reason=other}\n", "- ^.unused {reason=ignore}\n",
	"@at <- at\n@at <- another\n", "@columns a, a\n", "@columns\n",
	"@fn F Text -> Text\nPerson <- people[*] {id=id}\n",
])
def testInvalidBindingDeclarationsAreRejected(body: str):
	with pytest.raises(FormatError):
		load(body)


def testAFieldAloneTestsThatItHasAValue():
	binding = load("Person <- people[*] {id=id}\n  Name <- name {when=name}\n")
	assert binding.scopes[0].lines[0].when == {"path": ["name"]}
	assert "  Name <- name {when=name}\n" in printBinding(binding)


def testStructuredTargetsTakeTheirFieldsNotADocumentObject():
	"""A structure has no scalar value: `check` rejects what the executor cannot read."""
	ontology = loadOntology([Source("s.onto", "@ontology S rev=v1\nPerson\n  Address Address\nAddress =\n  City Text\n")])
	source = "@binding S rev=v1\nPerson <- people[*] {id=id}\n"
	assert loadBinding(ontology, Source("t", source + "  Address.City <- address.city\n")).scopes[0].lines[0].target == "Address.City"
	with pytest.raises(FormatError, match="a structure has no value of its own"):
		loadBinding(ontology, Source("t", source + "  Address <- address\n"))


@pytest.mark.parametrize("header", ["complete=invalid", "name=\"a b\"", "retract=101%", "retract=-1%", "retract=1.5%", "confirm=0", "confirm=x", "format=yaml", "null=invalid", "extra=yes"])
def testInvalidHeaderDomainsAreRejected(header: str):
	with pytest.raises(FormatError):
		loadBinding(ONTOLOGY, Source("t", f"@binding A {header}\nPerson <- people[*] {{id=id}}\n"))


@pytest.mark.parametrize("change", [
	lambda data: data.update(extra=True),
	lambda data: data.update(header={"confirm": True}),
	lambda data: data.update(columns=[]),
	lambda data: data.update(at=None),
	lambda data: data["scopes"][0].update(extra=True),
	lambda data: data["scopes"][0].pop("id"),
	lambda data: data["scopes"][0].update(path={"call": "trim", "args": []}),
	lambda data: data["scopes"][0]["lines"][0].update(expr={"number": "1.0"}),
	lambda data: data["scopes"][0]["lines"][0].update(verb="knows"),
	lambda data: data["scopes"][0]["lines"][0].update(doc="a\nb"),
	lambda data: data["scopes"][0]["lines"][0].update(candidate=True),
])
def testStrictJsonRejectsMalformedAndNonRoundTrippableBindings(change):
	data = bindingToJson(load("Person <- people[*] {id=id}\n  Name <- name\n"))
	change(data)
	with pytest.raises(FormatError):
		bindingFromJson(ONTOLOGY, data)


@pytest.mark.parametrize(("line", "printed"), [
	("  Count <- count {unset=0.00}\n", "  Count <- count {unset=0}\n"),
	("  Name <- name {null=unknown, unset=N/A}\n", "  Name <- name {null=unknown, unset=N/A}\n"),
	('  Name <- name {unset=""}\n', '  Name <- name {unset=""}\n'),
	('  Name <- name {unset="not given, see note"}\n', '  Name <- name {unset="not given, see note"}\n'),
	('  Name <- name {unset="\\"none\\""}\n', '  Name <- name {unset="\\"none\\""}\n'),
])
def testUnsetValuesAreTypedAndCanonical(line: str, printed: str):
	binding = load("Person <- people[*] {id=id}\n" + line)
	assert printed in printBinding(binding)
	data = bindingToJson(binding)
	schemaValidator("mapping").validate(data)
	assert bindingToJson(bindingFromJson(ONTOLOGY, data)) == data


@pytest.mark.parametrize("line", [
	"  Count <- count {unset=x}\n",
	"  Count <- count {unset=1.5}\n",
	"  Tags <- tags {unset=a}\n",
	"  Owner <- ref(Person, ownerId) {unset=x}\n",
	"  knows <- ref(Person, friendId) {unset=x}\n",
	"  [Investor] {unset=x}\n",
])
def testUnsetIsRejectedOutsideSingleValuedScalarAttributes(line: str):
	with pytest.raises(FormatError):
		load("Person <- people[*] {id=id}\n" + line)


# EOF
