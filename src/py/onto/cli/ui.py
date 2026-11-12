"""Module: cli.ui — terminal styles, diagnostics, summaries and tables for human output."""

from __future__ import annotations

import os
import shutil
import textwrap
from dataclasses import dataclass
from typing import TextIO

from ..text import Diagnostic

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

STYLES = {
	"error": "1;31",
	"warning": "1;33",
	"location": "1",
	"code": "2",
	"namespace": "35",
	"name": "32",
	"kind": "36",
	"heading": "1;36",
	"command": "1",
	"hint": "2",
	"ok": "32",
}
# NOTE: Coverage statuses, from fully covered (green) to not covered (red).
STATUS_STYLES = {
	"direct": "32",
	"transformed": "36",
	"condition": "33",
	"ambiguous": "33",
	"ignore": "2",
	"out-of-scope": "2",
	"unmapped": "31",
	"unassigned": "31",
	"uninventoried": "31",
	"missing": "31",
	"passed": "32",
	"failed": "31",
}


@dataclass(slots=True, frozen=True)
class Style:
	"""ANSI styling for one stream; disabled styles return text unchanged."""

	enabled: bool = False

	def paint(self, name: str, text: str) -> str:
		"""Render `text` in style `name`."""
		code = STYLES.get(name) or STATUS_STYLES.get(name)
		return f"\x1b[{code}m{text}\x1b[0m" if self.enabled and code and text else text

	def path(self, text: str) -> str:
		"""Color an element path: namespaces magenta, the element name green."""
		if not self.enabled or not text:
			return text
		head, slash, tail = text.rpartition("/")
		return (self.paint("namespace", head + slash) if slash else "") + self.paint("name", tail)


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def colorEnabled(when: str, stream: TextIO) -> bool:
	"""Whether to color `stream` under `--color when`."""
	if when != "auto":
		return when == "always"
	isTty = getattr(stream, "isatty", None)
	return bool(isTty and isTty()) and os.environ.get("TERM") != "dumb" and not (os.environ.get("NO_COLOR") or os.environ.get("NOCOLOR"))


def width() -> int:
	"""Terminal width for wrapping help, at least 60 columns."""
	return max(60, min(100, shutil.get_terminal_size((88, 24)).columns - 2))


def wrap(text: str, indent: str = "", hanging: str | None = None) -> str:
	"""Wrap `text` to the terminal width, with `indent` and an optional `hanging` indent."""
	return textwrap.fill(text, width(), initial_indent=indent, subsequent_indent=indent if hanging is None else hanging)


def plural(count: int, word: str) -> str:
	"""`1 file`, `2 files`."""
	return f"{count} {word}{'' if count == 1 else 's'}"


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Render:
	"""Human-readable rendering of diagnostics, summaries and tables."""

	@staticmethod
	def SortKey(item: Diagnostic) -> tuple:
		"""Order by file, line, then errors before warnings."""
		return ((item.loc.file or "") if item.loc else "", item.loc.line if item.loc else 0, item.level != "error")

	@staticmethod
	def DiagnosticLine(item: Diagnostic, style: Style) -> str:
		"""`file:line: level code: message`, as `str(Diagnostic)` prints it, with optional color."""
		line = f"{item.loc.line}:" if item.loc and item.loc.line else ""
		where = style.paint("location", f"{item.loc.file}:{line}") + " " if item.loc and item.loc.file else ""
		return f"{where}{style.paint(item.level, item.level)} {style.paint('code', item.code + ':')} {item.message}"

	@staticmethod
	def Summary(diagnostics: list[Diagnostic], checked: int, read: int) -> str:
		"""`N errors, M warnings in K files (R read)`."""
		errors = sum(item.level == "error" for item in diagnostics)
		warnings = len(diagnostics) - errors
		files = f" in {plural(checked, 'file')}" if checked else ""
		extra = f" ({read} read)" if read > checked else ""
		if not diagnostics:
			return f"no problems{files}{extra}"
		counts = [plural(count, word) for count, word in ((errors, "error"), (warnings, "warning")) if count]
		return f"{', '.join(counts)}{files}{extra}"

	@staticmethod
	def Table(columns: tuple[str, ...], rows: list[dict[str, str]], style: Style, header: bool = True) -> str:
		"""Tab-separated rows; colored columns are padded for terminals, plain ones stay TSV."""
		lines = []
		if not style.enabled:
			if header:
				lines.append("\t".join(columns))
			lines.extend("\t".join(row.get(column) or "" for column in columns) for row in rows)
			return "\n".join(lines)
		widths = {column: max([len(column)] + [len(row.get(column) or "") for row in rows]) for column in columns}
		if header:
			lines.append(style.paint("hint", "  ".join(column.ljust(widths[column]) for column in columns).rstrip()))
		for row in rows:
			cells = []
			for column in columns:
				value = row.get(column) or ""
				cells.append(Render.Cell(column, value, style) + " " * (widths[column] - len(value)))
			lines.append("  ".join(cells).rstrip())
		return "\n".join(lines)

	@staticmethod
	def Cell(column: str, value: str, style: Style) -> str:
		"""Style one table cell by its column."""
		if column == "kind":
			return style.paint("kind", value)
		if column == "status":
			return "+".join(style.paint(part, part) for part in value.split("+"))
		if column in ("namespace", "source", "target", "path", "name"):
			return style.path(value)
		if column in ("rev", "note", "doc"):
			return style.paint("hint", value)
		return value


__all__ = ["Render", "Style", "colorEnabled", "plural", "wrap"]

# EOF
