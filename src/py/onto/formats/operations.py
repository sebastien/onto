"""Module: formats.operations — fold a run's format tallies into a formats file."""

from __future__ import annotations

from copy import deepcopy

from .model import FormatChange, Formats, FormatsEntry

# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def formatsUpdate(previous: Formats | None, counts: dict[str, dict[str, int]]) -> tuple[Formats, list[FormatChange]]:
	"""Add a run's `counts` (field path → format → count) to `previous`.

	The chosen format becomes the most frequent one (then by name), unless the field
	is pinned; each change of an existing chosen format is listed. `previous` is not mutated.
	"""
	entries = deepcopy(previous.entries) if previous else {}
	changes: list[FormatChange] = []
	for path, tally in sorted(counts.items()):
		if not tally:
			continue
		entry = entries.setdefault(path, FormatsEntry(path, ""))
		for name, count in tally.items():
			entry.seen[name] = entry.seen.get(name, 0) + count
		if entry.pin or not entry.seen:
			continue
		chosen = entry.ordered()[0][0]
		# NOTE: A field's first chosen format is learned, not changed: only later switches are listed.
		if entry.format and chosen != entry.format:
			changes.append(FormatChange(path, entry.format, chosen))
		entry.format = chosen
	return Formats(dict(sorted(entries.items()))), changes


__all__ = ["formatsUpdate"]

# EOF
