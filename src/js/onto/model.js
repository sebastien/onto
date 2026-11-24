/** Module: model — ontology lookups over a bundle's model facts, as `ontology/model.py`'s `Model`. */

// -----------------------------------------------------------------------------
//
// DEFINITIONS
//
// -----------------------------------------------------------------------------

export const QUALIFIERS = ["cur", "unit", "period", "scale"];
const RE_ELEMENT_KEY = /\[[^\]]*\]/g;

// -----------------------------------------------------------------------------
//
// UTILITIES
//
// -----------------------------------------------------------------------------

/** An attribute path without its element keys: `Phones[Mobile].Number` is `Phones.Number`. */
export function unkeyed(path) {
	return path.includes("[") ? path.replace(RE_ELEMENT_KEY, "") : path;
}

// -----------------------------------------------------------------------------
//
// OPERATIONS
//
// -----------------------------------------------------------------------------

/** Look up declarations and inherited attributes in a compiled model index; the index is assumed well formed. */
export class Model {
	/**
	 * `index` is the `modelJson` of a bundle: `{namespace, defaultCard, types, relations, facets, structs}`.
	 * Attributes are `{multi, numeric?, numericRange?, qualifiers?, struct?, ref?}`.
	 */
	constructor(index) {
		this.namespace = index.namespace;
		this.defaultCard = index.defaultCard ?? "?";
		this.types = index.types;
		this.relations = index.relations;
		this.facetsBySubject = index.facets;
		this.structs = index.structs ?? {};
		this.lineages = new Map();
		this.relationList = Object.entries(this.relations).map(([path, relation]) => ({ path, kind: "relation", ...relation }));
	}

	/** The declaration at `path`, or undefined if it is not a type or relation. */
	get(path) {
		if (!path) return undefined;
		if (Object.hasOwn(this.types, path)) return { path, ...this.types[path] };
		if (Object.hasOwn(this.relations, path)) return { path, kind: "relation", ...this.relations[path] };
		return undefined;
	}

	/** Entity `path` and its bases, nearest first; an association is its own lineage. */
	lineage(path) {
		if (this.lineages.has(path)) return this.lineages.get(path);
		const decl = this.types[path];
		let chain = [];
		if (decl?.association) chain = [path];
		else {
			let current = path;
			while (current && !chain.includes(current) && this.types[current]?.kind === "entity") {
				chain.push(current);
				current = this.types[current].base;
			}
		}
		this.lineages.set(path, chain);
		return chain;
	}

	/** Whether `path` is `ancestor` or inherits from it. */
	isA(path, ancestor) {
		return this.lineage(path).includes(ancestor);
	}

	/** Attributes of entity `path` by name, including inherited ones. */
	entityAttrs(path) {
		const attrs = {};
		for (const entity of [...this.lineage(path)].reverse()) Object.assign(attrs, this.types[entity].attrs);
		return attrs;
	}

	/** Attribute and role names of `path`, which facet names must not shadow. */
	ownNames(path) {
		const decl = this.types[path];
		if (decl?.association) return new Set([...decl.roles.map(item => item.role), ...Object.keys(decl.attrs)]);
		if (decl?.kind === "entity") return new Set(Object.keys(this.entityAttrs(path)));
		return new Set();
	}

	/** Facets applicable to `path`, including inherited ones, by addressing name. */
	facets(path) {
		const result = new Map();
		for (const entity of [...this.lineage(path)].reverse()) for (const facet of this.facetsBySubject[entity] ?? []) result.set(facet.name, facet);
		return result;
	}

	/** The facet that `attrPath` goes through on `ownerPath`, if any. */
	facetOf(ownerPath, attrPath) {
		const name = attrPath.split(".")[0];
		if (this.ownNames(ownerPath).has(name)) return undefined;
		return this.facets(ownerPath).get(name);
	}

	/** Attribute `attrPath` of `ownerPath`, through facets and structures; roles act as attributes. */
	lookup(ownerPath, attrPath) {
		attrPath = unkeyed(attrPath);
		const decl = this.get(ownerPath);
		if (!decl) return undefined;
		const segments = attrPath.split(".");
		let attr, rest = segments.slice(1);
		const facet = this.facetOf(ownerPath, attrPath);
		if (facet) {
			if (segments.length < 2) return undefined;
			attr = facet.attrs[segments[1]];
			rest = segments.slice(2);
		} else if (decl.kind === "entity") attr = this.entityAttrs(ownerPath)[segments[0]];
		else if (decl.kind === "relation") {
			attr = decl.attrs[segments[0]];
			const role = (decl.roles ?? decl.participants ?? []).find(item => item.role === segments[0]);
			if (!attr && role) attr = { multi: false, ref: role.type };
		}
		for (const name of rest) {
			const struct = attr?.struct ? this.structs[attr.struct] : undefined;
			if (!struct) return undefined;
			attr = struct.fields[name];
		}
		return attr;
	}

	/** Binary relations usable from `path` with `verb`, as `[relation, inverse]` pairs. */
	verbs(path, verb) {
		const lineage = this.lineage(path), found = [];
		for (const decl of this.relationList) {
			if (decl.verb === verb && lineage.includes(decl.participants[0].type)) found.push([decl, false]);
			else if (decl.inverse === verb && lineage.includes(decl.participants[1].type)) found.push([decl, true]);
		}
		return found;
	}

	/** The qualifiers of a claim's value: a fixed observed qualifier wins over the attribute's own (`useType`). */
	qualifiers(attr, claim) {
		const result = {};
		for (const name of QUALIFIERS) {
			const observed = typeof claim[name] === "string" ? claim[name] : undefined, declared = attr?.qualifiers?.[name];
			if (observed !== undefined && !observed.startsWith("?")) result[name] = observed;
			else if (declared !== undefined) result[name] = declared;
			else if (observed !== undefined) result[name] = "?";
		}
		return result;
	}
}

// EOF
