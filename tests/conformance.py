"""Module: tests.conformance — record what the test suite runs on hexa, for the JavaScript runtime to replay.

	ONTO_CONFORMANCE=build/conformance.json python -m pytest -p tests.conformance
	bun test tests/js/conformance.test.js

Each `BindingRead` and `MappingRead` run, and each `HexaViewOperator` plan, report and retrieval, becomes a
case: the compiled program (or view bundle), its input, what the host answered (library functions, view
identities and discoveries) and Python's output. A report or retrieval also keeps its hexa journal, which
the JavaScript runtime replays instead of reading: the same effects, in the same strands, must answer it.
The JavaScript runtime must reproduce the output from the rest. Without `ONTO_CONFORMANCE` this plugin does
nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any as AnyValue

import hexa.runtime

# NOTE: `run` is wrapped before anything imports it from hexa.runtime, onto's integration included.
OUTPUT = os.environ.get("ONTO_CONFORMANCE")
ORIGINAL_RUN = hexa.runtime.run
OBJECTS: dict[str, AnyValue] = {}
CASES: list[dict] = []
STAGES: dict[int, tuple] = {}
EXPORTS: dict[int, tuple] = {}
CURRENT = {"test": None}


def dumps(value: AnyValue) -> str:
	"""A lookup key: canonical JSON, as the JavaScript replay spells it (`valueKey`)."""
	return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def store(value: AnyValue) -> str:
	"""Keep a JSON value once, by content; programs, models and inputs repeat across cases.

	Member order is kept: it is significant in programs (template order is claim order) and bundles (catalogue order)."""
	text = json.dumps(value, ensure_ascii=False, default=str)
	key = hashlib.sha256(text.encode()).hexdigest()[:20]
	OBJECTS.setdefault(key, json.loads(text))
	return key


def errorJson(error: BaseException) -> dict:
	from hexa.shapes import Failure
	if isinstance(error, Failure):
		return {"failure": str(error.kind), "code": str(error.code)}
	return {"error": type(error).__name__, "message": str(error), **({"reason": error.reason} if hasattr(error, "reason") else {})}


def policyJson(policy: AnyValue) -> dict | None:
	"""A run policy as data: a retry delay function becomes the delay of each attempt."""
	if not isinstance(policy, dict):
		return None
	result = {key: value for key, value in policy.items() if key != "retry"}
	if isinstance(retry := policy.get("retry"), dict):
		result["retry"] = {key: value for key, value in retry.items() if key != "delay"}
		if callable(retry.get("delay")):
			result["retry"]["delays"] = [retry["delay"](attempt) for attempt in range(1, retry.get("attempts", 1) + 1)]
	return result


def exported(owner: AnyValue, build) -> dict:
	"""Export once per compiled object; an export failure marks its cases unsupported."""
	if id(owner) not in EXPORTS or EXPORTS[id(owner)][0] is not owner:
		try:
			EXPORTS[id(owner)] = (owner, {"key": store(build())})
		except Exception as error:  # noqa: BLE001 — reported as an unsupported case
			EXPORTS[id(owner)] = (owner, {"unsupported": f"{type(error).__name__}: {error}"})
	return EXPORTS[id(owner)][1]


def recordingImplementations(operator: AnyValue) -> None:
	"""Record each library function call, so the JavaScript replay answers as the Python implementation did."""
	table = getattr(operator, "conformanceCalls", None)
	if table is None:
		table = operator.conformanceCalls = {}

	def wrap(name, function):
		def call(*args):
			key = dumps(list(args))
			try:
				value = function(*args)
			except Exception as error:
				table.setdefault(name, {})[key] = {"error": str(error) or type(error).__name__}
				raise
			table.setdefault(name, {})[key] = {"value": value}
			return value
		return call

	operator.implementations = {name: wrap(name, function) for name, function in operator.implementations.items()}


class RecordingAccess:
	"""A view host that records each answer by its arguments; reads are in the journal instead.

	It has the hooks the host has, no more: the operator's defaults stand in for the others."""

	def __init__(self, access: AnyValue):
		self.access = access
		self.calls: dict[str, dict] = {}
		if callable(getattr(access, "fetch", None)):
			self.fetch = access.fetch
		for name in ("rootHandle", "describe", "discover", "check"):
			if callable(getattr(access, name, None)):
				self.calls[name] = {}
				setattr(self, name, getattr(self, "recorded" + name[0].upper() + name[1:]))
		# NOTE: A session's store operations (spec-09) pass through unrecorded: only its system's plans are replayed until
		# the JavaScript runtime runs sessions.
		for name in ("storeRead", "storeAppend"):
			if callable(getattr(access, name, None)):
				setattr(self, name, getattr(access, name))

	def record(self, kind: str, key: list, call, encode=lambda value: value):
		try:
			value = call()
		except Exception as error:
			self.calls[kind][dumps(key)] = {"error": errorJson(error)}
			raise
		self.calls[kind][dumps(key)] = {"value": encode(value)}
		return value

	def recordedRootHandle(self, item, value, target):
		return self.record("rootHandle", [item.key, value, target], lambda: self.access.rootHandle(item, value, target))

	def recordedDescribe(self, step, value):
		return self.record("describe", [step, value], lambda: self.access.describe(step, value))

	def recordedDiscover(self, state, provides):
		digest = hashlib.sha256(dumps(state).encode()).hexdigest()
		return self.record("discover", [provides.key if provides else None, digest], lambda: self.access.discover(state, provides), list)

	def recordedCheck(self, step, value, response):
		digest = hashlib.sha256(dumps(response).encode()).hexdigest()
		return self.record("check", [step, value, digest], lambda: self.access.check(step, value, response), lambda document: {"document": document.document,
			"source": document.source, "emptyTypes": list(document.emptyTypes), "emptyInputs": list(document.emptyInputs)})


def install() -> None:
	from onto import Model, Observations, observationsToJson, printObservationsCompact, printObservationsLog
	from onto.integrations.hexa import HexaBindingOperator, HexaMappingOperator, HexaViewOperator
	from onto.integrations.hexa.bundle import bindingProgramJson, mappingProgramJson, modelJson, viewBundle

	def model(ontology):
		return exported(ontology, lambda: modelJson(Model(ontology)))

	async def run(env, stage, *inputs):
		entry = STAGES.get(id(stage))
		if entry is None or entry[0] is not stage:
			return await ORIGINAL_RUN(env, stage, *inputs)
		_, kind, operator, program, libraries = entry
		clock = []
		if isinstance(env, dict) and callable(env.get("ClockRead")):
			read = env["ClockRead"]
			env = {**env, "ClockRead": lambda context: clock.append(read(context)) or clock[-1]}
		if kind == "binding":
			sources = {"model": model(operator.ontology), "program": exported(program, lambda: bindingProgramJson(operator, program))}
		else:
			sources = {"model": model(operator.fromOntology), "targetModel": model(operator.toOntology),
				"program": exported(program, lambda: mappingProgramJson(operator, program, libraries))}
		value = inputs[0] if inputs else None
		policy = env.get("policy") if isinstance(env, dict) else None
		replay = env.get("replay") if isinstance(env, dict) else None
		case = {"kind": kind, "test": CURRENT["test"], "operator": operator, "clock": clock, "formats": getattr(program, "formats", None) is not None,
			**({"replay": replay} if replay is not None else {}),
			"input": store(observationsToJson(value) if isinstance(value, Observations) else value),
			**({"policy": policy} if isinstance(policy, dict) and all(isinstance(item, int) for item in policy.values()) else {})}
		for key, item in sources.items():
			if "unsupported" in item:
				case["unsupported"] = item["unsupported"]
			else:
				case[key] = item["key"]
		CASES.append(case)
		try:
			result = await ORIGINAL_RUN(env, stage, *inputs)
		except Exception as error:
			case["error"] = errorJson(error)
			raise
		case["output"] = store(result["value"] if isinstance(result, dict) and "ledger" in result else result)
		return result

	hexa.runtime.run = run

	def recordInit(cls):
		original = cls.__init__

		def init(self, *args, **options):
			original(self, *args, **options)
			recordingImplementations(self)
		cls.__init__ = init

	recordInit(HexaBindingOperator)
	recordInit(HexaMappingOperator)

	originalBinding, originalMapping = HexaBindingOperator.compile, HexaMappingOperator.compile

	def bindingCompile(self, binding, formats=None, inventory=None):
		program = originalBinding(self, binding, formats, inventory)
		STAGES[id(program.stages.BindingRead)] = (program.stages.BindingRead, "binding", self, program, None)
		return program

	def mappingCompile(self, mapping, libraries=None):
		program = originalMapping(self, mapping, libraries)
		STAGES[id(program.stages.MappingRead)] = (program.stages.MappingRead, "mapping", self, program, libraries)
		return program

	HexaBindingOperator.compile, HexaMappingOperator.compile = bindingCompile, mappingCompile

	originalView = HexaViewOperator.__init__
	originalPlan, originalReport, originalRetrieve = HexaViewOperator.plan, HexaViewOperator.report, HexaViewOperator.retrieve

	def viewInit(self, mapper, mapping, reads, access, operations=None):
		originalView(self, mapper, mapping, reads, RecordingAccess(access) if access is not None else None, operations)

	async def recordView(self, method: str, view, seed, fields, now, call, journal=None, policy=None):
		item = exported(self, lambda: viewBundle(self))
		case = {"kind": "view", "method": method, "test": CURRENT["test"], "operator": self, "view": view, "seed": seed, "fields": fields, "now": now,
			**({"policy": policyJson(policy)} if policy is not None else {}),
			**({"bundle": item["key"]} if "key" in item else {"unsupported": item["unsupported"]})}
		CASES.append(case)
		try:
			result = await call()
		except Exception as error:
			case["error"] = errorJson(error)
			raise
		finally:
			if journal is not None:
				case["journal"] = store(journal)
		if method == "retrieve":
			output = {"observations": observationsToJson(result)}
			for name, printer in (("log", printObservationsLog), ("compact", printObservationsCompact)):
				try:
					output[name] = printer(self.target, result)
				except ValueError:
					output[name] = None
		else:
			output = result
		case["output"] = store(output)
		return result

	clockNow = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

	async def plan(self, view, seed, fields=None):
		return await recordView(self, "plan", view, seed, fields, None, lambda: originalPlan(self, view, seed, fields))

	def journaled(options: dict) -> tuple[list, dict]:
		"""Keep the run's journal, still passing each entry to a sink the test gave."""
		journal, sink = [], options.get("record")
		def record(entry):
			journal.append(entry)
			if callable(sink):
				sink(entry)
		return journal, {**options, "record": record}

	async def report(self, view, seed, fields=None, now=None, **options):
		now = now or clockNow()
		journal, options = journaled(options)
		return await recordView(self, "report", view, seed, fields, now, lambda: originalReport(self, view, seed, fields, now, **options), journal, options.get("policy"))

	async def retrieve(self, view, seed, fields=None, now=None, **options):
		now = now or clockNow()
		journal, options = journaled(options)
		return await recordView(self, "retrieve", view, seed, fields, now, lambda: originalRetrieve(self, view, seed, fields, now, **options), journal, options.get("policy"))

	HexaViewOperator.__init__, HexaViewOperator.plan, HexaViewOperator.report, HexaViewOperator.retrieve = viewInit, plan, report, retrieve

	# NOTE: A store's batch validation (spec-08 "Validation"): the JavaScript store must accept what Python accepts and
	# reject the rest with the same check and statement, from the bundle and what the partition already types.
	from onto.store.runtime import ObservationStore, StoreError

	originalValidate = ObservationStore.validate

	def validate(self, data, partition):
		case = {"kind": "store-validate", "test": CURRENT["test"], "bundle": exported(self.bundle, lambda: self.bundle)["key"],
			"partition": {"id": partition.id, "anchor": partition.anchor, "types": dict(partition.types)}, "data": store(data)}
		CASES.append(case)
		try:
			result = originalValidate(self, data, partition)
		except StoreError as error:
			case["outcome"] = {"status": error.status, "error": error.error, **{key: error.details[key] for key in ("check", "n") if key in error.details}}
			raise
		case["outcome"] = {"accepted": True}
		return result

	ObservationStore.validate = validate


def write() -> None:
	"""Resolve each case's host answers, recorded until the end of the session, and write the cases."""
	cases = []
	for case in CASES:
		if "operator" not in case:
			cases.append(case)  # A store case carries what it needs.
			continue
		operator = case.pop("operator")
		calls = dict(getattr(operator, "conformanceCalls", {}))
		for nested in ("binder", "mapper"):
			calls |= getattr(getattr(operator, nested, None), "conformanceCalls", {})
		case["calls"] = store(calls)
		if isinstance(getattr(operator, "access", None), RecordingAccess):
			case["access"] = store(operator.access.calls)
		cases.append(case)
	path = Path(OUTPUT)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps({"format": "onto.conformance/1", "objects": OBJECTS, "cases": cases}, ensure_ascii=False, default=str), encoding="utf-8")


if OUTPUT:
	install()


def pytest_runtest_setup(item):
	CURRENT["test"] = item.nodeid


def pytest_unconfigure(config):
	if OUTPUT:
		write()


# EOF
