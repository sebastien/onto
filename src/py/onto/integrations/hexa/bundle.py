"""Module: integrations.hexa.bundle — compiled programs, model facts and views as JSON, for runtimes that do not compile.

A bundle carries what executing a program needs and nothing a compiler needs: hexa encodings of
selectors, shapes, templates and slots, plus the few ontology facts claim emission and retrieval
consult. The JavaScript runtime (`src/js/onto/`) loads it; Python remains the compiler and the
reference for conformance.
"""

from __future__ import annotations

import json
import re
from typing import Any as AnyValue

from hexa.shape import SLOTS, Slot, children as shapeChildren, compileShape, references as shapeSlots
from hexa.shapes import encode
from hexa.template import compileTemplate

from ...binding.model import bindingBy
from ...functions.operations import resolveSignature
from ...ontology.facts import NUMERIC, attrJson, modelJson
from ...ontology.model import Model, ResolvedType, TypeExpr, ViewInput, isSetValued
from ...ontology.rooted import Field, Hop, RootedView
from ...text import annotation
from .catalogue import ListDirection, ListFilter, ListKeys, ListRead, ListSort
from .compiler import BindingCompiler, MappingCompiler
from .requests import requestTemplate

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


BUNDLE_FORMAT = "onto.view-bundle/2"
RE_SELECTOR_SLOT = re.compile(r":\$([A-Za-z][A-Za-z0-9.]*)")
# Standard slots every hexa runtime declares itself.
STANDARD_SLOTS = ("Location", "Origin")


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def slotsJson(slots: set[Slot]) -> dict[str, dict]:
	"""The encoded shape of each slot; `global` slots are declared process-wide, as Python declares them."""
	result = {}
	for item in sorted(slots, key=lambda slot: slot.name):
		if item.name in STANDARD_SLOTS:
			continue
		if item.name in result:
			raise ValueError(f"two slots named {item.name}")
		result[item.name] = {"shape": encode(item.shape), **({"global": True} if SLOTS.get(item.name) is item else {})}
	return result


def scopeSlots(scope: AnyValue) -> set[Slot]:
	"""The slots a compiled scope captures, expands, receives from enclosing scopes or names in its selector."""
	found = shapeSlots(compileShape(scope.shape)) | shapeSlots(compileTemplate(scope.template)) | set(scope.outer)
	for level in getattr(scope, "levels", None) or ():
		found.update(SLOTS[name] for name in RE_SELECTOR_SLOT.findall(level))
	return found


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def typeJson(resolved: ResolvedType, collection: bool = False) -> dict:
	"""A resolved signature type, as `types.js` checks values against it."""
	result = {"kind": resolved.kind, **{key: value for key in ("builtin", "path") if (value := getattr(resolved, key))}}
	if resolved.kind == "vocab":
		result |= {"values": list(resolved.values or []), "open": resolved.open, "hierarchical": resolved.hierarchical, "ordered": resolved.ordered}
	if resolved.qualifiers.get("unit"):
		result["unit"] = resolved.qualifiers["unit"]
	if resolved.element is not None:
		result["element"] = typeJson(resolved.element)
	if resolved.builtin in NUMERIC:
		result["numeric"] = True
	if resolved.kind == "range" and resolved.element is not None and resolved.element.builtin in NUMERIC:
		result["numericRange"] = True
	return result | ({"collection": True} if collection else {})


def viaCodecs(shape: AnyValue, found: list) -> list:
	"""The codecs a compiled shape converts captures with."""
	if shape.kind == "via":
		found.append(shape.args[1])
	for child in shapeChildren(shape):
		viaCodecs(child, found)
	return found


def bindingProgramJson(operator: AnyValue, program: AnyValue) -> dict:
	"""A compiled `BindingProgram` for reading: its scopes in run order, the slots they reference and the functions they call."""
	binding, scopes, slots = program.binding, [], set()
	evaluator = BindingCompiler(operator.ontology, binding, program.formats, operator.libraries, operator.implementations, operator.ontologies).calls.evaluator
	names = {name.replace("/", "."): name for name in evaluator.functions}
	codecs, used = {}, set(program.vocabulary)
	for scope in program.scopes:
		shape, template = encode(scope.shape), encode(scope.template)
		slots |= scopeSlots(scope)
		scopes.append({"name": scope.name, "type": scope.type, "levels": list(scope.levels), "picks": list(scope.picks or []),
			"outer": [item.name for item in scope.outer], "shape": shape, "template": template, **({"optional": True} if scope.optional else {})})
		# A declared function with an inverse converts captures as a program-local codec (`Calls.codec`).
		for codec in viaCodecs(compileShape(scope.shape), []):
			if (name := names.get(codec.name)) is None:
				continue
			namespace = name.rpartition("/")[0]
			inverse = str(annotation(evaluator.functions[name].ann, "inverse"))
			inverse = f"{namespace}/{inverse}" if namespace else inverse
			entry = {"function": name, "inverse": inverse, "canonical": encode(codec.canonical)}
			if codecs.setdefault(codec.name, entry) != entry:
				raise ValueError(f"{codec.name}: one function decodes two canonical shapes in one program")
			used.add(inverse.replace("/", "."))
	functions, maps = functionsJson(evaluator, used)
	return {"name": binding.header.get("name"), "ontology": binding.ontology, "scope": str(binding.header.get("scope", binding.ontology)),
		"by": bindingBy(binding), "mode": program.mode, "csv": binding.header.get("format") == "csv",
		"slots": slotsJson(slots), "functions": functions, "maps": maps, "codecs": codecs, "scopes": scopes}


def lookupJson(lookup: AnyValue) -> dict:
	"""A lookup step's declaration: the looked-up type and its compared attributes, `[attr, owner attribute]`."""
	return {"type": lookup.type, "lines": [[line.attr, line.source] for line in lookup.lines]}


def reachJson(reach: dict) -> dict:
	"""A scope's reach: `{key: {segment, children}}`, with the segment facts unfolding uses."""
	return {key: {"segment": {"key": node["segment"].key, "kind": node["segment"].kind, "owner": node["segment"].owner, "multi": node["segment"].multi,
		**({"next": node["segment"].next} if node["segment"].next else {}), **({"context": node["segment"].context} if node["segment"].context else {}),
		**({"lookup": lookupJson(node["segment"].lookup)} if node["segment"].lookup else {})},
		"children": reachJson(node["children"])} for key, node in reach.items()}


def lineJson(info: AnyValue, target: str, model: Model) -> dict:
	"""A compiled mapping line, with the vocabularies its qualifiers must take values from."""
	result = {"section": info.section, "key": info.key, "inputs": info.inputs, "source": info.source, "contextual": info.contextual,
		"qualifiers": list(info.qualifiers), **{key: value for key in ("also", "contextType", "slot", "when", "unless") if (value := getattr(info, key))}}
	if info.qualifiers:
		attr = model.lookup(target, info.key)
		resolved = model.resolveType(attr.type, attr.ann)
		checks = {}
		for key in info.qualifiers:
			vocabulary = resolved.qualifierVocabularies.get(key)
			kind = model.resolveType(TypeExpr(path=vocabulary)) if vocabulary else None
			checks[key] = {"open": kind.open, "values": list(kind.values or [])} if kind is not None else None
		result["qualifierChecks"] = checks
	return result


def functionsJson(evaluator: AnyValue, used: set[str]) -> tuple[dict, dict]:
	"""The declared functions and value maps a program's transforms call, with their resolved signatures."""
	functions, maps = {}, {}
	for name, function in evaluator.functions.items():
		if name.replace("/", ".") in used:
			functions[name] = {"args": [typeJson(resolveSignature(evaluator.model, item), item.collection) for item in function.args],
				"result": typeJson(resolveSignature(evaluator.model, function.result), function.result.collection),
				**({"nulls": True} if annotation(function.ann, "nulls") else {})}
	for name, decl in evaluator.maps.items():
		if name.replace("/", ".") in used:
			# An excluded value's line is `[value, null]`; a set-valued map gives sets (spec-01 Maps).
			maps[name] = {"from": typeJson(evaluator.model.resolveType(TypeExpr(path=decl.mapFrom))),
				"to": typeJson(evaluator.mapTargetModel(name).resolveType(TypeExpr(path=decl.mapTo))),
				"lines": [[line.fromValue, line.toValue] for line in decl.mapLines], **({"setValued": True} if isSetValued(decl) else {})}
	return functions, maps


def mappingProgramJson(mapper: AnyValue, program: AnyValue, libraries: list | None = None) -> dict:
	"""A compiled `MappingProgram` for reading: its scope plans, the slots they reference and the functions they call.

	`libraries`: those `program` was compiled with, when not the mapper's own."""
	mapping, slots, plans = program.mapping, set(), []
	target = program.targetModel
	for plan in program.plans:
		scope = plan.program
		slots |= scopeSlots(scope) | shapeSlots(compileTemplate(plan.handleTemplate))
		plans.append({"name": plan.name, "source": plan.source, "target": plan.target, "reach": reachJson(plan.reach),
			"lines": [lineJson(info, plan.target, target) for info in plan.lines], "when": plan.when,
			"shape": encode(scope.shape), "template": encode(scope.template), "handleTemplate": encode(plan.handleTemplate),
			"segmentKeys": [[list(steps), keys] for steps, keys in plan.segmentKeys.items()],
			"contextOverride": plan.contextOverride, "contextualScope": plan.contextualScope, "contextInputs": plan.contextInputs,
			"readsSelf": plan.readsSelf, "presence": plan.presence, "presenceInputs": plan.presenceInputs, "update": plan.update,
			"targetInputs": plan.targetInputs, "sourceRefs": {key: [typePath, keys] for key, (typePath, keys) in plan.sourceRefs.items()},
			**({"scopeName": plan.scopeName} if plan.scopeName else {})})
	compiler = MappingCompiler(mapper.fromOntology, mapper.toOntology, mapping, mapper.referential, mapper.libraries if libraries is None else libraries,
		mapper.implementations, mapper.ontologies)
	functions, maps = functionsJson(compiler.calls.evaluator, set(program.vocabulary))
	return {"fromNamespace": mapping.fromNamespace, "toNamespace": mapping.toNamespace, "scope": str(mapping.header.get("scope", mapping.toNamespace)),
		"by": f"map:{mapping.fromNamespace}->{mapping.toNamespace}", "mode": program.mode, "slots": slotsJson(slots),
		"functions": functions, "maps": maps, "plans": plans}


def inputJson(item: ViewInput) -> dict:
	return {"name": item.name, "path": item.path, "attr": item.attr, "key": item.key, **({"many": True} if item.many else {})}


def listParameterJson(item) -> dict:
	"""A list read's parameter (spec-09 "List reads"), by its kind."""
	if isinstance(item, ListFilter):
		return {"kind": "filter", "attr": item.attr, "operator": item.operator}
	if isinstance(item, ListKeys):
		return {"kind": "keys", "mode": item.mode, "limit": item.limit}
	if isinstance(item, ListSort):
		return {"kind": "sort", "spellings": dict(item.spellings), **({"default": item.default} if item.default is not None else {})}
	if isinstance(item, ListDirection):
		return {"kind": "direction", "asc": item.asc, "desc": item.desc}
	return {"kind": "page", "part": item.part, **({"first": item.first} if item.part == "number" else {})}


def fieldJson(item: Field) -> dict:
	return {"owner": item.owner, "member": item.member, "path": item.path,
		**{key: value for key in ("other", "relation") if (value := getattr(item, key))}, **({"roles": list(item.roles)} if item.roles else {}),
		**({"context": list(item.association)} if item.association else {}), **({"ctx": item.contextType} if item.contextType else {})}


def hopJson(hop: Hop) -> dict:
	return {"parent": hop.parent, "population": hop.population, "field": fieldJson(hop.field), **({"reverse": True} if hop.reverse else {}),
		**({"test": hop.test} if hop.test is not None else {}), **({"proves": hop.proves} if hop.proves else {}),
		**({"ctx": hop.contextPopulation} if hop.contextPopulation else {})}


def viewJson(operator: AnyValue, name: str, view: RootedView) -> dict:
	"""A rooted view resolved against both models, with the reads that supply each obligation."""
	decl = operator.targetModel.get(f"{operator.target.namespace}/{name}")
	return {"input": inputJson(view.input), "root": view.root, **({"doc": decl.doc} if decl and decl.doc else {}),
		"sourceModule": operator.sourceModel.moduleOf(view.input.path), "targetModules": list(view.targetModules),
		"rootTarget": operator.rootTargets[name],
		"populations": {alias: {"type": population.type} for alias, population in view.populations.items()},
		"paths": {alias: [hopJson(hop) for hop in path] for alias, path in view.paths.items()},
		"guardedLinks": [[parent, relation, list(roles), alias] for (parent, relation, roles), alias in view.guardedLinks.items()],
		"selections": {key: [item.population, fieldJson(item.field)] for key, item in view.selections.items()},
		"contexts": {key: item.contextPopulation for key, item in view.selections.items() if item.contextPopulation},
		"typeSelections": view.typeSelections, "defaults": view.defaults, **({"pages": dict(view.pages)} if view.pages else {}), "steps": operator.steps[name],
		**{key: value for key, value in (("page", view.page), ("max", view.max)) if value is not None},
		**({"list": operator.listQueries[name]} if name in getattr(operator, "listQueries", {}) else {}),
		"matches": operator.correspondences(view, operator.steps[name])}


def viewBundle(operator: AnyValue) -> dict:
	"""Everything a runtime needs to plan, read, map and project the views of a `HexaViewOperator`, without compiling."""
	programs, ids, reads = {}, {}, {}
	for step, read in operator.reads.items():
		keys = []
		for binding in read.bindings:
			program = bindingProgramJson(operator.binder, operator.binder.compile(binding))
			text = json.dumps(program, sort_keys=True)
			if text not in ids:
				ids[text] = f"b{len(ids) + 1}"
				programs[ids[text]] = program
			keys.append(ids[text])
		reads[step] = {"input": inputJson(read.input), **({"provides": inputJson(read.provides)} if read.provides else {}), "bindings": keys,
			"bindingNames": [binding.header.get("name", binding.ontology) for binding in read.bindings],
			**({"request": requestTemplate(read)} if read.request is not None else {}), **({"source": read.source} if read.source is not None else {}),
			**({"list": {"rows": read.rows, **({"total": read.total} if read.total else {}), **({"absent": read.absent} if read.absent != "omit" else {}),
				"parameters": {key: listParameterJson(item) for key, item in read.parameters.items()}}} if isinstance(read, ListRead) else {})}
	return {"format": BUNDLE_FORMAT, "source": modelJson(operator.sourceModel), "target": modelJson(operator.targetModel),
		"bindings": programs, "reads": reads, "mapping": mappingProgramJson(operator.mapper, operator.mapProgram),
		"keyTypes": {key: typeJson(item) for key, item in operator.keyTypes.items()},
		"inputTargets": {key: sorted(items) for key, items in operator.inputTargets.items()},
		"views": {name: viewJson(operator, name, view) for name, view in operator.views.items()}}


__all__ = ["BUNDLE_FORMAT", "bindingProgramJson", "mappingProgramJson", "modelJson", "viewBundle"]

# EOF
