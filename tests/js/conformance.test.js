/** Module: conformance — replay Python's recorded hexa cases and compare outputs.
 * `make test-js` records the fixture before running this suite.
 */

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { expect, test } from "bun:test";
import { Failure } from "hexa/shapes.js";
import { failureFromData } from "hexa/core.js";
import { http } from "hexa/http.js"; // Also declares the `Request` codes of failed requests that journals name.
import { run } from "hexa/runtime.js";
import { Model, ViewOperator, ViewReadError, loadBindingProgram, loadMappingProgram, printObservationsCompact, printObservationsLog } from "../../src/js/onto/index.js";
import { pyJson, valueKey } from "../../src/js/onto/values.js";
import { BatchValidator, StoreError } from "../../src/js/onto/store/validate.js";
import { Forbidden } from "../../src/js/onto/store/errors.js";
import { ObservationStore } from "../../src/js/onto/store/store.js";
import { Database } from "bun:sqlite";

const PATH = process.env.ONTO_CONFORMANCE ?? "build/conformance.json";
const data = existsSync(PATH) ? JSON.parse(readFileSync(PATH, "utf8")) : null;
const get = key => data.objects[key];
const name = member => typeof member === "symbol" ? member.description.replace(/^member:/, "") : String(member);
const unwrap = raw => raw && raw.ledger && Object.hasOwn(raw, "value") ? raw.value : raw;
// Python's binding and mapping results also report what this runtime does not compute (inventory fields).
const COMPARED = {
	binding: ["log", "gaps", "stale", "unidentified", "deleted", "documents"],
	mapping: ["log", "gaps", "stale", "unidentified", "deleted", "formats", "mixed", "correspondence", "documents"],
};

/** Library functions that answer as the recorded Python implementations did. */
function implementations(calls) {
	return Object.fromEntries(Object.entries(calls).map(([fn, table]) => [fn, (...args) => {
		const answer = table[valueKey(args)];
		if (!answer) throw new Error(`unrecorded call ${fn}${valueKey(args)}`);
		if (Object.hasOwn(answer, "error")) throw new Error(answer.error);
		return answer.value;
	}]));
}

/** A view host with the hooks the Python host had, answering as it did; its reads are replayed from the journal. */
function access(calls) {
	const answer = (kind, key) => {
		const item = calls[kind][valueKey(key)];
		if (!item) throw new Error(`unrecorded ${kind}${valueKey(key)}`);
		if (Object.hasOwn(item, "error")) {
			const { error } = item;
			throw error.reason ? new ViewReadError(error.message, error.reason) : new Error(error.message ?? error.code);
		}
		return structuredClone(item.value);
	};
	const digest = value => createHash("sha256").update(pyJson(value, { ascii: false })).digest("hex");
	const hooks = {
		rootHandle: (input, value, target) => answer("rootHandle", [input.key, value, target]),
		describe: (step, value) => answer("describe", [step, value]),
		discover: (state, provides) => answer("discover", [provides?.key ?? null, digest(state)]),
		check: (step, value, response) => answer("check", [step, value, digest(response)]),
	};
	return { ...Object.fromEntries(Object.keys(calls).map(name => [name, hooks[name]])), fetch: async () => { throw new Error("a replayed retrieval read from the host"); } };
}

/**
 * A host reading live what the journal recorded: `fetch` and `RequestSend` answer each read, or fail as the Python
 * host raised (a failed request as hexa's `http` fails it).
 */
function liveHost(journal) {
	const answers = new Map();
	for (const entry of journal.filter(entry => ["DocumentFetch", "RequestSend"].includes(entry.operation))) {
		const key = valueKey([entry.operation, ...entry.arguments]);
		answers.set(key, [...(answers.get(key) ?? []), entry]);
	}
	const answer = (operation, args) => {
		const entry = answers.get(valueKey([operation, ...args]))?.shift();
		if (!entry) throw new Error(`unrecorded ${operation}${JSON.stringify(args)}`);
		if (Object.hasOwn(entry, "result")) return structuredClone(entry.result);
		const { code, detail, transient } = entry.failure;
		if (!code.startsWith("ViewRead.")) throw failureFromData(entry.failure);
		const error = code === "ViewRead.UnreadableResponse" ? new Error(detail) : new ViewReadError(detail, code.slice("ViewRead.".length));
		if (transient) error.transient = true;
		throw error;
	};
	return { fetch: async (step, value) => answer("DocumentFetch", [step, value]), operations: { RequestSend: async request => answer("RequestSend", [request]) } };
}

const STATUSES = { "Request.BadRequest": 400, "Request.Unauthorized": 401, "Request.Forbidden": 403, "Request.NotFound": 404,
	"Request.Conflict": 409, "Request.Gone": 410, "Request.TooManyRequests": 429, "Request.ServerError": 500, "Request.Unavailable": 503 };
const requestKey = (method, target, body) => valueKey([method, target, body ?? null]);

/** Whether an HTTP API can answer a journal's requests: it has some, and each failed with an HTTP status. */
function servable(journal) {
	const sends = journal.filter(entry => entry.operation === "RequestSend");
	return sends.length > 0 && sends.every(entry => !entry.failure || STATUSES[entry.failure.code]);
}

/** An HTTP API answering each request as the journal recorded it, for hexa's `http` to read. */
function httpApi(journal) {
	const sends = journal.filter(entry => entry.operation === "RequestSend"), answers = new Map();
	for (const entry of sends) {
		const [{ method, path, query = {}, body }] = entry.arguments;
		const search = new URLSearchParams(Object.entries(query).flatMap(([key, value]) => [value].flat().map(item => [key, String(item)]))).toString();
		const key = requestKey(method, path + (search ? "?" + search : ""), body);
		answers.set(key, [...(answers.get(key) ?? []), entry]);
	}
	const server = Bun.serve({ port: 0, async fetch(request) {
		const url = new URL(request.url), text = await request.text();
		const entry = answers.get(requestKey(request.method, url.pathname + url.search, text ? JSON.parse(text) : undefined))?.shift();
		if (!entry) return new Response("unrecorded request", { status: 400 });
		if (entry.failure) return Response.json({ error: entry.failure.code }, { status: STATUSES[entry.failure.code] });
		return Response.json(entry.result.data, { status: entry.result.status });
	} });
	return { server, operations: http({ base: `http://localhost:${server.port}` }) };
}

/** What two journals must share: each effect at its position, with its arguments and outcome. */
function journalFacts(journal) {
	return journal.map(({ strand, seq, operation, arguments: args, result, failure }) => ({ strand, seq, operation, args, result,
		failure: failure && { code: failure.code, detail: failure.detail, transient: failure.transient } }))
		.sort((a, b) => a.strand.localeCompare(b.strand) || a.seq - b.seq);
}

/** An output without its gaps' messages: a failed request's names the server that answered it. */
function withoutDetails(output) {
	return Array.isArray(output?.gaps) ? { ...output, gaps: output.gaps.map(({ detail, ...gap }) => gap) } : output;
}

/** A recorded run policy: a retry waits the recorded delays, so replay yields the same `DelayWait` effects. */
function policy({ retry, ...rest }) {
	if (!retry) return rest;
	const { delays, ...options } = retry;
	return { ...rest, retry: { ...options, ...(delays ? { delay: attempt => delays[attempt - 1] } : {}) } };
}

/** The first path where two JSON values differ, for a readable failure. */
function difference(actual, expected, path = "") {
	if (valueKey(actual) === valueKey(expected)) return null;
	if (actual && expected && typeof actual === "object" && typeof expected === "object" && Array.isArray(actual) === Array.isArray(expected)) {
		for (const key of new Set([...Object.keys(actual), ...Object.keys(expected)])) {
			const found = difference(actual[key], expected[key], `${path}/${key}`);
			if (found) return found;
		}
	}
	return `${path || "/"}: JS ${JSON.stringify(actual)?.slice(0, 400)} != PY ${JSON.stringify(expected)?.slice(0, 400)}`;
}

async function replay(item, live = null) {
	const clock = [...(item.clock ?? [])];
	const env = { ClockRead: () => clock.length > 1 ? clock.shift() : clock[0], policy: { maxNodes: 1000000, ...item.policy },
		...(item.replay ? { replay: item.replay } : {}) };
	if (item.kind === "view") {
		const operator = new ViewOperator(get(item.bundle), { access: access(get(item.access)), implementations: implementations(get(item.calls)) });
		if (item.method === "plan") return operator.plan(item.view, item.seed, item.fields);
		const options = { now: item.now, ...(item.policy ? { policy: policy(item.policy) } : {}),
			...(live ?? (item.journal ? { replay: get(item.journal) } : {})) };
		if (item.method === "report") return operator.report(item.view, item.seed, item.fields, options);
		const observations = await operator.retrieve(item.view, item.seed, item.fields, options);
		const print = printer => { try { return printer(operator.targetModel, observations); } catch { return null; } };
		return { observations, log: print(printObservationsLog), compact: print(printObservationsCompact) };
	}
	const model = new Model(get(item.model));
	const program = item.kind === "binding"
		? loadBindingProgram(get(item.program), model, { implementations: implementations(get(item.calls)) })
		: loadMappingProgram(get(item.program), model, new Model(get(item.targetModel)), { implementations: implementations(get(item.calls)) });
	const output = unwrap(await run(env, program.stages[item.kind === "binding" ? "BindingRead" : "MappingRead"], structuredClone(get(item.input))));
	const keys = [...COMPARED[item.kind], ...(item.kind === "binding" && !item.formats ? ["formats"] : [])];
	return Object.fromEntries(keys.map(key => [key, output[key]]));
}

function expected(item) {
	const output = get(item.output);
	if (item.kind === "view") return output;
	const keys = [...COMPARED[item.kind], ...(item.kind === "binding" && !item.formats ? ["formats"] : [])];
	return Object.fromEntries(keys.map(key => [key, output[key]]));
}

/** A store's validation of a batch: accepted, or rejected with Python's status, error, check and statement. */
const validators = new Map();
function validated(item) {
	if (!validators.has(item.bundle)) validators.set(item.bundle, new BatchValidator(get(item.bundle)));
	try {
		validators.get(item.bundle).validate(get(item.data), item.partition);
		return { accepted: true };
	} catch (error) {
		if (!(error instanceof StoreError)) throw error;
		return { status: error.status, error: error.error, ...error.details };
	}
}

/** SQLite storage of Cloudflare's shape over Bun's SQLite: `sql.exec` and `transactionSync`. */
function sqlite() {
	const database = new Database(":memory:");
	return {
		sql: {
			exec(query, ...bindings) {
				if (query.trim().split(";").filter(part => part.trim()).length > 1) {
					database.exec(query);
					return { toArray: () => [] };
				}
				const rows = database.query(query).all(...bindings);
				return { toArray: () => rows };
			},
		},
		transactionSync(action) {
			database.exec("BEGIN IMMEDIATE");
			try {
				const result = action();
				database.exec("COMMIT");
				return result;
			} catch (error) {
				database.exec("ROLLBACK");
				throw error;
			}
		},
	};
}

/** A time Python recorded, in epoch milliseconds; Python's microseconds are cut to milliseconds, as its stamps are. */
const instant = text => Date.parse(text.replace(/(\.\d{3})\d+/, "$1"));

/** Replay a store's calls on a JavaScript store: each with Python's grants and clock, each answered as Python answered. */
async function replayStore(item) {
	let grants = [], clocks = [];
	const store = new ObservationStore(get(item.bundle), {
		authorize: () => {
			if (!grants.length) throw new Error("an authorization Python did not make");
			const grant = grants.shift();
			if (grant && Object.hasOwn(grant, "forbidden")) throw new Forbidden(grant.forbidden);
			return grant;
		},
		storageFor: () => sqlite(),
		clock: () => {
			if (!clocks.length) throw new Error("a clock reading Python did not make");
			return instant(clocks.length > 1 ? clocks.shift() : clocks[0]);
		},
	});
	for (const [index, call] of item.calls.entries()) {
		grants = [...call.grants];
		clocks = [...call.clocks];
		const args = call.method === "log" ? [call.args[0], call.args[1] ?? call.kwargs.after ?? 0, call.args[2] ?? call.kwargs.limit ?? null]
			: [...call.args, ...Object.values(call.kwargs)];
		let answer, failure;
		try { answer = await store[call.method]({}, ...structuredClone(args)); }
		catch (error) { failure = error; }
		const where = `call ${index} ${call.method}`;
		if (call.raised) {
			expect(failure, `${where}: Python raised ${call.raised}`).toBeDefined();
			continue;
		}
		if (call.error) {
			if (!(failure instanceof StoreError)) throw failure ?? new Error(`${where}: Python answered ${JSON.stringify(call.error)}`);
			const { message, ...expected } = call.error, { message: _, ...actual } = { status: failure.status, ...failure.toJSON() };
			expect(difference(JSON.parse(JSON.stringify(actual)), expected), where).toBeNull();
			continue;
		}
		if (failure) throw failure;
		expect(difference(JSON.parse(JSON.stringify(answer)), call.answer), where).toBeNull();
	}
}

if (!data) test.skip(`conformance cases (record ${PATH} first)`, () => {});
else for (const [index, item] of data.cases.entries()) {
	const label = `${index} ${item.kind}${item.method ? " " + item.method : ""} ${item.test}`;
	if (item.kind === "store-validate") {
		test(label, () => expect(validated(item)).toEqual(item.outcome));
		continue;
	}
	if (item.kind === "store") {
		if (item.calls.length) test(label, () => replayStore(item));
		continue;
	}
	if (item.unsupported) {
		test.skip(`${label}: ${item.unsupported}`, () => {});
		continue;
	}
	test(label, async () => {
		let actual, failure;
		try { actual = await replay(item); }
		catch (error) { failure = error; }
		if (item.error) {
			expect(failure, `Python raised ${JSON.stringify(item.error)}`).toBeDefined();
			if (item.error.failure) {
				expect(failure).toBeInstanceOf(Failure);
				expect([name(failure.kind), name(failure.code)]).toEqual([item.error.failure, item.error.code]);
			}
			return;
		}
		if (failure) throw failure;
		const found = difference(JSON.parse(JSON.stringify(actual)), expected(item));
		expect(found).toBeNull();
	});
	// Read live as well: the JavaScript host adapter, its codes and the concurrent reads must give Python's journal.
	if (item.kind === "view" && item.journal && !item.error) test(`${label} (live)`, async () => {
		const journal = [], recorded = get(item.journal);
		const actual = await replay(item, { ...liveHost(recorded), record: entry => journal.push(entry) });
		expect(difference(JSON.parse(JSON.stringify(actual)), expected(item))).toBeNull();
		expect(journalFacts(journal)).toEqual(journalFacts(recorded));
	});
	// And send its requests over HTTP with hexa's `http`, to a server answering as Python's did.
	if (item.kind === "view" && item.journal && !item.error && servable(get(item.journal))) {
		test(`${label} (http)`, async () => {
			const { server, operations } = httpApi(get(item.journal));
			try {
				const actual = await replay(item, { fetch: liveHost(get(item.journal)).fetch, operations });
				expect(difference(withoutDetails(JSON.parse(JSON.stringify(actual))), withoutDetails(expected(item)))).toBeNull();
			} finally { server.stop(true); }
		});
	}
}

// EOF
