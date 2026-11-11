"""Module: text — shared lexical rules: lines, comments, docs, annotations and diagnostics."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

type Annotations = list[tuple[str, str | bool]]


NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*")
TOKEN = re.compile(r"[^\s{},=]+")
RE_ANNOTATION = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*=\s*(.*))?")
RE_ARGUMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.+)")


@dataclass(slots=True, frozen=True)
class Loc:
	"""Position of a line in a source file."""

	file: str | None
	line: int


@dataclass(slots=True, frozen=True)
class Source:
	"""A named source text."""

	name: str
	text: str


@dataclass(slots=True, frozen=True)
class Line:
	"""A significant source line: comments removed, indentation measured."""

	indent: int
	text: str
	loc: Loc
	tabs: bool


@dataclass(slots=True, frozen=True)
class Diagnostic:
	"""An error or warning about a location."""

	level: str
	code: str
	message: str
	loc: Loc | None = None

	def __str__(self) -> str:
		where = f"{self.loc.file}:{self.loc.line}: " if self.loc else ""
		return f"{where}{self.level} {self.code}: {self.message}"


class FormatError(Exception):
	"""Raised when a stage collected errors; carries every diagnostic."""

	def __init__(self, diagnostics: list[Diagnostic]):
		errors = [str(item) for item in diagnostics if item.level == "error"]
		super().__init__("\n".join(errors) or "Format error")
		self.diagnostics = diagnostics


@dataclass(slots=True)
class Diagnostics:
	"""Collects diagnostics; `check` raises when any error was recorded."""

	items: list[Diagnostic] = field(default_factory=list)

	def error(self, code: str, message: str, loc: Loc | None = None) -> None:
		"""Record an error with `code`, `message` and optional `loc`."""
		self.items.append(Diagnostic("error", code, message, loc))

	def warn(self, code: str, message: str, loc: Loc | None = None) -> None:
		"""Record a warning with `code`, `message` and optional `loc`."""
		self.items.append(Diagnostic("warning", code, message, loc))

	def hasErrors(self) -> bool:
		"""Whether any recorded diagnostic is an error."""
		return any(item.level == "error" for item in self.items)

	def check(self) -> list[Diagnostic]:
		"""Return collected diagnostics, raising `FormatError` if any are errors."""
		if self.hasErrors():
			raise FormatError(self.items)
		return self.items


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def isName(text: str) -> bool:
	"""Whether `text` is a name."""
	return NAME.fullmatch(text) is not None


def isPath(text: str) -> bool:
	"""Whether `text` is a `/`-separated path of names."""
	return PATH.fullmatch(text) is not None


def isToken(text: str) -> bool:
	"""Whether `text` is an annotation token, without whitespace, braces, commas or `=`."""
	return TOKEN.fullmatch(text) is not None


def lastSegment(path: str) -> str:
	"""Return the last segment of `path`."""
	return path[path.rfind("/") + 1 :]


def scanUnquoted(text: str) -> Iterator[int]:
	"""Yield indexes of `text` outside JSON-style double-quoted strings."""
	quoted = False
	i = 0
	while i < len(text):
		char = text[i]
		if quoted:
			if char == "\\":
				i += 1
			elif char == '"':
				quoted = False
		elif char == '"':
			quoted = True
		else:
			yield i
		i += 1


def stripComment(text: str) -> str:
	"""Remove an unquoted `//` comment starting the line or following whitespace in `text`."""
	for i in scanUnquoted(text):
		if text.startswith("//", i) and (i == 0 or text[i - 1].isspace()):
			return text[:i]
	return text


def splitDoc(text: str) -> tuple[str, str | None]:
	"""Split a trailing ` -- doc` from `text` into body and doc."""
	for i in scanUnquoted(text):
		if (
			text.startswith("--", i)
			and (i == 0 or text[i - 1].isspace())
			and (i + 2 == len(text) or text[i + 2].isspace())
		):
			return text[:i].rstrip(), (text[i + 2 :].strip() or None)
	return text, None


def splitAnnotations(text: str) -> tuple[str, str | None]:
	"""Split a trailing `{...}` block from `text` into body and annotation text."""
	trimmed = text.rstrip()
	if not trimmed.endswith("}"):
		return trimmed, None
	opening = -1
	for i in scanUnquoted(trimmed):
		if trimmed[i] == "{" and (i == 0 or trimmed[i - 1].isspace()):
			opening = i
	if opening < 0:
		return trimmed, None
	return trimmed[:opening].rstrip(), trimmed[opening + 1 : -1]


def sourceLines(source: Source) -> list[Line]:
	"""Read significant lines from `source`, dropping comments/blanks and normalizing line endings."""
	result: list[Line] = []
	for index, raw in enumerate(source.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
		text = stripComment(raw).rstrip()
		if not text.strip():
			continue
		stripped = text.lstrip()
		indentation = text[: len(text) - len(stripped)]
		result.append(Line(len(indentation), stripped, Loc(source.name, index + 1), "\t" in indentation))
	return result


def parseAnnotations(text: str | None, loc: Loc | None, diag: Diagnostics) -> Annotations:
	"""Parse `text` as `k=v, flag` annotations, reporting invalid or duplicate tokens in `diag`."""
	pairs: Annotations = []
	if not text or not text.strip():
		return pairs
	for part in text.split(","):
		item = part.strip()
		match = RE_ANNOTATION.fullmatch(item)
		if not match:
			diag.error("annotation", f"Invalid annotation '{item}'", loc)
			continue
		key, value = match.group(1), match.group(2)
		if value is not None and not isToken(value):
			diag.error("annotation", f"Invalid annotation value '{item}'", loc)
			continue
		if any(k == key for k, _ in pairs):
			diag.error("annotation", f"Duplicate annotation '{key}'", loc)
			continue
		pairs.append((key, True if value is None else value))
	return pairs


def printAnnotations(pairs: Annotations | None, order: list[str]) -> str:
	"""Render `pairs` in `order`, unknown keys last by name; return an empty string if absent."""
	if not pairs:
		return ""
	ranked = sorted(pairs, key=lambda pair: (order.index(pair[0]) if pair[0] in order else len(order), pair[0]))
	return "{" + ", ".join(key if value is True else f"{key}={value}" for key, value in ranked) + "}"


def annotation(pairs: Annotations | None, key: str) -> str | bool | None:
	"""Find annotation `key` in `pairs`, returning None when absent."""
	for k, value in pairs or ():
		if k == key:
			return value
	return None


def parseArguments(text: str, loc: Loc | None, diag: Diagnostics) -> list[tuple[str, str]]:
	"""Parse directive arguments `text` as `k=v k=v`, reporting errors in `diag`."""
	pairs: list[tuple[str, str]] = []
	for item in text.split():
		match = RE_ARGUMENT.fullmatch(item)
		if not match or not isToken(match.group(2)):
			diag.error("directive", f"Invalid argument '{item}'", loc)
			continue
		if any(k == match.group(1) for k, _ in pairs):
			diag.error("directive", f"Duplicate argument '{match.group(1)}'", loc)
			continue
		pairs.append((match.group(1), match.group(2)))
	return pairs


def printArguments(pairs: list[tuple[str, str]]) -> str:
	"""Render directive argument `pairs` as `k=v k=v`."""
	return " ".join(f"{key}={value}" for key, value in pairs)


# EOF
