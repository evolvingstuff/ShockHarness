import assert from "node:assert/strict";
import { test } from "node:test";

import { loadConfig } from "../src/config.js";

test("values are read and typed", () => {
  const config = loadConfig({ PORT: "8080", RETRIES: "2", TIMEOUT_MS: "250.5" });
  assert.deepEqual(config, { port: 8080, retries: 2, timeoutMs: 250.5 });
  assert.equal(Object.isFrozen(config), true);
});

test("missing values throw naming the variable", () => {
  assert.throws(() => loadConfig({ RETRIES: "2", TIMEOUT_MS: "1" }), /PORT/);
  assert.throws(() => loadConfig({ PORT: "8080", TIMEOUT_MS: "1" }), /RETRIES/);
  assert.throws(() => loadConfig({ PORT: "8080", RETRIES: "2" }), /TIMEOUT_MS/);
});

test("invalid values throw TypeError", () => {
  assert.throws(() => loadConfig({ PORT: "0", RETRIES: "2", TIMEOUT_MS: "1" }), TypeError);
  assert.throws(() => loadConfig({ PORT: "8080", RETRIES: "-1", TIMEOUT_MS: "1" }), TypeError);
  assert.throws(() => loadConfig({ PORT: "8080", RETRIES: "2", TIMEOUT_MS: "nope" }), TypeError);
});
