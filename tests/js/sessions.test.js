/** Module: sessions — a JavaScript session's changes to members another system links (spec-09 "Changes"), over the
 * JavaScript store, as tests/T09-002-session-home-links.py checks the Python session. */

import { beforeAll, expect, test } from "bun:test";
import { Session, SessionViewOperator } from "../../src/js/onto/sessions.js";
import { ObservationStore } from "../../src/js/onto/store/store.js";
import { sqlite } from "./sqlite.js";

const SCOPE = "adviser-app", COMPANY = "Company_ACM", PARTITION = `Issuer/${COMPANY}`;
const DIVIDENDS = ["Dividend_Exchange_2FDividend_2FD1", "Dividend_Exchange_2FDividend_2FD2"];
let BUNDLE;

beforeAll(() => {
	// NOTE: The exchange produces dividends and fills their Payer role, so a company's partition cannot state that link.
	const store = "@store Issuers rev=1 edit=edit:adviser-app\\n@use Finance as F\\n@system Exchange -> Finance\\n\\n@partition Issuer(company: F/Company)\\n  dividends: F/Dividend = company <- Payer\\n";
	const script = `import json; from tests.store import OPS, checked; print(json.dumps(OPS.bundle(checked("${store}"))))`;
	const run = Bun.spawnSync(["uv", "run", "--quiet", "python", "-c", script], { stderr: "pipe" });
	if (run.exitCode !== 0) throw new Error(run.stderr.toString());
	BUNDLE = JSON.parse(run.stdout.toString());
});

/** A session over the exchange's view of a company and its two dividends, appending to a JavaScript store. */
function session(bodies) {
	const store = new ObservationStore(BUNDLE, { storageFor: () => sqlite(), authorize: () => ({ scope: SCOPE, principal: "user:adviser" }) });
	const operator = { store: BUNDLE, storeName: "Issuers", scope: SCOPE, system: "Exchange", targetModel: { namespace: "Finance" },
		access: { storeAppend: (partition, body) => (bodies.push(body), store.append({}, partition, body)) } };
	operator.subjectOf = SessionViewOperator.prototype.subjectOf.bind(operator);
	operator.claimHolder = SessionViewOperator.prototype.claimHolder.bind(operator);
	const item = new Session(operator, { newId: () => "r1" });
	item.state = { instances: { [COMPANY]: { type: "Finance/Company" }, ...Object.fromEntries(DIVIDENDS.map(handle => [handle, { type: "Finance/Dividend" }])) },
		claims: DIVIDENDS.map((handle, index) => ({ n: index + 1, s: handle, p: "Payer", v: { ref: COMPANY }, src: "x" })) };
	return [item, store];
}

test("a batch carries only the links that home its subjects", async () => {
	const bodies = [], [item, store] = session(bodies);
	const { statements: [statement] } = await item.change({ claims: [{ s: DIVIDENDS[0], p: "Audit.Checked", v: true, version: 0 }] });
	expect([statement.result, statement.partition]).toEqual(["applied", PARTITION]);
	expect(bodies.map(body => body.links)).toEqual([[{ s: DIVIDENDS[0], p: "Payer", v: { ref: COMPANY } }]]);
	const { entries } = await store.log({}, PARTITION);
	expect(entries.filter(entry => entry.kind === "link").map(entry => entry.s)).toEqual([DIVIDENDS[0]]);
});

// EOF
