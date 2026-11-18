"""Module: change tracking tests — combined-model snapshots and semantic diffs."""

from __future__ import annotations

import io
import json
import sys

import pytest

from onto import Source, loadOntology, ontologyDiff, ontologyFromJson, ontologyToJson
from tests.cli import onto


@pytest.fixture
def files(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	# NOTE: Both revisions intentionally share a namespace and a project root.
	(tmp_path / ".git").mkdir()

	def write(name, body):
		path = tmp_path / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text("@ontology Model\n" + body)
		return name

	return write


def test_snap_combines_only_explicit_files_and_is_deterministic(files):
	a = files("a.onto", "Person\n  Name Text\n")
	b = files("b.onto", "Account\n  Owner Person\n")
	files("broken.onto", "Invalid\n  Value Missing\n")
	status, out, err = onto("snap", a, b)
	assert (status, err) == (0, "")
	data = json.loads(out)
	assert data["format"] == "onto.ontology/1"
	assert {decl["path"] for decl in data["decls"]} == {"Model/Person", "Model/Account"}
	assert onto("snap", b, a)[1] == out
	status, text, err = onto("snap", a, b, "--format", "onto")
	assert (status, err) == (0, "")
	assert ontologyToJson(loadOntology([Source("snapshot", text)])) == data


def test_diff_ignores_file_placement_order_and_comments(files):
	a = files("old/a.onto", "Person\n  Name Text\n")
	b = files("old/b.onto", "Account\n  Owner Person\n")
	c = files("new/a.onto", "// Moved and reordered\nAccount\n  Owner Person\nPerson\n  Name Text\n")
	d = files("new/b.onto", "")
	assert onto("diff", "--before", b, a, "--after", c, d) == (0, "", "")


def test_diff_exit_status_follows_diff1(files):
	"""0 same, 1 different, 2 an input that could not be read; warnings change nothing."""
	same = files("same.onto", "Person\n  * Phones Phone\nPhone =\n  Number Text\n")
	assert onto("diff", same, same)[0] == 0
	other = files("other.onto", "Person\n  * Phones Phone\n  Name Text\nPhone =\n  Number Text\n")
	assert onto("diff", same, other)[0] == 1
	broken = files("broken.onto", "Person\n  Name Missing\n")
	status, _, err = onto("diff", same, broken)
	assert status == 2 and "Missing" in err


def test_snapshots_text_and_mixed_sets_compare(files, tmp_path):
	a = files("a.onto", "Person\n  Name Text\n")
	b = files("b.onto", "Account\n")
	snapshot = onto("snap", a)[1]
	(tmp_path / "a.json").write_text(snapshot)
	(tmp_path / "all.json").write_text(onto("snap", a, b)[1])
	assert onto("diff", a, "a.json") == (0, "", "")
	assert onto("diff", "--before", "a.json", b, "--after", "all.json") == (0, "", "")


def test_diff_has_structured_before_and_after_values(files):
	a = files("old.onto", "Person\n  Email Text\n")
	b = files("new.onto", "Person\n  1 Email Text\n  Name Text\n")
	status, out, err = onto("diff", a, b)
	assert status == 1 and not err
	assert "~ Model/Person.Email card ? => 1" in out
	assert "+ Model/Person.Name Text" in out
	status, out, err = onto("diff", a, b, "--json")
	document = json.loads(out)
	assert status == 1 and not err and document["diagnostics"] == []
	assert document["result"]["format"] == "onto.diff/1"
	change = next(item for item in document["result"]["changes"] if item["op"] == "change")
	assert change == {"op": "change", "path": "Model/Person.Email", "field": "card", "before": "?", "after": "1"}
	assert document["files"] == {"checked": 2, "read": 2}


def test_snap_json_uses_existing_envelope(files):
	a = files("a.onto", "Person\n")
	status, out, err = onto("snap", a, "--json")
	assert status == 0 and not err
	assert json.loads(out)["result"] == json.loads(onto("snap", a)[1])


@pytest.mark.parametrize("body", [
	"Person\nPerson\n",
	"Person\n  Value Missing\n",
])
def test_snap_validates_combined_model(files, body):
	a = files("a.onto", body)
	status, out, err = onto("snap", a)
	assert status == 1 and out == "" and "error" in err


def test_snap_checks_cross_file_references_duplicates_and_headers(files, tmp_path):
	a = files("a.onto", "Person\n  Account Account\n")
	b = files("b.onto", "Account\n")
	assert onto("snap", a)[0] == 1
	assert onto("snap", a, b)[0] == 0
	c = files("c.onto", "Account\n")
	assert "Duplicate" in onto("snap", a, b, c)[2]
	(tmp_path / b).write_text("@ontology Other\nAccount\n")
	assert "same @ontology namespace" in onto("snap", a, b)[2]
	(tmp_path / b).write_text("@ontology Model card=1\nAccount\n")
	assert "same @ontology defaults" in onto("snap", a, b)[2]


def test_missing_invalid_and_wrong_kind_inputs(files, tmp_path):
	assert onto("snap", "missing.onto")[0] == 1
	(tmp_path / "bad.json").write_text("{")
	status, out, err = onto("snap", "bad.json")
	assert status == 1 and out == "" and "bad.json" in err
	(tmp_path / "wrong.json").write_text('{"format": "onto.mapping/1"}')
	assert onto("snap", "wrong.json")[0] == 1
	(tmp_path / "wrong.obs").write_text("@obs Model\n")
	assert onto("snap", "wrong.obs")[0] == 1


@pytest.mark.parametrize("args", [
	("snap",),
	("diff",),
	("diff", "a"),
	("diff", "a", "b", "c"),
	("diff", "--before", "a"),
	("diff", "--after", "b"),
	("diff", "a", "b", "--before", "c", "--after", "d"),
	("diff", "--before", "-", "--after", "-"),
])
def test_change_tracking_usage_errors(args):
	assert onto(*args)[0] == 2


def test_stdin_text_and_json(files, monkeypatch):
	a = files("a.onto", "Person\n")
	monkeypatch.setattr(sys, "stdin", io.StringIO("@ontology Model\nPerson\n"))
	assert onto("diff", "-", a) == (0, "", "")
	monkeypatch.setattr(sys, "stdin", io.StringIO(onto("snap", a)[1]))
	assert onto("diff", a, "-") == (0, "", "")


def test_ids_sidecars_preserve_renames_and_embedded_ids(files, tmp_path):
	a = files("old/model.onto", "Person\n  Name Text\n")
	b = files("new/model.onto", "Party\n  Name Text\n")
	(tmp_path / "old/Model.ids").write_text("Model/Person\tperson-1\n")
	(tmp_path / "new/Model.ids").write_text("Model/Party\tperson-1\n")
	snapshot = onto("snap", a)[1]
	assert json.loads(snapshot)["ids"] == {"Model/Person": "person-1"}
	(tmp_path / "old.json").write_text(snapshot)
	assert onto("diff", "old.json", b) == (1, "> Model/Person => Model/Party\n", "")
	(tmp_path / "old/Model.ids").unlink()
	status, out, _ = onto("diff", a, b)
	assert status == 1 and "- Model/Person" in out and "+ Model/Party" in out


def test_ids_malformed_and_conflicting_sidecars(files, tmp_path):
	a = files("old/a.onto", "Person\n")
	b = files("new/b.onto", "Party\n")
	sidecar = tmp_path / "old/Model.ids"
	sidecar.write_text("not a tab separated row\n")
	assert "old/Model.ids:1: error cli.ids" in onto("snap", a)[2]
	sidecar.write_text("Model/Person\tone\nModel/Person\ttwo\n")
	assert "conflicting identifiers" in onto("snap", a)[2]
	sidecar.write_text("Model/Person\tone\n")
	(tmp_path / "new/Model.ids").write_text("Model/Person\ttwo\n")
	assert "conflicting identifiers" in onto("snap", a, b)[2]


def model(body):
	return loadOntology([Source("model.onto", "@ontology Model\n" + body)])


def test_api_no_mutation_aliases_and_explicit_defaults():
	before = loadOntology([Source("a", "@ontology Model\n@use External as E\nE/Value = Text\nPerson\n  Value E/Value\n")])
	after = loadOntology([Source("b", "@ontology Model card=? cards=stated rel=*:* \n@use External as X\nPerson\n  ? Value X/Value\nX/Value = Text\n")])
	original = ontologyToJson(before)
	assert ontologyDiff(before, after) == []
	assert ontologyToJson(before) == original


def test_api_vocabulary_values_order_and_taxonomies():
	assert ontologyDiff(model("Value = A|B\n"), model("Value = B|A\n")) == []
	changes = ontologyDiff(model("Value = A|B\n"), model("Value = B|C\n"))
	assert [(item["op"], item["path"]) for item in changes] == [("remove", "Model/Value:A"), ("add", "Model/Value:C")]
	assert ontologyDiff(model("Value = A|B {ordered}\n"), model("Value = B|A {ordered}\n"))
	assert ontologyDiff(model("Value = |A/B {hierarchical}\n"), model("Value = A|A/B {hierarchical}\n")) == []


def test_api_all_properties_and_member_kinds():
	before = model("Value = Text\nStruct =\n  Name Text\nPerson\n  Email Text\n  Age Integer\nPerson -knows-> Person *:*\n@view People\n  Person.Email\n")
	after = model("Value = Integer\nStruct =\n  Name Integer\nPerson -- A person\n  1 Email Text {key}\n  Age Number\nPerson -knows-> Person 1:*\n@view People\n  Person.Age\n")
	changes = ontologyDiff(before, after)
	properties = {(item["path"], item.get("field")) for item in changes}
	assert {
		("Model/Value", "type"),
		("Model/Struct.Name", "type"),
		("Model/Person", "doc"),
		("Model/Person.Email", "card"),
		("Model/Person.Email", "ann"),
		("Model/Person.Age", "type"),
		("Model/Person.knows.Model/Person", "counts"),
		("Model/People", "lines"),
	} <= properties
	# NOTE: JSON and text models use the same comparison API.
	assert ontologyDiff(after, ontologyFromJson(ontologyToJson(after))) == []


def test_diff_ignores_view_selection_order_even_with_a_shared_path(files):
	concepts = "Person\nBuyer of Person\nSeller of Person\n@view People\n"
	a = files("old.onto", concepts + "  Person[Seller]\n  Person[*]\n  Person[Seller, Buyer]\n  Person[Buyer]\n")
	b = files("new.onto", concepts + "  Person[Buyer]\n  Person[Buyer, Seller]\n  Person[Seller]\n  Person[*]\n")
	assert onto("diff", a, b) == (0, "", "")
	assert onto("snap", a, "--format", "onto")[1] == onto("snap", b, "--format", "onto")[1]


def test_diff_identifies_declared_domain_order(tmp_path):
	before, after = "@domain First\n@domain Second\n", "@domain Second\n@domain First\n"
	assert ontologyDiff(model(before), model(after)) == []

	def layered(domains):
		return loadOntology([Source("model.onto", "@ontology Model layering=declared\n" + domains)])

	assert ontologyDiff(layered(before), layered(after)) == [{
		"op": "change", "path": "@ontology", "field": "domainOrder",
		"before": ["Model/First", "Model/Second"], "after": ["Model/Second", "Model/First"],
	}]
	assert ontologyDiff(layered("@domain Meta\n" + before), layered(before + "@domain Meta\n")) == []


def test_api_ids_match_attributes_roles_and_values_without_heuristics():
	before = model("Value = A|B\nPerson\n  Name Text\nLink(person: Person, other: Person)\n")
	after = model("Value = B|C\nPerson\n  Label Text\nLink(party: Person, other: Person)\n")
	before.ids = {"Model/Person.Name": "name", "Model/Value:A": "value", "Model/Link.person": "role"}
	after.ids = {"Model/Person.Label": "name", "Model/Value:C": "value", "Model/Link.party": "role"}
	changes = ontologyDiff(before, after)
	assert len(changes) == 3 and all(item["op"] == "move" for item in changes)
	before.ids = {path: "(authored)" for path in before.ids}
	after.ids = {path: "(authored)" for path in after.ids}
	assert not any(item["op"] == "move" for item in ontologyDiff(before, after))


def test_api_owner_renames_carry_facet_members_and_swapped_names():
	before = model("Person\nInvestor of Person\n  Name Text\n")
	after = model("Person\nClient of Person\n  Name Text\n")
	before.ids, after.ids = {"Model/Investor": "facet"}, {"Model/Client": "facet"}
	assert ontologyDiff(before, after) == [{"op": "move", "path": "Model/Investor", "to": "Model/Client"}]
	before = model("A\n  Name Text\nB\n  Name Integer\n")
	after = model("A\n  Name Integer\nB\n  Name Text\n")
	before.ids = {"Model/A": "first", "Model/B": "second"}
	after.ids = {"Model/B": "first", "Model/A": "second"}
	changes = ontologyDiff(before, after)
	assert len(changes) == 2 and all(item["op"] == "move" for item in changes)


def test_diff_metadata_removals_annotations_and_quiet(files, tmp_path):
	a = files("old.onto", "Person\n  Name Text {key}\n  Ticker Text\n")
	b = files("new.onto", "Person\n  Name Text\n")
	status, out, err = onto("diff", a, b)
	assert (status, err) == (1, "")
	assert "~ Model/Person.Name ann -key" in out
	assert "- Model/Person.Ticker" in out
	assert onto("diff", a, b, "--quiet") == (1, "", "")
	(tmp_path / b).write_text("@ontology Model rev=2026-11-16\nPerson\n  Name Text\n")
	assert "~ @ontology rev - => 2026-11-16" in onto("diff", a, b)[1]


# EOF
