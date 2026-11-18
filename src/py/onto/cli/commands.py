"""Module: cli.commands — one function per command, returning results and leaving diagnostics to the workspace."""

from __future__ import annotations

import argparse
import asyncio
import csv
import difflib
import importlib
import io
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..binding import Binding, bindingCoverage, bindingToJson, printBinding
from ..coverage import CoverageReport, observationsCoverage
from ..formats import Formats, printFormats
from ..functions import FunctionEvaluator, FunctionLibrary, functionsToJson, printFunctions
from ..inventory import Inventory, defaultBinding, inventoryFromDocuments, printInventory
from ..meta import META_DOMAIN, metaDeclarations, metaObservations
from ..mapping import Mapping, mappingCoverage, mappingReverse, mappingToJson, printMapping
from ..observations import Observations, observationsFromJson, observationsToJson, printObservationsLog, printObservationsState, reconcileObservations
from ..ontology import Ontology, loadOntology, normaliseOntology, ontologyDiff, ontologyFromJson, ontologyToJson, printOntology, printOntologyDiff
from ..referential import Referential, printReferential, referentialToJson
from ..text import Diagnostic, FormatError, Loc, Source, annotation, layoutText
from .usage import UsageError
from .workspace import STDIN, Entry, Workspace

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

type Row = dict[str, str]
COVERAGE_COLUMNS = ("source", "target", "status", "note")
# NOTE: Kinds whose lines may end with a ` -- doc`.
DOC_KINDS = ("ontology", "functions", "binding", "mapping", "referential")
JSON_WRITERS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
	(Ontology, ontologyToJson),
	(Observations, observationsToJson),
	(FunctionLibrary, functionsToJson),
	(Binding, bindingToJson),
	(Mapping, mappingToJson),
	(Referential, referentialToJson),
)



@dataclass(slots=True)
class Result:
	"""A command's outcome: text or table for standard output, a hint for standard error, a JSON result."""

	text: str | None = None
	columns: tuple[str, ...] = ()
	rows: list[Row] | None = None
	header: bool = True
	data: Any = None
	hint: str | None = None
	failed: bool = False
	checked: int = 0

	def resultJson(self) -> Any:
		"""The `result` member of `--json` output."""
		if self.data is not None:
			return self.data
		if self.rows is not None:
			return self.rows
		return self.text


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def targets(ws: Workspace, args: argparse.Namespace, files: list[str], kinds: tuple[str, ...] | None = None) -> list[Entry]:
	"""Entries for the named `files`, or for the whole workspace when none are named."""
	if not files:
		return ws.all(kinds)
	entries = [ws.add(path, getattr(args, "kind", None)) for path in files]
	return [entry for entry in entries if entry is not None]


def one(ws: Workspace, args: argparse.Namespace, kinds: tuple[str, ...] | None = None) -> Entry | None:
	"""The single named entry, checked against `kinds`."""
	entry = ws.add(args.file, getattr(args, "kind", None))
	if entry is not None and kinds and entry.kind not in kinds:
		ws.error("cli.kind", f"expected {' or '.join(kinds)}, not {entry.kind}", entry.path, 0)
		return None
	return entry


def mergedLogs(logs: list[Observations]) -> dict[str, Any]:
	"""One observations document from several: statements renumbered, source aliases made distinct."""
	out: dict[str, Any] | None = None
	for log in logs:
		data = observationsToJson(log)
		if out is None:
			out = {**data, "sources": {}, "instances": {}, "claims": [], "retractions": []}
			out.pop("gaps", None)
		aliases = {}
		for alias, token in data["sources"].items():
			aliases[alias] = f"d{len(out['sources']) + 1}"
			out["sources"][aliases[alias]] = token
		for handle, item in data["instances"].items():
			out["instances"].setdefault(handle, item)
		for key in ("claims", "retractions"):
			for claim in data[key]:
				renamed = {name: aliases.get(value, value) if name in ("src", "of") else value for name, value in claim.items()}
				out[key].append({**renamed, "n": len(out["claims"]) + len(out["retractions"]) + 1})
	return out or {}


def load(ws: Workspace, entry: Entry) -> Any:
	"""Load `entry`, or None when it has errors (already reported)."""
	try:
		return ws.load(entry)
	except FormatError:
		return None


def textual(ws: Workspace, entry: Entry, observations: Observations) -> bool:
	"""Whether `observations` have a text form; lenient gaps exist only in JSON, so report them."""
	if not observations.gaps:
		return True
	count = len(observations.gaps)
	ws.report([Diagnostic("error", "cli.gaps", f"{count} statement{'s are gaps' if count != 1 else ' is a gap'} (lenient mode), which text forms cannot hold; use 'onto json'", Loc(entry.path, entry.line))])
	return False


def coverageRows(report: CoverageReport) -> list[Row]:
	"""Coverage rows, then unassigned targets and uninventoried paths."""
	rows = [{"source": row.source, "target": row.target or "", "status": row.status, "note": row.note or ""} for row in sorted(report.rows, key=lambda row: (row.source, row.target or ""))]
	rows += [{"source": "", "target": path, "status": "unassigned", "note": ""} for path in report.unassigned]
	rows += [{"source": path, "target": "", "status": "uninventoried", "note": ""} for path in report.uninventoried]
	return rows


def signatureText(signature: Any) -> str:
	"""A signature type as `.fn` files write it."""
	name = signature.builtin or signature.path
	return (f"Range<{name}>" if signature.range else name) + ("*" if signature.collection else "")


def snapshotModel(ws: Workspace, files: list[str]) -> Ontology | None:
	"""Load exactly `files` as one model, retaining embedded IDs and adjacent namespace sidecars."""
	sources: list[Source] = []
	ids: dict[str, str] = {}
	textPaths: list[Path] = []

	def mergeIds(values: dict[str, str], name: str) -> None:
		for path, identifier in values.items():
			if path in ids and ids[path] != identifier:
				ws.error("cli.ids", f"conflicting identifiers for '{path}'", name)
			ids[path] = identifier

	for file in sorted(set(files)):
		name = ws.indexer.display(file)
		text = ws.indexer.read(file, name)
		ws.readPaths.add(name)
		if text is None:
			return None
		if Path(file).suffix == ".json" or text.lstrip().startswith("{"):
			try:
				model = ontologyFromJson(json.loads(text), name)
			except FormatError as error:
				ws.report(error.diagnostics)
				return None
			except ValueError as error:
				ws.error("cli.json", f"invalid ontology JSON: {error}", name)
				return None
			mergeIds(model.ids or {}, name)
			text = printOntology(normaliseOntology(model))
		else:
			if file != STDIN:
				textPaths.append(Path(file))
		sources.append(Source(name, text))
	try:
		model = loadOntology(sources)
	except FormatError as error:
		ws.report(error.diagnostics)
		return None
	for sidecar in sorted({path.parent / f"{model.namespace}.ids" for path in textPaths}):
		if not sidecar.is_file():
			continue
		name = ws.indexer.display(str(sidecar))
		text = ws.indexer.read(str(sidecar), name)
		ws.readPaths.add(name)
		if text is None:
			return None
		values: dict[str, str] = {}
		for line, row in enumerate(text.splitlines(), 1):
			if not row.strip():
				continue
			parts = row.split("\t")
			if len(parts) != 2 or not all(parts):
				ws.error("cli.ids", "expected a path and identifier separated by a tab", name, line)
			elif parts[0] in values and values[parts[0]] != parts[1]:
				ws.error("cli.ids", f"conflicting identifiers for '{parts[0]}'", name, line)
			else:
				values[parts[0]] = parts[1]
		mergeIds(values, name)
	model.ids = ids or None
	ws.report(model.diagnostics)
	return None if any(item.level == "error" for item in ws.diagnostics()) else model


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Forms:
	"""Normal-form text and JSON of loaded models, per kind."""

	@staticmethod
	def Text(ws: Workspace, entry: Entry, model: Any) -> str:
		"""Normal text of a loaded model, as `onto text` prints it."""
		match model:
			case Ontology():
				return printOntology(normaliseOntology(model))
			case Observations():
				return printObservationsLog(ws.context(entry).ontology, model)
			case FunctionLibrary():
				return printFunctions(model)
			case Referential():
				return printReferential(model)
			case Binding():
				return printBinding(model)
			case Mapping():
				return printMapping(model)
			case Inventory():
				return printInventory(model)
			case Formats():
				return printFormats(model)
		raise TypeError(f"no text form for {type(model).__name__}")

	@staticmethod
	def Json(model: Any) -> Any:
		"""JSON form of `model`; None for kinds without one."""
		for kind, function in JSON_WRITERS:
			if isinstance(model, kind):
				return function(model)
		return None


class Commands:
	"""The command implementations, sharing a workspace and the parsed arguments."""

	def __init__(self, ws: Workspace, args: argparse.Namespace):
		self.ws = ws
		self.args = args

	def run(self, name: str) -> Result:
		"""Dispatch command `name`; format errors raised outside loading become diagnostics."""
		try:
			return getattr(self, f"cmd{name.capitalize()}")()
		except FormatError as error:
			self.ws.report(error.diagnostics)
		except ValueError as error:
			# NOTE: Format operations reject inputs they cannot process with ValueError.
			self.ws.error("cli.failed", f"{name} failed: {error}")
		return Result(failed=True)

	# -- Files -----------------------------------------------------------------

	def cmdCheck(self) -> Result:
		"""Load every target with its context."""
		entries = targets(self.ws, self.args, self.args.files)
		for entry in entries:
			load(self.ws, entry)
		return Result(checked=len(entries))

	def cmdFmt(self) -> Result:
		"""Print, rewrite, list or diff the layout of files; their content is kept as written."""
		mode = "write" if self.args.write else "check" if self.args.check else "diff" if self.args.diff else "print"
		if sum(map(bool, (self.args.write, self.args.check, self.args.diff))) > 1:
			raise UsageError("use only one of --write, --check and --diff", "fmt")
		if mode == "print" and not self.args.files:
			raise UsageError("fmt prints the files named; use --write, --check or --diff for the whole workspace", "fmt")
		entries = targets(self.ws, self.args, self.args.files)
		outputs: list[tuple[str, str]] = []
		changed: list[str] = []
		for entry in entries:
			if entry.isJson:
				self.ws.error("cli.kind", "fmt formats text files; use 'onto text' for JSON", entry.path, 0)
				continue
			if mode == "write" and entry.path == STDIN:
				self.ws.error("cli.read", "cannot rewrite standard input; omit --write to print it laid out")
				continue
			# NOTE: Only files that validate are laid out, so that layout never hides an error.
			if load(self.ws, entry) is None:
				continue
			current = self.ws.indexer.texts.get(entry.path, "")
			normal = layoutText(current, entry.kind in DOC_KINDS)
			if mode == "print":
				outputs.append((entry.path, normal))
			elif normal != current:
				changed.append(entry.path)
				if mode == "write":
					Path(self.ws.file(entry)).write_text(normal, encoding="utf-8")
				elif mode == "diff":
					outputs.append((entry.path, "".join(difflib.unified_diff(current.splitlines(True), normal.splitlines(True), f"a/{entry.path}", f"b/{entry.path}"))))
		result = Result(checked=len(entries))
		if mode in ("print", "diff"):
			result.text = "".join(text for _, text in outputs)
			result.data = dict(outputs) if mode == "print" and len(self.args.files) > 1 else result.text
			result.failed = mode == "diff" and bool(changed)
		else:
			result.text = "".join(f"{path}\n" for path in changed)
			result.data = changed
			if mode == "check" and changed:
				result.failed = True
				result.hint = f"{len(changed)} file{'s' if len(changed) != 1 else ''} not laid out; run 'onto fmt -w' to rewrite {'it' if len(changed) == 1 else 'them'}"
		return result

	def cmdJson(self) -> Result:
		"""The JSON form of one file."""
		entry = one(self.ws, self.args)
		model = load(self.ws, entry) if entry else None
		if model is None:
			return Result(checked=1)
		data = Forms.Json(model)
		if data is None:
			self.ws.error("cli.kind", f"{entry.kind} files have no JSON form", entry.path, 0)
			return Result(checked=1)
		return Result(text=json.dumps(data, ensure_ascii=False, indent=2) + "\n", data=data, checked=1)

	def cmdText(self) -> Result:
		"""The normal text form of one JSON file; standard input is read as JSON."""
		entry = self.ws.add(self.args.file, "json") if self.args.file == STDIN else one(self.ws, self.args)
		if entry is not None and not entry.isJson:
			self.ws.error("cli.kind", "expected a JSON file; use 'onto fmt' for text files", entry.path, 0)
			return Result(checked=1)
		model = load(self.ws, entry) if entry else None
		if model is None:
			return Result(checked=1)
		return Result(text=Forms.Text(self.ws, entry, model), checked=1)

	def cmdSnap(self) -> Result:
		"""Print the normalized model of an explicit file set."""
		model = snapshotModel(self.ws, self.args.files)
		if model is None:
			return Result(checked=len(self.args.files))
		data = ontologyToJson(model)
		text = printOntology(normaliseOntology(model)) if self.args.format == "onto" else json.dumps(data, ensure_ascii=False, indent=2) + "\n"
		return Result(text=text, data=data, checked=len(self.args.files))

	def cmdDiff(self) -> Result:
		"""Compare independent explicit file sets, using snapshots and text interchangeably."""
		before, after = self.args.before, self.args.after
		if self.args.files:
			if before or after or len(self.args.files) != 2:
				raise UsageError("name BEFORE AFTER, or use --before FILE... --after FILE...", "diff")
			before, after = [self.args.files[0]], [self.args.files[1]]
		if not before or not after:
			raise UsageError("both --before and --after require at least one file", "diff")
		if before.count(STDIN) + after.count(STDIN) > 1:
			raise UsageError("standard input can appear on only one side", "diff")
		left = snapshotModel(self.ws, before)
		right = snapshotModel(self.ws, after)
		checked = len(before) + len(after)
		if left is None or right is None:
			return Result(checked=checked)
		changes = ontologyDiff(left, right)
		return Result(text=printOntologyDiff(changes), data={"format": "onto.diff/1", "changes": changes}, failed=bool(changes), checked=checked)

	def cmdLs(self) -> Result:
		"""One row per model: kind, namespace, revision and files."""
		self.ws.reportAll = True
		groups: dict[tuple[str, str], list[Entry]] = {}
		for entry in self.ws.all(tuple(self.args.kinds) or None):
			groups.setdefault((entry.kind, self.ws.groupId(entry)), []).append(entry)
		rows = []
		for (kind, _), entries in sorted(groups.items(), key=lambda item: (item[0][0], item[1][0].key or "", item[1][0].path)):
			first = entries[0]
			rows.append({"kind": kind, "namespace": first.key or "", "rev": first.rev or "", "files": " ".join(entry.path for entry in entries)})
		hint = None if rows else f"No onto files found (searched: {self.ws.searched()}). Add directories with -I DIR."
		return Result(columns=("kind", "namespace", "rev", "files"), rows=rows, header=False, hint=hint)

	def cmdMeta(self) -> Result:
		"""The ontology as observations of its `Meta` domain, or that domain's declarations."""
		entry = one(self.ws, self.args, ("ontology",))
		ontology = load(self.ws, entry) if entry else None
		if ontology is None:
			return Result(checked=1)
		if self.args.decl:
			return Result(text=metaDeclarations(ontology), checked=1)
		hint = None if any(decl.kind == "domain" and decl.path == f"{ontology.namespace}/{META_DOMAIN}" for decl in ontology.decls) else (
			f"{ontology.namespace} has no {META_DOMAIN} domain; add it with 'onto meta --decl {entry.path} > meta.onto'"
		)
		return Result(text=metaObservations(ontology), hint=hint, checked=1)

	# -- Observations ----------------------------------------------------------

	def observations(self) -> tuple[Entry | None, Observations | None]:
		"""The named observations, loaded."""
		entry = one(self.ws, self.args, ("observations",))
		log = load(self.ws, entry) if entry else None
		return entry, log if log is not None and textual(self.ws, entry, log) else None

	def cmdState(self) -> Result:
		"""Reconciled state form."""
		entry, log = self.observations()
		if log is None:
			return Result(checked=1)
		ontology = self.ws.context(entry).ontology
		return Result(text=printObservationsState(ontology, reconcileObservations(ontology, log, self.ws.mode)), checked=1)

	def cmdLog(self) -> Result:
		"""Log form."""
		entry, log = self.observations()
		if log is None:
			return Result(checked=1)
		return Result(text=printObservationsLog(self.ws.context(entry).ontology, log), checked=1)

	# -- Mappings --------------------------------------------------------------

	def cmdCoverage(self) -> Result:
		"""Coverage table of a mapping, binding or observations."""
		entry = one(self.ws, self.args, ("mapping", "binding", "observations"))
		model = load(self.ws, entry) if entry else None
		if model is None:
			return Result(checked=1)
		context = self.ws.context(entry)
		if entry.kind == "observations":
			if not self.args.view:
				raise UsageError("coverage of observations needs --view VIEW", "coverage")
			try:
				items = observationsCoverage(context.ontology, model, self.args.view, self.ws.mode)
			except FormatError as error:
				self.ws.report([replace(item, loc=item.loc or Loc(entry.path, entry.line)) for item in error.diagnostics])
				return Result(checked=1)
			rows = [{
				"path": item.path, "subject": item.subject or "", "ctx": item.ctx or "", "status": "+".join(item.statuses),
				"note": " ".join(flag for flag, on in (("conflict", item.conflict), ("partial", item.partial)) if on),
			} for item in items]
			return Result(columns=("path", "subject", "ctx", "status", "note"), rows=rows, checked=1)
		if entry.kind == "mapping":
			report = mappingCoverage(context.ontology, context.toOntology, model)
		else:
			inventory = self.inventory(entry)
			report = bindingCoverage(context.ontology, model, inventory)
		return Result(columns=COVERAGE_COLUMNS, rows=coverageRows(report), checked=1)

	def inventory(self, entry: Entry) -> Inventory | None:
		"""The inventory named by --inventory, else the binding's `.inv` sidecar."""
		if self.args.inventory:
			found = self.ws.add(self.args.inventory, "inventory")
		else:
			sidecar = Path(self.ws.file(entry)).with_suffix(".inv")
			found = self.ws.add(str(sidecar)) if sidecar.exists() else None
		return load(self.ws, found) if found else None

	def cmdReverse(self) -> Result:
		"""The reversed mapping; lossy lines become warnings."""
		entry = one(self.ws, self.args, ("mapping",))
		mapping = load(self.ws, entry) if entry else None
		if mapping is None:
			return Result(checked=1)
		context = self.ws.context(entry)
		reverse, lossy = mappingReverse(mapping, context.ontology, context.toOntology, context.libraries, self.args.referential)
		self.ws.report([
			Diagnostic("warning", "map.lossy", f"{line.source} -> {line.target}: '{line.line}' is not reversed: {line.reason}", line.loc or Loc(entry.path, entry.line))
			for line in lossy
		])
		return Result(text=printMapping(reverse), checked=1)

	def cmdRun(self) -> Result:
		"""One-shot run of a binding over documents or a mapping over observations: the observations log it produces."""
		entry = one(self.ws, self.args, ("binding", "mapping"))
		model = load(self.ws, entry) if entry else None
		if model is None:
			return Result(checked=1)
		try:
			from hexa.runtime import run
			from ..integrations.hexa.operations import HexaBindingOperator, HexaMappingOperator
		except ImportError as error:
			raise UsageError(f"running needs the hexa package: {error}", "run") from error
		context = self.ws.context(entry)
		mode = "strict" if self.args.strict else "lenient"
		at = self.args.at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
		clock = {"ClockRead": lambda _context: at}
		implementations = self.implementations()
		if entry.kind == "binding":
			items = []
			for path in self.args.inputs:
				try:
					text = sys.stdin.read() if path == STDIN else Path(path).read_text(encoding="utf-8")
					document = list(csv.DictReader(io.StringIO(text))) if model.header.get("format") == "csv" else json.loads(text)
				except (OSError, UnicodeError, ValueError, csv.Error) as error:
					self.ws.error("cli.read", f"cannot read document: {error}", self.ws.indexer.display(path))
					continue
				items.append({"src": self.args.src or self.ws.indexer.display(path), "document": document})
			if len(items) != len(self.args.inputs):
				return Result(checked=1)
			ops = HexaBindingOperator(context.ontology, mode, context.libraries, implementations, context.ontologies)
			program = ops.compile(model)
			log, report = ops.result(program, asyncio.run(run(clock, program.stages.BindingRead, items)))
			ontology = context.ontology
		else:
			logs = []
			for path in self.args.inputs:
				found = self.ws.add(path, "observations")
				observations = load(self.ws, found) if found else None
				if observations is None:
					return Result(checked=1)
				logs.append(observations)
			try:
				state = observationsToJson(reconcileObservations(context.ontology, observationsFromJson(context.ontology, mergedLogs(logs), "inputs", self.ws.mode), self.ws.mode))
			except FormatError as error:
				self.ws.report(error.diagnostics)
				return Result(checked=1)
			referential = context.referentials[0] if context.referentials else None
			ops = HexaMappingOperator(context.ontology, context.toOntology, referential, mode, context.libraries, implementations, context.ontologies)
			program = ops.compile(model)
			log, report = ops.result(program, asyncio.run(run(clock, program.stages.MappingRead, state)))
			ontology = context.toOntology
		level = "error" if self.args.strict else "warning"
		self.ws.report([Diagnostic(level, "run.gap", f"{gap.target}: {gap.reason}" + (f" ({gap.handle})" if gap.handle else "") + (f" in {gap.src}" if gap.src else "") + (f" at {gap.location}" if gap.location else ""),
			Loc(entry.path, entry.line)) for gap in report.gaps])
		return Result(text=printObservationsLog(ontology, log), data=observationsToJson(log), checked=1)

	def cmdInventory(self) -> Result:
		"""Inventory, or default binding, of sample documents."""
		documents = []
		for path in self.args.documents:
			try:
				text = sys.stdin.read() if path == STDIN else Path(path).read_text(encoding="utf-8")
				documents.append(list(csv.DictReader(io.StringIO(text))) if self.args.csv else json.loads(text))
			except (OSError, UnicodeError, ValueError, csv.Error) as error:
				self.ws.error("cli.read", f"cannot read document: {error}", self.ws.indexer.display(path))
		if len(documents) != len(self.args.documents):
			return Result(checked=len(self.args.documents))
		inventory = inventoryFromDocuments(documents, self.args.csv)
		if self.args.binding:
			text = printBinding(defaultBinding(inventory, self.args.binding, self.args.csv))
		else:
			text = printInventory(inventory)
		return Result(text=text, checked=len(documents))

	# -- Functions -------------------------------------------------------------

	def libraries(self) -> list[tuple[Entry, FunctionLibrary]]:
		"""Named or workspace libraries, one per namespace, loaded."""
		seen: dict[str, tuple[Entry, FunctionLibrary]] = {}
		for entry in targets(self.ws, self.args, self.args.files, ("functions",)):
			if entry.kind != "functions":
				self.ws.error("cli.kind", f"expected functions, not {entry.kind}", entry.path, 0)
				continue
			library = load(self.ws, entry)
			if library is not None:
				seen.setdefault(self.ws.groupId(entry), (entry, library))
		return list(seen.values())

	def implementations(self) -> dict[str, Callable[..., Any]]:
		"""Merge the IMPLEMENTATIONS of the --impl modules, importable from the working directory."""
		merged: dict[str, Callable[..., Any]] = {}
		if not self.args.impl:
			return merged
		path = list(sys.path)
		sys.path.insert(0, self.ws.cwd)
		importlib.invalidate_caches()
		for name in self.args.impl:
			try:
				module = importlib.import_module(name)
			except Exception as error:
				raise UsageError(f"cannot import --impl {name}: {type(error).__name__}: {error}", self.args.command) from error
			finally:
				sys.path[:] = path
			table = getattr(module, "IMPLEMENTATIONS", None)
			if not isinstance(table, dict):
				raise UsageError(f"--impl {name} has no IMPLEMENTATIONS mapping", self.args.command)
			merged.update(table)
		return merged

	def cmdFn(self) -> Result:
		"""`fn ls` lists signatures; `fn test` runs examples of implemented functions."""
		libraries = self.libraries()
		checked = len({entry.path for entry, _ in libraries})
		if self.args.action == "ls":
			rows = [
				{"name": f"{library.namespace}/{function.name}", "signature": f"{', '.join(signatureText(arg) for arg in function.args)} -> {signatureText(function.result)}", "doc": function.doc or ""}
				for _, library in libraries for function in library.functions
			]
			return Result(columns=("name", "signature", "doc"), rows=sorted(rows, key=lambda row: row["name"]), header=False, checked=checked)
		implementations = self.implementations()
		rows, failed = [], False
		for entry, library in libraries:
			names = {function.name: f"{library.namespace}/{function.name}" for function in library.functions}
			runnable, skipped = [], []
			for function in library.functions:
				inverse = annotation(function.ann, "inverse")
				needed = [names[function.name]] + ([f"{library.namespace}/{inverse}"] if inverse else [])
				(runnable if all(name in implementations for name in needed) else skipped).append(function)
			for function in skipped:
				self.ws.report([Diagnostic("warning", "fn.unimplemented", f"{library.namespace}/{function.name} has no implementation; its examples were not run", function.loc or Loc(entry.path, entry.line))])
			evaluator = FunctionEvaluator(self.ws.context(entry).ontologies, [replace(library, functions=runnable)], implementations=implementations)
			try:
				count = evaluator.conformance(replace(library, functions=runnable))
				status = "passed"
			except FormatError as error:
				self.ws.report(error.diagnostics)
				count, status, failed = sum(len(function.examples) for function in runnable), "failed", True
			rows.append({"name": library.namespace, "status": status, "examples": str(count), "skipped": str(len(skipped))})
		return Result(columns=("name", "status", "examples", "skipped"), rows=rows, failed=failed, checked=checked)


__all__ = ["Commands", "Forms", "Result"]

# EOF
