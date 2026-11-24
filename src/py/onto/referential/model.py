"""Module: referential.model — identity policy declarations, not registry allocations."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..text import Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


REFERENTIAL_FORMAT = "onto.referential/1"


@dataclass(slots=True)
class Policy:
	"""A key/minted identity policy, or an implicit-age-only declaration for an instance type."""

	type: str
	keys: list[str] = field(default_factory=list)
	minted: bool = False
	fromNamespace: str | None = None
	implicit: str | None = None
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class Referential:
	"""One referential's files with qualified type paths, locations and diagnostics."""

	namespace: str
	header: dict[str, str] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	policies: list[Policy] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)
	loc: Loc | None = None


__all__ = ["Policy", "Referential", "REFERENTIAL_FORMAT"]

# EOF
