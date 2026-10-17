import { test } from "node:test";
import assert from "node:assert/strict";
import { parseToastMs } from "../src/settings.js";

test("parseToastMs accepts a positive integer", () => {
  assert.equal(parseToastMs("3000"), Number("3000"));
});

test("parseToastMs rejects missing or invalid values", () => {
  for (const bad of [undefined, "", " ", "0", "-5", "1.5", "soon"]) {
    assert.throws(() => parseToastMs(bad), TypeError);
  }
});
