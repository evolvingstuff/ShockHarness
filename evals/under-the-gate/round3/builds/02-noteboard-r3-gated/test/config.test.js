import { test } from "node:test";
import assert from "node:assert/strict";
import { parseToastDuration } from "../src/config.js";

test("toast duration is a positive integer", () => {
  assert.equal(parseToastDuration("3000"), 3000);
  assert.throws(() => parseToastDuration(undefined), TypeError);
  assert.throws(() => parseToastDuration(""), TypeError);
  assert.throws(() => parseToastDuration("0"), RangeError);
  assert.throws(() => parseToastDuration("1.5"), RangeError);
  assert.throws(() => parseToastDuration("soon"), RangeError);
});
