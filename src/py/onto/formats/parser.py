"""Module: formats.parser — read formats files and check format names."""

from __future__ import annotations

import json
import re

from ..expressions import parseExpression, printExpression
from ..text import Diagnostics, Loc, Source
from .model import HEADER, Formats, FormatsEntry

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


RE_FORMAT = re.compile(r"decimals:[0-9]+|case:(?:upper|lower)|trim|padded|sep:.+", re.DOTALL)
DECODER = json.JSONDecoder()


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def isFormat(name: str) -> bool:
	"""Date and date-time patterns (with `YYYY`, `MM` and `DD`), `decimals:N`, `case:…`, `trim`, `padded` or `sep:…`."""
	return RE_FORMAT.fullmatch(name) is not None or all(token in name for token in ("YYYY", "MM", "DD"))


def parseSeen(text: str) -> dict[str, int]:
	"""`YYYYMMDD 412; YYYY-MM-DD 3` → counts by format."""
	result: dict[str, int] = {}
	while text:
		if text.startswith('"'):
			name, end = DECODER.raw_decode(text)
			if text[end:end + 1] != " ":
				raise ValueError(f"Invalid seen formats '{text}'")
			count, separator, rest = text[end + 1:].partition("; ")
			item = text[:end] + " " + count
		else:
			item, separator, rest = text.partition("; ")
			name, _, count = item.rpartition(" ")
		if not count.isascii() or not count.isdigit() or not isFormat(name) or name in result or separator and not rest:
			raise ValueError(f"Invalid seen formats '{item}'")
		result[name] = int(count)
		text = rest
	return result


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseFormats(source: Source) -> Formats:
	"""Parse a formats file: the header line, then `path, format, seen[, pin]` tab-separated lines."""
	diag = Diagnostics()
	entries: dict[str, FormatsEntry] = {}
	lines = source.text.replace("\r\n", "\n").split("\n")
	if lines[0] != HEADER:
		diag.error("formats", "Expected the formats header line", Loc(source.name, 1))
		return Formats(diagnostics=diag.check())
	for number, text in enumerate(lines[1:], 2):
		if not text.strip():
			continue
		loc = Loc(source.name, number)
		parts = text.split("\t")
		try:
			if len(parts) not in (3, 4) or len(parts) == 4 and parts[3] not in ("pin", ""):
				raise ValueError("Expected 'path<TAB>format<TAB>seen[<TAB>pin]'")
			expr = parseExpression(parts[0], binding=True)
			if "path" not in expr or any(isinstance(step, dict) and "up" in step for step in expr["path"]):
				raise ValueError(f"Invalid formats path '{parts[0]}'")
			path = printExpression(expr, binding=True)
			name = json.loads(parts[1]) if parts[1].startswith('"') else parts[1]
			if not isFormat(name):
				raise ValueError(f"Unknown format '{name}'")
			if path in entries:
				raise ValueError(f"Duplicate field '{path}'")
			entries[path] = FormatsEntry(path, name, parseSeen(parts[2]), len(parts) == 4 and parts[3] == "pin", loc)
		except ValueError as error:
			diag.error("formats", str(error), loc)
	return Formats(dict(sorted(entries.items())), diag.check())


__all__ = ["isFormat", "parseFormats"]

# EOF
