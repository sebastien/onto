"""Module: formats.parser — read formats files and check format names."""

from __future__ import annotations

import re

from ..inventory.parser import canonicalPath
from ..text import Diagnostics, Loc, Source
from .model import HEADER, Formats, FormatsEntry

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


RE_FORMAT = re.compile(r"decimals:[0-9]+|case:(?:upper|lower)|trim|padded|sep:.+")


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
	for item in text.split("; ") if text else []:
		name, _, count = item.rpartition(" ")
		if not name or not count.isdigit() or not isFormat(name) or name in result:
			raise ValueError(f"Invalid seen formats '{item}'")
		result[name] = int(count)
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
			path = canonicalPath(parts[0])
			if not isFormat(parts[1]):
				raise ValueError(f"Unknown format '{parts[1]}'")
			if path in entries:
				raise ValueError(f"Duplicate field '{path}'")
			entries[path] = FormatsEntry(path, parts[1], parseSeen(parts[2]), len(parts) == 4 and parts[3] == "pin", loc)
		except ValueError as error:
			diag.error("formats", str(error), loc)
	return Formats(dict(sorted(entries.items())), diag.check())


__all__ = ["isFormat", "parseFormats"]

# EOF
