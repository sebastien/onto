"""Module: formats.formatter — print formats files in their sorted tab-separated form."""

from __future__ import annotations

from .model import HEADER, Formats

# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def printFormats(formats: Formats) -> str:
	"""The header, then one line per field sorted by path; seen formats most frequent first."""
	lines = [HEADER]
	for path, entry in sorted(formats.entries.items()):
		seen = "; ".join(f"{name} {count}" for name, count in entry.ordered())
		lines.append(f"{path}\t{entry.format}\t{seen}" + ("\tpin" if entry.pin else ""))
	return "\n".join(lines) + "\n"


__all__ = ["printFormats"]

# EOF
