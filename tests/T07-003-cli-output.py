"""Module: CLI output tests — help, usage errors, JSON output, colors, quiet mode and exit status (spec-07)."""

from __future__ import annotations

import io
import json

from onto.cli import main, run
from tests.cli import onto

# -----------------------------------------------------------------------------
#
# HELP AND USAGE
#
# -----------------------------------------------------------------------------


def test_top_help_groups_commands_and_terms():
	for argv in ([], ["--help"], ["help"]):
		status, out, _ = onto(*argv)
		assert status == 0
		for text in ("Usage: onto", "Files:", "Observations:", "Mappings:", "Functions:", "Terms:", "Getting started:", "check [FILE...]"):
			assert text in out


def test_command_help_has_options_and_examples():
	status, out, _ = onto("coverage", "--help")
	assert status == 0 and out.startswith("Usage: onto coverage FILE")
	assert "--view VIEW" in out and "Examples:" in out
	assert onto("help", "coverage")[1] == out


def test_unknown_command_suggests_the_closest():
	status, _, err = onto("chek")
	assert status == 2
	assert err == "onto: error: unknown command 'chek'. Did you mean 'check'?\nRun 'onto --help' for examples and argument descriptions.\n"


def test_unknown_option_suggests_the_closest():
	status, _, err = onto("check", "--lenent")
	assert status == 2 and "Did you mean --lenient?" in err and "Run 'onto check --help'" in err


def test_abbreviations_are_rejected():
	assert onto("check", "--len")[0] == 2


def test_version():
	status, out, _ = onto("--version")
	assert status == 0 and out.startswith("onto ")


# -----------------------------------------------------------------------------
#
# OUTPUT
#
# -----------------------------------------------------------------------------


def test_json_output_wraps_result_and_diagnostics(workspace):
	(workspace / "finance/bad.onto").write_text("@ontology Bad\nThing\n  Field NoSuchType\n")
	status, out, err = onto("--json", "check", "finance/bad.onto")
	document = json.loads(out)
	assert status == 1 and err == ""
	assert document["format"] == "onto.cli/1" and document["command"] == "check" and document["ok"] is False
	assert document["diagnostics"][0] | {"message": ""} == {"level": "error", "code": "reference", "message": "", "file": "finance/bad.onto", "line": 3}
	assert document["files"] == {"checked": 1, "read": 1}


def test_json_option_may_follow_the_command(workspace):
	status, out, _ = onto("ls", "--json", "ontology")
	assert status == 0 and {row["namespace"] for row in json.loads(out)["result"]} == {"Exchange", "Finance", "Sheet"}


def test_json_result_of_conversions_is_the_document(workspace):
	_, out, _ = onto("--json", "json", "finance/markets.fn")
	assert json.loads(out)["result"]["format"] == "onto.functions/1"


def test_colors_are_off_unless_asked(workspace):
	assert "\x1b[" not in "".join(onto("check", "finance/missing.onto")[1:])
	_, _, err = onto("--color", "always", "check", "finance/missing.onto")
	assert "\x1b[1;31merror\x1b[0m" in err


def test_normal_forms_are_never_colored(workspace):
	assert "\x1b[" not in onto("--color", "always", "fmt", "finance/finance.onto")[1]


def test_quiet_keeps_diagnostics_only(workspace):
	assert onto("-q", "check") == (0, "", "")
	status, out, err = onto("-q", "check", "finance/missing.onto")
	assert status == 1 and out == "" and err == "error cli.read: no such file: finance/missing.onto\n"


def test_main_reports_internal_errors(monkeypatch, capsys):
	def fail(*args):
		raise RuntimeError("boom")
	monkeypatch.setattr("onto.cli.run", fail)
	monkeypatch.delenv("ONTO_DEBUG", raising=False)
	assert main(["check"]) == 1
	assert capsys.readouterr().err == "onto: internal error: boom\nRerun with ONTO_DEBUG=1 for the traceback.\n"


def test_stdout_and_stderr_are_separate(workspace):
	stdout, stderr = io.StringIO(), io.StringIO()
	run(["reverse", "finance/exchange-finance.map"], stdout, stderr)
	assert "map.lossy" not in stdout.getvalue() and "map.lossy" in stderr.getvalue()


# EOF


def test_help_and_version_need_no_command_arguments():
	assert onto("-h", "json")[1].startswith("Usage: onto json FILE")
	assert onto("--version", "json")[1].startswith("onto ")
	assert onto("json", "--version") == onto("--version", "json")


def test_json_fmt_result_is_keyed_by_file_even_when_one_fails(workspace):
	(workspace / "finance/bad.onto").write_text("@ontology Bad\nThing\n  Field NoSuchType\n")
	status, out, _ = onto("--json", "fmt", "finance/bad.onto", "finance/sheet.onto")
	document = json.loads(out)
	assert status == 1 and list(document["result"]) == ["finance/sheet.onto"]


def test_tables_keep_every_column(workspace):
	_, out, _ = onto("coverage", "finance/exchange-finance.map")
	assert {line.count("\t") for line in out.splitlines()} == {3}


def test_whole_file_diagnostics_have_a_null_line_in_json(workspace):
	document = json.loads(onto("--json", "state", "finance/markets.fn")[1])
	assert document["diagnostics"][0]["line"] is None
