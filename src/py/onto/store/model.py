"""Module: store.model — spec-08 store files: partition kinds, systems, exclusions and indexes."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..text import Diagnostic, Loc

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


STORE_FORMAT = "onto.store/1"
HEADER_KEYS = ("rev", "edit")
POLICY_KEYS = ("orphaned", "archived", "grace")
POPULATION_KEYS = (*POLICY_KEYS, "privacy")
PRIVACY_VALUES = ("kept",)


@dataclass(slots=True)
class StoreSystem:
	"""A `@system From -> To` line: the mapping whose filled slots another system holds."""

	fromNamespace: str
	toNamespace: str
	scope: str | None = None
	doc: str | None = None
	loc: Loc | None = None

	@property
	def header(self) -> str:
		return f"{self.fromNamespace} -> {self.toNamespace}"

	@property
	def scopeToken(self) -> str:
		"""The `@scope` of the system's observations: `scope`, else its source ontology."""
		return self.scope or self.fromNamespace


@dataclass(slots=True)
class StorePopulation:
	"""A partition's root (no parent) or member population, with the rooted-view population syntax."""

	name: str
	type: str
	parent: str = ""
	via: str = ""
	reverse: bool = False
	through: str = ""
	keys: dict[str, str] = field(default_factory=dict)
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class StorePartition:
	"""A partition kind: its root population declares the key entity, its members follow links from it."""

	kind: str
	root: StorePopulation
	populations: list[StorePopulation] = field(default_factory=list)
	keys: dict[str, str] = field(default_factory=dict)
	doc: str | None = None
	loc: Loc | None = None

	@property
	def all(self) -> list[StorePopulation]:
		"""The root, then the member populations in declared order."""
		return [self.root, *self.populations]


@dataclass(slots=True)
class StoreExclusion:
	"""A slot the store must not hold although no `@system` mapping fills it."""

	type: str
	path: str
	reason: str | None = None
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class StoreColumn:
	"""An index column: a population of the kind and a slot of its type."""

	population: str
	path: str
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class StoreIndex:
	"""Declared held slots of a partition kind, kept across its partitions."""

	name: str
	kind: str
	columns: list[StoreColumn] = field(default_factory=list)
	doc: str | None = None
	loc: Loc | None = None


@dataclass(slots=True)
class Store:
	"""One store's files, with qualified type paths, locations and diagnostics."""

	name: str
	header: dict[str, str] = field(default_factory=dict)
	uses: dict[str, str] = field(default_factory=dict)
	systems: list[StoreSystem] = field(default_factory=list)
	partitions: list[StorePartition] = field(default_factory=list)
	exclusions: list[StoreExclusion] = field(default_factory=list)
	indexes: list[StoreIndex] = field(default_factory=list)
	diagnostics: list[Diagnostic] = field(default_factory=list)
	loc: Loc | None = None

	def partition(self, kind: str) -> StorePartition | None:
		"""The partition kind named `kind`."""
		return next((item for item in self.partitions if item.kind == kind), None)


__all__ = [
	"Store", "StoreColumn", "StoreExclusion", "StoreIndex", "StorePartition", "StorePopulation", "StoreSystem",
	"STORE_FORMAT", "HEADER_KEYS", "POLICY_KEYS", "POPULATION_KEYS", "PRIVACY_VALUES",
]

# EOF
