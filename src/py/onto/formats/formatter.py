"""Module: formats.formatter — print formats files in their sorted tab-separated form."""

from __future__ import annotations

import json

from .model import HEADER, Formats

# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def spellFormat(name: str) -> str:
	"""Quote a name when it would otherwise be mistaken for a delimiter."""
	return json.dumps(name, ensure_ascii=False) if name.startswith('"') or any(mark in name for mark in ("; ", "\t", "\r", "\n")) else name


def printFormats(formats: Formats) -> str:
	"""The header, then one line per field sorted by path; seen formats most frequent first."""
	lines = [HEADER]
	for path, entry in sorted(formats.entries.items()):
		seen = "; ".join(f"{spellFormat(name)} {count}" for name, count in entry.ordered())
		lines.append(f"{path}\t{spellFormat(entry.format)}\t{seen}" + ("\tpin" if entry.pin else ""))
	return "\n".join(lines) + "\n"


__all__ = ["printFormats"]

# EOF
