/** Module: sqlite — test storage of Cloudflare's Durable Object shape over Bun's SQLite. */

import { Database } from "bun:sqlite";

/** SQLite storage of Cloudflare's shape over Bun's SQLite: `sql.exec` and `transactionSync`. */
export function sqlite() {
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

// EOF
