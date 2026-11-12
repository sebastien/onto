"""Module: formats.model — spec-04 formats files: the value formats learned per document field."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..text import Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


HEADER = "path\tformat\tseen\tpin"


@dataclass(slots=True)
class FormatsEntry:
	"""One field: its chosen format, the formats seen with their counts, and whether a person pinned it."""

	path: str
	format: str
	seen: dict[str, int] = field(default_factory=dict)
	pin: bool = False
	loc: Loc | None = None

	def ordered(self) -> list[tuple[str, int]]:
		"""Seen formats, most frequent first, then by name."""
		return sorted(self.seen.items(), key=lambda item: (-item[1], item[0]))


@dataclass(slots=True)
class Formats:
	"""A formats file (`<binding>.formats`), entries by field path."""

	entries: dict[str, FormatsEntry] = field(default_factory=dict)
	diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class FormatChange:
	"""A field whose chosen format changed: strict hosts wait for approval, lenient ones warn."""

	path: str
	previous: str
	format: str


__all__ = ["HEADER", "FormatsEntry", "Formats", "FormatChange"]

# EOF
