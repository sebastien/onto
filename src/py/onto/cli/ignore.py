"""Module: cli.ignore — workspace exclusions from `.gitignore` and `.ontoignore` files (spec-07 Workspace)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


# NOTE: Read in this order in each directory: `.ontoignore` comes last, so it may add exclusions or
# re-include (`!`) what `.gitignore` excludes, as ripgrep's `.ignore` does.
IGNORE_FILES = (".gitignore", ".ontoignore")


@dataclass(slots=True)
class Rule:
	"""One pattern line: its regular expression over paths relative to its file's directory."""

	pattern: re.Pattern[str]
	negated: bool
	directoryOnly: bool


@dataclass(slots=True)
class Rules:
	"""The rules of one directory's ignore files, in file and line order."""

	base: str
	rules: list[Rule] = field(default_factory=list)


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def translate(glob: str) -> str:
	"""A gitignore glob as a regular expression body; only a full `**` segment crosses slashes."""
	result, index = "", 0
	while index < len(glob):
		char = glob[index]
		if glob.startswith("**/", index) and (index == 0 or glob[index - 1] == "/"):
			result += "(?:.*/)?"
			index += 3
			continue
		if glob.startswith("/**", index) and index + 3 == len(glob):
			result += "/.*"
			index += 3
			continue
		if char == "*":
			result += "[^/]*"
		elif char == "?":
			result += "[^/]"
		elif char == "\\" and index + 1 < len(glob):
			index += 1
			result += re.escape(glob[index])
		elif char == "[":
			end = glob.find("]", index + 1)
			if end == -1:
				result += re.escape(char)
			else:
				body = glob[index + 1:end].replace("\\", "\\\\")
				result += "[" + ("^" + body[1:] if body.startswith("!") else body) + "]"
				index = end
		else:
			result += re.escape(char)
		index += 1
	return result


def parseRule(line: str) -> Rule | None:
	"""A rule from one line of an ignore file; None for blank lines and comments."""
	line = line.rstrip("\n").rstrip("\r")
	if not line.strip() or line.startswith("#"):
		return None
	line = re.sub(r"(?<!\\)\s+$", "", line)
	negated = line.startswith("!")
	if negated or line.startswith("\\!") or line.startswith("\\#"):
		line = line[1:]
	directoryOnly = line.endswith("/")
	line = line.rstrip("/")
	if not line:
		return None
	# A pattern with a slash before its end is anchored to its file's directory; otherwise it matches at any depth.
	anchored = "/" in line
	line = line.lstrip("/")
	body = translate(line)
	try:
		return Rule(re.compile(("" if anchored else "(?:.*/)?") + body + "$"), negated, directoryOnly)
	except re.error:
		return None


def readRules(directory: str) -> Rules | None:
	"""The rules of `directory`'s ignore files, or None when it has none."""
	rules = Rules(directory)
	for name in IGNORE_FILES:
		path = os.path.join(directory, name)
		try:
			with open(path, encoding="utf-8") as handle:
				rules.rules += [rule for line in handle if (rule := parseRule(line)) is not None]
		except (OSError, UnicodeDecodeError):
			continue
	return rules if rules.rules else None


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class Ignores:
	"""Decide whether a path below a scanned root is excluded, by the ignore files from the root down."""

	def __init__(self, root: str):
		self.root = os.path.abspath(root)
		self.cache: dict[str, Rules | None] = {}

	def rules(self, directory: str) -> Rules | None:
		if directory not in self.cache:
			self.cache[directory] = readRules(directory)
		return self.cache[directory]

	def ignored(self, path: str, isDirectory: bool) -> bool:
		"""Whether `path` is excluded: the last matching rule of the nearest files decides, as in git."""
		path = os.path.abspath(path)
		parent = os.path.dirname(path)
		chain = []
		directory = parent
		while True:
			chain.append(directory)
			if directory == self.root or os.path.dirname(directory) == directory or not directory.startswith(self.root):
				break
			directory = os.path.dirname(directory)
		excluded = False
		for directory in reversed(chain):
			rules = self.rules(directory)
			if rules is None:
				continue
			relative = os.path.relpath(path, directory).replace(os.sep, "/")
			for rule in rules.rules:
				if rule.directoryOnly and not isDirectory:
					continue
				if rule.pattern.match(relative):
					excluded = not rule.negated
		return excluded


__all__ = ["IGNORE_FILES", "Ignores", "parseRule", "readRules"]

# EOF
