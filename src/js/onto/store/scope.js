/**
 * Module: store/scope — a scope's change feed and indexes over synchronous SQLite storage (spec-08 "Changes",
 * "Indexes"), as `store/runtime.py` keeps them: partitions report their changes, and servers read the feed and query
 * the indexes. One engine runs in a scope's Durable Object (`server/cloudflare.js`), or in this process for a store
 * whose partitions do (`store.js`).
 */

import { StoreError, canonical, invalid } from "./errors.js";
import { indexValue } from "./partition.js";

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

const SCHEMA = `
CREATE TABLE IF NOT EXISTS feed (id INTEGER PRIMARY KEY CHECK(id = 1), scope TEXT NOT NULL, epoch TEXT NOT NULL, seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS changes (partition TEXT PRIMARY KEY, seq INTEGER NOT NULL, generation INTEGER NOT NULL, head INTEGER NOT NULL,
	state TEXT NOT NULL, purged INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS indexed (name TEXT NOT NULL, partition TEXT NOT NULL, anchor TEXT NOT NULL, state TEXT NOT NULL, columns TEXT NOT NULL,
	PRIMARY KEY (name, partition));
`;
// NOTE: An index query's operators (spec-08 "Indexes"); negation, ranges and sorting are deferred.
const FILTERS = ["eq", "in", "exists", "and"];
const EPOCH = "1";

const rows = (storage, query, ...bindings) => storage.sql.exec(query, ...bindings).toArray();

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** One scope's change feed and index rows in one SQLite storage. */
export class ScopeStore {
	constructor(storage, { bundle, scope }) {
		this.storage = storage;
		this.bundle = bundle;
		this.scope = scope;
		this.limits = bundle.limits;
		this.indexes = Object.fromEntries((bundle.indexes ?? []).map(index => [index.name, index]));
		storage.transactionSync(() => storage.sql.exec(SCHEMA));
		const [row] = rows(storage, "SELECT scope FROM feed WHERE id = 1");
		if (row && row.scope !== scope) throw new StoreError(409, "identity_conflict", "The storage holds another scope");
	}

	/** The feed's position: the latest change's. */
	position() {
		return rows(this.storage, "SELECT seq FROM feed WHERE id = 1")[0]?.seq ?? 0;
	}

	/** Move a partition to the feed's next position, and rewrite its index rows, from its `change()`. */
	record(change) {
		return this.storage.transactionSync(() => {
			const exec = (query, ...bindings) => this.storage.sql.exec(query, ...bindings);
			exec("INSERT INTO feed VALUES (1, ?, ?, 1) ON CONFLICT DO UPDATE SET seq = seq + 1", this.scope, EPOCH);
			const seq = this.position();
			exec("INSERT OR REPLACE INTO changes VALUES (?, ?, ?, ?, ?, 0)", change.partition, seq, change.generation, change.head, change.state);
			for (const [name, columns] of Object.entries(change.rows ?? {}))
				if (Object.hasOwn(this.indexes, name)) exec("INSERT OR REPLACE INTO indexed VALUES (?, ?, ?, ?, ?)", name, change.partition, change.anchor, change.state, canonical(columns));
			return { seq };
		});
	}

	/** The change feed after a cursor: each partition once, at its latest position (spec-08 "Changes"). */
	changes(after = 0, epoch = null, limit = null) {
		if (![null, undefined, EPOCH].includes(epoch) || !Number.isInteger(after) || after < 0) after = 0;
		const size = Math.min(limit || this.limits.logPage, this.limits.logPage), position = this.position();
		const found = rows(this.storage, "SELECT partition, seq, generation, head, state, purged FROM changes WHERE seq > ? ORDER BY seq LIMIT ?", after, size);
		const through = found.length ? found.at(-1).seq : position;
		return { epoch: EPOCH, after, through, hasMore: through < position,
			entries: found.map(({ partition, seq, generation, head, state, purged }) => ({ partition, seq, generation, head, state, purged: Boolean(purged) })) };
	}

	/** Whether an index row passes a filter, after checking the filter's shape (spec-08 "Indexes"). */
	matches(filter, row, columns) {
		const entries = filter !== null && typeof filter === "object" && !Array.isArray(filter) ? Object.entries(filter) : [];
		if (entries.length !== 1 || !FILTERS.includes(entries[0][0])) throw invalid("filter", `An index filter is one of ${FILTERS.join(", ")}`);
		const [[op, args]] = entries;
		if (op === "and") {
			if (!Array.isArray(args) || !args.length) throw invalid("filter", "and lists filters");
			return args.map(item => this.matches(item, row, columns)).every(Boolean);
		}
		const column = op === "exists" ? args : Array.isArray(args) && args.length === 2 ? args[0] : null;
		if (typeof column !== "string" || op === "in" && !Array.isArray(args[1]))
			throw invalid("filter", `${op} takes ${op === "exists" ? "a column" : `a column and ${op === "in" ? "values" : "a value"}`}`);
		if (!columns.has(column)) throw invalid("column", `No column '${column}' in this index`);
		const values = new Set(row[column] ?? []);
		if (op === "exists") return values.size > 0;
		if (op === "in" && args[1].length > this.limits.inValues) throw invalid("filter", `in takes at most ${this.limits.inValues} values`);
		return (op === "in" ? args[1] : [args[1]]).flatMap(indexValue).some(item => values.has(item));
	}

	/** The partitions whose index rows pass a filter, by partition ID and paged, with the feed's position (spec-08 "Indexes"). */
	indexQuery(name, body) {
		const index = this.indexes[name];
		if (!index) throw new StoreError(404, "not_found", `No index '${name}'`);
		body = body !== null && typeof body === "object" && !Array.isArray(body) ? body : {};
		const include = body.include ?? [];
		if (!Array.isArray(include) || include.some(item => !["orphaned", "archived", "deletion"].includes(item)))
			throw invalid("include", "include names lifecycle states: orphaned, archived or deletion");
		const limit = body.limit ?? this.limits.indexPage, after = body.after ?? null;
		if (!Number.isInteger(limit) || limit < 1 || limit > this.limits.indexPage) throw invalid("limit", `limit is from 1 to ${this.limits.indexPage}`);
		if (after !== null && typeof after !== "string") throw invalid("after", "after is a partition ID");
		const columns = new Set(index.columns.map(column => column.name)), states = new Set(["active", ...include]);
		this.matches(body.filter, {}, columns);
		const found = [];
		for (const { partition, anchor, state, columns: row } of rows(this.storage, "SELECT partition, anchor, state, columns FROM indexed WHERE name = ? "
			+ "AND (? IS NULL OR partition > ?) ORDER BY partition", name, after, after)) {
			if (states.has(state) && this.matches(body.filter, JSON.parse(row), columns)) {
				found.push({ partition, anchor, state });
				if (found.length > limit) break;
			}
		}
		const page = found.slice(0, limit);
		return { index: name, partitions: page, through: this.position(), ...(found.length > limit ? { next: page.at(-1).partition } : {}) };
	}
}

// EOF
