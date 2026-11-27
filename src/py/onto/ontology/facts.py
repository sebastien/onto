"""Module: ontology.facts — the model facts runtimes consult, as JSON: view bundles (spec-06) and store bundles (spec-08)."""

from __future__ import annotations

from ..text import annotation, lastSegment
from .model import Attr, Model, ResolvedType, TypeExpr, isAssociation, isSymmetric

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


class ValidationFacts:
	"""What spec-02's strict validation adds to the model facts (spec-08 "Store bundle"): vocabularies, once each, and per
	attribute its cardinality, value type and exclusive group."""

	def __init__(self, model: Model):
		self.model = model
		self.vocabs: dict[str, dict] = {}

	def vocab(self, resolved: ResolvedType, inline: str = "") -> str:
		"""The key of a vocabulary's entry, its path or for an inline one its attribute's (`inline`); a hierarchical use,
		whose values include their ancestors, is a variant."""
		key = (resolved.path or inline) + ("~hierarchical" if resolved.hierarchical else "")
		self.vocabs.setdefault(key, {"values": list(resolved.values or []), "open": resolved.open})
		return key

	def type(self, resolved: ResolvedType, inline: str = "") -> dict:
		"""A value type: a builtin, a vocabulary by key, an entity or relation, a structure, or a range of one of these."""
		if resolved.kind == "vocab":
			return {"kind": "vocab", **({"path": resolved.path} if resolved.path else {}), "vocab": self.vocab(resolved, inline),
				**({"ordered": True} if resolved.ordered else {}), **({"hierarchical": True} if resolved.hierarchical else {})}
		if resolved.kind == "range":
			return {"kind": "range", **({"element": self.type(resolved.element, inline)} if resolved.element is not None else {})}
		if resolved.builtin:
			return {"kind": "builtin", "builtin": resolved.builtin}
		return {"kind": resolved.kind, **({"path": resolved.path} if resolved.path else {})}

	def attr(self, owner: str, attr: Attr) -> dict:
		resolved = self.model.resolveType(attr.type, attr.ann)
		vocabs = {name: self.vocab(self.model.resolveType(TypeExpr(path=path))) for name, path in resolved.qualifierVocabularies.items()}
		return {"card": attr.card or self.model.defaultCard, "type": self.type(resolved, f"{owner}.{attr.name}"),
			**({"qualifierVocabs": vocabs} if vocabs else {}), **({"one": group} if (group := annotation(attr.ann, "one")) else {})}


def modelJson(model: Model, validation: bool = False) -> dict:
	"""The ontology facts runtimes consult: declaration kinds and bases, attributes, facets, structures and binary relations.
	With `validation`, also what spec-02's strict validation consults, as store bundles carry (spec-08)."""
	types, relations, facets, structs = {}, {}, {}, {}
	checks = ValidationFacts(model) if validation else None
	attrs = lambda owner, items: {attr.name: attrJson(model, attr) | (checks.attr(owner, attr) if checks else {}) for attr in items}
	event = lambda decl: {"event": True} if checks and annotation(decl.ann, "kind") == "event" else {}
	participants = lambda decl: [{"role": item.role, "type": item.type, **({"card": item.card} if item.card else {})} for item in decl.participants]
	for decl in model.ontology.decls:
		if decl.kind == "entity" or isAssociation(decl):
			types[decl.path] = {"kind": decl.kind, **({"base": decl.base} if decl.base else {}),
				**({"association": True, "roles": participants(decl)} if isAssociation(decl) else {}), "attrs": attrs(decl.path, decl.attrs), **event(decl)}
		elif decl.kind == "relation" and decl.arrow:
			relations[decl.path] = {"verb": decl.arrow.verb, **({"inverse": decl.arrow.inverse} if decl.arrow.inverse else {}),
				"participants": participants(decl), **({"symmetric": True} if isSymmetric(decl) else {}), "attrs": attrs(decl.path, decl.attrs), **event(decl)}
		elif decl.kind == "facet" and decl.subject:
			when = annotation(decl.ann, "when") if checks else None
			attr, _, value = when.partition(":") if isinstance(when, str) else ("", "", "")
			facets.setdefault(decl.subject, []).append({"name": lastSegment(decl.path), "path": decl.path,
				**({"ctx": annotation(decl.ann, "ctx")} if annotation(decl.ann, "ctx") else {}), "attrs": attrs(decl.path, decl.attrs),
				**({"when": {"attr": attr, "value": value}} if attr else {})})
		elif decl.kind == "type" and decl.fields is not None:
			key = next((field.name for field in decl.fields if annotation(field.ann, "key")), None) if checks else None
			structs[decl.path] = {"fields": attrs(decl.path, decl.fields), **({"key": key} if key else {})}
	result = {"namespace": model.ontology.namespace, "uses": [list(pair) for pair in model.ontology.uses], "defaultCard": model.defaultCard,
		"types": types, "relations": relations, "facets": facets, "structs": structs}
	if checks:
		result |= {**({"rev": rev} if (rev := dict(model.ontology.header).get("rev")) else {}), "vocabs": dict(sorted(checks.vocabs.items()))}
	return result


__all__ = ["NUMERIC", "ValidationFacts", "attrJson", "modelJson"]

# EOF
