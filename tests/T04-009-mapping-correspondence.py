"""Module: mapping correspondence tests — explicit selection and revision-specific typing."""

from __future__ import annotations

import pytest

from onto import FormatError, Source, loadMapping, loadOntology


def revisions(*, sourceInherits: bool, targetInherits: bool):
	source = loadOntology([Source("old.onto", """@ontology A rev=old
Person
Employee""" + (" < Person" if sourceInherits else "") + """
Incoming
  Contact Employee
  Fallback Person
Review of Incoming {ctx=Employee}
  Included Boolean
""")])
	target = loadOntology([Source("new.onto", """@ontology A rev=new
Person
Employee""" + (" < Person" if targetInherits else "") + """
Record
  Owner Person
Record -contacts-> Person
Assessment of Record {ctx=Person}
  Included Boolean
""")])
	return source, target


def testAsSelectsOneScopeNotJustOneType():
	source, target = revisions(sourceInherits=False, targetInherits=True)
	text = """@mapping A -> A from=old to=new
Employee -> Employee
Employee -> Person {name=Primary}
Incoming -> Record
  Owner <- Contact {as=Person}
"""
	mapping = loadMapping(source, target, Source("test.map", text))
	assert not mapping.diagnostics
	with pytest.raises(FormatError, match="Ambiguous instance correspondence.*as=A/Person"):
		loadMapping(source, target, Source("test.map", text + "Employee -> Person {name=Secondary}\n"))


@pytest.mark.parametrize(("body", "diagnostic"), [
	("Incoming -> Record\n  Owner <- Contact\n", "Owner: incompatible"),
	("Incoming -> Record\n  contacts <- Contact\n", "Unknown or ambiguous target/verb 'contacts'"),
	("Incoming -> Person {into=Contact}\n", "into target: incompatible"),
	("Incoming -> Record {ctx=Contact}\n  [Assessment]\n", "target context: incompatible"),
	("Incoming -> Record\n  Assessment.Included <- Review.Included\n", "target context: incompatible"),
])
def testTranslatedReferencesUseTargetInheritance(body: str, diagnostic: str):
	text = "@mapping A -> A from=old to=new\nEmployee -> Employee\n" + body
	source, target = revisions(sourceInherits=False, targetInherits=True)
	assert not loadMapping(source, target, Source("test.map", text)).diagnostics
	source, target = revisions(sourceInherits=True, targetInherits=False)
	with pytest.raises(FormatError, match=diagnostic):
		loadMapping(source, target, Source("test.map", text))


def testCoalesceAlternativesStillUseSourceInheritance():
	text = """@mapping A -> A from=old to=new
Person -> Person
Incoming -> Record
  Owner <- Fallback ?? Contact
"""
	source, target = revisions(sourceInherits=True, targetInherits=False)
	assert not loadMapping(source, target, Source("test.map", text)).diagnostics
	source, target = revisions(sourceInherits=False, targetInherits=True)
	with pytest.raises(FormatError, match="Coalesce alternatives have incompatible types"):
		loadMapping(source, target, Source("test.map", text))


# EOF
