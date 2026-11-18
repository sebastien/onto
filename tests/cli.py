"""Module: tests.cli — a spec-example workspace and an in-process runner for CLI tests (spec-07)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from onto.cli import run
from tests.helpers import specExample

# -----------------------------------------------------------------------------
#
# FIXTURES
#
# -----------------------------------------------------------------------------


FILES = {
	"finance/finance.onto": ("spec-01-ontology", 0),
	"finance/exchange.onto": ("spec-04-mapping", 1),
	"finance/exchange.bind": ("spec-04-mapping", 2),
	"finance/markets.fn": ("spec-04-mapping", 3),
	"finance/market-ids.ref": ("spec-04-mapping", 4),
	"finance/exchange-finance.map": ("spec-04-mapping", 5),
	"finance/sheet.onto": ("spec-04-mapping", 7),
	"finance/finance-sheet.map": ("spec-04-mapping", 8),
	"finance/sheet.bind": ("spec-04-mapping", 9),
	"finance/exchange.formats": ("spec-04-mapping", 15),
	"finance/exchange.inv": ("spec-04-mapping", 16),
	"finance/statement.obs": ("spec-02-observations", 0),
}


def makeWorkspace(root: Path) -> Path:
	"""A project (with a .git marker) holding the spec examples."""
	(root / ".git").mkdir(parents=True)
	for path, (spec, index) in FILES.items():
		(root / path).parent.mkdir(parents=True, exist_ok=True)
		(root / path).write_text(specExample(spec, index))
	return root


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
	root = makeWorkspace(tmp_path / "project")
	monkeypatch.chdir(root)
	monkeypatch.delenv("ONTO_PATH", raising=False)
	return root


def onto(*argv: str) -> tuple[int, str, str]:
	"""Run the CLI in process: exit status, standard output, standard error."""
	stdout, stderr = io.StringIO(), io.StringIO()
	status = run(list(argv), stdout, stderr)
	return status, stdout.getvalue(), stderr.getvalue()


# EOF
