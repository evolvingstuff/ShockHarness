import { test } from "node:test";
import assert from "node:assert/strict";

import {
  READ_OK,
  READ_UNREADABLE,
  STORAGE_KEY,
  UNREADABLE_KEY_PREFIX,
  readStoredNotes,
  setAsideUnreadable,
  writeNotes,
} from "../src/storage.js";
import { createFakeStorage } from "./helpers/fakeStorage.js";

const NOTE = Object.freeze({ id: "a", text: "hello", pinned: false });

test("no stored notes reads as an empty board", () => {
  const read = readStoredNotes(createFakeStorage([]));
  assert.deepEqual(read, { status: READ_OK, notes: [] });
});

test("written notes read back unchanged", () => {
  const storage = createFakeStorage([]);
  writeNotes(storage, [NOTE]);
  assert.deepEqual(readStoredNotes(storage), { status: READ_OK, notes: [NOTE] });
});

test("invalid JSON is reported as unreadable, with the raw text kept", () => {
  const storage = createFakeStorage([[STORAGE_KEY, "{not json"]]);
  const read = readStoredNotes(storage);
  assert.equal(read.status, READ_UNREADABLE);
  assert.equal(read.raw, "{not json");
  assert.match(read.reason, /not valid JSON/);
});

test("valid JSON of the wrong shape is reported as unreadable", () => {
  const shapes = ['{"a":true}', '[{"id":"a"}]', '[null]', '"text"', `[${JSON.stringify(NOTE)},${JSON.stringify(NOTE)}]`];
  shapes.forEach((raw) => {
    const read = readStoredNotes(createFakeStorage([[STORAGE_KEY, raw]]));
    assert.equal(read.status, READ_UNREADABLE, raw);
    assert.ok(read.reason.length > 0);
  });
});

test("unreadable data is set aside, not discarded, and reported only once", () => {
  const storage = createFakeStorage([[STORAGE_KEY, "garbage"]]);
  const read = readStoredNotes(storage);
  const key = setAsideUnreadable(storage, read.raw, "t1");
  assert.equal(key, `${UNREADABLE_KEY_PREFIX}t1`);
  assert.equal(storage.getItem(key), "garbage");
  assert.deepEqual(readStoredNotes(storage), { status: READ_OK, notes: [] });
});

test("setting aside never overwrites earlier kept data", () => {
  const storage = createFakeStorage([[`${UNREADABLE_KEY_PREFIX}t1`, "older"]]);
  assert.throws(() => setAsideUnreadable(storage, "newer", "t1"));
  assert.equal(storage.getItem(`${UNREADABLE_KEY_PREFIX}t1`), "older");
});

test("writing invalid notes is refused", () => {
  const storage = createFakeStorage([]);
  assert.throws(() => writeNotes(storage, [{ id: "a", text: "x" }]), TypeError);
  assert.equal(storage.getItem(STORAGE_KEY), null);
});
