"""Module: cli.usage — the command catalog, argument parsing and help text."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any, NoReturn

from .ui import Style, wrap
from .workspace import KINDS

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Option:
	"""A command-line option: a flag when `metavar` is empty."""

	flags: tuple[str, ...]
	help: str
	metavar: str = ""
	choices: tuple[str, ...] = ()
	repeat: bool = False
	default: Any = None
	nargs: str | None = None

	@property
	def dest(self) -> str:
		"""The namespace attribute, from the long flag."""
		return self.flags[-1].lstrip("-").replace("-", "_")

	@property
	def label(self) -> str:
		"""`-I, --path DIR` as help prints it."""
		return ", ".join(self.flags) + (f" {self.metavar}" if self.metavar else "")


@dataclass(slots=True, frozen=True)
class Argument:
	"""A positional argument; `nargs` as argparse takes it."""

	name: str
	nargs: str | None = None
	choices: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class Command:
	"""One command: synopsis, summary, description, options and examples."""

	name: str
	group: str
	synopsis: str
	summary: str
	description: str
	arguments: tuple[Argument, ...] = ()
	options: tuple[Option, ...] = ()
	examples: tuple[str, ...] = ()


class UsageError(Exception):
	"""A command-line error: printed with a hint, exit status 2."""

	def __init__(self, message: str, command: str | None = None):
		super().__init__(message)
		self.command = command


GLOBAL_OPTIONS = (
	Option(("-I", "--path"), "Add DIR to the search path (repeatable; ONTO_PATH adds more, ':'-separated)", "DIR", repeat=True, default=[]),
	Option(("--no-workspace",), "Use only the files named on the command line and -I directories"),
	Option(("--color",), "Color human output: auto (terminals only), always or never", "WHEN", ("auto", "always", "never"), default="auto"),
	Option(("--json",), "Write the result and diagnostics as one JSON document"),
	Option(("-q", "--quiet"), "Suppress results and summaries; diagnostics remain"),
	Option(("-h", "--help"), "Show help and examples"),
	Option(("--version",), "Print the version"),
)
LENIENT = Option(("--lenient",), "Read observations in lenient mode: invalid statements become gaps (spec-02)")
KIND = Option(("--kind",), "Kind of a '-' (standard input) argument", "KIND", KINDS)

COMMANDS = (
	Command(
		"check", "Files", "[FILE...]",
		"Validate files with their context",
		"Parse and validate files, loading the ontologies, function libraries and referentials they name from "
		"the workspace. Prints diagnostics and a summary. Without FILE, checks every file of the workspace.",
		(Argument("files", "*"),), (LENIENT, KIND),
		("onto check", "onto check finance/exchange-finance.map", "onto check --json statement.obs"),
	),
	Command(
		"fmt", "Files", "[-w|--check|--diff] [FILE...]",
		"Align the layout of files, keeping what they say",
		"Fix the layout of hand-edited files: docs (' -- text') aligned at column 48, no trailing whitespace, LF "
		"line endings, one final newline. Order, comments, blank lines and forms are kept as written; 'onto text' "
		"prints a normal form instead. Only files that validate are formatted. With --write, --check or --diff and "
		"no FILE, applies to the whole workspace.",
		(Argument("files", "*"),),
		(
			Option(("-w", "--write"), "Rewrite files in place; lists the files rewritten"),
			Option(("--check",), "List files whose layout would change, write nothing; exit 1 if any"),
			Option(("--diff",), "Print a unified diff for each file whose layout would change; exit 1 if any"),
			LENIENT, KIND,
		),
		("onto fmt finance.onto", "onto fmt --check", "onto fmt --diff", "onto fmt -w exchange.bind"),
	),
	Command(
		"json", "Files", "FILE",
		"Print the JSON form of a text file",
		"Print the JSON form of a file, with its context resolved from the workspace. Files sharing an ontology, "
		"library or referential namespace are printed together, as one model.",
		(Argument("file"),), (LENIENT, KIND),
		("onto json finance.onto", "onto json statement.obs | jq .claims"),
	),
	Command(
		"text", "Files", "FILE.json",
		"Print the normal text form of a JSON file",
		"Read a JSON file (its kind comes from its 'format' member) and print its normal text form. Context comes "
		"from the workspace, as for text files.",
		(Argument("file"),), (LENIENT,),
		("onto text finance.json > finance.onto",),
	),
	Command(
		"snap", "Files", "FILE... [--format json|onto]",
		"Snapshot an ontology from an explicit set of files",
		"Merge and validate exactly the files named, then print the normalized ontology as JSON (default) or "
		"onto text. No workspace files are added. Reads <Namespace>.ids beside each text input when present.",
		(Argument("files", "+"),),
		(Option(("--format",), "Snapshot representation", "FORMAT", ("json", "onto"), default="json"),),
		("onto snap core.onto finance.onto > baseline.json", "onto snap core.onto finance.onto --format onto"),
	),
	Command(
		"diff", "Files", "[BEFORE AFTER] [--before FILE...] [--after FILE...]",
		"Compare combined ontology models, not source files",
		"Compare two independent sets of ontology text files or JSON snapshots. Declaration placement, comments "
		"and layout do not matter. Prints semantic changes, or structured changes with --json. "
		"Exit 1 means changes; exit 2 means input errors or invalid usage.",
		(Argument("files", "*"),),
		(
			Option(("--before",), "Files making up the old model", "FILE", nargs="+"),
			Option(("--after",), "Files making up the new model", "FILE", nargs="+"),
		),
		("onto diff baseline.json current.json", "onto diff --before old/core.onto old/finance.onto --after core.onto finance.onto"),
	),
	Command(
		"ls", "Files", "[KIND...]",
		"List the workspace",
		"List the files of the workspace by kind and namespace, with their revision, sorted by kind then namespace. "
		"Shows what the other commands will resolve.",
		(Argument("kinds", "*", KINDS),), (),
		("onto ls", "onto ls ontology functions", "onto -I ../shared ls"),
	),
	Command(
		"meta", "Files", "[--decl] FILE.onto",
		"Describe an ontology as Meta observations",
		"Print the ontology as observations of its own Meta domain (spec-01): one Meta/Concept per entity, facet "
		"and relation, one Meta/Attribute per attribute and one Meta/Dimension per type, so that data can refer to "
		"them. With --decl, print the Meta domain declarations instead, to keep as a file of the ontology. Files "
		"sharing the ontology namespace are described together.",
		(Argument("file"),), (Option(("--decl",), "Print the Meta domain declarations, as an ontology file"), KIND),
		("onto meta --decl finance.onto > meta.onto", "onto meta finance.onto > finance-meta.obs"),
	),
	Command(
		"state", "Observations", "FILE.obs",
		"Print the reconciled state form",
		"Print observations in state form (spec-02): retractions applied, superseded claims removed, conflicts "
		"marked and identity links resolved.",
		(Argument("file"),), (LENIENT, KIND),
		("onto state statement.obs",),
	),
	Command(
		"log", "Observations", "[--compact] FILE.obs",
		"Print the log form",
		"Print observations in log form (spec-02): every statement, retractions included, ordered by time.",
		(Argument("file"),), (Option(("--compact",), "Group consecutive observations in @entity blocks with local handle aliases"), LENIENT, KIND),
		("onto log statement.obs", "onto log --compact statement.obs"),
	),
	Command(
		"coverage", "Mappings", "FILE [--view VIEW] [--inventory FILE.inv]",
		"Print a coverage table",
		"Print the coverage table (spec-04), tab-separated and sorted by source. For a mapping, the static coverage "
		"of its From ontology, then the To elements no line assigns. For a binding, the document fields of its "
		"inventory (the .inv file with the same name, or --inventory) and the ontology elements no line assigns. "
		"For observations, the coverage of --view.",
		(Argument("file"),),
		(
			Option(("--view",), "View to cover, for observations (full or namespace-relative path)", "VIEW"),
			Option(("--inventory",), "Inventory of a binding's documents (default: FILE's .inv sidecar)", "FILE"),
			LENIENT,
		),
		("onto coverage exchange-finance.map", "onto coverage exchange.bind", "onto coverage statement.obs --view PortfolioReview"),
	),
	Command(
		"reverse", "Mappings", "FILE.map [--referential NAME]",
		"Print the reversed mapping",
		"Print the mapping To -> From made of the reverses of the reversible lines. Lines that cannot be reversed "
		"are reported as map.lossy warnings and omitted.",
		(Argument("file"),),
		(Option(("--referential",), "Referential of the reverse, giving keys back their forward handles", "NAME"),),
		("onto reverse exchange-finance.map",),
	),
	Command(
		"run", "Mappings", "FILE.bind DOCUMENT... | FILE.map STATE.obs... [--src TOKEN] [--impl MODULE] [--strict]",
		"Run a binding over documents, or a mapping over observations, once",
		"Run a binding over source documents (JSON, or CSV for a format=csv binding), or a mapping over the "
		"observations of its From ontology (several files form one state), and print the observations log it "
		"produces. Each run is one-shot: it compares with no previous output, so it retracts nothing; re-running "
		"against a store belongs to the host (spec-06). Values that could not be produced are reported as run.gap "
		"warnings; --strict makes them errors. --impl names the Python modules implementing the functions the file "
		"calls, as for 'fn test'.",
		(Argument("file"), Argument("inputs", "+")),
		(
			Option(("--src",), "Source token of the documents; {path} and {stem} name each document (default: its path)", "TOKEN"),
			Option(("--impl",), "Python module providing IMPLEMENTATIONS (repeatable)", "MODULE", repeat=True, default=[]),
			Option(("--at",), "Run time recorded on the claims (default: now)", "TIME"),
			Option(("--max-nodes",), "Largest input hexa accepts, in nodes (default: hexa's limit)", "N"),
			Option(("--report",), "Write what the run could not produce to FILE, as JSON: {format, gaps: [{target, reason, src, location, handle}]}", "FILE"),
			Option(("--strict",), "Report values that could not be produced as errors (exit 1)"),
			LENIENT,
		),
		("onto run exchange.bind feed.json", "onto run exchange.bind feed.json --src feed:instruments > exchange.obs",
			"onto run exchange-finance.map exchange.obs --impl markets_impl"),
	),
	Command(
		"inventory", "Mappings", "DOCUMENT... [--csv] [--binding NAMESPACE]",
		"Derive an inventory or a default binding from documents",
		"Print the inventory of sample documents: their field paths and JSON types, sorted by path. With --binding, "
		"print the default binding of the inventory instead: one scope per list of objects, one line per field.",
		(Argument("documents", "+"),),
		(
			Option(("--csv",), "Read documents as CSV with a header row"),
			Option(("--binding",), "Print the default binding for ontology NAMESPACE", "NAMESPACE"),
		),
		("onto inventory feed.json > exchange.inv", "onto inventory --binding Exchange feed.json"),
	),
	Command(
		"fn", "Functions", "test|ls [FILE.fn...] [--impl MODULE]",
		"Run or list function libraries",
		"'fn test' runs the examples of the libraries, and their inverse round trips. Functions are code: "
		"--impl names Python modules, importable from the working directory, whose IMPLEMENTATIONS map fully "
		"qualified names (Markets/FrequencyFromInterval) to callables. Functions without an implementation are "
		"skipped with a warning. 'fn ls' lists functions and their signatures. Without FILE, every library of the "
		"workspace.",
		(Argument("action", None, ("test", "ls")), Argument("files", "*")),
		(Option(("--impl",), "Python module providing IMPLEMENTATIONS (repeatable)", "MODULE", repeat=True, default=[]),),
		("onto fn ls", "onto fn test --impl markets_impl", "onto fn test markets.fn --impl markets_impl"),
	),
	Command(
		"store", "Stores", "bundle FILE.store",
		"Compile a store bundle",
		"'store bundle' prints the onto.store-bundle/1 JSON document a store runs with (spec-08), compiled from the "
		"store's files, its ontology, its @system mappings and their referentials. A store with errors prints nothing.",
		(Argument("action", None, ("bundle",)), Argument("file")),
		(),
		("onto store bundle adviser-app.store",),
	),
	Command(
		"help", "Help", "[COMMAND]",
		"Show help for onto or a command",
		"Same as 'onto --help' or 'onto COMMAND --help'.",
		(Argument("topic", "?"),), (),
		("onto help", "onto help coverage"),
	),
)
COMMAND_INDEX = {command.name: command for command in COMMANDS}
GROUPS = ("Files", "Observations", "Mappings", "Functions", "Help")

TERMS = (
	("FILE", "A path to an onto file; '-' reads standard input, with --kind"),
	("KIND", ", ".join(KINDS)),
	("DIR", "A directory added to the search path"),
	("VIEW", "An ontology view path, e.g. Finance/PortfolioReview"),
	("NAMESPACE", "An ontology namespace, e.g. Exchange"),
	("DOCUMENT", "A sample source document: JSON, or CSV with --csv"),
	("MODULE", "A Python module name, e.g. markets_impl"),
)
GETTING_STARTED = (
	("onto ls", "see what the workspace holds"),
	("onto check", "validate every file"),
	("onto fmt --diff", "see what layout fixes fmt would make"),
	("onto state statement.obs", "read the current state of observations"),
)
DESCRIPTION = "onto — check, format and convert ontologies, observations, bindings and mappings."
WORKSPACE = (
	"Files name each other by namespace (@use Finance as F). onto indexes the files under the project root (the "
	"nearest directory with .git, .hg or .jj) and the -I directories by their header, and loads what each file "
	"names from there."
)

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


class Parser(argparse.ArgumentParser):
	"""Argument parser raising `UsageError`, with suggestions for unknown options."""

	def __init__(self, *args: Any, command: str | None = None, **kwargs: Any):
		kwargs.setdefault("add_help", False)
		kwargs.setdefault("allow_abbrev", False)
		kwargs.setdefault("suggest_on_error", True)
		super().__init__(*args, **kwargs)
		self.command = command
		self.flags: list[str] = []

	def error(self, message: str) -> NoReturn:
		"""Raise a `UsageError`, suggesting the closest option of an unrecognized one."""
		if message.startswith("unrecognized arguments:"):
			for token in message.split(":", 1)[1].split():
				matches = get_close_matches(token.split("=", 1)[0], self.flags, n=1)
				if matches:
					message += f". Did you mean {matches[0]}?"
					break
		raise UsageError(message, self.command)


def addOption(parser: Parser, option: Option, suppress: bool = False) -> None:
	"""Declare `option`; `suppress` leaves it unset when absent, so it does not override earlier values."""
	kwargs: dict[str, Any] = {"dest": option.dest}
	if suppress:
		kwargs["default"] = argparse.SUPPRESS
	elif option.default is not None:
		kwargs["default"] = list(option.default) if isinstance(option.default, list) else option.default
	if option.metavar:
		kwargs["metavar"] = option.metavar
		kwargs["action"] = "append" if option.repeat else "store"
		if option.choices:
			kwargs["choices"] = option.choices
		if option.nargs:
			kwargs["nargs"] = option.nargs
	else:
		kwargs["action"] = "store_true"
	parser.add_argument(*option.flags, **kwargs)
	parser.flags.extend(option.flags)


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Arguments:
	"""Two-stage parsing: global options and the command, then the command's own arguments."""

	@staticmethod
	def Parse(argv: list[str]) -> argparse.Namespace:
		"""Parse `argv`; `command` is None for top-level help."""
		top = Parser(prog="onto")
		for option in GLOBAL_OPTIONS:
			addOption(top, option)
		top.add_argument("command", nargs="?")
		top.add_argument("rest", nargs=argparse.REMAINDER)
		parsed = top.parse_args(argv)
		if parsed.command is None:
			return parsed
		command = COMMAND_INDEX.get(parsed.command)
		if command is None:
			matches = get_close_matches(parsed.command, list(COMMAND_INDEX), n=1)
			hint = f". Did you mean '{matches[0]}'?" if matches else ""
			raise UsageError(f"unknown command '{parsed.command}'{hint}")
		local = Parser(prog=f"onto {command.name}", command=command.name)
		for option in GLOBAL_OPTIONS:
			addOption(local, option, suppress=True)
		for option in command.options:
			addOption(local, option)
		for argument in command.arguments:
			kwargs: dict[str, Any] = {"metavar": argument.name.upper()}
			if argument.nargs:
				kwargs["nargs"] = argument.nargs
			if argument.choices:
				kwargs["choices"] = argument.choices
				del kwargs["metavar"]
			local.add_argument(argument.name, **kwargs)
		rest = parsed.rest
		# NOTE: Help and version need no command arguments.
		flags = rest[:rest.index("--")] if "--" in rest else rest
		parsed.version = parsed.version or "--version" in flags
		if parsed.help or parsed.version or "-h" in flags or "--help" in flags:
			parsed.help = parsed.help or not parsed.version
			return parsed
		values = local.parse_args(rest)
		for key, value in vars(values).items():
			if key == "path":
				parsed.path = parsed.path + value
			else:
				setattr(parsed, key, value)
		del parsed.rest
		return parsed


class Help:
	"""Help text for onto and its commands, colored for terminals."""

	@staticmethod
	def Rows(rows: list[tuple[str, str]], style: Style, name: str = "command", indent: str = "  ") -> list[str]:
		"""Two aligned columns, the second wrapped under itself."""
		left = max(len(key) for key, _ in rows) + 2
		lines = []
		for key, text in rows:
			body = wrap(text, "", " " * (len(indent) + left)).split("\n")
			lines.append(indent + style.paint(name, key) + " " * (left - len(key)) + "\n".join(body))
		return lines

	@staticmethod
	def Top(style: Style) -> str:
		"""Overview: description, usage, commands by group, options, terms and a getting-started sequence."""
		sections = [
			style.paint("heading", DESCRIPTION),
			f"{style.paint('heading', 'Usage:')} onto [-I DIR]... [--color WHEN] [--json] [-q] <command> [ARGS]",
			wrap(WORKSPACE),
		]
		for group in GROUPS:
			rows = [(f"{command.name} {command.synopsis}".rstrip(), command.summary) for command in COMMANDS if command.group == group]
			syntax = max(len(key) for key, _ in rows)
			lines = [style.paint("heading", f"{group}:")]
			for key, summary in rows:
				name, _, arguments = key.partition(" ")
				lines.append("  " + style.paint("command", name) + (" " + arguments if arguments else "") + " " * (syntax - len(key) + 2) + style.paint("hint", summary))
			sections.append("\n".join(lines))
		sections.append("\n".join([style.paint("heading", "Options:")] + Help.Rows([(option.label, option.help) for option in GLOBAL_OPTIONS], style)))
		sections.append("\n".join([style.paint("heading", "Terms:")] + Help.Rows(list(TERMS), style, "name")))
		sections.append("\n".join([style.paint("heading", "Getting started:")] + [f"  {command.ljust(28)}{style.paint('hint', text)}" for command, text in GETTING_STARTED]))
		sections.append(style.paint("hint", "Run 'onto help COMMAND' or 'onto COMMAND --help' for details and examples."))
		return "\n\n".join(sections)

	@staticmethod
	def Command(name: str, style: Style) -> str:
		"""A command's usage, description, options and examples."""
		command = COMMAND_INDEX[name]
		sections = [
			f"{style.paint('heading', 'Usage:')} onto {style.paint('command', command.name)} {command.synopsis}".rstrip(),
			wrap(command.description),
		]
		if command.options:
			sections.append("\n".join([style.paint("heading", "Options:")] + Help.Rows([(option.label, option.help) for option in command.options], style)))
		sections.append("\n".join([style.paint("heading", "Global options:")] + Help.Rows([(option.label, option.help) for option in GLOBAL_OPTIONS], style)))
		if command.examples:
			sections.append("\n".join([style.paint("heading", "Examples:")] + [f"  {example}" for example in command.examples]))
		return "\n\n".join(sections)


__all__ = ["COMMANDS", "COMMAND_INDEX", "GLOBAL_OPTIONS", "Arguments", "Command", "Help", "Option", "UsageError"]

# EOF
