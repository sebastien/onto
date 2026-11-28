/**
 * Module: store/partition — one partition of an observation store over synchronous SQLite storage (spec-08), as
 * `store/runtime.py` keeps each partition: appends with homes, origins, held slots, preconditions and retries; state
 * and log reads.
 *
 * The storage has Cloudflare's shape, `sql.exec(query, ...bindings)` and `transactionSync(action)`, so one engine runs
 * in a Durable Object, in Bun or Node over SQLite, and in tests. Its operations run in one synchronous turn; the caller
 * authorizes requests and computes digests first (`store.js`).
 */

import { Model } from "../model.js";
import { reconcileObservations } from "../observations.js";
import { compareTimestamps, referenceHandles, timestampValue, valueKey } from "../values.js";
import { StoreError, canonical, invalid } from "./errors.js";
import { holds, isA, originOf, elementPath, unkeyedPath } from "./origins.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const STAMPS = ["seq", "recorded", "principal", "requestId", "bundle", "retract"];
const SCHEMA = `
CREATE TABLE IF NOT EXISTS partition (id INTEGER PRIMARY KEY CHECK(id = 1), scope TEXT NOT NULL, partition TEXT NOT NULL, kind TEXT NOT NULL,
	anchor TEXT NOT NULL, generation INTEGER NOT NULL, head INTEGER NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries (generation INTEGER NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (generation, seq));
CREATE TABLE IF NOT EXISTS instances (generation INTEGER NOT NULL, handle TEXT NOT NULL, type TEXT NOT NULL, population TEXT, first INTEGER,
	PRIMARY KEY (generation, handle));
CREATE TABLE IF NOT EXISTS versions (generation INTEGER NOT NULL, slot TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY (generation, slot));
CREATE TABLE IF NOT EXISTS retries (request TEXT PRIMARY KEY, digest TEXT NOT NULL, answer TEXT NOT NULL, recorded TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reads (principal TEXT NOT NULL, selection TEXT NOT NULL, recorded TEXT NOT NULL);
`;

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** An ISO 8601 UTC time with milliseconds, as spec-02 times are written. */
export const timeText = moment => new Date(moment).toISOString();

const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);

/** A slot's identity as Python keys it: the canonical JSON of `[subject, member, ctx]` (spec-02 `claimSlot`). */
export function slotKey(statement) {
	for (const kind of ["same", "distinct"]) if (Object.hasOwn(statement, kind)) return canonical([kind, valueKey(statement[kind]), ""]);
	if (Object.hasOwn(statement, "rel")) return canonical([statement.s || `${statement.rel}:${valueKey(statement.roles)}`, "", statement.ctx ?? ""]);
	return canonical([statement.s, Object.hasOwn(statement, "facet") ? `[${statement.facet}]` : statement.p ?? "", statement.ctx ?? ""]);
}

/** The handles a statement mentions: subject, context, roles, references and identity links. */
export function handlesOf(statement) {
	const found = [statement.s, statement.ctx, ...Object.values(statement.roles ?? {}), ...referenceHandles(statement.v)];
	for (const key of ["same", "distinct"]) found.push(...(statement[key] ?? []));
	return found.filter(item => typeof item === "string" && item !== "?");
}

const rows = (storage, query, ...bindings) => storage.sql.exec(query, ...bindings).toArray();

/**
 * A value as index columns hold it: its spec-02 JSON encoding, a number as its canonical decimal text, each member of a
 * set on its own (spec-08 "Indexes"), as `indexValue` in `store/runtime.py`.
 */
export function indexValue(value) {
	if (isObject(value) && Array.isArray(value.set)) return value.set.flatMap(indexValue);
	if (typeof value === "number") return [canonical(String(value))];
	return [canonical(value)];
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** One partition's statements, members, versions, retry records and audit in one SQLite storage. */
export class PartitionStore {
	/**
	 * `storage` is SQLite storage of Cloudflare's shape; `bundle` the store bundle and `validator` its `BatchValidator`;
	 * `clock()` the time in epoch milliseconds; `scope` and `id` the partition's identity, which the storage keeps.
	 */
	constructor(storage, { bundle, validator, clock = Date.now, scope, id }) {
		this.storage = storage;
		this.bundle = bundle;
		this.validator = validator;
		this.clock = clock;
		this.scope = scope;
		this.id = id;
		this.model = new Model(bundle.model);
		this.limits = bundle.limits;
		const [kind, anchor] = [id.slice(0, id.indexOf("/")), id.slice(id.indexOf("/") + 1)];
		this.kind = bundle.kinds.find(item => item.kind === kind);
		this.anchor = anchor;
		storage.transactionSync(() => storage.sql.exec(SCHEMA));
		const [row] = rows(storage, "SELECT scope, partition FROM partition WHERE id = 1");
		if (row && (row.scope !== scope || row.partition !== id)) throw new StoreError(409, "identity_conflict", "The storage holds another partition");
	}

	get root() {
		return this.kind.root;
	}

	/** What an append and a read know of the partition. */
	load() {
		const [row] = rows(this.storage, "SELECT generation, head, state FROM partition WHERE id = 1");
		const item = { scope: this.scope, id: this.id, kind: this.kind, anchor: this.anchor, generation: row?.generation ?? 1, head: row?.head ?? 0,
			state: row?.state ?? "active", exists: Boolean(row), types: {}, members: {} };
		for (const { handle, type, population } of rows(this.storage, "SELECT handle, type, population FROM instances WHERE generation = ?", item.generation)) {
			item.types[handle] = type;
			if (population !== null) item.members[handle] = population;
		}
		return item;
	}

	/** Whether the partition was ever appended to; a read of one that was not is `404`. */
	exists() {
		return rows(this.storage, "SELECT 1 AS found FROM partition WHERE id = 1").length > 0;
	}

	statements(partition, through = null, kind = "statement") {
		return rows(this.storage, "SELECT body FROM entries WHERE generation = ? AND kind = ? AND seq <= ? ORDER BY seq",
			partition.generation, kind, through ?? partition.head).map(({ body }) => JSON.parse(body));
	}

	/** A statement's subject: its `s`, a binary relation's first participant, an identity link's first handle. */
	subjectOf(statement) {
		if (Object.hasOwn(statement, "s")) return statement.s;
		if (Object.hasOwn(statement, "rel")) return statement.roles[this.bundle.model.relations[statement.rel].participants[0].role];
		return (statement.same ?? statement.distinct)[0];
	}

	// -- Appends -----------------------------------------------------------------

	/**
	 * Append a batch, after the caller authorized it and checked its request ID and size: whole or not at all
	 * (spec-08 "Batches"). `digest` is the SHA-256 of the batch's canonical payload, which identifies a retry.
	 */
	append(principal, body, digest) {
		const partition = this.load(), now = this.clock();
		const retry = this.retry(body.requestId, now);
		if (retry) {
			if (retry.digest !== digest) throw new StoreError(409, "request_reused", "This request ID was used for another batch");
			return JSON.parse(retry.answer);
		}
		if (partition.state !== "active") throw new StoreError(409, "lifecycle", `Partition '${partition.id}' is ${partition.state}`);
		const recorded = timeText(now);
		const observations = this.validator.validate(body.observations, partition);
		if ((observations.obs.scope ?? null) !== this.scope) throw invalid("scope", `The batch's scope must be the store's, '${this.scope}'`);
		const strip = ({ conflict, ...claim }) => claim;
		const batch = [...observations.claims.map(claim => ({ ...strip(claim) })), ...observations.retractions.map(claim => ({ ...strip(claim), retract: true }))]
			.map((item, index) => [item, index]).sort((a, b) => a[0].n - b[0].n || a[1] - b[1]).map(([item]) => item);
		if (batch.length > this.limits.statementsPerBatch) throw new StoreError(413, "too_large", `A batch holds at most ${this.limits.statementsPerBatch} statements`);
		// NOTE: The kind types the anchor when no statement does, as validation does.
		const types = { ...partition.types, [partition.anchor]: partition.types[partition.anchor] ?? this.root.type };
		for (const [handle, item] of Object.entries(observations.instances)) {
			// NOTE: A compatible specialisation refines the type (spec-02 "Type-only declarations"); validation refused others.
			const known = types[handle] ?? item.type;
			types[handle] = isA(this.bundle, item.type, known) ? item.type : known;
		}
		for (const statement of batch) {
			if (new TextEncoder().encode(canonical(statement)).length > this.limits.statementBytes)
				throw new StoreError(413, "too_large", "A statement is larger than the store accepts", { n: statement.n });
			const src = statement.src;
			if (src === undefined || src === null) throw invalid("src", "A statement needs a source, its own or the document's", statement.n);
			statement.src = observations.sources[src] ?? src;
			statement.at = statement.at ?? recorded;
			if (compareTimestamps(timestampValue(statement.at), timestampValue(recorded)) > 0) throw invalid("at", "A statement cannot be observed after the store records it", statement.n);
		}
		const links = this.checkLinks(partition, body.links ?? [], types);
		const members = this.homes(partition, batch, types, links);
		for (const statement of batch) this.checkStatement(statement, types);
		this.checkPreconditions(partition, body.expect ?? []);
		return this.commit(partition, batch, types, members, { principal, requestId: body.requestId, recorded }, digest, links);
	}

	/** Members after the batch: the anchor, and the subjects whose stated links, or home links, reach a parent (spec-08 "Homes"). */
	homes(partition, batch, types, links) {
		const root = this.root, members = { ...partition.members };
		const anchorType = types[partition.anchor] ?? root.type;
		if (!isA(this.bundle, anchorType, root.type)) throw invalid("home.mismatch", `The anchor of '${partition.id}' is a ${anchorType}, not a ${root.type}`);
		members[partition.anchor] = root.name;
		const claims = [...[...this.statements(partition), ...batch].filter(item => !item.retract), ...this.statements(partition, null, "link"), ...links];
		const subjects = [...new Set(batch.map(item => this.subjectOf(item)))];
		const pending = subjects.filter(item => !Object.hasOwn(members, item));
		const linked = (handle, population) => {
			const { link, parent } = population;
			if (Object.hasOwn(link, "rel")) return claims.some(item => item.rel === link.rel && item.roles[link.memberRole] === handle && members[item.roles[link.parentRole]] === parent);
			if (link.on === "member") return claims.some(item => item.s === handle && item.p === link.slot && referenceHandles(item.v).some(target => members[target] === parent));
			return claims.some(item => item.p === link.slot && members[item.s] === parent && referenceHandles(item.v).includes(handle));
		};
		let changed = true;
		while (changed && pending.length) {
			changed = false;
			for (const handle of [...pending]) {
				const population = this.kind.populations.find(item => isA(this.bundle, types[handle], item.type) && linked(handle, item));
				if (population) {
					members[handle] = population.name;
					pending.splice(pending.indexOf(handle), 1);
					changed = true;
				}
			}
		}
		for (const handle of pending) {
			const n = batch.find(item => this.subjectOf(item) === handle).n, type = types[handle];
			const accepting = this.kind.populations.filter(item => isA(this.bundle, type, item.type));
			if (isA(this.bundle, type, root.type)) throw invalid("home.mismatch", `'${handle}' is the anchor of another partition, not of '${partition.id}'`, n);
			if (!accepting.length) throw invalid("home.none", `No population of '${this.kind.kind}' holds a ${type}`, n);
			const stated = claims.filter(item => item.s === handle && accepting.some(population => population.link.on === "member" && item.p === population.link.slot));
			if (stated.length) throw invalid("home.mismatch", `'${handle}' links to an instance that is not a member of '${partition.id}'`, n);
			throw invalid("home.unlinked", `No statement links '${handle}' to '${partition.id}'`, n);
		}
		return members;
	}

	/** Home links: claims on slots the store does not hold, each followed by a population line (spec-08 "Homes"). */
	checkLinks(partition, links, types) {
		if (!Array.isArray(links)) throw invalid("link", "links lists the claims that home members from another system");
		const result = [];
		for (const [index, given] of links.entries()) {
			const refuse = message => new StoreError(400, "invalid", message, { check: "link", link: index });
			const has = keys => isObject(given) && keys.every(key => Object.hasOwn(given, key));
			if (!has(["s", "p", "v"]) && !has(["rel", "roles"])) throw refuse("A home link is a claim: a subject, an attribute and a value, or a relation and its roles");
			const link = Object.fromEntries(["s", "p", "v", "rel", "roles"].filter(key => Object.hasOwn(given, key)).map(key => [key, given[key]]));
			const handles = Object.hasOwn(link, "rel") ? Object.values(link.roles) : [link.s, ...referenceHandles(link.v)];
			if (!handles.length || handles.some(handle => typeof handle !== "string" || !Object.hasOwn(types, handle)))
				throw refuse("A home link's handles need their types, from the partition or the batch");
			const populations = this.kind.populations;
			const typeOf = { [this.root.name]: this.root.type, ...Object.fromEntries(populations.map(item => [item.name, item.type])) };
			let followed;
			if (Object.hasOwn(link, "rel")) followed = populations.some(item => item.link.rel === link.rel);
			else {
				// A member's own link reaches its parent; a parent's link reaches the member.
				const subject = types[link.s], targets = referenceHandles(link.v).map(handle => types[handle]);
				followed = targets.length > 0 && populations.some(item => item.link.slot === link.p && (
					item.link.on === "member" && isA(this.bundle, subject, item.type) && targets.every(target => isA(this.bundle, target, typeOf[item.parent]))
					|| item.link.on === "parent" && isA(this.bundle, subject, typeOf[item.parent]) && targets.every(target => isA(this.bundle, target, item.type))));
			}
			if (!followed) throw refuse(`No population line of '${this.kind.kind}' follows this link`);
			const holders = (Object.hasOwn(link, "rel") ? handles : [link.s]).map(handle => [handle, types[handle]]);
			const origins = holders.map(([handle, type]) => originOf(this.bundle, handle, type, this.scope));
			if (origins.includes(null) || origins.every((origin, at) => holds(this.bundle, origin, holders[at][1], link)))
				throw refuse("A home link is for a slot another system holds; the store's own links are statements");
			result.push(link);
		}
		return result;
	}

	/** Origins and held slots of a statement's subject, or of every participant of a binary relation. */
	checkStatement(statement, types) {
		const n = statement.n;
		const handles = Object.hasOwn(statement, "rel") ? Object.values(statement.roles) : [this.subjectOf(statement)];
		for (const handle of handles) {
			const type = types[handle], origin = originOf(this.bundle, handle, type, this.scope);
			if (origin === null) throw invalid("origin.unknown", `'${handle}' is a ${type}, which a system produces, but its handle tells no origin`, n);
			// NOTE: `- h` withdraws what the store holds about `h`, whatever its origin.
			const whole = statement.retract && statement.exists && Object.keys(statement).every(key => ["n", "s", "exists", "src", "at", "by", "retract"].includes(key));
			if (!whole && !holds(this.bundle, origin, type, statement)) throw invalid("slot.not-held", `The store does not hold this slot of '${handle}': its system of record does`, n);
		}
	}

	/** A retry record of this request, while it is kept (7 days). */
	retry(requestId, now) {
		const [row] = rows(this.storage, "SELECT digest, answer, recorded FROM retries WHERE request = ?", requestId);
		if (!row) return null;
		const days = Number(this.limits.retries.replace(/^P/, "").replace(/D$/, ""));
		if (now - Date.parse(row.recorded) > days * 86400000) {
			this.storage.sql.exec("DELETE FROM retries WHERE request = ?", requestId);
			return null;
		}
		return row;
	}

	/** Current versions of slots by key; a slot never changed is at `0`. */
	versions(partition, keys) {
		const found = new Map();
		for (const key of keys) {
			const [row] = rows(this.storage, "SELECT version FROM versions WHERE generation = ? AND slot = ?", partition.generation, key);
			if (row) found.set(key, row.version);
		}
		return Object.fromEntries(keys.map(key => [key, found.get(key) ?? 0]));
	}

	/** `409 precondition` when a slot moved since the writer read it, with the slots' current versions. */
	checkPreconditions(partition, expect) {
		if (!Array.isArray(expect) || expect.some(item => !isObject(item) || !Number.isInteger(item.version)))
			throw invalid("expect", "expect lists slots with the versions the batch was prepared against");
		const slots = expect.map(({ version, ...slot }) => slot), keys = slots.map(slotKey);
		const current = this.versions(partition, keys);
		if (keys.some((key, index) => current[key] !== expect[index].version))
			throw new StoreError(409, "precondition", "A slot moved since the batch was prepared", { versions: slots.map((slot, index) => ({ ...slot, version: current[keys[index]] })) });
	}

	/** Stamp the batch and write its home links, statements, slot versions, members and retry record in one transaction. */
	commit(partition, batch, types, members, stamps, digest, links) {
		const exec = (query, ...bindings) => this.storage.sql.exec(query, ...bindings);
		const generation = partition.generation, start = partition.head + 1;
		return this.storage.transactionSync(() => {
			let first = start;
			const moved = new Map();
			if (!partition.exists) exec("INSERT INTO partition VALUES (1, ?, ?, ?, ?, ?, 0, 'active')", this.scope, this.id, this.kind.kind, this.anchor, generation);
			// NOTE: The anchor is the root population's member from the partition's first batch, mentioned or not.
			exec("INSERT INTO instances VALUES (?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET population = COALESCE(instances.population, excluded.population), "
				+ "first = COALESCE(instances.first, excluded.first)", generation, this.anchor, types[this.anchor], this.root.name, start);
			for (const [offset, link] of links.entries()) {
				const entry = { ...link, ...stamps, seq: first + offset, bundle: this.bundle.revision };
				exec("INSERT INTO entries VALUES (?, ?, 'link', ?)", generation, first + offset, canonical(entry));
				for (const handle of Object.hasOwn(link, "roles") ? Object.values(link.roles) : [link.s, ...referenceHandles(link.v)])
					exec("INSERT INTO instances VALUES (?, ?, ?, NULL, NULL) ON CONFLICT DO NOTHING", generation, handle, types[handle]);
			}
			first += links.length;
			for (const [offset, statement] of batch.entries()) {
				const seq = first + offset, { n, ...rest } = statement;
				exec("INSERT INTO entries VALUES (?, ?, 'statement', ?)", generation, seq, canonical({ ...rest, ...stamps, seq, bundle: this.bundle.revision }));
				const subject = this.subjectOf(statement);
				if (statement.retract && statement.exists && !Object.hasOwn(statement, "p")) {
					// NOTE: `- h` moves every slot of `h`.
					for (const { slot } of rows(this.storage, "SELECT slot FROM versions WHERE generation = ?", generation))
						if (JSON.parse(slot)[0] === subject) moved.set(slot, seq);
				}
				moved.set(slotKey(statement), seq);
				for (const handle of [subject, ...handlesOf(statement)])
					exec("INSERT INTO instances VALUES (?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET type = excluded.type, "
						+ "population = COALESCE(instances.population, excluded.population), first = COALESCE(instances.first, excluded.first)",
						generation, handle, types[handle], members[handle] ?? null, Object.hasOwn(members, handle) ? seq : null);
			}
			for (const [slot, seq] of moved) exec("INSERT INTO versions VALUES (?, ?, ?) ON CONFLICT DO UPDATE SET version = excluded.version", generation, slot, seq);
			const head = first + batch.length - 1;
			exec("UPDATE partition SET head = ? WHERE id = 1", head);
			const answer = { partition: this.id, generation, from: start, through: head, head, recorded: stamps.recorded };
			exec("INSERT INTO retries VALUES (?, ?, ?, ?)", stamps.requestId, digest, canonical(answer), stamps.recorded);
			return answer;
		});
	}

	// -- Changes -----------------------------------------------------------------

	/**
	 * The partition's change for its scope's feed and indexes (spec-08 "Changes", "Indexes"): its generation, head and
	 * state, and its row in each index of its kind, each column the values its population's subjects hold at its slot.
	 */
	change() {
		const partition = this.existing(), rows = {};
		const indexes = (this.bundle.indexes ?? []).filter(index => index.kind === this.kind.kind);
		const state = indexes.length ? this.reconcile(partition, this.statements(partition)) : null;
		for (const index of indexes) {
			const row = Object.fromEntries(index.columns.map(column => [column.name, new Set()]));
			const members = Object.fromEntries(index.columns.map(column => [column.name, new Set([
				...Object.entries(partition.members).filter(([, population]) => population === column.population).map(([handle]) => handle),
				...(column.population === this.root.name ? [this.anchor] : [])])]));
			for (const claim of state.claims) {
				if (typeof claim.p !== "string") continue;
				for (const column of index.columns)
					if (members[column.name].has(claim.s) && unkeyedPath(claim.p) === column.path) for (const value of indexValue(claim.v)) row[column.name].add(value);
			}
			rows[index.name] = Object.fromEntries(Object.entries(row).map(([name, values]) => [name, [...values].sort()]));
		}
		return { partition: this.id, anchor: this.anchor, generation: partition.generation, head: partition.head, state: partition.state, rows };
	}

	// -- Reads -------------------------------------------------------------------

	/** Record a read: its principal, selection and time (spec-08 "Authorization and audit"). */
	audit(principal, selection) {
		this.storage.sql.exec("INSERT INTO reads VALUES (?, ?, ?)", principal, canonical(selection ?? null), timeText(this.clock()));
	}

	/** A partition that was appended to; `404` otherwise. */
	existing() {
		const partition = this.load();
		if (!partition.exists) throw new StoreError(404, "not_found", `Partition '${this.id}' was never appended to`);
		return partition;
	}

	/** Spec-02 reconciliation of statements, with the log order as statement order. */
	reconcile(partition, statements) {
		const stripped = statements.map(entry => ({ ...Object.fromEntries(Object.entries(entry).filter(([key]) => !STAMPS.includes(key))), n: entry.seq }));
		const observations = { format: "onto.observations/1", obs: { ontology: this.bundle.model.namespace, scope: this.scope }, sources: {},
			instances: Object.fromEntries(Object.entries(partition.types).map(([handle, type]) => [handle, { type }])),
			claims: stripped.filter((_, index) => !statements[index].retract), retractions: stripped.filter((_, index) => statements[index].retract) };
		const { warnings, ...state } = reconcileObservations(this.model, observations, "lenient");
		return state;
	}

	/** Each slot's identity and version: the `seq` of the latest statement that changed it. */
	slotVersions(statements) {
		const found = new Map();
		for (const entry of statements) {
			const subject = this.subjectOf(entry);
			if (entry.retract && entry.exists && !Object.hasOwn(entry, "p"))
				for (const [key, [slot]] of found) if (JSON.parse(key)[0] === subject) found.set(key, [slot, entry.seq]);
			const slot = Object.fromEntries(["s", "p", "facet", "rel", "roles", "ctx", "same", "distinct"].filter(key => Object.hasOwn(entry, key)).map(key => [key, entry[key]]));
			if (!["p", "facet", "rel", "same", "distinct"].some(key => Object.hasOwn(slot, key))) slot.exists = true;
			found.set(slotKey(entry), [slot, entry.seq]);
		}
		return found;
	}

	/** The selected subjects, each with its slots (null: all), and a cursor per population page with more members. */
	selection(partition, select, through) {
		if (select === undefined || select === null) return [new Map(Object.keys(partition.types).map(handle => [handle, null])), {}];
		if (!Array.isArray(select)) throw invalid("select", "select lists subjects and populations");
		const subjects = new Map(), cursors = {};
		for (const item of select) {
			if (!isObject(item) || Object.hasOwn(item, "s") === Object.hasOwn(item, "population")) throw invalid("select", "A selection entry names a subject (s) or a population");
			const slots = Object.hasOwn(item, "slots") ? new Set(item.slots) : null;
			let handles;
			if (Object.hasOwn(item, "s")) handles = [item.s];
			else {
				if (![this.root, ...this.kind.populations].some(population => population.name === item.population))
					throw invalid("select", `'${item.population}' is not a population of '${this.kind.kind}'`);
				const page = item.page ?? {}, after = Object.hasOwn(page, "after") ? Number.parseInt(page.after, 10) : null;
				const found = rows(this.storage, "SELECT handle, first FROM instances WHERE generation = ? AND population = ? AND first <= ? AND (? IS NULL OR first < ?) ORDER BY first DESC",
					partition.generation, item.population, through, after, after);
				const size = page.size ?? found.length;
				handles = found.slice(0, size).map(row => row.handle);
				if (found.length > size) cursors[item.population] = String(found[size - 1].first);
			}
			for (const handle of handles) {
				const known = subjects.has(handle) ? subjects.get(handle) : new Set();
				subjects.set(handle, known === null || slots === null ? null : new Set([...known, ...slots]));
			}
		}
		return [subjects, cursors];
	}

	/** The reconciled state of a selection of the partition (spec-08 "State"). */
	state(principal, body = {}) {
		const partition = this.existing();
		body = body ?? {};
		const include = body.include ?? [];
		if (!Array.isArray(include) || include.some(item => !["orphaned", "archived", "deletion"].includes(item)))
			throw invalid("include", "include names lifecycle states: orphaned, archived or deletion");
		const through = Object.hasOwn(body, "asOf") ? body.asOf : partition.head;
		if (!Number.isInteger(through) || through < 0 || through > partition.head) throw invalid("asOf", `asOf is a seq of the log, at most ${partition.head}`);
		const statements = this.statements(partition, through);
		const [subjects, cursors] = this.selection(partition, body.select, through);
		const selected = item => {
			const subject = this.subjectOf(item);
			if (!subjects.has(subject)) return false;
			const slots = subjects.get(subject);
			// NOTE: A slot without keys keeps each of its keyed elements (spec-08 "State").
			const member = item.p;
			return slots === null || (item.exists === true && !Object.hasOwn(item, "p"))
				|| (member !== undefined && (slots.has(member) || slots.has(elementPath(member)) || slots.has(unkeyedPath(member))))
				|| slots.has(`[${item.facet}]`) || slots.has(item.rel);
		};
		const state = this.reconcile(partition, statements);
		const claims = state.claims.filter(selected);
		const handles = new Set(claims.flatMap(item => [this.subjectOf(item), ...handlesOf(item)]));
		for (const handle of subjects.keys()) if (Object.hasOwn(state.instances, handle)) handles.add(handle);
		const chosen = { ...state, instances: Object.fromEntries(Object.entries(state.instances).filter(([handle]) => handles.has(handle))), claims, retractions: [] };
		const versions = [...this.slotVersions(statements).values()].filter(([slot]) => selected(slot)).map(([slot, version]) => ({ ...slot, version }));
		this.audit(principal, body.select);
		return { partition: this.id, generation: partition.generation, head: partition.head, state: partition.state,
			...(Object.hasOwn(body, "asOf") ? { asOf: through } : {}), versions, observations: chosen, ...(Object.keys(cursors).length ? { pages: cursors } : {}) };
	}

	/** The statements and records after a `seq`, in order, with their stamps (spec-08 "Log"). */
	log(principal, after = 0, limit = null) {
		const partition = this.existing();
		if (!Number.isInteger(after) || after < 0 || after > partition.head) throw invalid("cursor", `A log cursor is a seq of the log, at most ${partition.head}`);
		const size = Math.min(limit || this.limits.logPage, this.limits.logPage);
		const found = rows(this.storage, "SELECT seq, kind, body FROM entries WHERE generation = ? AND seq > ? ORDER BY seq LIMIT ?", partition.generation, after, size);
		const through = found.length ? found.at(-1).seq : after;
		this.audit(principal, { log: after });
		return { partition: this.id, generation: partition.generation, after, through, head: partition.head, hasMore: through < partition.head,
			entries: found.map(({ kind, body }) => ({ ...JSON.parse(body), kind })) };
	}
}

// EOF
