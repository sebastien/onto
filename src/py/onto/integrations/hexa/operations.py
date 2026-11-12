"""Module: integrations.hexa.operations — `HexaBindingOperator`, `HexaMappingOperator` and their functional forms (spec-06)."""

from __future__ import annotations

from typing import Any

from hexa.shapes import encode

from ...binding.model import Binding
from ...binding.operations import bindingFromJson
from ...formats.model import FormatChange, Formats
from ...formats.operations import formatsUpdate
from ...functions.model import FunctionLibrary
from ...inventory.model import Inventory
from ...observations.model import Observations
from ...observations.operations import observationsFromJson
from ...ontology.model import Model, Ontology
from .compiler import BindingCompiler
from .model import BindingProgram, BindingReport, ReportGap, ScopeProgram, StageNamespace
from .stages import bindingStages

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def reportGaps(items: list[dict]) -> list[ReportGap]:
	return [ReportGap(item["target"], item["reason"], item.get("src"), item.get("location"), item.get("handle"), item.get("origin")) for item in items]


def programEncoding(program: Any) -> dict[str, Any]:
	"""The hexa encodings of a program's selectors, shapes and templates: equal inputs compile to equal encodings."""
	return {scope.name: {"selector": scope.selector, "shape": encode(scope.shape), "template": encode(scope.template), "outer": [item.name for item in scope.outer]}
		for scope in program.scopes}


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class HexaBindingOperator:
	"""Compile and interpret bindings over one source ontology, in `strict` or `lenient` mode."""

	def __init__(self, ontology: Ontology, mode: str = "strict", libraries: list[FunctionLibrary] | None = None,
		implementations: dict | None = None, ontologies: list[Ontology] | None = None):
		if mode not in ("strict", "lenient"):
			raise ValueError(f"Unknown mode '{mode}'")
		self.ontology = ontology
		self.mode = mode
		self.libraries = list(libraries or [])
		self.implementations = dict(implementations or {})
		self.ontologies = list(ontologies or [])

	def compile(self, binding: Binding | dict, formats: Formats | None = None, inventory: Inventory | None = None) -> BindingProgram:
		"""Compile `binding` (model or JSON form); pure: it never reads documents."""
		if isinstance(binding, dict):
			binding = bindingFromJson(self.ontology, binding, libraries=self.libraries, ontologies=self.ontologies)
		compiler = BindingCompiler(self.ontology, binding, formats, self.libraries, self.implementations, self.ontologies)
		scopes = []
		for item in compiler.compile():
			template = item.template()
			scopes.append(ScopeProgram(item.name, item.scope.type, item.selector(), item.shape(), template, tuple(item.outer), item.levels()))
		program = BindingProgram(self.ontology, binding, self.mode, dict(compiler.slots), {scope.name: scope.shape for scope in scopes},
			{scope.name: scope.template for scope in scopes}, {scope.name: scope.selector for scope in scopes}, sorted(compiler.used),
			StageNamespace({}), scopes, formats, inventory, Model(self.ontology))
		program.stages = StageNamespace(bindingStages(program))
		return program

	def result(self, program: BindingProgram, result: dict) -> tuple[Observations, BindingReport]:
		"""The validated observations log of a `BindingRead` result and its report; never source values."""
		value = result["value"] if "ledger" in result else result
		log = observationsFromJson(self.ontology, value["log"], mode=program.mode)
		report = BindingReport(gaps=reportGaps(value["gaps"]), formats=value["formats"], fields=value.get("fields"), stale=value["stale"])
		return log, report

	def formatsUpdate(self, previous: Formats | None, report: BindingReport) -> tuple[Formats, list[FormatChange]]:
		"""Fold a run's format tallies into the formats file; changes of chosen format are listed."""
		return formatsUpdate(previous, report.formats)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def bindingCompile(ontology: Ontology, binding: Binding | dict, formats: Formats | None = None, inventory: Inventory | None = None,
	mode: str = "strict", libraries: list[FunctionLibrary] | None = None, implementations: dict | None = None) -> BindingProgram:
	"""Functional form of `HexaBindingOperator(ontology, mode).compile(...)`."""
	return HexaBindingOperator(ontology, mode, libraries, implementations).compile(binding, formats, inventory)


def bindingResult(ontology: Ontology, program: BindingProgram, result: dict) -> tuple[Observations, BindingReport]:
	"""Functional form of `HexaBindingOperator(ontology, program.mode).result(...)`."""
	return HexaBindingOperator(ontology, program.mode).result(program, result)


def bindingFormatsUpdate(previous: Formats | None, report: BindingReport) -> tuple[Formats, list[FormatChange]]:
	"""Functional form of `formatsUpdate`."""
	return formatsUpdate(previous, report.formats)


__all__ = ["HexaBindingOperator", "bindingCompile", "bindingResult", "bindingFormatsUpdate", "programEncoding"]

# EOF
