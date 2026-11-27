"""Module: handles — spec-05 handle forms: derived from a key or qualified by a source, encoded and decoded."""

from __future__ import annotations

import re

from .text import lastSegment

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


RE_ENCODED = re.compile(r"(?:[A-Za-z0-9]|_[0-9A-F]{2})*")
RE_PLAIN = re.compile(r"[A-Za-z0-9]")


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def encodeKey(key: str) -> str:
	"""Every character outside `[A-Za-z0-9]` as `_` and the uppercase hex of its UTF-8 bytes (spec-04)."""
	return "".join(char if RE_PLAIN.fullmatch(char) else "".join(f"_{byte:02X}" for byte in char.encode()) for char in key)


def decodeKey(text: str) -> str | None:
	"""Invert `encodeKey`, or None when `text` is not such an encoding."""
	if not RE_ENCODED.fullmatch(text):
		return None
	data = bytearray()
	index = 0
	while index < len(text):
		if text[index] == "_":
			data.append(int(text[index + 1:index + 3], 16))
			index += 3
		else:
			data += text[index].encode()
			index += 1
	try:
		return data.decode()
	except UnicodeDecodeError:
		return None


def derivedHandle(typePath: str, key: str) -> str:
	"""`<Type>_<encoded key>`, `Type` being the last segment of the type path (spec-05)."""
	return f"{lastSegment(typePath)}_{encodeKey(key)}"


def sourceQualifiedHandle(typePath: str, scope: str, sourceType: str, key: str) -> str:
	"""`<Type>_` and the encoding of `<scope>/<S>/<key>`, `S` being the source record's type (spec-05)."""
	return derivedHandle(typePath, f"{scope}/{lastSegment(sourceType)}/{key}")


def handleKey(handle: str, typePath: str) -> str | None:
	"""The decoded part of a handle of `typePath`, or None when the handle is not of that type's form."""
	prefix = f"{lastSegment(typePath)}_"
	return decodeKey(handle[len(prefix):]) if handle.startswith(prefix) else None


def sourceParts(key: str) -> tuple[str, str, str] | None:
	"""A source-qualified handle's `<scope>/<S>/<key>`, or None when `key` has not that form."""
	scope, slash, rest = key.partition("/")
	sourceType, slash2, value = rest.partition("/")
	if not (slash and slash2 and scope and sourceType and value):
		return None
	return scope, sourceType, value


__all__ = ["encodeKey", "decodeKey", "derivedHandle", "sourceQualifiedHandle", "handleKey", "sourceParts"]

# EOF
