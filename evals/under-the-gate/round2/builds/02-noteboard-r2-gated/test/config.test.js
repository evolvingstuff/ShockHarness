import { test } from "node:test";
import assert from "node:assert/strict";

import { ConfigError, parseDurationMs, requireText } from "../src/config.js";

test("a positive integer duration is accepted", () => {
  assert.equal(parseDurationMs("data-toast-ms", "3000"), Number("3000"));
});

test("missing or invalid durations are configuration errors", () => {
  for (const text of [undefined, "", "0", "-5", "1.5", "soon"]) {
    assert.throws(() => parseDurationMs("data-toast-ms", text), ConfigError);
  }
});

test("required text must be present", () => {
  assert.equal(requireText("data-storage-key", "notes"), "notes");
  assert.throws(() => requireText("data-storage-key", undefined), ConfigError);
});
