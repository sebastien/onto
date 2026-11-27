"""Module: store.runtime — the Python observation store over one SQLite database (spec-08), the reference implementation.

It runs with a store bundle and the store's ontology: the bundle decides kinds, homes, origins, held slots and
limits, as it does for the JavaScript store; the ontology validates and reconciles statements with spec-02.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ..observations.formatter import observationsToJson, renderObservationsLog
from ..observations.model import Observations, claimSlot, referenceHandles, timestampValue
from ..observations.operations import observationsFromJson, reconcileObservations
from ..observations.parser import parseObservations, readObservationsJson
from ..ontology.model import Model, Ontology
from ..text import FormatError, Source
from .origins import RE_ELEMENT_KEY, elementPath, holds, isA, originOf

# -----------------------------------------------------------------------------
#
# DEFINITIONS
#
# -----------------------------------------------------------------------------


RE_HANDLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STAMPS = ("seq", "recorded", "principal", "requestId", "bundle", "retract")
SCHEMA = """
CREATE TABLE IF NOT EXISTS partitions (scope TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, anchor TEXT NOT NULL,
	generation INTEGER NOT NULL, head INTEGER NOT NULL, state TEXT NOT NULL, PRIMARY KEY (scope, id));
CREATE TABLE IF NOT EXISTS entries (scope TEXT NOT NULL, partition TEXT NOT NULL, generation INTEGER NOT NULL, seq INTEGER NOT NULL,
	kind TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (scope, partition, generation, seq));
CREATE TABLE IF NOT EXISTS instances (scope TEXT NOT NULL, partition TEXT NOT NULL, generation INTEGER NOT NULL, handle TEXT NOT NULL,
	type TEXT NOT NULL, population TEXT, first INTEGER, PRIMARY KEY (scope, partition, generation, handle));
CREATE TABLE IF NOT EXISTS versions (scope TEXT NOT NULL, partition TEXT NOT NULL, generation INTEGER NOT NULL, slot TEXT NOT NULL,
	version INTEGER NOT NULL, PRIMARY KEY (scope, partition, generation, slot));
CREATE TABLE IF NOT EXISTS retries (scope TEXT NOT NULL, partition TEXT NOT NULL, request TEXT NOT NULL, digest TEXT NOT NULL,
	answer TEXT NOT NULL, recorded TEXT NOT NULL, PRIMARY KEY (scope, partition, request));
CREATE TABLE IF NOT EXISTS reads (scope TEXT NOT NULL, partition TEXT NOT NULL, principal TEXT NOT NULL, selection TEXT NOT NULL,
	recorded TEXT NOT NULL);
"""

type Json = dict[str, Any]
type Authorize = Callable[[Any, str | None, str], Json | None]


class StoreError(Exception):
	"""A refused request: its HTTP status, stable `error` code and details (spec-08 "Protocol")."""

	def __init__(self, status: int, error: str, message: str, **details: Any):
		super().__init__(message)
		self.status, self.error, self.details = status, error, details

	def toJson(self) -> Json:
		return {"error": self.error, "message": str(self), **self.details}


class Forbidden(Exception):
	"""Raised by an authorization callback to deny a request (`403`)."""


def invalid(check: str, message: str, n: int | None = None) -> StoreError:
	return StoreError(400, "invalid", message, check=check, **({"n": n} if n is not None else {}))


# -----------------------------------------------------------------------------
#
# UTILITIES
#
# -----------------------------------------------------------------------------


def timeText(moment: datetime) -> str:
	"""An ISO 8601 UTC time with milliseconds, as spec-02 times are written."""
	return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(value: Any) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def slotKey(statement: Json) -> str:
	"""A slot's identity, as spec-02 identifies a claim's slot: subject, member and context."""
	return canonical(list(claimSlot(statement)))


def handlesOf(statement: Json) -> list[str]:
	"""The handles a statement mentions: subject, context, roles, references and identity links."""
	found = [statement.get("s"), statement.get("ctx"), *statement.get("roles", {}).values(), *referenceHandles(statement.get("v"))]
	for key in ("same", "distinct"):
		found += statement.get(key, [])
	return [item for item in found if isinstance(item, str) and item != "?"]


@dataclass(slots=True)
class Partition:
	"""What an append and a read know of a partition."""

	scope: str
	id: str
	kind: Json
	anchor: str
	generation: int = 1
	head: int = 0
	state: str = "active"
	exists: bool = False
	types: dict[str, str] = field(default_factory=dict)
	members: dict[str, str] = field(default_factory=dict)

	@property
	def root(self) -> Json:
		return self.kind["root"]


# -----------------------------------------------------------------------------
#
# OPERATIONS
#
# -----------------------------------------------------------------------------


class ObservationStore:
	"""Partitions of observations in SQLite: appends with homes, origins, held slots and preconditions; state and log reads."""

	def __init__(self, bundle: Json, ontology: Ontology, authorize: Authorize, *, path: str = ":memory:", clock: Callable[[], datetime] | None = None):
		self.bundle = bundle
		self.ontology = ontology
		self.model = Model(ontology)
		self.authorizeCallback = authorize
		self.clock = clock or (lambda: datetime.now(UTC))
		self.kinds = {item["kind"]: item for item in bundle["kinds"]}
		self.limits = bundle["limits"]
		self.db = sqlite3.connect(path)
		self.db.executescript(SCHEMA)

	def close(self) -> None:
		"""Close the store's database; a store is also a context manager that closes it."""
		self.db.close()

	def __enter__(self) -> ObservationStore:
		return self

	def __exit__(self, *_: object) -> None:
		self.close()

	# -- Requests ----------------------------------------------------------------

	def authorize(self, request: Any, partition: str | None, access: str) -> tuple[str, str]:
		"""The request's scope and principal, or `401` and `403` as the host's callback decides."""
		try:
			grant = self.authorizeCallback(request, partition, access)
		except Forbidden as error:
			raise StoreError(403, "forbidden", str(error) or f"{access} denied") from error
		if grant is None:
			raise StoreError(401, "unauthorized", "The request is not authenticated")
		return grant["scope"], grant["principal"]

	def partition(self, scope: str, id: str, *, create: bool = False) -> Partition:
		"""A partition by ID: `<Kind>/<anchor handle>`; `404` when it was never appended to, unless creating it."""
		kind, slash, anchor = id.partition("/")
		if not slash or kind not in self.kinds or not RE_HANDLE.fullmatch(anchor) or len(id.encode()) > self.limits["handleBytes"]:
			raise invalid("partition", f"Expected a partition ID '<Kind>/<anchor handle>' of a declared kind, not '{id}'")
		item = Partition(scope, id, self.kinds[kind], anchor)
		row = self.db.execute("SELECT generation, head, state FROM partitions WHERE scope = ? AND id = ?", (scope, id)).fetchone()
		if row is None and not create:
			raise StoreError(404, "not_found", f"Partition '{id}' was never appended to")
		if row is not None:
			item.generation, item.head, item.state = row
			item.exists = True
		for handle, type, population in self.db.execute("SELECT handle, type, population FROM instances WHERE scope = ? AND partition = ? AND generation = ?",
			(scope, id, item.generation)):
			item.types[handle] = type
			if population is not None:
				item.members[handle] = population
		return item

	def statements(self, partition: Partition, through: int | None = None, kind: str = "statement") -> list[Json]:
		"""The partition's statements in log order, up to `through`; its home links with `kind="link"`."""
		rows = self.db.execute("SELECT body FROM entries WHERE scope = ? AND partition = ? AND generation = ? AND kind = ? AND seq <= ? ORDER BY seq",
			(partition.scope, partition.id, partition.generation, kind, partition.head if through is None else through))
		return [json.loads(body) for (body,) in rows]

	# -- Appends -----------------------------------------------------------------

	def validate(self, data: Any, partition: Partition) -> Observations:
		"""Spec-02 strict validation of a batch, with the types the partition knows; errors name the statement."""
		if not isinstance(data, dict) or data.get("format") != "onto.observations/1":
			raise invalid("observations", "observations must be an onto.observations/1 document")
		data = deepcopy(data)
		registry = data.setdefault("instances", {})
		if not isinstance(registry, dict):
			raise invalid("observations", "instances must be an object")
		known = partition.types | {partition.anchor: partition.types.get(partition.anchor, partition.root["type"])}
		for handle, item in registry.items():
			type = item.get("type") if isinstance(item, dict) else None
			if handle in partition.types and isinstance(type, str) and not (isA(self.bundle, type, known[handle]) or isA(self.bundle, known[handle], type)):
				raise invalid("type", f"'{handle}' is a {known[handle]} in '{partition.id}', not a {type}")
		for statement in [*data.get("claims", []), *data.get("retractions", [])]:
			for handle in handlesOf(statement) if isinstance(statement, dict) else []:
				if handle not in registry and handle in known:
					registry[handle] = {"type": known[handle]}
		try:
			return observationsFromJson(self.ontology, data, "batch", "strict")
		except FormatError as error:
			first = next(item for item in error.diagnostics if item.level == "error")
			raise invalid(first.code, first.message, self.statementAt(data, first.loc.line if first.loc else 0)) from error

	def statementAt(self, data: Json, line: int) -> int | None:
		"""The `n` of the statement a validation error's rendered line holds, when it can be told."""
		try:
			ordinals: list[int] = []
			text = renderObservationsLog(self.ontology, readObservationsJson(self.ontology, data), ordinals)
			statement = next((item for item in parseObservations(Source("batch", text)).statements if item.loc.line == line), None)
			return ordinals[statement.n - 1] if statement is not None else None
		except (ValueError, KeyError, IndexError, FormatError):
			return None

	def subjectOf(self, statement: Json) -> str:
		"""A statement's subject: its `s`, a binary relation's first participant, an identity link's first handle."""
		if "s" in statement:
			return statement["s"]
		if "rel" in statement:
			relation = self.model.get(statement["rel"])
			return statement["roles"][relation.participants[0].role]
		return (statement.get("same") or statement.get("distinct"))[0]

	def homes(self, partition: Partition, batch: list[Json], types: dict[str, str], links: list[Json]) -> dict[str, str]:
		"""Members after the batch: the anchor, and the subjects whose stated links, or home links, reach a parent
		(spec-08 "Homes")."""
		root = partition.root
		members = dict(partition.members)
		anchorType = types.get(partition.anchor, root["type"])
		if not isA(self.bundle, anchorType, root["type"]):
			raise invalid("home.mismatch", f"The anchor of '{partition.id}' is a {anchorType}, not a {root['type']}")
		members[partition.anchor] = root["name"]
		claims = [item for item in [*self.statements(partition), *batch] if not item.get("retract")]
		claims += self.statements(partition, kind="link") + links
		subjects = list(dict.fromkeys(self.subjectOf(item) for item in batch))
		pending = [item for item in subjects if item not in members]

		def linked(handle: str, population: Json) -> bool:
			link, parent = population["link"], population["parent"]
			if "rel" in link:
				return any(item.get("rel") == link["rel"] and item["roles"].get(link["memberRole"]) == handle
					and members.get(item["roles"].get(link["parentRole"])) == parent for item in claims)
			if link["on"] == "member":
				return any(item.get("s") == handle and item.get("p") == link["slot"]
					and any(members.get(target) == parent for target in referenceHandles(item.get("v"))) for item in claims)
			return any(item.get("p") == link["slot"] and members.get(item.get("s")) == parent and handle in referenceHandles(item.get("v")) for item in claims)

		changed = True
		while changed and pending:
			changed = False
			for handle in list(pending):
				population = next((item for item in partition.kind["populations"] if isA(self.bundle, types[handle], item["type"]) and linked(handle, item)), None)
				if population is not None:
					members[handle] = population["name"]
					pending.remove(handle)
					changed = True
		for handle in pending:
			n = next(item["n"] for item in batch if self.subjectOf(item) == handle)
			type = types[handle]
			accepting = [item for item in partition.kind["populations"] if isA(self.bundle, type, item["type"])]
			if isA(self.bundle, type, root["type"]):
				raise invalid("home.mismatch", f"'{handle}' is the anchor of another partition, not of '{partition.id}'", n)
			if not accepting:
				raise invalid("home.none", f"No population of '{partition.kind['kind']}' holds a {type}", n)
			stated = [item for item in claims if item.get("s") == handle and any(population["link"].get("on") == "member"
				and item.get("p") == population["link"]["slot"] for population in accepting)]
			if stated:
				raise invalid("home.mismatch", f"'{handle}' links to an instance that is not a member of '{partition.id}'", n)
			raise invalid("home.unlinked", f"No statement links '{handle}' to '{partition.id}'", n)
		return members

	def checkLinks(self, partition: Partition, links: Any, types: dict[str, str], scope: str) -> list[Json]:
		"""Home links: claims on slots the store does not hold, each followed by a population line (spec-08 "Homes")."""
		if not isinstance(links, list):
			raise invalid("link", "links lists the claims that home members from another system")
		result = []
		for index, link in enumerate(links):
			def refuse(message: str) -> StoreError:
				return StoreError(400, "invalid", message, check="link", link=index)

			if not isinstance(link, dict) or not ({"s", "p", "v"} <= link.keys() or {"rel", "roles"} <= link.keys()):
				raise refuse("A home link is a claim: a subject, an attribute and a value, or a relation and its roles")
			link = {key: link[key] for key in ("s", "p", "v", "rel", "roles") if key in link}
			handles = list(link["roles"].values()) if "rel" in link else [link["s"], *referenceHandles(link["v"])]
			if any(not isinstance(handle, str) or handle not in types for handle in handles) or not handles:
				raise refuse("A home link's handles need their types, from the partition or the batch")
			populations = partition.kind["populations"]
			typeOf = {partition.root["name"]: partition.root["type"]} | {population["name"]: population["type"] for population in populations}
			if "rel" in link:
				followed = any(population["link"].get("rel") == link["rel"] for population in populations)
			else:
				# A member's own link reaches its parent; a parent's link reaches the member.
				subject, targets = types[link["s"]], [types[handle] for handle in referenceHandles(link["v"])]
				followed = bool(targets) and any(population["link"].get("slot") == link["p"] and (
					population["link"]["on"] == "member" and isA(self.bundle, subject, population["type"])
					and all(isA(self.bundle, target, typeOf[population["parent"]]) for target in targets)
					or population["link"]["on"] == "parent" and isA(self.bundle, subject, typeOf[population["parent"]])
					and all(isA(self.bundle, target, population["type"]) for target in targets)) for population in populations)
			if not followed:
				raise refuse(f"No population line of '{partition.kind['kind']}' follows this link")
			holders = [(handle, types[handle]) for handle in (handles if "rel" in link else [link["s"]])]
			origins = [originOf(self.bundle, handle, type, scope) for handle, type in holders]
			if None in origins or all(holds(self.bundle, origin, type, link) for origin, (_, type) in zip(origins, holders)):
				raise refuse("A home link is for a slot another system holds; the store's own links are statements")
			result.append(link)
		return result

	def checkStatement(self, statement: Json, types: dict[str, str], scope: str) -> None:
		"""Origins and held slots of a statement's subject, or of every participant of a binary relation."""
		n = statement["n"]
		handles = list(statement["roles"].values()) if "rel" in statement else [self.subjectOf(statement)]
		for handle in handles:
			type = types[handle]
			origin = originOf(self.bundle, handle, type, scope)
			if origin is None:
				raise invalid("origin.unknown", f"'{handle}' is a {type}, which a system produces, but its handle tells no origin", n)
			# NOTE: `- h` withdraws what the store holds about `h`, whatever its origin.
			whole = statement.get("retract") and statement.get("exists") and len(statement.keys() - {"n", "s", "exists", "src", "at", "by", "retract"}) == 0
			if not whole and not holds(self.bundle, origin, type, statement):
				raise invalid("slot.not-held", f"The store does not hold this slot of '{handle}': its system of record does", n)

	def append(self, request: Any, partitionId: str, body: Json) -> Json:
		"""Append a batch to a partition: whole or not at all (spec-08 "Batches")."""
		scope, principal = self.authorize(request, partitionId, "append")
		if not isinstance(body, dict) or not isinstance(body.get("requestId"), str) or not body["requestId"]:
			raise invalid("requestId", "A batch needs a request ID")
		if len(canonical(body).encode()) > self.limits["requestBytes"]:
			raise StoreError(413, "too_large", "The request is larger than the store accepts")
		partition = self.partition(scope, partitionId, create=True)
		payload = {"observations": body.get("observations"), "expect": body.get("expect", []), "links": body.get("links", [])}
		digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
		now = self.clock()
		if retry := self.retry(partition, body["requestId"], now):
			if retry[0] != digest:
				raise StoreError(409, "request_reused", "This request ID was used for another batch")
			return json.loads(retry[1])
		if partition.state != "active":
			raise StoreError(409, "lifecycle", f"Partition '{partitionId}' is {partition.state}")
		recorded = timeText(now)
		observations = self.validate(body.get("observations"), partition)
		if observations.obs.get("scope") != scope:
			raise invalid("scope", f"The batch's scope must be the store's, '{scope}'")
		batch = sorted([claim | {} for claim in observations.claims] + [claim | {"retract": True} for claim in observations.retractions], key=lambda item: item["n"])
		if len(batch) > self.limits["statementsPerBatch"]:
			raise StoreError(413, "too_large", f"A batch holds at most {self.limits['statementsPerBatch']} statements")
		# NOTE: The kind types the anchor when no statement does, as `validate` does.
		types = dict(partition.types) | {partition.anchor: partition.types.get(partition.anchor, partition.root["type"])}
		for handle, item in observations.instances.items():
			# NOTE: A compatible specialisation refines the type (spec-02 "Type-only declarations"); `validate` refused others.
			known = types.get(handle, item["type"])
			types[handle] = item["type"] if isA(self.bundle, item["type"], known) else known
		for statement in batch:
			if len(canonical(statement).encode()) > self.limits["statementBytes"]:
				raise StoreError(413, "too_large", "A statement is larger than the store accepts", n=statement["n"])
			src = statement.get("src")
			if src is None:
				raise invalid("src", "A statement needs a source, its own or the document's", statement["n"])
			statement["src"] = observations.sources.get(src, src)
			statement["at"] = statement.get("at", recorded)
			if timestampValue(statement["at"]) > timestampValue(recorded):
				raise invalid("at", "A statement cannot be observed after the store records it", statement["n"])
		links = self.checkLinks(partition, body.get("links", []), types, scope)
		members = self.homes(partition, batch, types, links)
		for statement in batch:
			self.checkStatement(statement, types, scope)
		self.checkPreconditions(partition, body.get("expect", []))
		stamps = {"principal": principal, "requestId": body["requestId"], "recorded": recorded}
		return self.commit(partition, batch, types, members, stamps, digest, links)

	def retry(self, partition: Partition, requestId: str, now: datetime) -> tuple[str, str] | None:
		"""A retry record of this request, while it is kept (7 days)."""
		row = self.db.execute("SELECT digest, answer, recorded FROM retries WHERE scope = ? AND partition = ? AND request = ?",
			(partition.scope, partition.id, requestId)).fetchone()
		if row is None:
			return None
		kept = timedelta(days=int(self.limits["retries"].removeprefix("P").removesuffix("D")))
		if now - datetime.fromisoformat(row[2].replace("Z", "+00:00")) > kept:
			with self.db:
				self.db.execute("DELETE FROM retries WHERE scope = ? AND partition = ? AND request = ?", (partition.scope, partition.id, requestId))
			return None
		return row[0], row[1]

	def versions(self, partition: Partition, keys: list[str]) -> dict[str, int]:
		"""Current versions of slots by key; a slot never changed is at `0`."""
		found = dict(self.db.execute(f"SELECT slot, version FROM versions WHERE scope = ? AND partition = ? AND generation = ? AND slot IN ({','.join('?' * len(keys))})",
			(partition.scope, partition.id, partition.generation, *keys))) if keys else {}
		return {key: found.get(key, 0) for key in keys}

	def checkPreconditions(self, partition: Partition, expect: Any) -> None:
		"""`409 precondition` when a slot moved since the writer read it, with the slots' current versions."""
		if not isinstance(expect, list) or any(not isinstance(item, dict) or not isinstance(item.get("version"), int) for item in expect):
			raise invalid("expect", "expect lists slots with the versions the batch was prepared against")
		keys = [slotKey({key: value for key, value in item.items() if key != "version"}) for item in expect]
		current = self.versions(partition, keys)
		if any(current[key] != item["version"] for key, item in zip(keys, expect)):
			raise StoreError(409, "precondition", "A slot moved since the batch was prepared",
				versions=[{key: value for key, value in item.items() if key != "version"} | {"version": current[slot]} for slot, item in zip(keys, expect)])

	def commit(self, partition: Partition, batch: list[Json], types: dict[str, str], members: dict[str, str], stamps: Json, digest: str,
		links: list[Json]) -> Json:
		"""Stamp the batch and write its home links, its statements, their slot versions, members and retry record in
		one transaction."""
		start = first = partition.head + 1
		moved: dict[str, int] = {}
		with self.db:
			if not partition.exists:
				self.db.execute("INSERT INTO partitions VALUES (?, ?, ?, ?, ?, 0, 'active')", (partition.scope, partition.id, partition.kind["kind"], partition.anchor, partition.generation))
			# NOTE: The anchor is the root population's member from the partition's first batch, mentioned or not.
			self.db.execute("INSERT INTO instances VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET population = COALESCE(instances.population, excluded.population), "
				"first = COALESCE(instances.first, excluded.first)", (partition.scope, partition.id, partition.generation, partition.anchor, types[partition.anchor],
				partition.root["name"], start))
			for offset, link in enumerate(links):
				entry = link | stamps | {"seq": first + offset, "bundle": self.bundle["revision"]}
				self.db.execute("INSERT INTO entries VALUES (?, ?, ?, ?, 'link', ?)", (partition.scope, partition.id, partition.generation, first + offset, canonical(entry)))
				for handle in list(link.get("roles", {}).values()) or [link["s"], *referenceHandles(link["v"])]:
					self.db.execute("INSERT INTO instances VALUES (?, ?, ?, ?, ?, NULL, NULL) ON CONFLICT DO NOTHING",
						(partition.scope, partition.id, partition.generation, handle, types[handle]))
			first += len(links)
			for offset, statement in enumerate(batch):
				seq = first + offset
				entry = {key: value for key, value in statement.items() if key != "n"} | stamps | {"seq": seq, "bundle": self.bundle["revision"]}
				self.db.execute("INSERT INTO entries VALUES (?, ?, ?, ?, 'statement', ?)", (partition.scope, partition.id, partition.generation, seq, canonical(entry)))
				subject = self.subjectOf(statement)
				if statement.get("retract") and statement.get("exists") and "p" not in statement:
					# NOTE: `- h` moves every slot of `h`.
					for (slot,) in self.db.execute("SELECT slot FROM versions WHERE scope = ? AND partition = ? AND generation = ?",
						(partition.scope, partition.id, partition.generation)).fetchall():
						if json.loads(slot)[0] == subject:
							moved[slot] = seq
				moved[slotKey(statement)] = seq
				for handle in [subject, *handlesOf(statement)]:
					self.db.execute("INSERT INTO instances VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET type = excluded.type, "
						"population = COALESCE(instances.population, excluded.population), first = COALESCE(instances.first, excluded.first)",
						(partition.scope, partition.id, partition.generation, handle, types[handle], members.get(handle), seq if handle in members else None))
			for slot, seq in moved.items():
				self.db.execute("INSERT INTO versions VALUES (?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET version = excluded.version",
					(partition.scope, partition.id, partition.generation, slot, seq))
			head = first + len(batch) - 1
			self.db.execute("UPDATE partitions SET head = ? WHERE scope = ? AND id = ?", (head, partition.scope, partition.id))
			answer = {"partition": partition.id, "generation": partition.generation, "from": start, "through": head, "head": head, "recorded": stamps["recorded"]}
			self.db.execute("INSERT INTO retries VALUES (?, ?, ?, ?, ?, ?)", (partition.scope, partition.id, stamps["requestId"], digest, canonical(answer), stamps["recorded"]))
		return answer

	# -- Reads -------------------------------------------------------------------

	def audit(self, partition: Partition, principal: str, selection: Any) -> None:
		"""Record a read: its principal, partition, selection and time (spec-08 "Authorization and audit")."""
		with self.db:
			self.db.execute("INSERT INTO reads VALUES (?, ?, ?, ?, ?)", (partition.scope, partition.id, principal, canonical(selection), timeText(self.clock())))

	def reconcile(self, partition: Partition, statements: list[Json]) -> Observations:
		"""Spec-02 reconciliation of statements, with the log order as statement order."""
		stripped = [{key: value for key, value in entry.items() if key not in STAMPS} | {"n": entry["seq"]} for entry in statements]
		observations = Observations({"ontology": self.ontology.namespace, "scope": partition.scope}, {},
			{handle: {"type": type} for handle, type in partition.types.items()},
			[item for item, entry in zip(stripped, statements) if not entry.get("retract")],
			[item for item, entry in zip(stripped, statements) if entry.get("retract")])
		try:
			return reconcileObservations(self.ontology, observations, "lenient")
		except FormatError as error:
			raise StoreError(500, "reconciliation", str(error)) from error

	def slotVersions(self, statements: list[Json]) -> dict[str, tuple[Json, int]]:
		"""Each slot's identity and version: the `seq` of the latest statement that changed it."""
		found: dict[str, tuple[Json, int]] = {}
		for entry in statements:
			subject = self.subjectOf(entry)
			if entry.get("retract") and entry.get("exists") and "p" not in entry:
				for key, (slot, _) in list(found.items()):
					if json.loads(key)[0] == subject:
						found[key] = (slot, entry["seq"])
			slot = {key: entry[key] for key in ("s", "p", "facet", "rel", "roles", "ctx", "same", "distinct") if key in entry}
			if not slot.keys() & {"p", "facet", "rel", "same", "distinct"}:
				slot["exists"] = True
			found[slotKey(entry)] = (slot, entry["seq"])
		return found

	def selection(self, partition: Partition, select: Any, through: int) -> tuple[dict[str, set[str] | None], dict[str, str]]:
		"""The selected subjects, each with its slots (None: all), and a cursor per population page with more members."""
		if select is None:
			return {handle: None for handle in partition.types}, {}
		if not isinstance(select, list):
			raise invalid("select", "select lists subjects and populations")
		subjects: dict[str, set[str] | None] = {}
		cursors: dict[str, str] = {}
		for item in select:
			if not isinstance(item, dict) or ("s" in item) == ("population" in item):
				raise invalid("select", "A selection entry names a subject (s) or a population")
			slots = set(item["slots"]) if "slots" in item else None
			if "s" in item:
				handles = [item["s"]]
			else:
				if not any(population["name"] == item["population"] for population in [partition.root, *partition.kind["populations"]]):
					raise invalid("select", f"'{item['population']}' is not a population of '{partition.kind['kind']}'")
				page = item.get("page", {})
				after = int(page["after"]) if "after" in page else None
				rows = self.db.execute("SELECT handle, first FROM instances WHERE scope = ? AND partition = ? AND generation = ? AND population = ? "
					"AND first <= ? AND (? IS NULL OR first < ?) ORDER BY first DESC", (partition.scope, partition.id, partition.generation,
					item["population"], through, after, after)).fetchall()
				size = page.get("size", len(rows))
				handles = [handle for handle, _ in rows[:size]]
				if len(rows) > size:
					cursors[item["population"]] = str(rows[size - 1][1])
			for handle in handles:
				known = subjects.get(handle, set())
				subjects[handle] = None if known is None or slots is None else known | slots
		return subjects, cursors

	def state(self, request: Any, partitionId: str, body: Json | None = None) -> Json:
		"""The reconciled state of a selection of a partition (spec-08 "State")."""
		scope, principal = self.authorize(request, partitionId, "read")
		partition = self.partition(scope, partitionId)
		body = body or {}
		include = body.get("include", [])
		if not isinstance(include, list) or set(include) - {"orphaned", "archived", "deletion"}:
			raise invalid("include", "include names lifecycle states: orphaned, archived or deletion")
		through = body.get("asOf", partition.head)
		if not isinstance(through, int) or not 0 <= through <= partition.head:
			raise invalid("asOf", f"asOf is a seq of the log, at most {partition.head}")
		statements = self.statements(partition, through)
		subjects, cursors = self.selection(partition, body.get("select"), through)

		def selected(item: Json) -> bool:
			subject = self.subjectOf(item)
			if subject not in subjects:
				return False
			slots = subjects[subject]
			# NOTE: A slot without keys keeps each of its keyed elements (spec-08 "State").
			member = item.get("p")
			return slots is None or item.get("exists") is True and "p" not in item or member is not None and (member in slots
				or elementPath(member) in slots or RE_ELEMENT_KEY.sub("", member) in slots) or \
				f"[{item.get('facet')}]" in slots or item.get("rel") in slots

		state = self.reconcile(partition, statements)
		claims = [item for item in state.claims if selected(item)]
		handles = {handle for item in claims for handle in [self.subjectOf(item), *handlesOf(item)]} | set(subjects) & set(state.instances)
		chosen = Observations(state.obs, state.sources, {handle: item for handle, item in state.instances.items() if handle in handles}, claims, [],
			state.diagnostics)
		versions = [slot | {"version": version} for slot, version in self.slotVersions(statements).values() if selected(slot)]
		self.audit(partition, principal, body.get("select"))
		return {"partition": partition.id, "generation": partition.generation, "head": partition.head, "state": partition.state,
			**({"asOf": through} if "asOf" in body else {}), "versions": versions, "observations": observationsToJson(chosen),
			**({"pages": cursors} if cursors else {})}

	def log(self, request: Any, partitionId: str, after: int = 0, limit: int | None = None) -> Json:
		"""The statements and records after a `seq`, in order, with their stamps (spec-08 "Log")."""
		scope, principal = self.authorize(request, partitionId, "read")
		partition = self.partition(scope, partitionId)
		if not isinstance(after, int) or not 0 <= after <= partition.head:
			raise invalid("cursor", f"A log cursor is a seq of the log, at most {partition.head}")
		size = min(limit or self.limits["logPage"], self.limits["logPage"])
		rows = self.db.execute("SELECT seq, kind, body FROM entries WHERE scope = ? AND partition = ? AND generation = ? AND seq > ? ORDER BY seq LIMIT ?",
			(scope, partition.id, partition.generation, after, size)).fetchall()
		through = rows[-1][0] if rows else after
		self.audit(partition, principal, {"log": after})
		return {"partition": partition.id, "generation": partition.generation, "after": after, "through": through, "head": partition.head,
			"hasMore": through < partition.head, "entries": [json.loads(body) | {"kind": kind} for _, kind, body in rows]}

	def stateMany(self, request: Any, body: Json) -> Json:
		"""Selections of several partitions, each authorized and answered on its own (spec-08 "Several partitions")."""
		reads = body.get("reads") if isinstance(body, dict) else None
		if not isinstance(reads, list) or any(not isinstance(item, dict) or not isinstance(item.get("partition"), str) for item in reads):
			raise invalid("reads", "A batch read lists partitions with their selections")
		results = []
		for item in reads:
			try:
				results.append(self.state(request, item["partition"], {key: value for key, value in item.items() if key != "partition"}))
			except StoreError as error:
				results.append({"partition": item["partition"], "status": error.status, **error.toJson()})
		return {"results": results}


__all__ = ["ObservationStore", "StoreError", "Forbidden", "timeText"]

# EOF
