"""Module: cli.workspace — index onto files by header namespace and load them with their context."""

from __future__ import annotations

import bisect
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ignore import Ignores
from ..binding import bindingFromJson, loadBinding
from ..formats import parseFormats
from ..functions import FunctionLibrary, functionsFromJson, loadFunctions
from ..inventory import parseInventory
from ..mapping import loadMapping, mappingFromJson
from ..observations import loadObservations, observationsFromJson
from ..ontology import Ontology, loadOntology, ontologyFromJson
from ..referential import Referential, loadReferential, referentialFromJson
from ..text import Diagnostic, FormatError, Loc, Source, sourceLines

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

# NOTE: Extension → kind. Headerless kinds (inventory, formats) are keyed by file stem.
EXTENSIONS = {
	".onto": "ontology",
	".obs": "observations",
	".fn": "functions",
	".bind": "binding",
	".map": "mapping",
	".ref": "referential",
	".inv": "inventory",
	".formats": "formats",
}
KINDS = tuple(EXTENSIONS.values())
EXTENSION_OF = {kind: extension for extension, kind in EXTENSIONS.items()}
DIRECTIVES = {
	"@ontology": "ontology",
	"@obs": "observations",
	"@functions": "functions",
	"@binding": "binding",
	"@mapping": "mapping",
	"@referential": "referential",
}
JSON_FORMATS = {
	"onto.ontology/1": "ontology",
	"onto.observations/1": "observations",
	"onto.functions/1": "functions",
	"onto.binding/1": "binding",
	"onto.mapping/1": "mapping",
	"onto.referential/1": "referential",
}
# NOTE: Kinds whose files sharing a namespace are loaded together, as one model.
# NOTE: Files of one key load as one model: an ontology's namespace, a mapping's `From->To`.
GROUPED = ("ontology", "functions", "referential", "mapping")
# NOTE: What `@use` (and `from=`) namespaces may name, per kind; libraries ignore other libraries.
CONTEXT_KINDS = {
	"functions": ("ontology",),
	"binding": ("ontology", "functions"),
	"mapping": ("ontology", "functions"),
	"referential": ("ontology",),
}
PROJECT_MARKERS = (".git", ".hg", ".jj")
RE_FROM = re.compile(r"\bfrom=([A-Za-z][\w/]*)")
STDIN = "-"


@dataclass(slots=True)
class Entry:
	"""One onto file: its kind, namespace key and the namespaces it names."""

	path: str
	kind: str
	key: str | None = None
	header: dict[str, str] = field(default_factory=dict)
	# NOTE: `needs` must resolve (the primary ontologies); `uses` are resolved when available.
	needs: list[str] = field(default_factory=list)
	uses: list[str] = field(default_factory=list)
	line: int = 1
	data: Any = None

	@property
	def isJson(self) -> bool:
		"""Whether the entry was read from the JSON form."""
		return self.data is not None

	@property
	def rev(self) -> str | None:
		"""The header's `rev`, when stated."""
		return self.header.get("rev")


@dataclass(slots=True)
class Context:
	"""What an entry is loaded against: primary ontologies, extra ontologies, libraries and referentials."""

	ontology: Ontology | None = None
	toOntology: Ontology | None = None
	ontologies: list[Ontology] = field(default_factory=list)
	libraries: list[FunctionLibrary] = field(default_factory=list)
	referentials: list[Referential] = field(default_factory=list)


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def projectRoot(cwd: str) -> str:
	"""Nearest ancestor of `cwd` holding a version-control marker, else `cwd`."""
	directory = cwd
	while True:
		if any(os.path.exists(os.path.join(directory, marker)) for marker in PROJECT_MARKERS):
			return directory
		parent = os.path.dirname(directory)
		if parent == directory:
			return cwd
		directory = parent


def headerTokens(text: str) -> tuple[list[str], dict[str, str]]:
	"""Split a directive line into its positional tokens and `key=value` pairs."""
	words, pairs = [], {}
	for token in text.split():
		if "=" in token:
			key, value = token.split("=", 1)
			pairs[key] = value
		else:
			words.append(token)
	return words, pairs


def jsonUses(value: Any) -> list[str]:
	"""Namespaces of a JSON `uses` member: an alias mapping or a list of pairs."""
	if isinstance(value, dict):
		return [item for item in value.values() if isinstance(item, str)]
	if isinstance(value, list):
		return [item[-1] for item in value if isinstance(item, list) and item and isinstance(item[-1], str)]
	return []


def textOf(value: Any) -> str | None:
	"""`value` when it is a non-empty string, else None."""
	return value if isinstance(value, str) and value else None


def mappingKey(fromNamespace: str | None, toNamespace: str | None) -> str | None:
	"""The namespace key of a mapping, `From->To`."""
	return f"{fromNamespace}->{toNamespace}" if fromNamespace and toNamespace else None


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Indexer:
	"""Reads entries from file headers, recording index diagnostics."""

	def __init__(self, cwd: str):
		self.cwd = cwd
		self.texts: dict[str, str] = {}
		self.diagnostics: list[Diagnostic] = []

	def display(self, path: str) -> str:
		"""`path` relative to the working directory, as diagnostics print it."""
		return path if path == STDIN else os.path.relpath(os.path.abspath(path), self.cwd)

	def error(self, code: str, message: str, path: str | None = None, line: int = 0, level: str = "error") -> None:
		"""Record an index diagnostic at `path`; line 0 means the whole file."""
		self.diagnostics.append(Diagnostic(level, code, message, Loc(path, line) if path else None))

	def read(self, path: str, name: str) -> str | None:
		"""Read `path` (or standard input) as `name`, caching its text; None when unreadable."""
		if name not in self.texts:
			try:
				self.texts[name] = sys.stdin.read() if path == STDIN else Path(path).read_text(encoding="utf-8", newline="")
			except (OSError, UnicodeError) as error:
				self.error("cli.read", f"cannot read file: {error.strerror if isinstance(error, OSError) else error}", name)
				return None
		return self.texts[name]

	def entry(self, path: str, kind: str | None = None) -> Entry | None:
		"""Read the entry of `path`; `kind` overrides detection (standard input), `json` reads the JSON form."""
		name = self.display(path)
		suffix = Path(path).suffix
		if kind == "json" or suffix == ".json" and kind is None:
			return self.jsonEntry(path, name)
		kind = kind or EXTENSIONS.get(suffix)
		if kind is None:
			self.error("cli.kind", f"unknown file kind '{suffix or name}'; use --kind KIND with '-'", name)
			return None
		text = self.read(path, name)
		if text is None:
			return None
		if kind in ("inventory", "formats"):
			return Entry(name, kind, Path(path).stem)
		return self.textEntry(name, kind, text)

	def textEntry(self, name: str, kind: str, text: str) -> Entry:
		"""Read the header and `@use` lines of a text file."""
		entry = Entry(name, kind)
		lines = sourceLines(Source(name, text))
		if not lines or not lines[0].text.startswith("@"):
			# NOTE: The format's own parser reports a missing header when the file is loaded.
			return entry
		words, entry.header = headerTokens(lines[0].text)
		entry.line = lines[0].loc.line
		if not words:
			self.error("cli.kind", f"expected @{self.Directive(kind)} header", name, entry.line)
			return entry
		if DIRECTIVES.get(words[0]) != kind:
			self.error("cli.kind", f"a {EXTENSION_OF[kind]} file must start with @{self.Directive(kind)}, not {words[0]}", name, entry.line)
		args = words[1:]
		if kind == "mapping":
			if len(args) >= 3 and args[1] == "->":
				entry.key = mappingKey(args[0], args[2])
				entry.needs = [args[0], args[2]]
		elif args:
			entry.key = args[0]
			if kind in ("observations", "binding"):
				entry.needs = [args[0]]
		for line in lines[1:]:
			if line.indent == 0:
				directive = line.text.split(maxsplit=2)
				if len(directive) >= 2 and directive[0] == "@use":
					entry.uses.append(directive[1])
			if kind == "referential":
				entry.uses.extend(RE_FROM.findall(line.text))
		return entry

	def jsonEntry(self, path: str, name: str) -> Entry | None:
		"""Read the kind and namespaces of a JSON file from its members; mistyped members are left to the format's reader."""
		text = self.read(path, name)
		if text is None:
			return None
		try:
			data = json.loads(text)
		except ValueError as error:
			self.error("cli.json", f"invalid JSON: {error}", name)
			return None
		kind = JSON_FORMATS.get(data.get("format")) if isinstance(data, dict) and isinstance(data.get("format"), str) else None
		if kind is None:
			self.error("cli.kind", f"unknown JSON format {data.get('format') if isinstance(data, dict) else None!r}", name)
			return None
		header = data.get("header")
		entry = Entry(name, kind, header=dict(header) if isinstance(header, dict) else {}, data=data, line=0)
		entry.uses = jsonUses(data.get("uses"))
		obs = data.get("obs")
		match kind:
			case "observations":
				entry.key = textOf(obs.get("ontology")) if isinstance(obs, dict) else None
				entry.needs = [entry.key] if entry.key else []
			case "binding":
				entry.key = textOf(data.get("ontology"))
				entry.needs = [entry.key] if entry.key else []
			case "mapping":
				fromNamespace, toNamespace = textOf(data.get("from")), textOf(data.get("to"))
				entry.key = mappingKey(fromNamespace, toNamespace)
				entry.needs = [fromNamespace, toNamespace] if entry.key else []
			case _:
				entry.key = textOf(data.get("namespace"))
		if kind == "referential" and isinstance(data.get("policies"), list):
			entry.uses.extend(policy["from"] for policy in data["policies"] if isinstance(policy, dict) and isinstance(policy.get("from"), str))
		return entry

	@staticmethod
	def Directive(kind: str) -> str:
		"""The header directive name of `kind`."""
		return next(name[1:] for name, value in DIRECTIVES.items() if value == kind)


class Workspace:
	"""The onto files of the search path, indexed by kind and namespace, with memoised loading."""

	def __init__(self, cwd: str, roots: list[str], scan: bool = True, mode: str = "strict"):
		self.cwd = cwd
		self.roots = list(roots)
		self.scan = scan
		self.mode = mode
		self.indexer = Indexer(cwd)
		self.entries: dict[str, Entry] = {}
		self.byKey: dict[tuple[str, str | None], list[Entry]] = {}
		self.indexed = False
		self.loaded: dict[str, Any] = {}
		self.failed: dict[str, FormatError] = {}
		self.loading: set[str] = set()
		self.contexts: dict[str, Context] = {}
		self.reported: dict[tuple, Diagnostic] = {}
		self.readPaths: set[str] = set()
		self.named: set[str] = set()
		# NOTE: Index diagnostics are reported for the files a command touches, or all of them for a full scan.
		self.reportAll = False

	# -- Indexing --------------------------------------------------------------

	def index(self) -> Workspace:
		"""Scan the search path once; roots added later are scanned as they are added."""
		if not self.indexed:
			self.indexed = True
			for root in self.roots:
				self.walk(root)
		return self

	def walk(self, root: str) -> None:
		"""Index the onto files below `root`, skipping hidden directories and what `.gitignore` and
		`.ontoignore` files exclude; JSON files are not indexed."""
		if not os.path.isdir(root):
			self.indexer.error("cli.read", f"search path entry is not a directory: {self.indexer.display(root)}", level="warning")
			return
		ignores = Ignores(root)
		for directory, names, files in os.walk(root):
			names[:] = sorted(name for name in names if not name.startswith(".") and not ignores.ignored(os.path.join(directory, name), True))
			for name in sorted(files):
				path = os.path.join(directory, name)
				if Path(name).suffix in EXTENSIONS and ignores.ignored(path, False):
					continue
				if Path(name).suffix in EXTENSIONS and self.indexer.display(path) not in self.entries:
					entry = self.indexer.entry(path)
					if entry:
						self.put(entry)

	def put(self, entry: Entry) -> Entry:
		"""Index `entry` by path and by kind and key."""
		if entry.path not in self.entries:
			self.entries[entry.path] = entry
			bisect.insort(self.byKey.setdefault((entry.kind, entry.key), []), entry, key=lambda item: item.path)
		return self.entries[entry.path]

	def addRoot(self, root: str) -> None:
		"""Add `root` to the search path, scanning it now if the workspace is already indexed."""
		if root in self.roots:
			return
		self.roots.append(root)
		if self.indexed:
			self.walk(root)

	def add(self, path: str, kind: str | None = None) -> Entry | None:
		"""Add a file named on the command line; it is part of the workspace even outside the search path."""
		if path == STDIN and kind is None:
			self.indexer.error("cli.kind", "standard input needs --kind KIND")
			return None
		if path != STDIN and not os.path.exists(path):
			self.indexer.error("cli.read", f"no such file: {path}")
			return None
		if os.path.isdir(path):
			self.indexer.error("cli.read", f"is a directory: {path}; use -I {path} to search it")
			return None
		if self.scan and path != STDIN:
			# NOTE: A file named from another project brings that project's files with it.
			self.addRoot(projectRoot(os.path.dirname(os.path.abspath(path))))
		name = self.indexer.display(path)
		# NOTE: Named before indexing, so that indexing errors about it are reported.
		self.named.add(name)
		# NOTE: `--kind` only qualifies standard input; files are known by their extension.
		entry = self.entries.get(name) or self.indexer.entry(path, kind if path == STDIN else None)
		return self.put(entry) if entry else None

	def file(self, entry: Entry) -> str:
		"""The filesystem path of `entry`."""
		return os.path.join(self.cwd, entry.path)

	def all(self, kinds: tuple[str, ...] | None = None) -> list[Entry]:
		"""Indexed entries of `kinds`, sorted by path."""
		self.index()
		return sorted((entry for entry in self.entries.values() if kinds is None or entry.kind in kinds), key=lambda entry: entry.path)

	@staticmethod
	def Indexable(entry: Entry) -> bool:
		"""Whether `entry` may be found by namespace: JSON and standard input are read only where named."""
		return not entry.isJson and entry.path != STDIN

	@staticmethod
	def Grouped(entry: Entry) -> bool:
		"""Whether `entry` loads with the files sharing its namespace."""
		return entry.kind in GROUPED and bool(entry.key) and Workspace.Indexable(entry)

	def groupId(self, entry: Entry) -> str:
		"""The memoisation key of `entry`: its namespace for grouped entries, else its path."""
		return f"{entry.kind}:{entry.key}" if self.Grouped(entry) else f"file:{entry.path}"

	def keyed(self, kind: str, key: str) -> list[Entry]:
		"""Indexable entries of `kind` with namespace `key`, sorted by path."""
		self.index()
		return [entry for entry in self.byKey.get((kind, key), []) if self.Indexable(entry)]

	def group(self, entry: Entry) -> list[Entry]:
		"""The entries loaded together with `entry`, sorted by path."""
		return self.keyed(entry.kind, entry.key) if self.Grouped(entry) else [entry]

	def find(self, kind: str, namespace: str) -> Entry | None:
		"""The first entry of `kind` declaring `namespace`."""
		return next(iter(self.keyed(kind, namespace)), None)

	def carriers(self, namespace: str) -> list[Entry]:
		"""Ontologies that `@use` `namespace`: they carry its declarations when it has no ontology of its own."""
		seen: dict[str, Entry] = {}
		for entry in self.all(("ontology",)):
			if namespace in entry.uses and entry.key and entry.key not in seen and self.Indexable(entry):
				seen[entry.key] = entry
		return list(seen.values())

	def searched(self) -> str:
		"""The search path, for messages."""
		return ", ".join(self.indexer.display(root) for root in self.roots) or "(none)"

	# -- Reporting -------------------------------------------------------------

	def report(self, diagnostics: list[Diagnostic]) -> None:
		"""Record `diagnostics` once each."""
		for item in diagnostics:
			key = (item.level, item.code, item.message, item.loc.file if item.loc else None, item.loc.line if item.loc else None)
			self.reported.setdefault(key, item)

	def error(self, code: str, message: str, path: str | None = None, line: int = 0) -> None:
		"""Report a command error at `path` (line 0: the whole file)."""
		self.report([Diagnostic("error", code, message, Loc(path, line) if path else None)])

	def diagnostics(self) -> list[Diagnostic]:
		"""Load diagnostics, and the index diagnostics of the files named or read (all of them with `reportAll`)."""
		touched = self.readPaths | self.named
		self.report([item for item in self.indexer.diagnostics if self.reportAll or not item.loc or item.loc.file in touched])
		return list(self.reported.values())

	# -- Loading ---------------------------------------------------------------

	def source(self, entry: Entry) -> Source:
		"""The source text of a text entry."""
		self.readPaths.add(entry.path)
		text = self.indexer.texts[entry.path].replace("\r\n", "\n").replace("\r", "\n")
		return Source(entry.path, text)

	def located(self, entry: Entry, code: str, message: str) -> FormatError:
		"""An error at `entry`'s header."""
		return FormatError([Diagnostic("error", code, message, Loc(entry.path, entry.line))])

	def required(self, kind: str, namespace: str, owner: Entry) -> Any:
		"""Load the `kind` named `namespace` that `owner` cannot do without."""
		found = self.find(kind, namespace)
		if found is None:
			raise self.located(owner, "cli.unresolved", f"no {kind} {namespace} in the workspace (searched: {self.searched()})")
		try:
			return self.load(found)
		except FormatError as error:
			raise self.located(owner, "cli.context", f"{kind} {namespace} has errors") from error

	def optional(self, namespaces: list[str], owner: Entry, kinds: tuple[str, ...], exclude: set[str]) -> tuple[list[Ontology], list[FunctionLibrary]]:
		"""Ontologies and libraries of `kinds` for `namespaces`, else the ontologies carrying a namespace."""
		loaded: dict[tuple[str, str], Any] = {}
		for namespace in namespaces:
			found = [item for item in (self.find(kind, namespace) for kind in kinds) if item]
			for item in found or self.carriers(namespace):
				key = (item.kind, item.key)
				# NOTE: The primary ontologies are passed apart; the owner's own group is not its context.
				if key in loaded or item.kind == "ontology" and item.key in exclude or self.groupId(item) == self.groupId(owner):
					continue
				try:
					loaded[key] = self.load(item)
				except FormatError as error:
					raise self.located(owner, "cli.context", f"{item.kind} {item.key} has errors") from error
		return [value for (kind, _), value in loaded.items() if kind == "ontology"], [value for (kind, _), value in loaded.items() if kind == "functions"]

	def context(self, entry: Entry) -> Context:
		"""Resolve and load what `entry` needs, memoised per group."""
		gid = self.groupId(entry)
		if gid in self.contexts:
			return self.contexts[gid]
		context = Context()
		group = self.group(entry)
		uses = list(dict.fromkeys(name for item in group for name in item.uses))
		if entry.kind in ("observations", "binding") and entry.needs:
			context.ontology = self.required("ontology", entry.needs[0], entry)
		elif entry.kind == "mapping" and entry.needs:
			context.ontology = self.required("ontology", entry.needs[0], entry)
			context.toOntology = self.required("ontology", entry.needs[1], entry)
			referentials = {name: item for item in group if (name := textOf(item.header.get("referential")))}
			# NOTE: The mapping parser diagnoses conflicting headers; only resolve an agreed dependency.
			if len(referentials) == 1:
				name, owner = next(iter(referentials.items()))
				context.referentials = [self.required("referential", name, owner)]
		if entry.kind in CONTEXT_KINDS:
			context.ontologies, context.libraries = self.optional(uses, entry, CONTEXT_KINDS[entry.kind], set(entry.needs))
		self.contexts[gid] = context
		return context

	def load(self, entry: Entry) -> Any:
		"""Load `entry` (its whole group) with its context; record diagnostics; raise `FormatError` on errors."""
		gid = self.groupId(entry)
		if gid in self.loaded:
			return self.loaded[gid]
		if gid in self.failed:
			raise self.failed[gid]
		if gid in self.loading:
			raise self.located(entry, "cli.cycle", f"{entry.kind} {entry.key or entry.path} is part of its own context")
		self.loading.add(gid)
		try:
			result = self.build(entry, self.context(entry))
		except FormatError as error:
			self.failed[gid] = error
			self.report(error.diagnostics)
			raise
		finally:
			self.loading.discard(gid)
		self.loaded[gid] = result
		self.report(list(getattr(result, "diagnostics", [])))
		return result

	def build(self, entry: Entry, context: Context) -> Any:
		"""Call the format's loader for `entry`."""
		if entry.isJson:
			return self.buildJson(entry, context)
		kind = entry.kind
		if kind in GROUPED and kind != "mapping":
			sources = [self.source(item) for item in self.group(entry)]
			if kind == "ontology":
				return loadOntology(sources)
			if kind == "functions":
				return loadFunctions(context.ontologies, sources)
			return loadReferential(context.ontologies, sources)
		source = self.source(entry)
		if kind == "inventory":
			return parseInventory(source)
		if kind == "formats":
			return parseFormats(source)
		if not context.ontology:
			raise self.headerless(entry)
		if kind == "observations":
			return loadObservations(context.ontology, source, self.mode)
		if kind == "binding":
			return loadBinding(context.ontology, source, context.libraries, context.ontologies)
		# Every file of the mapping (same `@mapping From -> To`), parsed before anything is resolved
		sources = [self.source(item) for item in self.group(entry)]
		return loadMapping(context.ontology, context.toOntology, sources, context.libraries, context.ontologies, context.referentials)

	def buildJson(self, entry: Entry, context: Context) -> Any:
		"""Call the format's JSON reader for `entry`."""
		self.readPaths.add(entry.path)
		data, name = entry.data, entry.path
		if entry.kind in ("observations", "binding", "mapping") and not context.ontology:
			raise self.headerless(entry)
		match entry.kind:
			case "ontology":
				return ontologyFromJson(data, name)
			case "observations":
				return observationsFromJson(context.ontology, data, name, self.mode)
			case "functions":
				return functionsFromJson(context.ontologies, data, name)
			case "binding":
				return bindingFromJson(context.ontology, data, name, context.libraries, context.ontologies)
			case "mapping":
				return mappingFromJson(context.ontology, context.toOntology, data, name, context.libraries, context.ontologies, context.referentials)
			case _:
				return referentialFromJson(context.ontologies, data, name)

	def headerless(self, entry: Entry) -> FormatError:
		"""The error of a file whose header names no ontology."""
		return self.located(entry, "cli.header", f"missing or invalid @{Indexer.Directive(entry.kind)} header")


__all__ = ["EXTENSIONS", "KINDS", "STDIN", "Context", "Entry", "Indexer", "Workspace", "projectRoot"]

# EOF
