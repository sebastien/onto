"""Rooted views: text/JSON round-trip and type checks independent of a mapping or Hexa."""

import pytest

from onto import FormatError, Model, Source, loadOntology, ontologyDiff, ontologyFromJson, ontologyToJson, printOntologyDiff
from onto.ontology import Operator
from onto.ontology.rooted import RootedView
from tests.helpers import schemaValidator


BRANCHES = loadOntology([Source("directory.onto", """@ontology Directory
@domain Registers
BranchNumber = Integer
Registers/Branch
  1 Number BranchNumber {key}
  Name Text
""")])
BODY = """@ontology Library
@use Directory/Registers as D
Branch
Person
  Name Text
Visit(Branch: Branch, Patron: Person)
  Active Boolean
Branch -hasPatron/visits-> Person {context=Visit, subjectRole=Branch, objectRole=Patron}
Branch -employs/worksAt-> Person
@view StaffAndPatrons(branchId: D/Branch.Number)
  branch: Branch
  patrons: Person = branch -> hasPatron through visits
  staff: Person = branch -> employs
  active: Visit = branch <- Branch where Active=true
  colleagues: Person = active -> Patron where worksAt=@branch
  patrons.Name
  staff.Name
  visits.Active
  ? colleagues.Name
"""


def testRootedViewsKeepTheirPopulationsAcrossNormalForms():
	ontology = loadOntology([Source("library.onto", BODY)], [BRANCHES])
	data = ontologyToJson(ontology)
	schemaValidator("ontology").validate(data)
	assert next(d["input"] for d in data["decls"] if d["kind"] == "view") == {
		"name": "branchId", "path": "Directory/Registers/Branch", "attr": "Number"}
	restored = ontologyFromJson(data, ontologies=[BRANCHES])
	text = Operator(restored).print()
	assert "@view StaffAndPatrons(branchId: D/Branch.Number)" in text
	assert ontologyToJson(loadOntology([Source("normal.onto", text)], [BRANCHES])) == data
	model = Model(restored)
	view = RootedView(model, model.get("Library/StaffAndPatrons"))
	assert not model.get(view.input.path)  # The source schema is a dependency, not part of the target.
	assert view.input.resolve(Model(BRANCHES)).builtin == "Integer"
	assert [h.field.path for h in view.paths["patrons"]] == ["Visit.Branch", "Visit.Patron"]
	assert view.paths["patrons"][1].parent == "visits"
	assert view.paths["colleagues"][-1].ancestor == "branch"
	assert set(view.selections) == {"staff.Name", "patrons.Name", "visits.Active", "colleagues.Name"}
	assert "colleagues.Name" not in view.select(None).values()


@pytest.mark.parametrize("old,new", [
	("  branch: Branch", "  branch.employs\n  branch: Branch"),
	("branch: Branch", "branch: Missing"),
	("staff: Person = branch", "staff: Person = staff"),
	("staff: Person = branch", "patrons: Person = branch"),
	("-> employs", "<- employs"),
	("-> employs", "-> employs through hiring"),
	("through visits", "through staff"),
	("Active=true", "Name=true"),
	("Active=true", "Active=yes"),
	("worksAt=@branch", "worksAt=@staff"),
	("worksAt=@branch", "Name=@branch"),
	("visits.Active", "visits.Missing"),
	("staff.Name", "unbound.Name"),
])
def testBadPopulationOrProjectionIsRejected(old, new):
	with pytest.raises(FormatError):
		loadOntology([Source("bad.onto", BODY.replace(old, new))], [BRANCHES])


@pytest.mark.parametrize("param,reason", [
	("branchId", "Entity.Attribute"),
	("branchId: Integer", "Entity.Attribute"),
	("branchId: D/Missing.Number", "unknown source entity"),
	("branchId: D/Branch.Missing", "unknown source key attribute"),
	("branchId: D/Branch.Name", "must be marked"),
])
def testInputNamesASourceKey(param, reason):
	with pytest.raises(FormatError, match=reason):
		loadOntology([Source("input.onto", BODY.replace("branchId: D/Branch.Number", param))], [BRANCHES])


def testImportedKeyRequiresItsSourceAndJsonCannotBypassTheKeyCheck():
	with pytest.raises(FormatError, match="Directory/Registers/Branch.Number"):
		loadOntology([Source("library.onto", BODY)])
	data = ontologyToJson(loadOntology([Source("library.onto", BODY)], [BRANCHES]))
	param = next(d for d in data["decls"] if "input" in d)
	param["input"]["attr"] = "Name"
	with pytest.raises(FormatError, match="must be marked"):
		ontologyFromJson(data, ontologies=[BRANCHES])
	param["input"] = "branchId"
	with pytest.raises(FormatError, match="input must be an object"):
		ontologyFromJson(data, ontologies=[BRANCHES])


def testRenamingTheCallerArgumentIsVisibleInTheContractDiff():
	def model(arg):
		return loadOntology([Source("library.onto", BODY.replace("branchId:", arg + ":"))], [BRANCHES])
	diff = printOntologyDiff(ontologyDiff(model("branchId"), model("number")))
	assert "branchId: Directory/Registers/Branch.Number => number: Directory/Registers/Branch.Number" in diff


def testPopulationSelectorsTakePrecedenceOverTypePaths():
	ontology = loadOntology([Source("view.onto", """@ontology Library
Branch
  Id Text {key}
  Name Text
Person
  Name Text
  Email Text
Branch -employs-> Person
@view Staff(id: Branch.Id)
  Person: Branch
  staff: Person = Person -> employs
  contractors: Person = Person -> employs
  Person.Name
  staff.Name
  staff.Email
  ? contractors.Email
""")])
	model = Model(ontology)
	view = RootedView(model, model.get("Library/Staff"))
	assert view.select(["Person.Name", "staff.Name"]) == {"Person.Name": "Person.Name", "staff.Name": "staff.Name"}
	assert view.select(["Branch.Name"]) == {"Branch.Name": "Person.Name"}
	assert list(view.select(None).values()) == ["Person.Name", "staff.Name", "staff.Email"]
	with pytest.raises(ValueError, match="ambiguous.*Person.Email"):
		view.select(["Person.Email"])


def testFlatViewsCannotIncludeRootedViewsWithoutProvidingASeed():
	with pytest.raises(FormatError, match="Rooted view.*requires a seed"):
		loadOntology([Source("library.onto", BODY + "@view Profile\n  StaffAndPatrons\n")], [BRANCHES])

# EOF
