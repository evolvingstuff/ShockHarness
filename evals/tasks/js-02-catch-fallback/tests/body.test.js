import assert from "node:assert/strict";
import { test } from "node:test";

import { ParseError, loadAll, parseBody } from "../src/body.js";

test("a JSON object body parses", () => {
  assert.deepEqual(parseBody('{"a": 1}'), { a: 1 });
});

test("malformed JSON is a ParseError with a cause", () => {
  assert.throws(() => parseBody("{nope"), (err) => err instanceof ParseError && err.cause instanceof SyntaxError);
});

test("a non-object body is a ParseError", () => {
  assert.throws(() => parseBody("[1]"), ParseError);
  assert.throws(() => parseBody("null"), ParseError);
});

test("loadAll rejects when any loader rejects", async () => {
  const results = await loadAll([async () => ["a"], async () => ["b"]]);
  assert.deepEqual(results, [["a"], ["b"]]);
  await assert.rejects(loadAll([async () => ["a"], async () => { throw new Error("down"); }]), /down/);
});
