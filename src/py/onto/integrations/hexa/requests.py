"""Module: integrations.hexa.requests — fill a view read's request template into a hexa `RequestSend` request.

A read's `request` is `{method?, path, api?, query?, headers?, body?}`. In `path`, `{name}` (the input's name)
is the input value as one encoded path segment; elsewhere a string `"{name}"` is the value itself, and `{name}`
within a longer string its text. A read's `source` spells the response's provenance token the same way.
"""

from __future__ import annotations

import json
import re
from string.templatelib import Interpolation, Template
from typing import TYPE_CHECKING

from hexa.runtime import p

if TYPE_CHECKING:
	from .catalogue import ViewRead

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


REQUEST_KEYS = ("method", "path", "api", "query", "headers", "body")
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
RE_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
ABSENT = object()


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def valueText(value: object) -> str:
	"""A key value as text, spelled as JavaScript's `String` spells it."""
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, float) and value.is_integer():
		return str(int(value))
	return str(value)


def templateFill(item: object, name: str, value: object) -> object:
	"""A request template part with the input value: `"{name}"` is the value, `{name}` in a longer string its text."""
	token = "{" + name + "}"
	if isinstance(item, str):
		return value if item == token else item.replace(token, valueText(value))
	if isinstance(item, dict):
		return {key: templateFill(entry, name, value) for key, entry in item.items()}
	if isinstance(item, list):
		return [templateFill(entry, name, value) for entry in item]
	return item


def templateFillMany(item: object, values: dict, absent: str = "omit") -> object:
	"""A list read's template part with its parameters' values (spec-09 "List reads"): `"{name}"` is the value, `{name}`
	in a longer string its text; a part whose placeholders are all absent is left out (`ABSENT`), or null."""
	if isinstance(item, str):
		names = RE_PLACEHOLDER.findall(item)
		if names and not any(name in values for name in names):
			return None if absent == "null" else ABSENT
		if len(names) == 1 and item == "{" + names[0] + "}":
			return values[names[0]]
		return RE_PLACEHOLDER.sub(lambda match: valueText(values[match[1]]) if match[1] in values else match[0], item)
	if isinstance(item, dict):
		filled = {key: templateFillMany(entry, values, absent) for key, entry in item.items()}
		kept = {key: entry for key, entry in filled.items() if entry is not ABSENT}
		return ABSENT if item and not kept else kept
	if isinstance(item, list):
		kept = [entry for entry in (templateFillMany(entry, values, absent) for entry in item) if entry is not ABSENT]
		return ABSENT if item and not kept else kept
	return item


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def listRequestFor(read, values: dict) -> dict:
	"""A list read's `RequestSend` request for its parameters' values, leaving out what no value fills."""
	request = {}
	for key, item in requestTemplate(read).items():
		filled = item if key in ("method", "path", "api") else templateFillMany(item, values, read.absent)
		if filled is not ABSENT:
			request[key] = filled
	return request


def checkListRequest(step: str, read) -> None:
	"""Reject a list read's request template naming other placeholders than its parameters, or in its path."""
	template = read.request
	path = template.get("path") if isinstance(template, dict) else None
	if (not isinstance(path, str) or not path.startswith("/") or re.search(r"[{}]", path) or set(template) - set(REQUEST_KEYS)
		or template.get("method", "GET") not in METHODS or not isinstance(template.get("api", ""), str)):
		raise ValueError(f"{step}: a list read's request is {{method?, path, api?, query?, headers?, body?}}, its path starting with / without placeholders")
	unknown = sorted(set(RE_PLACEHOLDER.findall(json.dumps(template))) - set(read.parameters))
	if unknown:
		raise ValueError(f"{step}: no list parameter {', '.join(unknown)}")


def requestTemplate(read: ViewRead) -> dict:
	"""A read's request template in its canonical member order, the method spelled out."""
	return {"method": read.request.get("method", "GET"), **{key: read.request[key] for key in REQUEST_KEYS[1:] if key in read.request}}


def requestFor(read: ViewRead, value: object) -> dict:
	"""A read's `RequestSend` request for an input value; hexa's `p` encodes the path segment."""
	request, literals = requestTemplate(read), read.request["path"].split("{" + read.input.name + "}")
	parts = [literals[0]]
	for literal in literals[1:]:
		parts += [Interpolation(value, read.input.name), literal]
	return {key: p(Template(*parts)) if key == "path" else item if key in ("method", "api") else templateFill(item, read.input.name, value)
		for key, item in request.items()}


def requestSource(read: ViewRead, request: dict, value: object) -> str:
	"""A response's provenance token: the read's `source` template, else the request's API and path."""
	if read.source is not None:
		return read.source.replace("{" + read.input.name + "}", valueText(value))
	return (request["api"] + ":" if "api" in request else "") + request["path"]


def checkRequest(step: str, read: ViewRead) -> None:
	"""Reject a request template that `requestFor` could not fill into a request."""
	template = read.request
	if template is None:
		if read.source is not None:
			raise ValueError(f"{step}: a source template needs a request template")
		return
	path = template.get("path") if isinstance(template, dict) else None
	if (not isinstance(path, str) or not path.startswith("/") or re.search(r"[{}]", path.replace("{" + read.input.name + "}", ""))
		or set(template) - set(REQUEST_KEYS) or template.get("method", "GET") not in METHODS or not isinstance(template.get("api", ""), str)
		or not isinstance(read.source if read.source is not None else "", str)):
		raise ValueError(f"{step}: a request is {{method?, path, api?, query?, headers?, body?}}, its path starting with / and naming only {{{read.input.name}}}")


__all__ = ["METHODS", "REQUEST_KEYS", "checkListRequest", "checkRequest", "listRequestFor", "requestFor", "requestSource", "requestTemplate"]

# EOF
