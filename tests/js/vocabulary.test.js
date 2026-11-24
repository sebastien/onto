/** Module: vocabulary tests — check Onto vocabulary and values against Python's examples. */

import { expect, test } from "bun:test";
import { Gap } from "hexa/shapes.js";
import { CODECS, TRANSFORMS } from "../../src/js/onto/vocabulary.js";
import { arithmetic } from "../../src/js/onto/functions.js";
import { canonicalNumber, decimalText, encodeKey, decodeKey, printValue, pyJson, sortedByJson, timestampValue } from "../../src/js/onto/values.js";

const short = code => code.description.split(".").at(-1);

test("every Onto transform reproduces its examples (vocabularyConformance)", () => {
	let count = 0;
	for (const item of Object.values(TRANSFORMS)) {
		for (const example of item.examples) {
			count += 1;
			let result;
			try { result = item.function(...example.input); }
			catch (error) {
				expect(error).toBeInstanceOf(Gap);
				expect([item.name, short(error.code)]).toEqual([item.name, example.gap]);
				continue;
			}
			expect([item.name, example.gap, result]).toEqual([item.name, undefined, example.output]);
		}
	}
	expect(count).toBeGreaterThan(50);
});

test("every Onto codec reproduces its examples in both directions", () => {
	for (const family of Object.values(CODECS)) {
		for (const example of family.examples) {
			const instance = example.arguments ? family(...example.arguments) : family, direction = example.direction ?? "both";
			try {
				if (direction === "backward") {
					expect(instance.convert(example.output ?? example.input, { formatting: true })).toEqual(example.input);
					expect(example.gap).toBeUndefined();
				} else {
					const value = instance.convert(example.input);
					expect([family.name, example.gap, value]).toEqual([family.name, undefined, example.output]);
					if (direction === "both") expect(instance.convert(value, { formatting: true })).toEqual(example.input);
				}
			} catch (error) {
				if (!(error instanceof Gap)) throw error;
				expect([family.name, short(error.code)]).toEqual([family.name, example.gap]);
			}
		}
	}
});

test("SplitText and generic split/join enforce reversible separators and members", () => {
	const codec = CODECS.SplitText("aba");
	const parse = text => codec.convert(text);
	const format = value => codec.convert({ set: value }, { formatting: true });
	const gap = (run, code) => {
		try { run(); throw new Error("expected a gap"); }
		catch (error) { expect(error).toBeInstanceOf(Gap); expect(short(error.code)).toBe(code); }
	};
	expect(parse("babab")).toEqual({ set: ["b"] });
	expect(format(["z", "b"])).toBe("babaz");
	expect(parse(format(["z", "b"]))).toEqual({ set: ["b", "z"] });
	expect(format([])).toBe("");
	for (const members of [[""], ["xabay"], ["ab", "z"]]) gap(() => format(members), "Unformattable");
	gap(() => CODECS.SplitText("").convert("abc"), "Invalid");
	gap(() => CODECS.SplitText("").convert({ set: [] }, { formatting: true }), "Unformattable");
	const split = TRANSFORMS["Onto.Split"].function, join = TRANSFORMS["Onto.Join"].function;
	expect(split("b,a,,b", ",")).toEqual({ set: ["a", "b"] });
	expect(join({ set: ["b", "a"] }, ",")).toBe("a,b");
	for (const args of [[{ set: ["ab", "z"] }, "aba"], [{ set: [""] }, ","], [{ set: [] }, ""]]) gap(() => join(...args), "Invalid");
	gap(() => split("abc", ""), "Invalid");
});

test("decimal, date and key spellings match Python's", () => {
	const decimals = [[0.1, "0.1"], [1e21, "1000000000000000000000"], [1e-7, "0.0000001"], [12, "12"], [-0, "0"], ["5e2", "500"], ["1.50e1", "15"], ["-.5", "-0.5"], ["007", "7"], [123456789.12345679, "123456789.12345679"]];
	for (const [value, expected] of decimals) expect(decimalText(value)).toBe(expected);
	expect(() => decimalText(" 1")).toThrow();
	expect(canonicalNumber("1.500e3")).toBe("1.5e3");
	for (const text of ["2024-02-29", "2026-01-01T24:00:00", "2026-01-01T10:30", "2026-01-01T00:00:00.1234567890", "2026-01-01T10:30:00-00:30"]) expect(() => timestampValue(text)).not.toThrow();
	for (const text of ["2026-02-29", "0000-01-01", "2026-01-01T10:30:60", "2026-01-01T10:30:00+24:00"]) expect(() => timestampValue(text)).toThrow();
	expect(encodeKey("AdviceLink/Client/12229")).toBe("AdviceLink_2FClient_2F12229");
	expect(decodeKey(encodeKey("é/x"))).toBe("é/x");
	expect(pyJson({ b: "é\u007f\n", a: [1, 2.5, null, true] })).toBe('{"a": [1, 2.5, null, true], "b": "\\u00e9\\u007f\\n"}');
	expect(sortedByJson(["é", "z", "\u{1F600}", "￿"])).toEqual(["é", "\u{1F600}", "￿", "z"]);
	expect(printValue({ set: ["b", "a b", ""] })).toBe('["", a b, b]');
});

test("arithmetic is exact and spelled as Python's Decimal results", () => {
	expect(arithmetic("sum", ["0.1", "0.2"])).toBe("0.3");
	expect(arithmetic("multiply", ["1e2", "1e2"])).toBe("1e4");
	expect(arithmetic("sum", ["1e2"])).toBe("100");
	expect(arithmetic("divide", ["1", "4"])).toBe("0.25");
	expect(arithmetic("divide", ["2", "3"])).toBe("0.6666666666666667");
	expect(arithmetic("multiply", ["0.0000001", "1"])).toBe("1e-7");
	expect(() => arithmetic("divide", ["1", "0"])).toThrow("Division by zero");
});

// EOF
