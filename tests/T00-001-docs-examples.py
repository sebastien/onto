"""Module: documentation example tests — every `onto` block of the skills and references loads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from onto.ontology import loadOntology
from onto.text import FormatError, Source
from tests._helpers import ROOT

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

# NOTE: Only these directories promise checked examples; the specs use `text`
# blocks, which mix formats and deliberate errors.
DOCS = ("docs/skills", "docs/ref")
BLOCK = re.compile(r"^```onto\n(.*?)^```", re.S | re.M)
# NOTE: Fragments omit the header; a file must start with one.
HEADER = "@ontology Example\n"


@dataclass(frozen=True, slots=True)
class Example:
	"""An `onto` block of a document, with where it starts."""

	path: Path
	line: int
	text: str

	@property
	def name(self) -> str:
		return f"{self.path.relative_to(ROOT)}:{self.line}"


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def documents() -> list[Path]:
	"""List the Markdown files of `DOCS` once each, whatever links lead to them."""
	found = {path.resolve() for base in DOCS for path in (ROOT / base).rglob("*.md")}
	return sorted(found)


def examples() -> list[Example]:
	"""Extract the `onto` blocks of every document."""
	result = []
	for path in documents():
		text = path.read_text()
		for match in BLOCK.finditer(text):
			line = text.count("\n", 0, match.start(1)) + 1
			result.append(Example(path, line, match.group(1)))
	return result


def problems(example: Example) -> list[str]:
	"""Load `example` as one ontology file and return its error messages."""
	text = example.text if example.text.startswith("@ontology") else HEADER + example.text
	try:
		loadOntology([Source(example.name, text)])
	except FormatError as error:
		return [str(item) for item in error.diagnostics if item.level == "error"]
	return []


EXAMPLES = examples()

# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------


def testDocumentsHaveExamples():
	assert EXAMPLES


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda example: example.name)
def testExampleLoads(example: Example):
	assert problems(example) == []


# EOF
