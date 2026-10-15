import assert from "node:assert/strict";
import { test } from "node:test";

import { lastPage, paginate, preview } from "../src/pages.js";

test("paginate splits by the given size", () => {
  assert.deepEqual(paginate(["a", "b", "c"], 2), [["a", "b"], ["c"]]);
  assert.throws(() => paginate(["a"], 0), RangeError);
});

test("preview takes the given length", () => {
  assert.deepEqual(preview(["a", "b", "c"], 2), ["a", "b"]);
  assert.deepEqual(preview(["a"], 0), []);
  assert.throws(() => preview(["a"], -1), RangeError);
});

test("lastPage returns the last page or throws", () => {
  assert.deepEqual(lastPage([["a"], ["b"]]), ["b"]);
  assert.throws(() => lastPage([]), RangeError);
});
