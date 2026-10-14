import assert from "node:assert/strict";
import { test } from "node:test";

import { loadConfig } from "../src/config.js";
import { isMissing } from "../src/http.js";
import { paginate } from "../src/pages.js";

test("paginate splits evenly", () => {
  assert.deepEqual(paginate(["a", "b", "c", "d"], 2), [["a", "b"], ["c", "d"]]);
});

test("paginate rejects a zero page size", () => {
  assert.throws(() => paginate(["a"], 0), RangeError);
});

test("config is required", () => {
  assert.equal(loadConfig({ REQUEST_TIMEOUT_MS: "2500" }).requestTimeoutMs, 2500);
  assert.throws(() => loadConfig({}), TypeError);
});

test("404 is missing", () => {
  assert.equal(isMissing(404), true);
  assert.equal(isMissing(200), false);
});
