"""Module: ontology.facts — the model facts runtimes consult, as JSON: view bundles (spec-06) and store bundles (spec-08)."""

from __future__ import annotations

from ..text import annotation, lastSegment
from .model import Attr, Model, isAssociation, isSymmetric

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


# NOTE: Wider than the binding and compiler NUMERIC: value identity compares Durations by number too, as
# `observations.model` does, so the runtime's `valueIdentity` needs them flagged numeric.
NUMERIC = ("Integer", "Number", "Amount", "Percent", "Duration")


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def attrJson(model: Model, attr: Attr) -> dict:
	"""What reconciliation and unfolding consult about an attribute: cardinality, numeric identity, declared qualifiers, structure and target."""
	resolved = model.resolveType(attr.type, attr.ann)
	structure = model.structOf(attr.type)
	element = resolved.element
	return {"multi": (attr.card or model.defaultCard) in ("*", "+"),
		**({"numeric": True} if resolved.builtin in NUMERIC else {}),
		**({"numericRange": True} if resolved.kind == "range" and element is not None and element.builtin in NUMERIC else {}),
		**({"qualifiers": dict(resolved.qualifiers)} if resolved.qualifiers else {}),
		**({"struct": structure.path} if structure is not None else {}),
		**({"ref": resolved.path} if resolved.kind in ("entity", "relation") else {})}


def modelJson(model: Model) -> dict:
	"""The ontology facts runtimes consult: declaration kinds and bases, attributes, facets, structures and binary relations."""
	types, relations, facets, structs = {}, {}, {}, {}
	attrs = lambda items: {attr.name: attrJson(model, attr) for attr in items}
	participants = lambda decl: [{"role": item.role, "type": item.type, **({"card": item.card} if item.card else {})} for item in decl.participants]
	for decl in model.ontology.decls:
		if decl.kind == "entity" or isAssociation(decl):
			types[decl.path] = {"kind": decl.kind, **({"base": decl.base} if decl.base else {}),
				**({"association": True, "roles": participants(decl)} if isAssociation(decl) else {}), "attrs": attrs(decl.attrs)}
		elif decl.kind == "relation" and decl.arrow:
			relations[decl.path] = {"verb": decl.arrow.verb, **({"inverse": decl.arrow.inverse} if decl.arrow.inverse else {}),
				"participants": participants(decl), **({"symmetric": True} if isSymmetric(decl) else {}), "attrs": attrs(decl.attrs)}
		elif decl.kind == "facet" and decl.subject:
			facets.setdefault(decl.subject, []).append({"name": lastSegment(decl.path), "path": decl.path,
				**({"ctx": annotation(decl.ann, "ctx")} if annotation(decl.ann, "ctx") else {}), "attrs": attrs(decl.attrs)})
		elif decl.kind == "type" and decl.fields is not None:
			structs[decl.path] = {"fields": attrs(decl.fields)}
	return {"namespace": model.ontology.namespace, "uses": [list(pair) for pair in model.ontology.uses], "defaultCard": model.defaultCard,
		"types": types, "relations": relations, "facets": facets, "structs": structs}


__all__ = ["NUMERIC", "attrJson", "modelJson"]

# EOF
