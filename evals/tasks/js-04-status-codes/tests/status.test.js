import assert from "node:assert/strict";
import { test } from "node:test";

import { NOT_FOUND, OK, SERVER_ERROR_FLOOR, isMissing, isOk, isServerError } from "../src/status.js";

test("constants carry the protocol values", () => {
  assert.equal(OK, 200);
  assert.equal(NOT_FOUND, 404);
  assert.equal(SERVER_ERROR_FLOOR, 500);
});

test("predicates", () => {
  assert.equal(isOk(200), true);
  assert.equal(isOk(201), false);
  assert.equal(isMissing(404), true);
  assert.equal(isMissing(200), false);
  assert.equal(isServerError(500), true);
  assert.equal(isServerError(503), true);
  assert.equal(isServerError(499), false);
});
