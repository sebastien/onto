"""Module: integrations.hexa.model — compiled programs, run reports and outcomes (spec-06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ...binding.model import Binding
from ...formats.model import Formats
from ...inventory.model import Inventory
from ...mapping.model import Mapping
from ...ontology.model import Model, Ontology

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


class StageNamespace:
	"""A frozen namespace of a program's stages, read by attribute (`program.stages.BindingRead`).

	hexa's `stages` registers names process-wide, which would forbid compiling two
	programs with the same scope types; these stages carry their names unregistered.
	"""

	__slots__ = ("members",)

	def __init__(self, members: dict[str, Any]):
		object.__setattr__(self, "members", MappingProxyType(dict(members)))

	def __getattr__(self, name: str) -> Any:
		try:
			return self.members[name]
		except KeyError:
			raise AttributeError(name) from None

	def __setattr__(self, name: str, value: Any) -> None:
		raise AttributeError("immutable stage namespace")

	def __iter__(self):
		return iter(self.members)


@dataclass(slots=True)
class ScopeProgram:
	"""One compiled scope line (or mapping scope): its selector, shape, record template and stages."""

	name: str
	type: str
	selector: str
	shape: Any
	template: dict[str, Any]
	outer: tuple[Any, ...] = ()
	levels: list[str] = field(default_factory=list)
	parent: str | None = None
	picks: list[int | None] = field(default_factory=list)  # per level, the one position an index step keeps
	source: str | None = None
	optional: bool = False  # a missing path makes no record and no gap (spec-04 Scope lines)


@dataclass(slots=True)
class BindingProgram:
	"""A compiled binding: hexa slots, shapes, templates and the stage namespace (`stages`)."""

	ontology: Ontology
	binding: Binding
	mode: str
	slots: dict[str, Any]
	shapes: dict[str, Any]
	templates: dict[str, Any]
	selectors: dict[str, str]
	vocabulary: list[str]
	stages: StageNamespace
	scopes: list[ScopeProgram]
	formats: Formats | None = None
	inventory: Inventory | None = None
	model: Model | None = None
	writeFields: set[str] = field(default_factory=set)


@dataclass(slots=True)
class MappingProgram:
	"""A compiled mapping: per-scope trees and templates, the reach, and the stage namespace."""

	fromOntology: Ontology
	toOntology: Ontology
	mapping: Mapping
	mode: str
	slots: dict[str, Any]
	shapes: dict[str, Any]
	templates: dict[str, Any]
	vocabulary: list[str]
	stages: StageNamespace
	scopes: list[ScopeProgram]
	reach: dict[str, list[list[str]]] = field(default_factory=dict)
	model: Model | None = None
	targetModel: Model | None = None
	plans: list[Any] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ReportGap:
	"""A value or record not produced: onto target path, reason code, document and location; never source values."""

	target: str
	reason: str
	src: str | None = None
	location: str | None = None
	handle: str | None = None
	origin: dict[str, Any] | None = None


@dataclass(slots=True)
class BindingReport:
	"""What a binding run could not produce, the formats it saw and, with an inventory, the fields it observed."""

	gaps: list[ReportGap] = field(default_factory=list)
	formats: dict[str, dict[str, int]] = field(default_factory=dict)
	fields: dict[str, Any] | None = None
	stale: list[dict[str, Any]] = field(default_factory=list)
	held: list[dict[str, Any]] = field(default_factory=list)
	confirmed: list[dict[str, Any]] = field(default_factory=list)
	lapsed: list[dict[str, Any]] = field(default_factory=list)
	safeguards: list[str] = field(default_factory=list)
	formatChanges: list[Any] = field(default_factory=list)
	lossy: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class MappingReport(BindingReport):
	"""A binding report plus mixed provenance and the instance correspondence."""

	mixed: list[dict[str, Any]] = field(default_factory=list)
	correspondence: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Outcome:
	"""What the host persists after a run: `Applied` (append `log`, record `held`) or `Pending` (strict; write nothing)."""

	status: str
	log: dict[str, Any]
	held: list[dict[str, Any]] = field(default_factory=list)
	lapsed: list[dict[str, Any]] = field(default_factory=list)
	report: BindingReport | None = None


@dataclass(slots=True)
class WriteReport:
	"""Lossy lines, holes, parentless records and, per field, values kept original or formatted."""

	lossy: list[Any] = field(default_factory=list)
	gaps: list[ReportGap] = field(default_factory=list)
	parentless: list[str] = field(default_factory=list)
	originals: dict[str, int] = field(default_factory=dict)
	formatted: dict[str, int] = field(default_factory=dict)


__all__ = [
	"StageNamespace", "ScopeProgram", "BindingProgram", "MappingProgram", "ReportGap", "BindingReport", "MappingReport", "Outcome", "WriteReport",
]

# EOF
