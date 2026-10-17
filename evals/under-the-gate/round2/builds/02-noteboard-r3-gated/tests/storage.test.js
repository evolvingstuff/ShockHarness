import { test } from "node:test";
import assert from "node:assert/strict";
import { LOAD_OK, LOAD_UNREADABLE, STORAGE_KEY, UNREADABLE_KEY_PREFIX, loadNotes, saveNotes } from "../src/storage.js";
import { addNote, createNote, togglePin } from "../src/notes.js";
import { memoryStorage } from "./helpers.js";

const NOW = 1;

test("an empty storage loads an empty board", () => {
  const result = loadNotes(memoryStorage([]), NOW);
  assert.equal(result.status, LOAD_OK);
  assert.deepEqual(result.notes, []);
});

test("saved notes load back unchanged", () => {
  const storage = memoryStorage([]);
  const notes = togglePin(addNote(addNote([], createNote("a", "one")), createNote("b", "two")), "a");
  saveNotes(storage, notes);
  const result = loadNotes(storage, NOW);
  assert.equal(result.status, LOAD_OK);
  assert.deepEqual(result.notes, notes);
});

function assertSetAside(raw) {
  const storage = memoryStorage([[STORAGE_KEY, raw]]);
  const result = loadNotes(storage, NOW);
  assert.equal(result.status, LOAD_UNREADABLE);
  assert.deepEqual(result.notes, []);
  assert.equal(result.keptUnder, `${UNREADABLE_KEY_PREFIX}${NOW}`);
  assert.equal(storage.getItem(result.keptUnder), raw, "the unreadable data is kept, not discarded");
  assert.match(result.message, /could not be read/);
  assert.ok(result.message.includes(result.keptUnder));
  // Reported once: the next load starts cleanly.
  assert.equal(loadNotes(storage, NOW).status, LOAD_OK);
}

test("invalid JSON is set aside and reported", () => {
  assertSetAside("{not json");
});

test("JSON of the wrong shape is set aside and reported", () => {
  assertSetAside('{"a":1}');
  assertSetAside('[{"id":"a","text":"t"}]');
  assertSetAside('[null]');
  assertSetAside('[{"id":"a","text":"t","pinned":false},{"id":"a","text":"u","pinned":true}]');
});

test("saveNotes refuses invalid notes", () => {
  assert.throws(() => saveNotes(memoryStorage([]), [{ id: "a" }]), TypeError);
});
