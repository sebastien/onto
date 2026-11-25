"""Module: integrations.hexa.operations — `HexaBindingOperator`, `HexaMappingOperator` and their functional forms (spec-06)."""

from __future__ import annotations

from typing import Any

from hexa.shapes import encode

from ...binding.coverage import absolute, documentPaths
from ...binding.model import Binding, bindingBy
from ...binding.operations import bindingFromJson
from ...conditions import conditionPaths
from ...expressions import printExpression
from ...formats.model import FormatChange, Formats
from ...formats.operations import formatsUpdate
from ...functions.model import FunctionLibrary
from ...inventory.model import Inventory
from ...mapping.model import Mapping
from ...mapping.operations import mappingFromJson
from ...observations.model import Observations
from ...observations.operations import observationsFromJson
from ...ontology.model import Model, Ontology
from .compiler import BindingCompiler, MappingCompiler
from .model import BindingProgram, BindingReport, MappingProgram, MappingReport, Outcome, ReportGap, ScopeProgram, StageNamespace, WriteReport
from .runs import RunSettings, approveLog, runStages
from .stages import bindingStages
from .unfold import MappingScopePlan, mappingStages
from .writing import BindingWriteProgram, WriteCompiler, Writer, writeStages

# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def reportGaps(items: list[dict]) -> list[ReportGap]:
	return [ReportGap(item["target"], item["reason"], item.get("src"), item.get("location"), item.get("handle"), item.get("origin")) for item in items]


def reportOf(data: dict, factory: type = BindingReport) -> BindingReport:
	"""A report dataclass from a run's JSON report."""
	report = factory(gaps=reportGaps(data.get("gaps", [])), formats=data.get("formats", {}), fields=data.get("fields"), stale=data.get("stale", []))
	for key in ("held", "confirmed", "lapsed", "safeguards", "formatChanges", "lossy", "mixed", "correspondence"):
		if key in data and hasattr(report, key):
			setattr(report, key, data[key])
	return report


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
			scopes.append(ScopeProgram(item.name, item.scope.type, item.selector(), item.shape(), template, tuple(item.outer), item.levels(), picks=item.levelPicks()))
		program = BindingProgram(self.ontology, binding, self.mode, dict(compiler.slots), {scope.name: scope.shape for scope in scopes},
			{scope.name: scope.template for scope in scopes}, {scope.name: scope.selector for scope in scopes}, sorted(compiler.used),
			StageNamespace({}), scopes, formats, inventory, Model(self.ontology))
		# Fields whose writing formats a run learns: those body lines read, except `$format` dates (learned from their patterns).
		program.writeFields = {printExpression({"path": path}, binding=True) for scope in binding.scopes for line in scope.lines if line.expr is not None
			and not ("call" in line.expr and {"meta": "format"} in line.expr["args"])
			for steps in documentPaths(line.expr) if (path := absolute(scope.path["path"], steps, binding.scopes))}
		members = bindingStages(program)
		header = binding.header
		settings = RunSettings(self.ontology, bindingBy(binding), self.mode, str(header.get("complete", "document")),
			str(header.get("retract", "20%")), int(header.get("confirm", 1)), formats)
		members |= runStages(settings, members["BindingRead"], "Binding")
		program.stages = StageNamespace(members)
		return program

	def result(self, program: BindingProgram, result: dict) -> tuple[Observations, BindingReport]:
		"""The validated observations log of a `BindingRead` result and its report; never source values."""
		value = result["value"] if "ledger" in result else result
		log = observationsFromJson(self.ontology, value["log"], mode=program.mode)
		return log, reportOf(value)

	def compileWrite(self, binding: Binding | dict, inventory: Inventory | None = None, formats: Formats | None = None) -> BindingWriteProgram:
		"""Compile `binding` for writing: `stages.BindingWrite` takes `{src, state}` and returns `{documents, report}`."""
		reading = self.compile(binding, formats=formats, inventory=inventory)
		compiler = BindingCompiler(self.ontology, reading.binding, formats, self.libraries, self.implementations, self.ontologies)
		writer = WriteCompiler(compiler, inventory, formats)
		scopes = writer.compile()
		program = BindingWriteProgram(reading.binding, scopes, writer.lossy, StageNamespace({}), reading)
		program.stages = StageNamespace(writeStages(program, Writer(program, Model(self.ontology), inventory.types() if inventory else {})))
		return program

	def written(self, result: dict) -> tuple[list[dict], WriteReport]:
		"""The documents of a `BindingWrite` result and its report."""
		report = result["report"]
		return result["documents"], WriteReport(report["lossy"], reportGaps([{**gap, "target": str(gap["target"])} for gap in report["gaps"]]),
			report["parentless"], report["originals"], report["formatted"])

	def outcome(self, program: BindingProgram, result: dict) -> Outcome:
		"""The `Outcome` of a `BindingRun`; its log is validated, as any output of the integration."""
		observationsFromJson(self.ontology, result["log"], mode=program.mode)
		return Outcome(result["status"], result["log"], result["held"], result["lapsed"], reportOf(result["report"]))

	def approve(self, outcome: Outcome, token: str) -> Observations:
		"""The log of an outcome approved by a person: a pending run's log, and held retractions with `approved=<token>`."""
		data = approveLog({"status": outcome.status, "log": outcome.log, "held": outcome.held}, token)
		return observationsFromJson(self.ontology, data, mode=self.mode)

	def formatsUpdate(self, previous: Formats | None, report: BindingReport) -> tuple[Formats, list[FormatChange]]:
		"""Fold a run's format tallies into the formats file; changes of chosen format are listed."""
		return formatsUpdate(previous, report.formats)


class HexaMappingOperator:
	"""Compile and interpret mappings between two ontologies, with an optional referential for target handles."""

	def __init__(self, fromOntology: Ontology, toOntology: Ontology, referential: Any = None, mode: str = "strict",
		libraries: list[FunctionLibrary] | None = None, implementations: dict | None = None, ontologies: list[Ontology] | None = None):
		if mode not in ("strict", "lenient"):
			raise ValueError(f"Unknown mode '{mode}'")
		self.fromOntology = fromOntology
		self.toOntology = toOntology
		self.referential = referential
		self.mode = mode
		self.libraries = list(libraries or [])
		self.implementations = dict(implementations or {})
		self.ontologies = list(ontologies or [])

	def compile(self, mapping: Mapping | dict, libraries: list[FunctionLibrary] | None = None) -> MappingProgram:
		"""Compile `mapping` (model or JSON form) with the function `libraries` it uses; pure."""
		libraries = list(libraries) if libraries is not None else self.libraries
		if isinstance(mapping, dict):
			mapping = mappingFromJson(self.fromOntology, self.toOntology, mapping, libraries=libraries, ontologies=self.ontologies,
				referentials=[self.referential] if self.referential is not None else None)
		compiler = MappingCompiler(self.fromOntology, self.toOntology, mapping, self.referential, libraries, self.implementations, self.ontologies)
		plans: list[MappingScopePlan] = []
		for item in compiler.compile():
			template = item.template()
			handleTemplate = item.handleTemplate()
			scope = ScopeProgram(item.name, item.scope.target, "", item.shape(), template, source=item.scope.source)
			whenPaths = conditionPaths(item.when)
			paths = [steps for info in item.lines for steps in info.inputs] + whenPaths
			scopePaths = item.paths(item.scope.ctx) + item.paths(item.scope.valid) + item.paths(item.scope.present) + item.paths(item.scope.into) + whenPaths
			contextualScope = any(segment.context for path in scopePaths for segment in item.segments(path))
			if contextualScope:
				for info in item.lines:
					info.contextual = True
			plans.append(MappingScopePlan(item.name, item.scope.source, item.scope.target, item.reach(), item.lines, item.when, handleTemplate, scope,
				{(info.section, info.record): info for info in item.lines}, {tuple(steps): [segment.key for segment in item.segments(steps)] for steps in paths},
				item.scope.ctx is not None, contextualScope,
				[[segment.key for segment in item.segments(path)] for path in item.paths(item.scope.ctx)], "@self" in item.roots,
				item.scope.present is not None, [[segment.key for segment in item.segments(path)] for path in item.paths(item.scope.present)],
				item.scope.into is not None, [[segment.key for segment in item.segments(path)] for path in item.paths(item.scope.into)],
				{key: (typePath, [segment.key for segment in item.segments(steps)]) for key, (typePath, steps) in item.sourceRefs.items()}))
		scopes = [plan.program for plan in plans]
		program = MappingProgram(self.fromOntology, self.toOntology, mapping, self.mode, dict(compiler.slots), {scope.name: scope.shape for scope in scopes},
			{scope.name: scope.template for scope in scopes}, sorted(compiler.used), StageNamespace({}), scopes,
			{plan.name: plan.reach for plan in plans}, Model(self.fromOntology), Model(self.toOntology), plans)
		members = mappingStages(program, plans, self.mode)
		header = mapping.header
		settings = RunSettings(self.toOntology, f"map:{mapping.fromNamespace}->{mapping.toNamespace}", self.mode, "document",
			str(header.get("retract", "20%")), int(header.get("confirm", 1)))
		members |= runStages(settings, members["MappingRead"], "Mapping")
		program.stages = StageNamespace(members)
		return program

	def result(self, program: MappingProgram, result: dict) -> tuple[Observations, MappingReport]:
		"""The validated output log of a `MappingRead` result and its report."""
		value = result["value"] if "ledger" in result else result
		log = observationsFromJson(self.toOntology, value["log"], mode=program.mode)
		return log, reportOf(value, MappingReport)

	def outcome(self, program: MappingProgram, result: dict) -> Outcome:
		"""The `Outcome` of a `MappingRun`."""
		observationsFromJson(self.toOntology, result["log"], mode=program.mode)
		return Outcome(result["status"], result["log"], result["held"], result["lapsed"], reportOf(result["report"], MappingReport))

	def approve(self, outcome: Outcome, token: str) -> Observations:
		"""The log of an outcome approved by a person, as for bindings."""
		data = approveLog({"status": outcome.status, "log": outcome.log, "held": outcome.held}, token)
		return observationsFromJson(self.toOntology, data, mode=self.mode)


# -----------------------------------------------------------------------------
#
# HIGH-LEVEL API
#
# -----------------------------------------------------------------------------


def mappingCompile(fromOntology: Ontology, toOntology: Ontology, mapping: Mapping | dict, referential: Any = None, mode: str = "strict",
	libraries: list[FunctionLibrary] | None = None, implementations: dict | None = None) -> MappingProgram:
	"""Functional form of `HexaMappingOperator(...).compile(mapping)`."""
	return HexaMappingOperator(fromOntology, toOntology, referential, mode, libraries, implementations).compile(mapping)


def mappingResult(fromOntology: Ontology, toOntology: Ontology, program: MappingProgram, result: dict) -> tuple[Observations, MappingReport]:
	"""Functional form of `HexaMappingOperator(...).result(program, result)`."""
	return HexaMappingOperator(fromOntology, toOntology, mode=program.mode).result(program, result)


def mappingApprove(fromOntology: Ontology, toOntology: Ontology, outcome: Outcome, token: str, mode: str = "strict") -> Observations:
	"""Functional form of `HexaMappingOperator(...).approve(outcome, token)`."""
	return HexaMappingOperator(fromOntology, toOntology, mode=mode).approve(outcome, token)


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


def bindingApprove(ontology: Ontology, outcome: Outcome, token: str, mode: str = "strict") -> Observations:
	"""Functional form of `HexaBindingOperator(ontology, mode).approve(...)`."""
	return HexaBindingOperator(ontology, mode).approve(outcome, token)


__all__ = [
	"HexaBindingOperator", "HexaMappingOperator", "bindingCompile", "bindingResult", "bindingFormatsUpdate", "bindingApprove",
	"mappingCompile", "mappingResult", "mappingApprove", "programEncoding",
]

# EOF
