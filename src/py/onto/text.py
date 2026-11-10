"""Module: text — shared lexical rules: lines, comments, docs, annotations and diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------

type Annotations = list[tuple[str, str | bool]]


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
		self.items.append(Diagnostic("error", code, message, loc))

	def warn(self, code: str, message: str, loc: Loc | None = None) -> None:
		self.items.append(Diagnostic("warning", code, message, loc))

	def hasErrors(self) -> bool:
		return any(item.level == "error" for item in self.items)

	def check(self) -> list[Diagnostic]:
		if self.hasErrors():
			raise FormatError(self.items)
		return self.items


NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*")
TOKEN = re.compile(r"[^\s{},=]+")
RE_ANNOTATION = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*=\s*(.*))?")
RE_ARGUMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.+)")

# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


# Function: isName
# True when `text` is a name.
def isName(text: str) -> bool:
	return NAME.fullmatch(text) is not None


# Function: isPath
# True when `text` is a `/`-separated path of names.
def isPath(text: str) -> bool:
	return PATH.fullmatch(text) is not None


# Function: isToken
# True when `text` is an annotation token (no whitespace, braces, commas or `=`).
def isToken(text: str) -> bool:
	return TOKEN.fullmatch(text) is not None


# Function: lastSegment
# The last segment of `path`.
def lastSegment(path: str) -> str:
	return path[path.rfind("/") + 1 :]


# Function: scanUnquoted
# Yields the indexes of `text` outside JSON-style double-quoted strings.
def scanUnquoted(text: str):
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


# Function: stripComment
# Removes a `//` comment that starts the line or follows whitespace, outside quotes.
def stripComment(text: str) -> str:
	for i in scanUnquoted(text):
		if text.startswith("//", i) and (i == 0 or text[i - 1].isspace()):
			return text[:i]
	return text


# Function: splitDoc
# Splits a trailing ` -- doc` from `text` → `(body, doc)`.
def splitDoc(text: str) -> tuple[str, str | None]:
	for i in scanUnquoted(text):
		if (
			text.startswith("--", i)
			and (i == 0 or text[i - 1].isspace())
			and (i + 2 == len(text) or text[i + 2].isspace())
		):
			return text[:i].rstrip(), (text[i + 2 :].strip() or None)
	return text, None


# Function: splitAnnotations
# Splits a trailing `{...}` block from `text` → `(body, annotation text)`.
def splitAnnotations(text: str) -> tuple[str, str | None]:
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


# Function: sourceLines
# Splits `source` into significant lines; comments and blank lines are dropped.
def sourceLines(source: Source) -> list[Line]:
	result: list[Line] = []
	for index, raw in enumerate(source.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
		text = stripComment(raw).rstrip()
		if not text.strip():
			continue
		stripped = text.lstrip()
		indentation = text[: len(text) - len(stripped)]
		result.append(Line(len(indentation), stripped, Loc(source.name, index + 1), "\t" in indentation))
	return result


# Function: parseAnnotations
# Parses `k=v, flag` annotation text; bad tokens and duplicate keys are errors.
def parseAnnotations(text: str | None, loc: Loc | None, diag: Diagnostics) -> Annotations:
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


# Function: printAnnotations
# Prints `pairs` as `{...}` in `order`, unknown keys last by name; "" when empty.
def printAnnotations(pairs: Annotations | None, order: list[str]) -> str:
	if not pairs:
		return ""
	ranked = sorted(pairs, key=lambda pair: (order.index(pair[0]) if pair[0] in order else len(order), pair[0]))
	return "{" + ", ".join(key if value is True else f"{key}={value}" for key, value in ranked) + "}"


# Function: annotation
# The value of annotation `key` in `pairs`, or None.
def annotation(pairs: Annotations | None, key: str) -> str | bool | None:
	for k, value in pairs or ():
		if k == key:
			return value
	return None


# Function: parseArguments
# Parses directive arguments `k=v k=v`.
def parseArguments(text: str, loc: Loc | None, diag: Diagnostics) -> list[tuple[str, str]]:
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


# Function: printArguments
# Prints directive arguments as `k=v k=v`.
def printArguments(pairs: list[tuple[str, str]]) -> str:
	return " ".join(f"{key}={value}" for key, value in pairs)


# EOF
