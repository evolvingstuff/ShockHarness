import { test } from "node:test";
import assert from "node:assert/strict";
import { StoredNotesError, decodeNotes, encodeNotes, openNotes, saveNotes } from "../src/storage.js";
import { createNote, togglePin } from "../src/notes.js";
import { MemoryStorage } from "./storage-helper.js";

const KEY = "noteboard.notes";
const FOUND_AT = new Date("2026-10-17T12:00:00.000Z");

test("notes round-trip through storage", () => {
  const storage = new MemoryStorage({});
  const notes = togglePin([createNote("a", "alpha"), createNote("b", "beta")], "b");
  saveNotes(storage, KEY, notes);
  const opened = openNotes(storage, KEY, FOUND_AT);
  assert.equal(opened.problem, null);
  assert.deepEqual(opened.notes.map((n) => ({ ...n })), notes.map((n) => ({ ...n })));
});

test("no stored data starts an empty board without a problem", () => {
  const opened = openNotes(new MemoryStorage({}), KEY, FOUND_AT);
  assert.deepEqual(opened.notes, []);
  assert.equal(opened.problem, null);
});

test("malformed JSON is a typed error with its cause", () => {
  assert.throws(() => decodeNotes("{nope"), StoredNotesError);
  assert.throws(() => decodeNotes("{nope"), (err) => err.cause instanceof SyntaxError);
});

test("data of the wrong shape is refused", () => {
  for (const text of [
    "{}",
    "[1]",
    '[{"id":"a","text":"x"}]',
    '[{"id":"","text":"x","pinned":false}]',
    '[{"id":"a","text":"x","pinned":false},{"id":"a","text":"y","pinned":true}]',
  ]) {
    assert.throws(() => decodeNotes(text), StoredNotesError, text);
  }
});

test("unreadable data is reported, kept under a backup key, and reported only once", () => {
  const storage = new MemoryStorage({ [KEY]: "{broken" });
  const opened = openNotes(storage, KEY, FOUND_AT);
  assert.deepEqual(opened.notes, []);
  assert.match(opened.problem, /could not be read/);
  const backupKey = `${KEY}.unreadable.2026-10-17T12:00:00.000Z`;
  assert.match(opened.problem, new RegExp(backupKey.replaceAll(".", "\\.")));
  assert.equal(storage.getItem(backupKey), "{broken");
  assert.equal(storage.getItem(KEY), null);

  const again = openNotes(storage, KEY, FOUND_AT);
  assert.equal(again.problem, null);
});

test("encoding keeps only the note fields", () => {
  const note = { ...createNote("a", "x"), extra: 1 };
  assert.equal(encodeNotes([note]), '[{"id":"a","text":"x","pinned":false}]');
});
