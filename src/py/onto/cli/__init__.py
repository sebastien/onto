"""Module: cli — the `onto` command line: parsing, dispatch, output and exit status (spec-07)."""

from __future__ import annotations

import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import TextIO

from .commands import Commands, Result
from .ui import Render, Style, colorEnabled
from .usage import COMMAND_INDEX, Arguments, Help, UsageError
from .workspace import Workspace, projectRoot

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

CLI_FORMAT = "onto.cli/1"
EXIT_OK, EXIT_ERRORS, EXIT_USAGE = 0, 1, 2
EXIT_TROUBLE = 2  # `onto diff`: an input could not be read
# NOTE: The shell convention for a process ended by SIGINT: 128 + 2.
EXIT_INTERRUPTED = 130

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def ontoVersion() -> str:
	"""The installed package version."""
	try:
		return version("onto-lang")
	except PackageNotFoundError:
		return "unknown"


def searchPath(cwd: str, paths: list[str], scan: bool) -> list[str]:
	"""The project root, `-I`, then `ONTO_PATH`; only `-I` when `scan` is off."""
	extra = [item for item in os.environ.get("ONTO_PATH", "").split(":") if item] if scan else []
	roots = ([projectRoot(cwd)] if scan else []) + paths + extra
	return list(dict.fromkeys(os.path.abspath(root) for root in roots))


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Output:
	"""Writes a command's result and diagnostics, as text or as one JSON document."""

	def __init__(self, stdout: TextIO, stderr: TextIO, color: str, asJson: bool, quiet: bool):
		self.stdout = stdout
		self.stderr = stderr
		self.out = Style(colorEnabled(color, stdout) and not asJson)
		self.err = Style(colorEnabled(color, stderr) and not asJson)
		self.asJson = asJson
		self.quiet = quiet

	def write(self, command: str, result: Result, ws: Workspace) -> int:
		"""Write `result` with the workspace's diagnostics and return the exit status."""
		diagnostics = sorted(ws.diagnostics(), key=Render.SortKey)
		errors = any(item.level == "error" for item in diagnostics)
		status = EXIT_ERRORS if result.failed or errors else EXIT_OK
		if command == "diff" and errors:
			status = EXIT_TROUBLE  # diff(1): 0 same, 1 different, 2 trouble
		if self.asJson:
			document = {
				"format": CLI_FORMAT,
				"command": command,
				"ok": status == EXIT_OK,
				"result": result.resultJson(),
				"diagnostics": [
					{"level": item.level, "code": item.code, "message": item.message, "file": item.loc.file if item.loc else None, "line": item.loc.line if item.loc and item.loc.line else None}
					for item in diagnostics
				],
				"files": {"checked": result.checked, "read": len(ws.readPaths)},
			}
			self.stdout.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
			return status
		if not self.quiet:
			if result.rows is not None:
				table = Render.Table(result.columns, result.rows, self.out, result.header)
				if table:
					self.stdout.write(table + "\n")
			elif result.text:
				self.stdout.write(result.text if result.text.endswith("\n") else result.text + "\n")
		for item in diagnostics:
			self.stderr.write(Render.DiagnosticLine(item, self.err) + "\n")
		if not self.quiet:
			if diagnostics or command == "check":
				summary = Render.Summary(diagnostics, result.checked, len(ws.readPaths))
				self.stderr.write(self.err.paint("hint" if diagnostics else "ok", summary) + "\n")
			if result.hint:
				self.stderr.write(self.err.paint("hint", result.hint) + "\n")
		return status


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def run(argv: list[str], stdout: TextIO, stderr: TextIO) -> int:
	"""Run the CLI on `argv`, writing to `stdout` and `stderr`; return the exit status."""
	try:
		args = Arguments.Parse(argv)
	except UsageError as error:
		hint = f"onto {error.command} --help" if error.command else "onto --help"
		stderr.write(f"onto: error: {error}\nRun '{hint}' for examples and argument descriptions.\n")
		return EXIT_USAGE
	style = Style(colorEnabled(args.color, stdout))
	if args.version:
		stdout.write(f"onto {ontoVersion()}\n")
		return EXIT_OK
	topic = args.command
	if topic == "help":
		topic = getattr(args, "topic", None)
		if topic and topic not in COMMAND_INDEX:
			stderr.write(f"onto: error: unknown command '{topic}'\nRun 'onto --help' for the list of commands.\n")
			return EXIT_USAGE
		args.help = True
	if args.help or topic is None:
		stdout.write((Help.Command(topic, style) if topic else Help.Top(style)) + "\n")
		return EXIT_OK
	cwd = os.getcwd()
	scan = not args.no_workspace
	ws = Workspace(cwd, searchPath(cwd, args.path, scan), scan, "lenient" if getattr(args, "lenient", False) else "strict")
	output = Output(stdout, stderr, args.color, args.json, args.quiet)
	try:
		result = Commands(ws, args).run(args.command)
	except UsageError as error:
		stderr.write(f"onto: error: {error}\nRun 'onto {error.command or args.command} --help' for examples and argument descriptions.\n")
		return EXIT_USAGE
	return output.write(args.command, result, ws)


def main(argv: list[str] | None = None) -> int:
	"""Entry point of the `onto` script."""
	try:
		return run(sys.argv[1:] if argv is None else list(argv), sys.stdout, sys.stderr)
	except KeyboardInterrupt:
		return EXIT_INTERRUPTED
	except BrokenPipeError:
		# NOTE: The reader went away (`onto json x | head`); silence the flush at exit.
		os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
		return EXIT_OK
	except Exception as error:
		if os.environ.get("ONTO_DEBUG") == "1":
			raise
		sys.stderr.write(f"onto: internal error: {error or type(error).__name__}\nRerun with ONTO_DEBUG=1 for the traceback.\n")
		return EXIT_ERRORS


__all__ = ["main", "run"]

# EOF
