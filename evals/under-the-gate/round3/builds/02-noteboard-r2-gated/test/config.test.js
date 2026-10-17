import test from "node:test";
import assert from "node:assert/strict";
import { parseToastDurationMs } from "../src/config.js";

test("toast duration parses a positive whole number", () => {
  assert.equal(parseToastDurationMs("3000"), 3000);
});

test("missing or invalid toast durations fail loudly", () => {
  assert.throws(() => parseToastDurationMs(undefined), TypeError);
  assert.throws(() => parseToastDurationMs("3s"), TypeError);
  assert.throws(() => parseToastDurationMs("0"), RangeError);
});
