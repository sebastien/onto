"""Module: CLI workspace tests — indexing by header, context resolution and location of diagnostics (spec-07)."""

from __future__ import annotations

import io
import json

from tests._cli import onto

# -----------------------------------------------------------------------------
#
# INDEXING
#
# -----------------------------------------------------------------------------


def test_ls_lists_every_kind_by_namespace(workspace):
	status, out, _ = onto("ls")
	rows = [line.split("\t") for line in out.splitlines()]
	assert status == 0
	assert ["mapping", "Exchange->Finance", "", "finance/exchange-finance.map"] in rows
	assert ["ontology", "Finance", "2026-11-10", "finance/finance.onto"] in rows
	assert ["inventory", "exchange", "", "finance/exchange.inv"] in rows
	assert [row[0] for row in rows] == sorted(row[0] for row in rows)


def test_ls_filters_kinds_and_skips_hidden_directories(workspace):
	(workspace / ".hidden").mkdir()
	(workspace / ".hidden/other.onto").write_text("@ontology Other\nThing\n")
	_, out, _ = onto("ls", "ontology")
	assert {line.split("\t")[1] for line in out.splitlines()} == {"Exchange", "Finance", "Sheet"}


def test_ignore_files_keep_generated_copies_out_of_the_workspace(workspace):
	"""`.gitignore` and `.ontoignore` exclude files and directories; `.ontoignore` may re-include; named files are still read."""
	(workspace / "build").mkdir()
	(workspace / "build/finance.onto").write_text("@ontology Finance\nCopy\n")
	(workspace / "drafts").mkdir()
	(workspace / "drafts/a.onto").write_text("@ontology DraftA\nThing\n")
	(workspace / "drafts/keep.onto").write_text("@ontology DraftKeep\nThing\n")
	(workspace / ".gitignore").write_text("# generated\n/build/\ndrafts/*.onto\n")
	(workspace / "drafts/.ontoignore").write_text("!keep.onto\n")
	status, out, err = onto("ls", "ontology")
	assert status == 0 and not err
	assert {line.split("\t")[1] for line in out.splitlines()} == {"DraftKeep", "Exchange", "Finance", "Sheet"}
	assert "build/finance.onto" not in out
	status, out, _ = onto("fmt", "drafts/a.onto")
	assert status == 0 and out.startswith("@ontology DraftA")


def test_patterns_follow_gitignore():
	from onto.cli.ignore import parseRule
	def matches(pattern, path):
		rule = parseRule(pattern)
		return bool(rule.pattern.match(path))
	assert matches("*.onto", "a/b/c.onto") and not matches("/*.onto", "a/c.onto") and matches("/*.onto", "c.onto")
	assert matches("a/**/z.onto", "a/z.onto") and matches("a/**/z.onto", "a/b/c/z.onto") and matches("build/**", "build/x/y")
	assert matches("x?.onto", "x1.onto") and not matches("x?.onto", "x/.onto") and matches("[ab].onto", "b.onto")
	assert parseRule("# comment") is None and parseRule("   ") is None and parseRule("!keep").negated and parseRule("dir/").directoryOnly


def test_files_sharing_a_mapping_header_form_one_mapping(workspace):
	"""Split mappings load as one: a reference resolves through a scope line of another file."""
	text = (workspace / "finance/exchange-finance.map").read_text()
	header, _, body = text.partition("\n")
	scopes = body.split("\n\n")
	issuers = [block for block in scopes if block.lstrip().startswith("Issuer ->")]
	assert issuers, "the spec mapping maps issuers"
	(workspace / "finance/exchange-finance.map").write_text(header + "\n" + "\n\n".join(block for block in scopes if block not in issuers))
	(workspace / "finance/exchange-issuers.map").write_text(header + "\n\n" + "\n\n".join(issuers) + "\n")
	_, out, _ = onto("ls", "mapping")
	assert "finance/exchange-finance.map finance/exchange-issuers.map" in out
	status, _, err = onto("check", "finance/exchange-finance.map")
	assert status == 0 and "reference" not in err, err


def test_files_sharing_a_namespace_form_one_ontology(workspace):
	(workspace / "finance/exchange-extra.onto").write_text("@ontology Exchange rev=2026-11-10 src=feed card=? cards=assumed\n\nExtra\n  Code Text\n")
	_, out, _ = onto("ls", "ontology")
	assert "finance/exchange-extra.onto finance/exchange.onto" in out
	status, out, _ = onto("fmt", "finance/exchange-extra.onto")
	assert status == 0 and out == "@ontology Exchange rev=2026-11-10 src=feed card=? cards=assumed\n\nExtra\n  Code Text\n"


def test_whole_workspace_checks_clean(workspace):
	status, _, err = onto("check")
	assert status == 0 and err == "no problems in 12 files\n"


# -----------------------------------------------------------------------------
#
# CONTEXT
#
# -----------------------------------------------------------------------------


def test_mapping_context_comes_from_the_workspace(workspace):
	status, _, err = onto("check", "finance/exchange-finance.map")
	# NOTE: Exchange, Finance, Markets and MarketIds; the referential's `from=Exchange` is shared.
	assert status == 0 and err == "no problems in 1 file (5 read)\n"


def test_context_errors_are_reported_in_their_own_file(workspace):
	with (workspace / "finance/finance.onto").open("a") as file:
		file.write("\nBroken\n  Thing NoSuchType\n")
	status, _, err = onto("check", "finance/exchange-finance.map")
	lines = err.splitlines()
	assert status == 1
	assert lines[0] == "finance/exchange-finance.map:1: error cli.context: ontology Finance has errors"
	assert lines[1].startswith("finance/finance.onto:") and "NoSuchType" in lines[1]


def test_missing_ontology_is_unresolved_at_the_header(workspace):
	(workspace / "finance/exchange.onto").unlink()
	status, _, err = onto("check", "finance/exchange.bind")
	assert status == 1
	assert err.startswith("finance/exchange.bind:1: error cli.unresolved: no ontology Exchange in the workspace")


def test_header_must_match_the_extension(workspace):
	(workspace / "finance/wrong.fn").write_text("@ontology Wrong\nThing\n")
	_, _, err = onto("ls")
	assert "finance/wrong.fn:1: error cli.kind: a .fn file must start with @functions, not @ontology" in err


def test_search_path_and_no_workspace(workspace, tmp_path, monkeypatch):
	other = tmp_path / "other"
	(other / ".git").mkdir(parents=True)
	monkeypatch.chdir(other)
	binding = str(workspace / "finance/exchange.bind")
	# NOTE: A named file brings its own project with it.
	assert onto("check", binding)[0] == 0
	status, _, err = onto("--no-workspace", "check", binding)
	assert status == 1 and "cli.unresolved" in err
	assert onto("--no-workspace", "-I", str(workspace), "check", binding)[0] == 0
	monkeypatch.setenv("ONTO_PATH", str(workspace))
	assert "Exchange->Finance" in onto("ls")[1]


def test_standard_input_needs_a_kind(workspace, monkeypatch):
	monkeypatch.setattr("sys.stdin", io.StringIO((workspace / "finance/statement.obs").read_text()))
	status, out, _ = onto("log", "--kind", "observations", "-")
	assert status == 0 and out.startswith("@obs Finance")
	status, _, err = onto("log", "-")
	assert status == 1 and "standard input needs --kind KIND" in err


def test_standard_input_loads_alone(workspace, monkeypatch):
	# NOTE: Piped text sharing a workspace namespace is not merged with that namespace's files.
	text = (workspace / "finance/exchange.onto").read_text()
	monkeypatch.setattr("sys.stdin", io.StringIO(text))
	status, out, _ = onto("fmt", "--kind", "ontology", "-")
	assert status == 0 and out == onto("fmt", "finance/exchange.onto")[1]
	monkeypatch.setattr("sys.stdin", io.StringIO(text))
	status, _, err = onto("fmt", "-w", "--kind", "ontology", "-")
	assert status == 1 and "cannot rewrite standard input" in err


def test_json_files_are_read_with_their_context(workspace):
	_, data, _ = onto("json", "finance/exchange-finance.map")
	(workspace / "map.json").write_text(data)
	status, out, _ = onto("text", "map.json")
	assert status == 0 and out == onto("fmt", "finance/exchange-finance.map")[1]
	assert json.loads(data)["format"] == "onto.mapping/1"


# EOF


# -----------------------------------------------------------------------------
#
# REVIEW REGRESSIONS
#
# -----------------------------------------------------------------------------


def test_index_errors_elsewhere_do_not_fail_a_command(workspace):
	(workspace / "finance/wrong.fn").write_text("@ontology X\nThing\n")
	assert onto("state", "finance/statement.obs")[0] == 0
	assert onto("ls")[0] == 1
	status, _, err = onto("check")
	assert status == 1 and "finance/wrong.fn:1: error cli.kind" in err


def test_libraries_using_each_other_do_not_recurse(workspace):
	# NOTE: A library's `@use` names ontologies only, so two libraries naming each other form no cycle.
	for name, other in (("Loop", "Loop2"), ("Loop2", "Loop")):
		(workspace / f"finance/{name.lower()}.fn").write_text(f"@functions {name} rev=1\n@use {other} as L\n\n@fn Same Integer -> Integer\n  1 => 1\n")
	status, _, err = onto("check", "finance/loop.fn")
	assert status == 1 and err.startswith("error reference: Unknown ontology 'Loop2'")


def test_a_library_may_share_an_ontology_namespace(workspace):
	# NOTE: An ontology Markets must not hide the library Markets a binding uses.
	(workspace / "finance/markets.onto").write_text("@ontology Markets rev=1\nThing\n")
	binding = (workspace / "finance/exchange.bind").read_text().replace("format=json\n", "format=json\n@use Markets as M\n", 1)
	(workspace / "finance/exchange.bind").write_text(binding)
	assert onto("check", "finance/exchange.bind")[0] == 0


def test_kind_only_qualifies_standard_input(workspace):
	status, _, err = onto("check", "--kind", "observations", "finance/finance.onto")
	assert status == 0 and err == "no problems in 1 file\n"


def test_mistyped_json_members_are_diagnostics(workspace):
	(workspace / "bad.json").write_text('{"format": "onto.observations/1", "obs": "x"}')
	status, _, err = onto("check", "bad.json")
	assert status == 1 and "internal error" not in err and "bad.json" in err


def test_missing_search_directories_warn(workspace):
	status, _, err = onto("-I", "no-such-dir", "ls", "ontology")
	assert status == 0 and "warning cli.read: search path entry is not a directory: no-such-dir" in err


def test_text_reads_json_from_standard_input(workspace, monkeypatch):
	monkeypatch.setattr("sys.stdin", io.StringIO(onto("json", "finance/sheet.onto")[1]))
	status, out, _ = onto("text", "-")
	assert status == 0 and out == onto("fmt", "finance/sheet.onto")[1]


def test_indexing_errors_of_named_files_are_reported(workspace, monkeypatch):
	monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
	status, _, err = onto("text", "-")
	assert status == 1 and "-: error cli.kind: unknown JSON format None" in err
	(workspace / "notes.txt").write_text("x")
	status, _, err = onto("check", "notes.txt")
	assert status == 1 and "notes.txt: error cli.kind: unknown file kind '.txt'" in err
