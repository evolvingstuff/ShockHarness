import { test } from "node:test";
import assert from "node:assert/strict";

import { parseToastDuration } from "../src/config.js";

test("toast duration must be a positive whole number of milliseconds", () => {
  assert.equal(parseToastDuration("3000"), Number("3000"));
  ["", "0", "-5", "1.5", "abc"].forEach((text) => assert.throws(() => parseToastDuration(text), text));
  assert.throws(() => parseToastDuration(undefined), TypeError);
});

test("index.html configures the toast duration", async () => {
  const { readFile } = await import("node:fs/promises");
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
  const match = html.match(/data-toast-ms="([^"]*)"/);
  assert.ok(match);
  assert.ok(parseToastDuration(match[1]) > 0);
});
