"""Module: referential.parser — spec-05 policy source and strict structural JSON decoding."""

from __future__ import annotations

import re
from typing import Any

from ..binding.parser import qualifyPath, readDoc
from ..observations.model import RE_DURATION
from ..observations.parser import jsonObject, jsonString
from ..text import Diagnostics, Loc, Source, isName, isPath, parseArguments, sourceLines, splitDoc
from .model import REFERENTIAL_FORMAT, Policy, Referential

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def checkPolicyShape(policy: Policy) -> None:
	"""Validate the structural constraints of `policy`."""
	if not isPath(policy.type):
		raise ValueError("A policy must name an instance type")
	if any(not isinstance(key, str) or not isName(key) for key in policy.keys) or len(set(policy.keys)) != len(policy.keys):
		raise ValueError("Policy keys must be distinct attribute names")
	if type(policy.minted) is not bool:
		raise ValueError("minted must be a flag")
	if policy.fromNamespace is not None and (not isPath(policy.fromNamespace) or policy.minted or not policy.keys):
		raise ValueError("from is allowed only on a key policy and must name a source ontology")
	if policy.implicit is not None and (not isinstance(policy.implicit, str) or policy.implicit != "never" and not RE_DURATION.fullmatch(policy.implicit)):
		raise ValueError("implicit must be an ISO duration or never")
	if not policy.keys and not policy.minted and policy.implicit is None:
		raise ValueError("A declaration needs a key policy, minted, or an implicit age")


def readReferentialJson(data: Any) -> Referential:
	"""Decode and validate referential JSON data."""
	value = jsonObject(data, ("format", "namespace", "policies"), ("header", "uses"))
	if value["format"] != REFERENTIAL_FORMAT:
		raise ValueError("Unknown referential JSON format")
	namespace = jsonString(value["namespace"], isPath)
	header = jsonObject(value.get("header", {}), (), ("rev",))
	for token in header.values():
		jsonString(token)
	uses = value.get("uses", {})
	if not isinstance(uses, dict) or any(not isinstance(alias, str) or not isName(alias) for alias in uses):
		raise ValueError("Invalid referential aliases")
	for path in uses.values():
		jsonString(path, isPath)
	if not isinstance(value["policies"], list):
		raise ValueError("policies must be an array")
	ref = Referential(namespace, dict(header), dict(uses))
	for item in value["policies"]:
		item = jsonObject(item, ("type",), ("keys", "minted", "from", "implicit", "doc"))
		policy = Policy(jsonString(item["type"], isPath), doc=readDoc(item))
		if "keys" in item:
			if not isinstance(item["keys"], list) or not item["keys"]:
				raise ValueError("keys must be a nonempty array")
			policy.keys = [jsonString(key, isName) for key in item["keys"]]
		if "minted" in item:
			if item["minted"] is not True:
				raise ValueError("minted must be true when present")
			policy.minted = True
		if "from" in item:
			policy.fromNamespace = jsonString(item["from"], isPath)
		if "implicit" in item:
			policy.implicit = jsonString(item["implicit"])
		checkPolicyShape(policy)
		ref.policies.append(policy)
	return ref


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def parseReferential(sources: list[Source]) -> Referential:
	"""Parse files of one referential, resolving file-local type aliases without loading a registry."""
	diag = Diagnostics()
	ref = Referential("")
	if not sources:
		diag.error("header", "A referential requires a source file")
	for source in sources:
		if "\r" in source.text:
			diag.error("lexical", "Referentials require LF line endings", Loc(source.name, 0))
		lines = sourceLines(source)
		if not lines or lines[0].indent or not (match := re.fullmatch(r"@referential\s+(\S+)(.*)", lines[0].text)) or not isPath(match[1]):
			diag.error("header", "@referential must come first and name a namespace", Loc(source.name, 1))
			continue
		namespace = match[1]
		header = dict(parseArguments(match[2], lines[0].loc, diag))
		if set(header) - {"rev"}:
			diag.error("header", "Only rev is allowed on @referential", lines[0].loc)
		if not ref.namespace:
			ref.namespace, ref.header, ref.loc = namespace, header, lines[0].loc
		elif ref.namespace != namespace or ref.header != header:
			diag.error("header", "Referential files must share namespace and revision", lines[0].loc)
		uses: dict[str, str] = {}
		for line in lines[1:]:
			try:
				if line.indent or line.tabs:
					raise ValueError("Referential directives and policies start in column zero")
				body, doc = splitDoc(line.text)
				if match := re.fullmatch(r"@use\s+(\S+)\s+as\s+(\S+)", body):
					path, alias = match.groups()
					if not isPath(path) or not isName(alias) or doc is not None or alias in uses or alias in ref.uses and ref.uses[alias] != path:
						raise ValueError("Invalid or conflicting referential alias")
					uses[alias] = ref.uses[alias] = path
					continue
				parts = body.split()
				if not parts:
					raise ValueError("Missing policy type")
				policy = Policy(qualifyPath(parts[0], namespace, uses), doc=doc, loc=line.loc)
				seen: set[str] = set()
				for part in parts[1:]:
					key, separator, value = part.partition("=")
					if key in seen:
						raise ValueError(f"Duplicate policy option '{key}'")
					seen.add(key)
					if key == "minted" and not separator:
						policy.minted = True
					elif key == "key" and separator and value:
						policy.keys = value.split(",")
					elif key == "from" and separator and isPath(value):
						policy.fromNamespace = value
					elif key == "implicit" and separator and value:
						policy.implicit = value
					else:
						raise ValueError(f"Invalid policy option '{part}'")
				checkPolicyShape(policy)
				ref.policies.append(policy)
			except ValueError as error:
				diag.error("policy", str(error), line.loc)
	ref.diagnostics = diag.check()
	return ref


__all__ = ["parseReferential", "checkPolicyShape", "readReferentialJson"]

# EOF
