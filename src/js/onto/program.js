/** Module: program — decode compiled programs from a bundle into hexa shapes, templates and slots. */

import { decode, slot } from "hexa/shapes.js";
import { REGISTRY } from "hexa/core.js";
import { Slot, compileShape, validateShape } from "hexa/shape.js";
import "./vocabulary.js";

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/**
 * Program-local names layered over hexa's process-wide registry, so that slots whose shapes depend
 * on an ontology revision and function transforms never compete for process-wide names.
 */
export class Registry extends Map {
	has(name) { return super.has(name) || REGISTRY.has(name); }
	get(name) { return super.has(name) ? super.get(name) : REGISTRY.get(name); }

	/** Declare encoded slots: local ones in this registry, `global` ones process-wide as Python declares them. */
	declareSlots(slots) {
		for (const [name, { shape, global }] of Object.entries(slots)) {
			if (super.has(name)) continue;
			const decoded = this.decode(shape);
			if (global) this.set(name, slot(name, decoded));
			else {
				const compiled = compileShape(decoded);
				validateShape(compiled);
				this.set(name, new Slot(name, compiled));
			}
		}
		return this;
	}

	decode(value) {
		return decode(value, null, { registry: this, maxNodes: Infinity, maxBytes: Infinity });
	}
}

// EOF
