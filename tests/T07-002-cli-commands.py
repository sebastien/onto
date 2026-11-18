"""Module: CLI command tests — formatting, conversion, observations, coverage, reversal, inventories and functions (spec-07)."""

from __future__ import annotations

import json
import sys

import pytest

from onto import Source, formatOntology
from tests.cli import onto
from tests.helpers import specExample

# -----------------------------------------------------------------------------
#
# FILES
#
# -----------------------------------------------------------------------------


MESSY = "@ontology Loose   \r\n\n// Kept\nThing -- A thing  // also kept\n  Name Text      --   The name\nOther\n\n\n"
LAID_OUT = (
	"@ontology Loose\n\n// Kept\n"
	+ "Thing".ljust(47) + " -- A thing  // also kept\n"
	+ "  Name Text".ljust(47) + " -- The name\nOther\n"
)


def test_fmt_keeps_hand_edited_files_as_written(workspace):
	# NOTE: The spec examples are laid out: comments, order and record forms stay.
	for path in ("finance/finance.onto", "finance/statement.obs", "finance/exchange-finance.map", "finance/market-ids.ref"):
		status, out, _ = onto("fmt", path)
		assert status == 0 and out == (workspace / path).read_text()
	assert onto("fmt", "--check") == (0, "", "")


def test_fmt_fixes_layout_only(workspace):
	(workspace / "finance/loose.onto").write_text(MESSY)
	status, out, _ = onto("fmt", "finance/loose.onto")
	assert status == 0 and out == LAID_OUT


def test_fmt_check_lists_files_and_fails(workspace):
	(workspace / "finance/loose.onto").write_text(MESSY)
	status, out, err = onto("fmt", "--check")
	assert status == 1 and out == "finance/loose.onto\n"
	assert err == "1 file not laid out; run 'onto fmt -w' to rewrite it\n"


def test_fmt_write_then_check_is_clean(workspace):
	(workspace / "finance/loose.onto").write_text(MESSY)
	status, out, _ = onto("fmt", "-w")
	assert status == 0 and out == "finance/loose.onto\n"
	assert (workspace / "finance/loose.onto").read_text() == LAID_OUT
	assert onto("fmt", "--check") == (0, "", "")


def test_fmt_checks_and_rewrites_crlf_only_changes(workspace):
	file = workspace / "crlf.onto"
	normal = b"@ontology Crlf\n\nThing\n"
	file.write_bytes(normal.replace(b"\n", b"\r\n"))
	assert onto("fmt", "--check", "crlf.onto")[:2] == (1, "crlf.onto\n")
	assert onto("fmt", "-w", "crlf.onto")[:2] == (0, "crlf.onto\n")
	assert file.read_bytes() == normal


def test_fmt_diff_is_unified(workspace):
	(workspace / "finance/loose.onto").write_text("@ontology Loose\nThing -- A thing\n")
	status, out, _ = onto("fmt", "--diff", "finance/loose.onto")
	assert status == 1 and out.startswith("--- a/finance/loose.onto\n+++ b/finance/loose.onto\n")
	assert "+Thing                                           -- A thing" in out


def test_fmt_usage_errors(workspace):
	assert onto("fmt")[0] == 2
	assert onto("fmt", "-w", "--check")[0] == 2


def test_json_and_text_round_trip(workspace):
	status, data, _ = onto("json", "finance/finance.onto")
	assert status == 0 and json.loads(data)["namespace"] == "Finance"
	(workspace / "finance.json").write_text(data)
	assert onto("text", "finance.json")[1] == formatOntology([Source("finance.onto", specExample("spec-01-ontology"))])


def test_json_rejects_kinds_without_a_json_form(workspace):
	status, _, err = onto("json", "finance/exchange.inv")
	assert status == 1 and "inventory files have no JSON form" in err


# -----------------------------------------------------------------------------
#
# OBSERVATIONS
#
# -----------------------------------------------------------------------------


def test_state_and_log(workspace):
	status, state, _ = onto("state", "finance/statement.obs")
	assert status == 0 and state.startswith("@obs Finance")
	assert onto("log", "finance/statement.obs")[1] != state


def test_lenient_gaps_have_no_text_form(workspace):
	(workspace / "finance/gap.obs").write_text("@obs Finance rev=2026-11-10 at=2026-11-10\n@src s=x:y\n@src s\n\np9:Person\n  NoSuchAttr 3\n")
	for command in ("state", "log"):
		status, out, err = onto(command, "--lenient", "finance/gap.obs")
		assert status == 1 and out == ""
		assert "finance/gap.obs:1: error cli.gaps: 1 statement is a gap (lenient mode), which text forms cannot hold; use 'onto json'" in err
	status, out, _ = onto("json", "--lenient", "finance/gap.obs")
	assert status == 0 and json.loads(out)["gaps"]
	# NOTE: Layout needs no text form, so fmt keeps a lenient file as written.
	status, out, _ = onto("fmt", "--lenient", "finance/gap.obs")
	assert status == 0 and out == (workspace / "finance/gap.obs").read_text()


def test_state_rejects_other_kinds(workspace):
	status, _, err = onto("state", "finance/markets.fn")
	assert status == 1 and "finance/markets.fn: error cli.kind: expected observations, not functions" in err


# -----------------------------------------------------------------------------
#
# MAPPINGS
#
# -----------------------------------------------------------------------------


def test_mapping_coverage_table(workspace):
	status, out, _ = onto("coverage", "finance/exchange-finance.map")
	lines = out.splitlines()
	assert status == 0 and lines[0] == "source\ttarget\tstatus\tnote"
	assert "Instrument.Class\tInstrument.AssetClass\ttransformed\t" in lines
	assert "Dividend.TaxCredit\t\tout-of-scope\tTax credits depend on the investor's jurisdiction" in lines


def test_binding_coverage_uses_the_inventory_sidecar(workspace):
	_, withSidecar, _ = onto("coverage", "finance/exchange.bind")
	(workspace / "finance/exchange.inv").unlink()
	_, without, _ = onto("coverage", "finance/exchange.bind")
	assert "uninventoried" in withSidecar and "uninventoried" not in without


def test_binding_coverage_rejects_a_non_inventory_input(workspace):
	status, _, err = onto("coverage", "finance/exchange.bind", "--inventory", "finance/exchange.onto")
	assert status == 1 and "expected inventory, not ontology" in err


def test_observations_coverage_needs_a_view(workspace):
	assert onto("coverage", "finance/statement.obs")[0] == 2
	status, _, err = onto("coverage", "finance/statement.obs", "--view", "NoSuchView")
	assert status == 1 and "Unknown view 'NoSuchView'" in err


def test_reverse_reports_lossy_lines_where_they_are(workspace):
	status, out, err = onto("reverse", "finance/exchange-finance.map")
	assert status == 0 and out.startswith("@mapping Finance -> Exchange")
	assert "finance/exchange-finance.map:19: warning map.lossy: Exchange/Instrument -> Finance/Instrument: 'AssetClass' is not reversed" in err


def test_inventory_and_default_binding(workspace):
	(workspace / "feed.json").write_text(specExample("spec-04-mapping", 0, "json"))
	status, out, _ = onto("inventory", "feed.json")
	assert status == 0 and "instruments[*].bond.couponRate\tnumber" in out.splitlines()
	status, out, _ = onto("inventory", "--binding", "Exchange", "feed.json")
	assert status == 0 and out.startswith("@binding Exchange\n")


def test_inventory_from_csv(workspace):
	(workspace / "rows.csv").write_text("date,value\n2026-11-10,1\n")
	status, out, _ = onto("inventory", "--csv", "rows.csv")
	assert status == 0 and "$[*].date\ttext" in out.splitlines()


# -----------------------------------------------------------------------------
#
# FUNCTIONS
#
# -----------------------------------------------------------------------------

IMPLEMENTATION = """
FREQ = {1: "Monthly", 3: "Quarterly", 6: "Biannually", 12: "%s"}
IMPLEMENTATIONS = {
	"Markets/FrequencyFromInterval": lambda months: FREQ[int(months)],
	"Markets/IntervalFromFrequency": lambda name: str({v: k for k, v in FREQ.items()}[name]),
}
"""


@pytest.fixture
def implementation(workspace, monkeypatch):
	def write(name: str, yearly: str) -> str:
		(workspace / f"{name}.py").write_text(IMPLEMENTATION % yearly)
		monkeypatch.setattr(sys, "path", list(sys.path))
		return name
	yield write
	for name in ("markets_good", "markets_bad"):
		sys.modules.pop(name, None)


def test_fn_ls(workspace):
	status, out, _ = onto("fn", "ls")
	assert status == 0
	assert out.splitlines()[0] == "Markets/FrequencyFromInterval\tInteger -> Dimensions/InterestFrequency\tMonths between payments"


def test_fn_test_skips_unimplemented_functions(workspace):
	status, out, err = onto("fn", "test")
	assert status == 0 and "Markets\tpassed\t0\t2" in out
	assert "warning fn.unimplemented: Markets/FrequencyFromInterval has no implementation" in err


def test_fn_test_runs_implementations(workspace, implementation):
	status, out, _ = onto("fn", "test", "--impl", implementation("markets_good", "Yearly"))
	assert status == 0 and "Markets\tpassed\t8\t0" in out
	status, out, err = onto("fn", "test", "--impl", implementation("markets_bad", "Monthly"))
	assert status == 1 and "Markets\tfailed" in out and "error conformance: Failed example" in err


def test_fn_test_imports_multiple_modules_from_the_working_directory(workspace):
	names = ("onto_test_first_impl", "onto_test_second_impl")
	for name in names:
		(workspace / f"{name}.py").write_text("IMPLEMENTATIONS = {}\n")
	try:
		status, _, err = onto("fn", "test", "--impl", names[0], "--impl", names[1])
		assert status == 0, err
	finally:
		for name in names:
			sys.modules.pop(name, None)


def test_fn_test_unknown_module_is_a_usage_error(workspace):
	status, _, err = onto("fn", "test", "--impl", "no_such_module")
	assert status == 2 and "cannot import --impl no_such_module" in err


# EOF


def test_lossy_lines_carry_their_own_location(workspace):
	_, _, err = onto("reverse", "finance/exchange-finance.map")
	lines = [line for line in err.splitlines() if "map.lossy" in line]
	assert lines and all(not line.startswith("finance/exchange-finance.map:1:") for line in lines)


# -----------------------------------------------------------------------------
#
# META
#
# -----------------------------------------------------------------------------


EXTRA = "Rating = Low|Medium|High {ordered} -- A rating\nScore = Number\nThing -- A thing\n  1 Name Text -- Its name\n  * Ratings Rating\n  Score Score\n  State On|Off|...\n  Other Thing\n"


def test_meta_declarations_and_observations_validate(workspace):
	status, declarations, _ = onto("meta", "--decl", "finance/finance.onto")
	assert status == 0 and declarations.startswith("@ontology Finance")
	(workspace / "finance/meta.onto").write_text(declarations)
	assert onto("fmt", "--check", "finance/meta.onto") == (0, "", "")
	status, observations, err = onto("meta", "finance/finance.onto")
	assert status == 0 and err == ""
	(workspace / "finance/finance-meta.obs").write_text(observations)
	status, _, err = onto("check", "finance/finance-meta.obs")
	assert status == 0, err


def test_meta_describes_concepts_attributes_and_dimensions(workspace):
	(workspace / "finance/meta.onto").write_text(onto("meta", "--decl", "finance/finance.onto")[1])
	(workspace / "finance/extra.onto").write_text((workspace / "finance/finance.onto").read_text().splitlines()[0] + "\n" + EXTRA)
	status, out, _ = onto("meta", "finance/finance.onto")
	assert status == 0
	for text in (
		"Thing:Meta/Concept\n  Path Thing\n  Kind Entity\n  Description A thing\n",
		"Thing__Name:Meta/Attribute\n  Path Thing.Name\n  IsRequired true\n  IsMultiple false\n  Description Its name\n",
		"Thing__Ratings:Meta/Attribute\n  Path Thing.Ratings\n  IsRequired false\n  IsMultiple true\n",
		"Rating:Meta/Dimension\n  Path Rating\n  Kind Vocabulary\n  Values [Low, Medium, High]\n  IsOpen false\n  IsOrdered true\n  Description A rating\n",
		"Thing__State__Values:Meta/Dimension\n  Path Thing.State\n  Kind Vocabulary\n  Values [On, Off]\n  IsOpen true\n",
		"Score:Meta/Dimension\n  Path Score\n  Kind Value\n",
		"Score isBasedOn Number\n",
		"Thing hasAttribute Thing__Name\n",
		"Thing__Name hasDimension Text\n",
		"Thing__Ratings hasDimension Rating\n",
		"Thing__State hasDimension Thing__State__Values\n",
		# NOTE: The Meta domain describes itself, as any other domain.
		"Meta_Concept__Kind hasDimension Meta_Concept_Kind\n",
	):
		assert text in out, text
	# NOTE: An attribute that refers to a concept has no dimension.
	assert "Thing__Other hasDimension" not in out
	(workspace / "finance/finance-meta.obs").write_text(out)
	status, _, err = onto("check", "finance/finance-meta.obs")
	assert status == 0, err


def test_meta_without_the_domain_hints_at_the_declarations(workspace):
	status, out, err = onto("meta", "finance/finance.onto")
	assert status == 0 and out.startswith("@obs Finance")
	assert err == "Finance has no Meta domain; add it with 'onto meta --decl finance/finance.onto > meta.onto'\n"


# -----------------------------------------------------------------------------
#
# RUN
#
# -----------------------------------------------------------------------------


def test_run_binds_documents_and_maps_their_observations(workspace, implementation):
	pytest.importorskip("hexa.shapes")
	(workspace / "feed.json").write_text(specExample("spec-04-mapping", 0, "json"))
	status, out, err = onto("run", "finance/exchange.bind", "feed.json", "--src", "feed:instruments", "--at", "2026-11-18T00:00:00Z")
	# The spec's feed has a bond without dividends: one gap below it, reported as a warning
	assert status == 0 and err.count("run.gap") == 1 and "Exchange/Dividend: Issue.Missing" in err
	assert "@src d1=feed:instruments" in out and "{by=bind:Exchange}" in out
	(workspace / "exchange.obs").write_text(out)
	status, out, err = onto("run", "finance/exchange-finance.map", "exchange.obs", "--impl", implementation("markets_run", "Yearly"), "--at", "2026-11-18T00:00:00Z")
	assert status == 0, err
	assert "@obs Finance" in out and "by=map:Exchange->Finance" in out
	status, data, _ = onto("run", "finance/exchange.bind", "feed.json", "--json", "--at", "2026-11-18T00:00:00Z")
	assert status == 0 and json.loads(data)["result"]["format"] == "onto.observations/1"
	status, _, _ = onto("run", "finance/exchange.bind", "feed.json", "--report", "report.json", "--at", "2026-11-18T00:00:00Z")
	report = json.loads((workspace / "report.json").read_text())
	assert status == 0 and report == {"format": "onto.run-report/1", "gaps": [{"target": "Exchange/Dividend", "reason": "Issue.Missing", "src": "feed.json", "location": "/instruments/1"}]}
	status, out, _ = onto("run", "finance/exchange.bind", "feed.json", "--src", "feed:{stem}", "--max-nodes", "500000", "--at", "2026-11-18T00:00:00Z")
	assert status == 0 and "@src d1=feed:feed" in out


def test_run_reports_gaps_as_warnings_or_with_strict_errors(workspace):
	pytest.importorskip("hexa.shapes")
	feed = json.loads(specExample("spec-04-mapping", 0, "json"))
	del feed["instruments"][0]["isin"]
	(workspace / "feed.json").write_text(json.dumps(feed))
	status, out, err = onto("run", "finance/exchange.bind", "feed.json")
	assert status == 0 and "warning run.gap: Exchange/Instrument" in err
	status, _, err = onto("run", "finance/exchange.bind", "feed.json", "--strict")
	assert status == 1


@pytest.fixture
def namesMapping(workspace):
	pytest.importorskip("hexa.shapes")
	for namespace in ("Input", "Output"):
		(workspace / f"{namespace}.onto").write_text(f"@ontology {namespace}\nPerson\n  Name Text\n")
	(workspace / "names.map").write_text("@mapping Input -> Output\nPerson -> Person\n  Name <- Name\n")
	return workspace


@pytest.mark.parametrize("source", ["", "@src names\n"])
def test_run_keeps_a_claim_after_an_equal_timestamp_retraction(namesMapping, source):
	(namesMapping / "names.obs").write_text(
		f"@obs Input\n{source}@at 2026-01-01\np:Person\np.Name Before\n- p.Name\np.Name After\n"
	)
	status, out, err = onto("run", "names.map", "names.obs", "--json", "--at", "2026-01-02T00:00:00Z")
	assert status == 0, err or out
	result = json.loads(out)["result"]
	claims = result["claims"]
	assert [claim["v"] for claim in claims if claim.get("p") == "Name"] == ["After"]
	assert bool(result["sources"]) == bool(source)
	assert all(("src" in claim) == bool(source) for claim in claims)


@pytest.mark.parametrize("files", [("a.obs", "b.obs"), ("b.obs", "a.obs")])
def test_run_keeps_each_inputs_claim_defaults(namesMapping, files):
	(namesMapping / "a.obs").write_text(
		"@obs Input src=feed at=2026-01-01 by=feed:a conf=0.7\n@src feed=feed:a\np:Person\np.Name Alice\n"
	)
	(namesMapping / "b.obs").write_text("@obs Input\nq:Person\nq.Name Bob\n")
	status, out, err = onto("run", "names.map", *files, "--json")
	assert status == 0, err or out
	result = json.loads(out)["result"]
	claims = {claim["v"]: claim for claim in result["claims"] if claim.get("p") == "Name"}
	assert claims.keys() == {"Alice", "Bob"}
	assert result["sources"][claims["Alice"]["src"]] == "feed:a" and claims["Alice"]["conf"] == 0.7
	assert "src" not in claims["Bob"] and "conf" not in claims["Bob"]


def test_run_keeps_bare_sources_apart_from_generated_aliases(namesMapping):
	from onto.integrations.hexa.vocabulary import sourceHandle

	(namesMapping / "a.obs").write_text(
		"@obs Input\n@scope shared\n@src feed=feed:a\np:Person\np.Name Alice {src=feed}\n"
	)
	(namesMapping / "b.obs").write_text(
		"@obs Input\n@scope shared\np:Person\np.Name Bob {src=d1}\n- p.Name {of=d1}\nq:Person\nq.Name Carol {src=d1}\n"
	)
	status, out, err = onto("run", "names.map", "a.obs", "b.obs", "--json")
	assert status == 0, err or out
	result = json.loads(out)["result"]
	assert {claim["v"]: (claim["s"], result["sources"][claim["src"]]) for claim in result["claims"] if claim.get("p") == "Name"} == {
		"Alice": (sourceHandle("Person", "shared", "p", "Input/Person"), "feed:a"),
		"Carol": (sourceHandle("Person", "shared", "q", "Input/Person"), "d1"),
	}


@pytest.mark.parametrize(("first", "second"), [("", ""), ("@scope east\n", ""), ("@scope east\n", "@scope west\n")])
def test_run_rejects_overlapping_handles_without_a_shared_scope(namesMapping, first, second):
	(namesMapping / "a.obs").write_text(f"@obs Input\n{first}p:Person\np.Name Alice\n")
	(namesMapping / "b.obs").write_text(f"@obs Input\n{second}p:Person\np.Name Bob\n")
	status, out, err = onto("run", "names.map", "a.obs", "b.obs")
	assert status == 1 and not out
	assert "b.obs:1: error run.scope:" in err and "@scope" in err


def test_run_needs_a_binding_or_mapping(workspace):
	status, _, err = onto("run", "finance/finance.onto", "x.json")
	assert status == 1 and "expected binding or mapping" in err
