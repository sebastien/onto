"""Module: store.parser — spec-08 store file source and strict structural JSON decoding."""

from __future__ import annotations

import re
from typing import Any

from ..binding.parser import readDoc
from ..observations.model import RE_DURATION
from ..observations.parser import jsonObject, jsonString
from ..text import Diagnostics, FormatError, Loc, Source, isName, isPath, isToken, parseAnnotations, parseArguments, sourceLines, splitAnnotations, splitDoc
from .model import (
	HEADER_KEYS, POLICY_KEYS, POPULATION_KEYS, PRIVACY_VALUES, STORE_FORMAT,
	Store, StoreColumn, StoreExclusion, StoreIndex, StorePartition, StorePopulation, StoreSystem,
)

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


NAME = r"[A-Za-z_][A-Za-z0-9_]*"
MEMBER = rf"{NAME}(?:\.{NAME})*"
RE_STORE = re.compile(r"@store\s+(\S+)(.*)")
RE_USE = re.compile(r"@use\s+(\S+)\s+as\s+(\S+)")
RE_SYSTEM = re.compile(r"@system\s+(\S+)\s+->\s+(\S+)")
RE_PARTITION = re.compile(rf"@partition\s+({NAME})\(\s*({NAME})\s*:\s*([^\s)]+)\s*\)", re.ASCII)
RE_POPULATION = re.compile(rf"({NAME}):\s*(\S+)\s*=\s*({NAME})\s+(->|<-)\s+({MEMBER})(?:\s+through\s+({NAME}))?", re.ASCII)
RE_EXCLUSION = re.compile(rf"-\s+([^\s.]+)\.({MEMBER})", re.ASCII)
RE_INDEX = re.compile(rf"@index\s+({NAME})\s+({NAME})", re.ASCII)
RE_COLUMN = re.compile(rf"({NAME})\.({MEMBER})", re.ASCII)
RE_MEMBER = re.compile(MEMBER, re.ASCII)

# Spec-08 "Limits": indexes per store and columns per index.
MAX_INDEXES = 16
MAX_COLUMNS = 8


class LineError(ValueError):
	"""A malformed line, reported under `code`."""

	def __init__(self, code: str, message: str):
		super().__init__(message)
		self.code = code


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def qualifyType(text: str, uses: dict[str, str]) -> str:
	"""A type written through a `@use` alias, as its full path."""
	head, slash, rest = text.partition("/")
	if not isPath(text) or not slash or head not in uses:
		raise LineError("store", f"Type '{text}' must be written through a @use alias")
	return f"{uses[head]}/{rest}"


def readKeys(text: str | None, loc: Loc, diag: Diagnostics, code: str) -> dict[str, str]:
	"""Annotation keys with values; flags have no meaning on store lines."""
	keys: dict[str, str] = {}
	for key, value in parseAnnotations(text, loc, diag):
		if value is True:
			raise LineError(code, f"'{key}' needs a value")
		keys[key] = value
	return keys


def checkKeys(keys: dict[str, str], allowed: tuple[str, ...]) -> None:
	"""Validate lifecycle policy and privacy keys where they are written."""
	for key, value in keys.items():
		if key not in allowed:
			raise LineError("policy", f"'{key}' is not allowed here; expected {', '.join(allowed)}")
		if key == "privacy":
			if value not in PRIVACY_VALUES:
				raise LineError("policy", "privacy accepts only 'kept'")
		elif not (value == "never" and key != "grace" or RE_DURATION.fullmatch(value)):
			raise LineError("policy", f"{key} must be an ISO duration" + ("" if key == "grace" else " or never"))


def checkStoreShape(store: Store, diag: Diagnostics) -> None:
	"""Report what spans lines or files: duplicates, parents, keys, index references and limits."""

	def check(loc: Loc | None, test: bool, code: str, message: str) -> None:
		if not test:
			diag.error(code, message, loc)

	def guarded(loc: Loc | None, action) -> None:
		try:
			action()
		except LineError as error:
			diag.error(error.code, str(error), loc)

	headers = [item.header for item in store.systems]
	for item in store.systems:
		check(item.loc, headers.count(item.header) == 1, "system", f"@system {item.header} is declared twice")
	kinds = [item.kind for item in store.partitions]
	for partition in store.partitions:
		check(partition.loc, kinds.count(partition.kind) == 1, "partition", f"Partition kind '{partition.kind}' is declared twice")
		guarded(partition.loc, lambda: checkKeys(partition.keys, POLICY_KEYS))
		check(partition.loc, not partition.root.parent and not partition.root.via and not partition.root.keys, "partition",
			f"The root of '{partition.kind}' has no parent and no keys of its own")
		aliases = {partition.root.name}
		for population in partition.populations:
			check(population.loc, population.name not in aliases, "population", f"Population '{population.name}' is declared twice in '{partition.kind}'")
			check(population.loc, population.parent in aliases, "population", f"'{population.name}': expected a previously declared parent, got '{population.parent}'")
			guarded(population.loc, lambda: checkKeys(population.keys, POPULATION_KEYS))
			aliases.add(population.name)
	slots = [(item.type, item.path) for item in store.exclusions]
	for item in store.exclusions:
		check(item.loc, slots.count((item.type, item.path)) == 1, "exclusion", f"Exclusion of {item.type}.{item.path} is declared twice")
	names = [item.name for item in store.indexes]
	check(store.loc, len(names) <= MAX_INDEXES, "index", f"A store declares at most {MAX_INDEXES} indexes")
	for index in store.indexes:
		check(index.loc, names.count(index.name) == 1, "index", f"Index '{index.name}' is declared twice")
		check(index.loc, 0 < len(index.columns) <= MAX_COLUMNS, "index", f"Index '{index.name}' needs 1 to {MAX_COLUMNS} columns")
		partition = store.partition(index.kind)
		if partition is None:
			diag.error("index", f"Index '{index.name}' names an unknown partition kind '{index.kind}'", index.loc)
			continue
		aliases = {population.name for population in partition.all}
		columns = [(column.population, column.path) for column in index.columns]
		for column in index.columns:
			check(column.loc, column.population in aliases, "index", f"'{column.population}' is not a population of '{index.kind}'")
			check(column.loc, columns.count((column.population, column.path)) == 1, "index", f"Column {column.population}.{column.path} is repeated")


# -----------------------------------------------------------------------------
#
# TEXT
#
# -----------------------------------------------------------------------------


class StoreParser:
	"""Read the files of one store into a `Store`, collecting diagnostics."""

	def __init__(self) -> None:
		self.diag = Diagnostics()
		self.store = Store("")

	def header(self, source: Source, lines) -> bool:
		"""Read `@store`, which must come first and agree with the other files."""
		match = RE_STORE.fullmatch(splitDoc(lines[0].text)[0]) if lines and not lines[0].indent else None
		if not match or not isName(match[1]):
			self.diag.error("header", "@store must come first and name the store", Loc(source.name, 1))
			return False
		header = dict(parseArguments(match[2], lines[0].loc, self.diag))
		if extra := set(header) - set(HEADER_KEYS):
			self.diag.error("header", f"Only {' and '.join(HEADER_KEYS)} are allowed on @store, not {', '.join(sorted(extra))}", lines[0].loc)
		if not self.store.name:
			self.store.name, self.store.header, self.store.loc = match[1], header, lines[0].loc
		elif (self.store.name, self.store.header) != (match[1], header):
			self.diag.error("header", "Store files must share the @store name and keys", lines[0].loc)
		return True

	def uses(self, lines) -> dict[str, str]:
		"""The file's aliases, which must agree with the other files'."""
		uses: dict[str, str] = {}
		for line in lines:
			if line.indent or not (match := RE_USE.fullmatch(line.text)):
				continue
			path, alias = match.groups()
			known = self.store.uses.get(alias, path)
			if not isPath(path) or not isName(alias) or alias in uses or known != path:
				self.diag.error("use", f"Invalid or conflicting alias '{alias}'", line.loc)
				continue
			uses[alias] = self.store.uses[alias] = path
		return uses

	def system(self, text: str, doc: str | None, loc: Loc) -> None:
		body, annotations = splitAnnotations(text)
		if not (match := RE_SYSTEM.fullmatch(body)) or not isPath(match[1]) or not isPath(match[2]):
			raise LineError("system", "Expected '@system From -> To'")
		keys = readKeys(annotations, loc, self.diag, "system")
		if set(keys) - {"scope"} or "scope" in keys and not isToken(keys["scope"]):
			raise LineError("system", "@system takes only a scope token")
		self.store.systems.append(StoreSystem(match[1], match[2], keys.get("scope"), doc, loc))

	def partition(self, text: str, doc: str | None, loc: Loc, uses: dict[str, str]) -> StorePartition:
		body, annotations = splitAnnotations(text)
		if not (match := RE_PARTITION.fullmatch(body)):
			raise LineError("partition", "Expected '@partition Kind(alias: Type)'")
		kind, alias, type = match.groups()
		root = StorePopulation(alias, qualifyType(type, uses), loc=loc)
		partition = StorePartition(kind, root, keys=readKeys(annotations, loc, self.diag, "policy"), doc=doc, loc=loc)
		self.store.partitions.append(partition)
		return partition

	def population(self, partition: StorePartition, text: str, doc: str | None, loc: Loc, uses: dict[str, str]) -> None:
		body, annotations = splitAnnotations(text)
		if not (match := RE_POPULATION.fullmatch(body)):
			hint = ": store populations take no where filters" if re.search(r"\swhere\s", body) else ""
			raise LineError("population", f"Expected 'alias: Type = parent -> member' or '<- member'{hint}")
		name, type, parent, direction, via, through = match.groups()
		partition.populations.append(StorePopulation(name, qualifyType(type, uses), parent, via, direction == "<-", through or "",
			readKeys(annotations, loc, self.diag, "policy"), doc, loc))

	def exclusion(self, text: str, doc: str | None, loc: Loc, uses: dict[str, str]) -> None:
		body, annotations = splitAnnotations(text)
		if not (match := RE_EXCLUSION.fullmatch(body)):
			raise LineError("exclusion", "Expected '- Type.Path'")
		keys = readKeys(annotations, loc, self.diag, "exclusion")
		if set(keys) - {"reason"} or "reason" in keys and not isToken(keys["reason"]):
			raise LineError("exclusion", "An exclusion takes only a reason token")
		self.store.exclusions.append(StoreExclusion(qualifyType(match[1], uses), match[2], keys.get("reason"), doc, loc))

	def index(self, text: str, doc: str | None, loc: Loc) -> StoreIndex:
		if not (match := RE_INDEX.fullmatch(text)):
			raise LineError("index", "Expected '@index Name Kind'")
		index = StoreIndex(match[1], match[2], doc=doc, loc=loc)
		self.store.indexes.append(index)
		return index

	def column(self, index: StoreIndex, text: str, doc: str | None, loc: Loc) -> None:
		if not (match := RE_COLUMN.fullmatch(text)):
			raise LineError("index", "Expected an index column 'population.Path'")
		index.columns.append(StoreColumn(match[1], match[2], doc, loc))

	def read(self, source: Source) -> None:
		if "\r" in source.text:
			self.diag.error("lexical", "Store files require LF line endings", Loc(source.name, 0))
		lines = sourceLines(source)
		if not self.header(source, lines):
			return
		uses = self.uses(lines[1:])
		block: StorePartition | StoreIndex | None = None
		for line in lines[1:]:
			text, doc = splitDoc(line.text)
			try:
				if line.tabs or line.indent < 0:
					raise LineError("lexical", "Store files indent with spaces")
				if line.indent:
					if isinstance(block, StorePartition):
						self.population(block, text, doc, line.loc, uses)
					elif isinstance(block, StoreIndex):
						self.column(block, text, doc, line.loc)
					else:
						raise LineError("syntax", "Indented lines follow @partition or @index")
					continue
				block = None
				if RE_USE.fullmatch(line.text):
					if doc is not None:
						raise LineError("use", "@use takes no doc")
				elif text.startswith("@system"):
					self.system(text, doc, line.loc)
				elif text.startswith("@partition"):
					block = self.partition(text, doc, line.loc, uses)
				elif text.startswith("@index"):
					block = self.index(text, doc, line.loc)
				elif text.startswith("- "):
					self.exclusion(text, doc, line.loc, uses)
				else:
					raise LineError("syntax", f"Unexpected line '{text}'")
			except LineError as error:
				self.diag.error(error.code, str(error), line.loc)

	def parse(self, sources: list[Source]) -> Store:
		if not sources:
			self.diag.error("header", "A store requires a source file")
		for source in sources:
			self.read(source)
		checkStoreShape(self.store, self.diag)
		self.store.diagnostics = self.diag.check()
		return self.store


# -----------------------------------------------------------------------------
#
# JSON
#
# -----------------------------------------------------------------------------


def readKeysJson(item: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, str]:
	return {key: jsonString(item[key]) for key in allowed if key in item}


def readPopulationJson(data: Any, root: bool) -> StorePopulation:
	if root:
		item = jsonObject(data, ("name", "type"))
	else:
		item = jsonObject(data, ("name", "type", "parent", "via"), ("reverse", "through", *POPULATION_KEYS, "doc"))
	population = StorePopulation(jsonString(item["name"], isName), jsonString(item["type"], isPath), doc=readDoc(item))
	if not root:
		population.parent = jsonString(item["parent"], isName)
		population.via = jsonString(item["via"], lambda text: RE_MEMBER.fullmatch(text) is not None)
		if "reverse" in item and item["reverse"] is not True:
			raise ValueError("reverse must be true when present")
		population.reverse = "reverse" in item
		population.through = jsonString(item["through"], isName) if "through" in item else ""
		population.keys = readKeysJson(item, POPULATION_KEYS)
	return population


def readStoreJson(data: Any) -> Store:
	"""Decode store JSON, structurally; checks against an ontology are separate."""
	value = jsonObject(data, ("format", "name", "partitions"), ("header", "uses", "systems", "exclusions", "indexes"))
	if value["format"] != STORE_FORMAT:
		raise ValueError("Unknown store JSON format")
	store = Store(jsonString(value["name"], isName))
	store.header = {key: jsonString(text) for key, text in jsonObject(value.get("header", {}), (), HEADER_KEYS).items()}
	uses = value.get("uses", {})
	if not isinstance(uses, dict) or any(not isinstance(alias, str) or not isName(alias) for alias in uses):
		raise ValueError("Invalid store aliases")
	store.uses = {alias: jsonString(path, isPath) for alias, path in uses.items()}
	for key in ("systems", "partitions", "exclusions", "indexes"):
		if not isinstance(value.get(key, []), list):
			raise ValueError(f"{key} must be an array")
	for data in value.get("systems", []):
		item = jsonObject(data, ("from", "to"), ("scope", "doc"))
		store.systems.append(StoreSystem(jsonString(item["from"], isPath), jsonString(item["to"], isPath),
			jsonString(item["scope"]) if "scope" in item else None, readDoc(item)))
	for data in value["partitions"]:
		item = jsonObject(data, ("kind", "root"), ("populations", *POLICY_KEYS, "doc"))
		populations = item.get("populations", [])
		if not isinstance(populations, list):
			raise ValueError("populations must be an array")
		store.partitions.append(StorePartition(jsonString(item["kind"], isName), readPopulationJson(item["root"], True),
			[readPopulationJson(population, False) for population in populations], readKeysJson(item, POLICY_KEYS), readDoc(item)))
	for data in value.get("exclusions", []):
		item = jsonObject(data, ("type", "path"), ("reason", "doc"))
		store.exclusions.append(StoreExclusion(jsonString(item["type"], isPath), jsonString(item["path"], lambda text: RE_MEMBER.fullmatch(text) is not None),
			jsonString(item["reason"]) if "reason" in item else None, readDoc(item)))
	for data in value.get("indexes", []):
		item = jsonObject(data, ("name", "kind", "columns"), ("doc",))
		if not isinstance(item["columns"], list):
			raise ValueError("columns must be an array")
		columns = [jsonObject(column, ("population", "path"), ("doc",)) for column in item["columns"]]
		store.indexes.append(StoreIndex(jsonString(item["name"], isName), jsonString(item["kind"], isName),
			[StoreColumn(jsonString(column["population"], isName), jsonString(column["path"], lambda text: RE_MEMBER.fullmatch(text) is not None),
				readDoc(column)) for column in columns], readDoc(item)))
	return store


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseStore(sources: list[Source]) -> Store:
	"""Parse the files of one store, resolving its type aliases without loading the ontology."""
	return StoreParser().parse(sources)


def storeFromJson(data: Any, name: str = "store.json") -> Store:
	"""Decode the JSON form, with the same structural checks as text."""
	diag = Diagnostics()
	try:
		store = readStoreJson(data)
	except ValueError as error:
		diag.error("json", str(error), Loc(name, 0))
		raise FormatError(diag.items) from error
	checkStoreShape(store, diag)
	store.diagnostics = diag.check()
	return store


__all__ = ["parseStore", "storeFromJson", "readStoreJson", "checkStoreShape", "checkKeys", "qualifyType"]

# EOF
